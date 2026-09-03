# This file is part of ts_maintel_standardscripts
#
# Developed for the Vera Rubin Observatory.
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

__all__ = ["PrepareForOnSky"]

import yaml
from lsst.ts import salobj
from lsst.ts.observatory.control.maintel.lsstcam import LSSTCam, LSSTCamUsages
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages
from lsst.ts.xml.enums.Script import ScriptState

BAND_TO_FILTER = {
    "u": "u_24",
    "g": "g_6",
    "r": "r_57",
    "i": "i_39",
    "z": "z_20",
    "y": "y_10",
}


class PrepareForOnSky(salobj.BaseScript):
    """Run MTCS prepare for on-sky operations.

    Parameters
    ----------
    index : `int`
        Index of Script SAL component.

    Notes
    -----
    **Checkpoints**

    Preparing MTCS components for on-sky operations: before running prepare for
    on-sky operations on MTCS and LSSTCam.
    Setting up LSSTCam with filter 'FILTER': before configuring LSSTCam with
    the specified filter.
    Ensure OCPS:101 is enabled: before checking its summary state and enabling
    it if necessary.
    Assert that MTM1M3TS is not in engineering mode: before running prepare
    for on-sky operations.
    """

    DEFAULT_TARGET_AZ = MTCS.DEFAULT_TEL_OPEN_AZ
    DEFAULT_TARGET_EL = MTCS.DEFAULT_TEL_OPEN_EL
    DEFAULT_TARGET_ROT = MTCS.DEFAULT_TEL_PARK_ROT
    MIN_TARGET_EL = MTCS.DEFAULT_TEL_OPERATE_MIRROR_COVERS_EL
    MAX_TARGET_EL = MTCS.DEFAULT_TEL_MAX_EL

    def __init__(self, index):
        super().__init__(index=index, descr="Run prepare for on-sky operations.")

        self.config = None

        self.mtcs = None
        self.lsstcam = None
        self.ocps = None
        self.mtm1m3ts = None
        self.homing_attempts = 10
        self.target_az = self.DEFAULT_TARGET_AZ
        self.target_el = self.DEFAULT_TARGET_EL
        self.target_rot = self.DEFAULT_TARGET_ROT

    @classmethod
    def get_schema(cls):
        schema_yaml = f"""
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_maintel_standardscripts/prepare_for/onsky.yaml
            title: PrepareForOnSky v1
            description: >-
                Configuration for PrepareForOnSky. This script prepares the
                telescope for on-sky operations by enabling the required
                components and setting them to the appropriate states.
            type: object
            properties:
                filter:
                    description: >-
                        Filter to be set up. May be specified either as a full
                        filter name (e.g. i_39) or as a band (e.g. i). Default
                        is "i_39".
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
                        CSCs from the group to ignore, e.g.; mtdometrajectory.
                        Note: Critical components required for on-sky operations
                        cannot be ignored (e.g., mtmount, mtrotator, mtm1m3, mtm2
                        and mtptg).
                    type: array
                    items:
                        type: string
                homing_attempts:
                    description: Number of attempts to home both axes.
                    type: integer
                    default: 10
                    minimum: 1
                target_az:
                    description: >-
                        Target azimuth for both the dome and telescope, in
                        degrees. If not provided, the default value is {cls.DEFAULT_TARGET_AZ}.
                    type: number
                    default: {cls.DEFAULT_TARGET_AZ}
                target_el:
                    description: >-
                        Target telescope elevation, in degrees. Must be high
                        enough for mirror cover operations. If not provided,
                        the default value is {cls.DEFAULT_TARGET_EL}.
                    type: number
                    default: {cls.DEFAULT_TARGET_EL}
                    minimum: {cls.MIN_TARGET_EL}
                    maximum: {cls.MAX_TARGET_EL}
                target_rot:
                    description: >-
                        Target rotator angle in mount physical coordinates, in
                        degrees. If not provided, the default value is {cls.DEFAULT_TARGET_ROT}.
                    type: number
                    default: {cls.DEFAULT_TARGET_ROT}
            additionalProperties: false
        """
        return yaml.safe_load(schema_yaml)

    @staticmethod
    def map_filter_value(filter_value: str) -> str:
        """Map a filter configuration value to a full filter name."""

        filter_text = str(filter_value).strip()
        filter_band_lower = filter_text.lower()

        if filter_band_lower in BAND_TO_FILTER:
            return BAND_TO_FILTER[filter_band_lower]

        return filter_text

    async def configure_tcs(self) -> None:
        """Initialize MTCS if not already initialized."""
        if self.mtcs is None:
            self.log.debug("Creating MTCS instance.")
            self.mtcs = MTCS(
                domain=self.domain, log=self.log, intended_usage=MTCSUsages.All
            )
            await self.mtcs.start_task
        else:
            self.log.debug("MTCS already initialized.")

    async def configure_camera(self) -> None:
        """Initialize LSST Camera if not already initialized."""
        if self.lsstcam is None:
            self.log.debug("Creating LSST Camera instance.")
            self.lsstcam = LSSTCam(
                domain=self.domain,
                intended_usage=LSSTCamUsages.All,
                log=self.log,
                mtcs=self.mtcs,
            )
            await self.lsstcam.start_task
        else:
            self.log.debug("LSST Camera already initialized.")

    async def configure_ocps(self) -> None:
        """Initialize OCPS:101 if not already initialized."""
        if self.ocps is None:
            self.log.debug("Creating OCPS:101 remote instance.")
            self.ocps = salobj.Remote(self.domain, "OCPS", index=101)
            await self.ocps.start_task
        else:
            self.log.debug("OCPS:101 already initialized.")

    async def configure_mtm1m3ts(self) -> None:
        """Initialize MTM1M3TS remote if not already initialized."""
        if self.mtm1m3ts is None:
            self.log.debug("Creating MTM1M3TS remote instance.")
            self.mtm1m3ts = salobj.Remote(self.domain, "MTM1M3TS")
            await self.mtm1m3ts.start_task
        else:
            self.log.debug("MTM1M3TS already initialized.")

    async def configure(self, config):
        await self.configure_tcs()
        await self.configure_camera()
        await self.configure_ocps()
        await self.configure_mtm1m3ts()

        critical_cscs = self.mtcs.get_critical_components_for_prepare_for_onsky()

        # Check that critical components are not ignored.
        if hasattr(config, "ignore") and any(
            component in critical_cscs for component in config.ignore
        ):
            raise ValueError(
                "Cannot ignore critical components: {}".format(config.ignore)
            )

        if hasattr(config, "ignore"):
            self.mtcs.disable_checks_for_components(components=config.ignore)
            self.lsstcam.disable_checks_for_components(components=config.ignore)

        filter_value = getattr(config, "filter", "i_39")
        self.filter = self.map_filter_value(filter_value)

        if hasattr(config, "homing_attempts"):
            self.homing_attempts = config.homing_attempts

        self.target_az = getattr(config, "target_az", self.DEFAULT_TARGET_AZ)
        self.target_el = getattr(config, "target_el", self.DEFAULT_TARGET_EL)
        self.target_rot = getattr(config, "target_rot", self.DEFAULT_TARGET_ROT)

    def set_metadata(self, metadata):
        metadata.duration = 600.0 + self.lsstcam.filter_change_timeout

    async def ensure_ocps_enabled(self) -> None:
        """Ensure the OCPS:101 CSC is enabled."""
        self.log.info("Ensuring OCPS:101 is enabled.")

        summary_state = (
            await self.ocps.evt_summaryState.aget(timeout=self.mtcs.fast_timeout)
        ).summaryState

        current_state = salobj.State(summary_state)

        if current_state == salobj.State.ENABLED:
            self.log.info("OCPS:101 is already enabled.")
        else:
            self.log.warning(
                f"OCPS:101 is not enabled (current state: {current_state!r}). "
                "Attempting to enable."
            )
            await salobj.set_summary_state(self.ocps, salobj.State.ENABLED)
            self.log.info("OCPS:101 has been enabled.")

    async def assert_mtm1m3ts_not_in_engineering_mode(self) -> None:
        """Assert that MTM1M3TS is not in engineering mode.

        This method checks whether the MTM1M3TS CSC is enabled and not in
        engineering mode. If the CSC is not enabled or is in engineering mode,
        the script will raise an error.

        Raises
        ------
        RuntimeError
            If MTM1M3TS is not enabled or is in engineering mode.
        """
        self.log.info("Assert that MTM1M3TS is not in engineering mode.")

        summary_state = (
            await self.mtm1m3ts.evt_summaryState.aget(timeout=self.mtcs.fast_timeout)
        ).summaryState

        current_state = salobj.State(summary_state)

        if current_state != salobj.State.ENABLED:
            raise RuntimeError(
                f"MTM1M3TS is not enabled (current state: {current_state!r}).\n"
                "Please check the MTM1M3TS CSC and enable it before proceeding."
            )

        self.mtm1m3ts.evt_engineeringMode.flush()
        engineering_mode_evt = await self.mtm1m3ts.evt_engineeringMode.aget(
            timeout=self.mtcs.fast_timeout
        )

        if engineering_mode_evt.engineeringMode:
            raise RuntimeError(
                "MTM1M3TS is in engineering mode.\n"
                "This prevents EAS/PID from commanding the glycol valve position.\n"
                "Please disable engineering mode on MTM1M3TS before on-sky operations.\n"
                "Check the troubleshooting documentation for more information."
            )

    async def run(self):
        await self.checkpoint("Preparing MTCS components for on-sky operations.")

        await self.mtcs.assert_all_enabled(
            message="All MTCS components need to be enabled to prepare for on-sky observations."
        )

        await self.mtcs.prepare_for_onsky(
            homing_attempts=self.homing_attempts,
            target_az=self.target_az,
            target_el=self.target_el,
            target_rot=self.target_rot,
        )

        await self.checkpoint(f"Setting up LSSTCam with filter '{self.filter}'.")

        await self.lsstcam.assert_all_enabled(
            message="All LSSTCam components need to be enabled to prepare for on-sky observations."
        )

        await self.lsstcam.setup_instrument(filter=self.filter)

        await self.checkpoint("Ensure OCPS:101 is enabled.")
        await self.ensure_ocps_enabled()

        await self.checkpoint("Assert that MTM1M3TS is not in engineering mode.")
        await self.assert_mtm1m3ts_not_in_engineering_mode()

        self.log.info("Prepare for on-sky operations completed successfully.")

    async def cleanup(self) -> None:
        if self.state.state == ScriptState.ENDING:
            return

        try:
            await self.mtcs.stop_tracking()
        except Exception:
            self.log.exception("Unable to stop tracking during cleanup.")
