# This file is part of ts_maintel_standardscripts
#
# Developed for the LSST Telescope and Site Systems.
# This product includes software developed by the LSST Project
# (https://www.lsst.org).
# See the COPYRIGHT file at the top-level directory of this distribution
# for details of code ownership.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

__all__ = ["LsstCamFesExercise"]

import asyncio
import random
from typing import Iterable, List, Optional

import yaml
from lsst.ts import salobj
from lsst.ts.observatory.control.maintel.lsstcam import LSSTCam, LSSTCamUsages
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages

BAND_TO_FILTER = {
    "u": "u_24",
    "g": "g_6",
    "r": "r_57",
    "i": "i_39",
    "z": "z_20",
    "y": "y_10",
}

SLEEP_BETWEEN_FILTER_CHANGES = 120  # seconds
CRITICAL_MTCS_COMPONENTS = {"mtptg", "mtmount", "mtrotator"}


class LsstCamFesExercise(salobj.BaseScript):
    """Exercise the LSSTCam Filter Exchange System (FES).

    This script exercises the LSSTCam filter exchange system by moving from
    the current filter to a different filter and then to a configured final
    filter. It verifies MTCS readiness, logs the current/available filters,
    and enforces a settling delay between filter changes. It does not perform
    telescope (or dome) motion beyond what is required for safe filter changes.

    Parameters
    ----------
    index : `int`
        Index of Script SAL component.

    Notes
    -----
    **Checkpoints**

    - "Checking Component Status": Before verifying CSCs are enabled.
    - "Checking LSSTCam Setup": Logs installed and available filters.
    - "Exercising filter exchange system.": Before exercising the FES.
    - "Changing filter to intermediate filter: FILTER": Before commanding
      the intermediate filter.
    - "Waiting 120 seconds before setting up final filter.": Between
      intermediate and final filter changes.
    - "Changing filter to final filter: FILTER": Before commanding the
      final filter.

    **Details**

    This script is intended for exercising the filter exchange system and
    verifying filter motion. It ensures MTCS components required for safe
    filter changes are enabled, handles the case where only one physical filter
    is available, and leaves the camera in the requested final filter.

    **Examples**

    - If a physical filter is already in the beam and it matches the
      configured final filter:
        - Select a different physical filter as an intermediate.
        - Command the intermediate filter, wait 120 seconds, then command
          the final filter.
    - If no physical filter is currently in the beam (reported filter
        ``NONE``):
        - Select any physical filter as an intermediate.
        - Command the intermediate filter, wait 120 seconds, then command
          the final filter.
    - If only one physical filter is available (extreme edge case):
        - Log a warning and skip the intermediate exercise.
        - If starting from ``NONE``, command the final filter once.
    """

    def __init__(self, index: int):
        super().__init__(index=index, descr="Exercise LSSTCam Filter Exchange System.")

        self.lsstcam = None
        self.mtcs = None
        self.final_filter = None
        self.current_filter = None
        self.available_filters = None

    @classmethod
    def get_schema(cls):
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_maintel_standardscripts/daytime/lsstcam_fes_exercise.yaml
            title: LsstCamFesExercise v1
            description: Configuration for the LSSTCam filter exercise script.
            type: object
            properties:
              final_filter:
                description: >-
                  Filter to leave in the beam when the exercise completes. May be
                  specified as either a band (e.g. i) or a full filter name (e.g. i_39).
                type: string
                default: "i_39"
                enum:
                  - "u"
                  - "g"
                  - "r"
                  - "i"
                  - "z"
                  - "y"
                  - "u_24"
                  - "g_6"
                  - "r_57"
                  - "i_39"
                  - "z_20"
                  - "y_10"
              ignore:
                description: >-
                  CSCs from the LSSTCam or MTCS groups to ignore in status checks.
                  Critical MTCS components required for filter changes (mtptg,
                  mtmount, mtrotator) will always be checked even if provided here.
                type: array
                items:
                  type: string
            additionalProperties: false
        """
        return yaml.safe_load(schema_yaml)

    @staticmethod
    def _map_filter_value(filter_value: str) -> str:
        """Map a filter value to a full filter name if a band is provided."""
        filter_text = str(filter_value).strip()
        if not filter_text:
            raise ValueError("final_filter must be a non-empty string")
        mapped = BAND_TO_FILTER.get(filter_text.lower(), filter_text)
        return mapped

    @staticmethod
    def _is_physical(filter_name: Optional[str]) -> bool:
        """Determine if a filter name corresponds to a physical filter."""
        if not filter_name:
            return False
        return filter_name.strip().casefold() != "none"

    def set_metadata(self, metadata):
        change_timeout = getattr(self.lsstcam, "filter_change_timeout", 120)
        metadata.duration = 2 * float(change_timeout) + SLEEP_BETWEEN_FILTER_CHANGES
        metadata.instrument = "LSSTCam"
        metadata.filter = self.final_filter

    async def configure(self, config):
        self.final_filter = self._map_filter_value(
            getattr(config, "final_filter", "i_39")
        )

        if self.mtcs is None:
            self.mtcs = MTCS(
                domain=self.domain,
                intended_usage=MTCSUsages.Slew | MTCSUsages.StateTransition,
                log=self.log,
            )
            await self.mtcs.start_task

        if self.lsstcam is None:
            self.lsstcam = LSSTCam(
                domain=self.domain,
                intended_usage=LSSTCamUsages.All,
                log=self.log,
                mtcs=self.mtcs,
            )
            await self.lsstcam.start_task

        if hasattr(config, "ignore"):
            ignore_components = list(config.ignore)
            filtered_ignore = []
            for component in ignore_components:
                if component in CRITICAL_MTCS_COMPONENTS:
                    self.log.warning(
                        f"Ignoring critical MTCS component '{component}' "
                        "is not allowed; removing from ignore list."
                    )
                    continue
                filtered_ignore.append(component)

            if filtered_ignore:
                self.mtcs.disable_checks_for_components(components=filtered_ignore)
                self.lsstcam.disable_checks_for_components(components=filtered_ignore)

    async def run(self):
        await self.checkpoint("Checking LSSTCam setup.")
        await self.assert_feasibility()
        await self.log_setup_info()

        await self.checkpoint("Exercising filter exchange system.")
        await self.exercise_filters()

    async def assert_feasibility(self):
        await self.mtcs.assert_all_enabled()
        await self.lsstcam.assert_all_enabled()

    async def log_setup_info(self):
        """Log current and available filters for debugging and verification."""
        try:
            self.current_filter = await self.lsstcam.get_current_filter()
        except Exception as e:
            raise RuntimeError("Could not determine current filter.") from e

        self.log.info(f"Current filter in beam: {self.current_filter}")

        try:
            self.available_filters = await self.lsstcam.get_available_filters()
        except Exception as e:
            raise RuntimeError("Could not determine available filters.") from e

        self.available_filters = self._normalize_available_filters(
            self.available_filters
        )

        self.log.info(f"Available filters: {self.available_filters}")

    async def exercise_filters(self):
        """Exercise the LSSTCam filter exchange system.

        It selects an intermediate physical filter distinct from both the
        current and final filters if possible, commands the intermediate
        filter, waits 120 seconds, and then commands the final filter.
        If no distinct intermediate physical filter is available, it logs
        a warning and performs the minimum necessary to reach the final
        filter. It always leaves the camera in the requested final filter
        if it is available.

        Raises
        ------
        RuntimeError
            If available filters are unknown, no physical filters are
            available, or the requested final filter is not currently
            available.
        """
        await self._ensure_mtcs_ready()

        if self.available_filters is None:
            raise RuntimeError(
                "Available filters are unknown; cannot exercise filters."
            )

        physical_filters = self._get_physical_filters(self.available_filters)
        if not physical_filters:
            raise RuntimeError("No physical filters are available for exercise.")

        if self.final_filter not in physical_filters:
            raise RuntimeError(
                f"Requested final filter {self.final_filter} is not currently available."
            )

        final_filter = self.final_filter.strip()
        intermediate_candidates = self._get_intermediate_candidates(physical_filters)

        if not intermediate_candidates:
            if len(physical_filters) == 1:
                only_filter = physical_filters[0]
                self.log.warning(
                    f"Only one physical filter ({only_filter}) is available; skipping exercise "
                    f"and ensuring final filter is {self.final_filter}."
                )
            else:
                self.log.warning(
                    "No distinct intermediate filter is available; skipping intermediate "
                    f"exercise and ensuring final filter is {self.final_filter}."
                )

            if self.current_filter and self.current_filter.strip() == final_filter:
                self.log.info(
                    f"Final filter {self.final_filter} already in beam; skipping filter motion."
                )
                return

            await self._change_filter(self.final_filter)
            return

        intermediate_filter = random.choice(intermediate_candidates)

        await self.checkpoint(
            f"Changing filter to intermediate filter: {intermediate_filter}"
        )
        await self._change_filter(intermediate_filter)

        await self.checkpoint("Waiting 120 seconds before setting up final filter.")
        await asyncio.sleep(SLEEP_BETWEEN_FILTER_CHANGES)

        await self.checkpoint(f"Changing filter to final filter: {self.final_filter}")
        await self._change_filter(self.final_filter)

    async def _ensure_mtcs_ready(self):
        """Ensure MTCS components are set for safe filter changes."""
        if self.mtcs is None:
            raise RuntimeError("MTCS is unavailable; cannot exercise filters.")

        await self._assert_state("mtptg", salobj.State.ENABLED)
        await self._assert_state("mtrotator", salobj.State.ENABLED)

        mtmount_acceptable_states = {salobj.State.ENABLED, salobj.State.DISABLED}
        mtmount_state = await self.mtcs.get_state("mtmount")

        if mtmount_state not in mtmount_acceptable_states:
            raise RuntimeError(
                "MTMount must be DISABLED or ENABLED before exercising filters; "
                f"current state is {mtmount_state.name}."
            )

    async def _assert_state(self, component: str, required_state: salobj.State) -> None:
        """Assert that a component is in the required state."""
        current_state = await self.mtcs.get_state(component)
        if current_state != required_state:
            raise RuntimeError(
                f"{component} must be {required_state.name} before exercising filters; "
                f"current state is {current_state.name}."
            )

    async def _change_filter(self, target_filter: str) -> None:
        """Change the filter to the target filter."""
        self.log.info(f"Changing filter to {target_filter}.")
        try:
            await self.lsstcam.setup_instrument(filter=target_filter)
            self.current_filter = target_filter
        except Exception as exc:
            raise RuntimeError(
                f"Failed to change filter to {target_filter}: {exc}."
            ) from exc

    def _get_physical_filters(self, filters: Iterable[str]) -> List[str]:
        """Return a list of physical filters from the given filters."""
        physical = []
        for filter_name in filters:
            if not filter_name:
                continue
            if filter_name.strip().casefold() == "none":
                continue
            physical.append(filter_name)
        return physical

    def _normalize_available_filters(
        self, available_filters: Iterable[str]
    ) -> List[str]:
        """Normalize available filter values into a list of filter names."""
        if available_filters is None:
            return []

        if isinstance(available_filters, str):
            return [flt.strip() for flt in available_filters.split(",") if flt.strip()]

        filters = list(available_filters)
        if len(filters) == 1 and isinstance(filters[0], str) and "," in filters[0]:
            return [flt.strip() for flt in filters[0].split(",") if flt.strip()]

        return [flt.strip() for flt in filters if str(flt).strip()]

    def _get_intermediate_candidates(self, physical_filters: List[str]) -> List[str]:
        """Return candidate intermediate physical filters.

        The intermediate is chosen from physical filters excluding the final
        filter. If the current filter is physical, it is also excluded so the
        intermediate change is not a no-op.
        """
        final_filter = self.final_filter.strip()
        candidates = [flt for flt in physical_filters if flt.strip() != final_filter]

        if self._is_physical(self.current_filter):
            current_filter = self.current_filter.strip()
            candidates = [flt for flt in candidates if flt.strip() != current_filter]

        return candidates
