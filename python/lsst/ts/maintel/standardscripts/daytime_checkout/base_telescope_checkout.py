# This file is part of ts_maintel_standardscripts.
#
# Developed for the Vera C. Rubin Observatory Telescope and Site Systems.
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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

__all__ = ["BaseTelescopeCheckout"]

import types
import typing

import yaml
from lsst.ts import salobj
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages
from lsst.ts.observatory.control.utils.enums import RotType
from lsst.ts.xml.enums.Script import ScriptState


class BaseTelescopeCheckout(salobj.BaseScript):
    """Base implementation for Simonyi Telescope daytime checkout scripts.

    Concrete subclasses define whether the checkout exercises only the TMA or
    both the TMA and MTDome. When checking the dome, its shutters are required
    to remain closed and are never commanded. Telescope-only checkout does
    not check or command the dome shutters.

    The high-level steps are:

    1. Ensure all checked MTCS components are enabled.
    2. Prepare the TMA for daytime motion: stop tracking, ensure M2
       force-balance system is enabled, check that elevation is safe
       for raising M1M3 and fail if it is not, close the mirror covers,
       prepare M1M3, home the mount, enable cable-wrap following, and
       enable compensation mode for each checked hexapod.
    3. If checking the dome, assert both shutter panels are closed, disable
       and verify dome following, then unpark the dome. Otherwise perform the
       optional defensive dome-following check.
    4. With dome following disabled, independently slew the TMA to the setup
       position defined by ``mtcs.tel_park_az``, ``mtcs.tel_park_el``, and
       ``mtcs.tel_park_rot``, then stop tracking.
    5. If checking the dome, independently slew it to ``mtcs.tel_park_az``,
       then enable following only after both systems have reached their setup
       positions.
    6. Slew to the tracked test target by subtracting ``delta_az`` and
       ``delta_el`` from the setup azimuth and elevation, and adding
       ``delta_rot`` to the setup rotator position using physical-sky
       rotation. When checking the dome, wait for its azimuth and elevation
       alignment while ignoring shutter vignetting.
    7. Verify tracking for ``track_duration``.
    8. If checking the dome, disable following.
    9. Return the TMA to the position defined by ``mtcs.tel_park_az``,
       ``mtcs.tel_park_el``, and ``mtcs.tel_park_rot``, then stop tracking.
    10. If checking the dome, park it. Otherwise perform
       only an optional defensive following check.
    11. Assert MTM1M3TS is enabled and not in engineering mode. This final
        check fails the script directly without repeating the completed
        movement checkout.

    Notes
    -----
    Telescope-only checkout ignores the dome and does not check its shutter
    state. The M1 mirror covers are kept closed as a precaution for optical
    protection in case the dome shutters are left open by mistake.

    On abnormal termination the script performs only minimal cleanup: it
    attempts to stop tracking and disable dome following. It does not command
    a return slew or dome park.
    """

    include_dome: bool

    delta_az = 15.0
    delta_el = 15.0
    delta_rot = 15.0
    track_duration = 30.0

    def __init__(self, index: int, descr: str) -> None:
        super().__init__(index=index, descr=descr)

        self.mtcs = None
        self.mtm1m3ts = None

        self.homing_attempts = 10

    @classmethod
    def get_dome_components(cls) -> list[str]:
        """Return the dome components required by the combined checkout."""

        telescope_components = set(
            MTCS.get_critical_components_for_daytime_checkout(check_dome=False)
        )
        return [
            component
            for component in MTCS.get_critical_components_for_daytime_checkout(
                check_dome=True
            )
            if component not in telescope_components
        ]

    @staticmethod
    def format_component_list(components: list[str]) -> str:
        """Format component identifiers as a natural-language list."""

        quoted_components = [f'"{component}"' for component in components]
        if len(quoted_components) == 1:
            return quoted_components[0]
        if len(quoted_components) == 2:
            return f"{quoted_components[0]} and {quoted_components[1]}"
        return f"{', '.join(quoted_components[:-1])}, and {quoted_components[-1]}"

    @classmethod
    def get_schema(cls) -> dict[str, typing.Any]:
        critical_telescope_components = cls.format_component_list(
            MTCS.get_critical_components_for_daytime_checkout(check_dome=False)
        )
        schema_id = (
            "https://github.com/lsst-ts/ts_maintel_standardscripts/"
            "base_telescope_checkout.yaml"
        )

        schema_yaml = f"""
            $schema: http://json-schema.org/draft-07/schema#
            $id: {schema_id}
            title: BaseTelescopeCheckout v1
            description: >-
                Common configuration for the Simonyi Telescope daytime
                checkout scripts.
            type: object
            properties:
                homing_attempts:
                    description: Number of attempts to home both mount axes.
                    type: integer
                    default: 10
                    minimum: 1
                ignore:
                    description: >-
                        CSCs from the MTCS group to ignore. Note: Critical
                        components required for daytime checkout cannot be ignored:
                        {critical_telescope_components}.
                    type: array
                    items:
                        type: string
                    uniqueItems: true
                    default: []
            additionalProperties: false
        """
        return yaml.safe_load(schema_yaml)

    async def configure_tcs(self) -> None:
        if self.mtcs is None:
            self.mtcs = MTCS(
                domain=self.domain,
                intended_usage=MTCSUsages.All,
                log=self.log,
            )
            await self.mtcs.start_task

    async def configure_mtm1m3ts(self) -> None:
        if self.mtm1m3ts is None:
            self.mtm1m3ts = salobj.Remote(self.domain, "MTM1M3TS")
            await self.mtm1m3ts.start_task

    async def configure(self, config: types.SimpleNamespace) -> None:
        self.homing_attempts = config.homing_attempts

        await self.configure_tcs()
        await self.configure_mtm1m3ts()

        ignore = list(config.ignore)
        known_components = set(self.mtcs.components_attr)
        unknown_components = [
            component for component in ignore if component not in known_components
        ]
        if unknown_components:
            raise ValueError(
                f"Unknown components in ignore: {unknown_components}. "
                f"Valid component names are: {sorted(known_components)}."
            )

        critical_components = set(
            self.mtcs.get_critical_components_for_daytime_checkout(
                check_dome=self.include_dome
            )
        )
        ignored_critical = [
            component for component in ignore if component in critical_components
        ]
        if ignored_critical:
            raise ValueError(
                "Cannot ignore components required for the requested daytime "
                f"checkout: {ignored_critical}."
            )

        ignored_mtcs_components = [
            component for component in ignore if component in self.mtcs.components_attr
        ]
        if ignored_mtcs_components:
            self.mtcs.disable_checks_for_components(components=ignored_mtcs_components)

        if not self.include_dome:
            self.mtcs.disable_checks_for_components(
                components=["mtdome", "mtdometrajectory"]
            )

    def set_metadata(self, metadata: salobj.type_hints.BaseMsgType) -> None:
        metadata.duration = 600.0 + self.track_duration

    async def ensure_group_all_enabled(
        self, group: typing.Any, group_name: str
    ) -> None:
        """Ensure all checked components in a remote group are enabled."""

        self.log.info(f"Ensuring all checked {group_name} components are enabled.")
        try:
            await group.assert_all_enabled()
            self.log.info(f"All checked {group_name} components are enabled.")
        except AssertionError as error:
            self.log.warning(
                f"Some {group_name} CSCs are not enabled: {error}. "
                f"Enabling checked {group_name} components."
            )
            await group.enable()
            await group.assert_all_enabled()
            self.log.info(f"All checked {group_name} components are enabled.")

    async def assert_mtm1m3ts_not_in_engineering_mode(self) -> None:
        """Assert that MTM1M3TS is enabled and not in engineering mode.

        Raises
        ------
        RuntimeError
            If MTM1M3TS is not enabled or is in engineering mode.
        """

        self.log.info("Assert that MTM1M3TS is not in engineering mode.")

        summary_state = await self.mtm1m3ts.evt_summaryState.aget(
            timeout=self.mtcs.fast_timeout
        )
        current_state = salobj.State(summary_state.summaryState)
        checkout_complete_message = (
            "The checkout movement was completed. No need to repeat it due "
            "to this failure. Resolve the MTM1M3TS issue before proceeding. "
        )

        if current_state != salobj.State.ENABLED:
            raise RuntimeError(
                f"MTM1M3TS is not enabled (current state: {current_state!r}). "
                "Please check the MTM1M3TS CSC and enable it before proceeding.\n"
                f"{checkout_complete_message}"
            )

        self.mtm1m3ts.evt_engineeringMode.flush()
        engineering_mode = await self.mtm1m3ts.evt_engineeringMode.aget(
            timeout=self.mtcs.fast_timeout
        )
        if engineering_mode.engineeringMode:
            raise RuntimeError(
                "MTM1M3TS is in engineering mode.\n"
                "This prevents EAS/PID from commanding the glycol valve position. "
                "Please disable engineering mode on MTM1M3TS before proceeding "
                "with telescope operations. Check the troubleshooting documentation "
                "for more information.\n"
                f"{checkout_complete_message}"
            )

        self.log.info("MTM1M3TS is enabled and not in engineering mode.")

    async def slew_to_tracking_target(self) -> None:
        tracked_az = self.mtcs.tel_park_az - self.delta_az
        tracked_el = self.mtcs.tel_park_el - self.delta_el
        coordinate = self.mtcs.radec_from_azel(az=tracked_az, el=tracked_el)

        check_mtdome = self.mtcs.check.mtdome
        try:
            if self.include_dome:
                self.mtcs.check.mtdome = False
            await self.mtcs.slew_icrs(
                ra=coordinate.ra,
                dec=coordinate.dec,
                rot=self.mtcs.tel_park_rot + self.delta_rot,
                rot_type=RotType.PhysicalSky,
                target_name="Daytime checkout tracking target",
            )
        finally:
            self.mtcs.check.mtdome = check_mtdome

        if self.include_dome:
            await self.mtcs.wait_for_dome_azel_inposition(
                timeout=self.mtcs.long_long_timeout
            )

    async def run(self) -> None:
        tracked_az = self.mtcs.tel_park_az - self.delta_az
        tracked_el = self.mtcs.tel_park_el - self.delta_el
        tracked_rot = self.mtcs.tel_park_rot + self.delta_rot
        self.log.info(
            "Daytime checkout configuration: "
            f"start/final=(az={self.mtcs.tel_park_az}, "
            f"el={self.mtcs.tel_park_el}, rot={self.mtcs.tel_park_rot}); "
            f"tracked target=(az={tracked_az}, el={tracked_el}, "
            f"rot={tracked_rot}); "
            f"track duration={self.track_duration}s; "
            f"include_dome={self.include_dome}. "
            "Dome shutters will not be commanded."
        )

        await self.checkpoint("Ensure required components are enabled.")
        await self.ensure_group_all_enabled(self.mtcs, "MTCS")

        await self.checkpoint(
            "Prepare TMA and dome for checkout."
            if self.include_dome
            else "Prepare TMA for checkout."
        )
        await self.mtcs.prepare_for_telescope_and_dome_checkout(
            check_dome=self.include_dome,
            homing_attempts=self.homing_attempts,
        )

        await self.checkpoint(
            "Slew to tracking target: "
            f"Az/El/Rot=({tracked_az}, {tracked_el}, {tracked_rot}) deg."
        )
        await self.slew_to_tracking_target()

        await self.checkpoint("Verify tracking.")
        await self.mtcs.check_tracking(track_duration=self.track_duration)

        final_components = "TMA and dome" if self.include_dome else "TMA"
        await self.checkpoint(f"Set final {final_components} state.")
        await self.mtcs.set_telescope_and_dome_checkout_final_state(
            check_dome=self.include_dome
        )

        await self.checkpoint("Assert MTM1M3TS readiness.")
        await self.assert_mtm1m3ts_not_in_engineering_mode()

    async def cleanup(self) -> None:
        if self.state.state == ScriptState.ENDING:
            return

        try:
            await self.mtcs.stop_tracking()
        except Exception:
            self.log.exception("Unable to stop tracking during cleanup.")

        try:
            if self.include_dome:
                await self.mtcs.disable_dome_following()
            else:
                await self.mtcs.disable_dome_following_if_dome_enabled()
        except Exception:
            self.log.exception("Unable to disable dome following during cleanup.")
