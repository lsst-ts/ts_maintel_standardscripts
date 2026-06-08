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

__all__ = ["PrepareForFlat"]

import yaml
from lsst.ts import salobj
from lsst.ts.observatory.control.maintel.lsstcam import LSSTCam, LSSTCamUsages
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages


class PrepareForFlat(salobj.BaseScript):
    """Run MTCS prepare for flat-field operations.

    Parameters
    ----------
    index : `int`
        Index of Script SAL component.

    Notes
    -----
    **Checkpoints**

    Preparing for flat-field operations: before running prepare for
    flat-field operations on MTCS and LSSTCam.
    Assert that MTM1M3TS is not in engineering mode: before completing
    flat-field preparation.
    """

    def __init__(self, index):
        super().__init__(
            index=index, descr="Run MTCS prepare for flat-field operations."
        )

        self.config = None

        self.mtcs = None
        self.lsstcam = None
        self.mtm1m3ts = None
        self.homing_attempts = 10

    @classmethod
    def get_schema(cls):
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_maintel_standardscripts/prepare_for/flat.yaml
            title: PrepareForFlat v1
            description: >-
                Configuration for PrepareForFlat. This script prepares the
                telescope for flat-field operations by enabling the required
                components and setting them to the appropriate states.
            type: object
            properties:
                ignore:
                    description: >-
                        CSCs from the group to ignore, e.g.; mthexapod_1.
                        Critical components required for flat-field operations
                        should be ignored (e.g., mtmount, mtrotator, mtm1m3,
                        mtm2, mtptg, etc).
                    type: array
                    items:
                        type: string
                homing_attempts:
                    description: Number of attempts to home both axes.
                    type: integer
                    default: 10
                    minimum: 1
            additionalProperties: false
        """
        return yaml.safe_load(schema_yaml)

    async def configure_tcs(self) -> None:
        """Initialize MTCS if not already initialized."""
        if self.mtcs is None:
            self.log.debug("Creating MTCS instance.")
            self.mtcs = MTCS(
                self.domain,
                log=self.log,
                intended_usage=MTCSUsages.All,
            )
            await self.mtcs.start_task
        else:
            self.log.debug("MTCS already initialized.")

    async def configure_camera(self) -> None:
        """Initialize LSST Camera if not already initialized."""
        if self.lsstcam is None:
            self.log.debug("Creating LSST Camera instance.")
            self.lsstcam = LSSTCam(
                self.domain, intended_usage=LSSTCamUsages.StateTransition, log=self.log
            )
            await self.lsstcam.start_task
        else:
            self.log.debug("LSST Camera already initialized.")

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
        await self.configure_mtm1m3ts()

        if hasattr(config, "ignore"):
            self.mtcs.disable_checks_for_components(components=config.ignore)
            self.lsstcam.disable_checks_for_components(components=config.ignore)

        if hasattr(config, "homing_attempts"):
            self.homing_attempts = config.homing_attempts

    def set_metadata(self, metadata):
        metadata.duration = 600.0

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
                "Please disable engineering mode on MTM1M3TS before flat-field operations.\n"
                "Check the troubleshooting documentation for more information."
            )

    async def run(self):

        await self.checkpoint(
            "Preparing for flat-field operations. Telescope and dome will move."
        )

        await self.lsstcam.assert_all_enabled(
            message="All LSSTCam components need to be enabled to prepare for flat-field operations."
        )
        await self.mtcs.prepare_for_flatfield(homing_attempts=self.homing_attempts)

        await self.checkpoint("Assert that MTM1M3TS is not in engineering mode.")
        await self.assert_mtm1m3ts_not_in_engineering_mode()

        self.log.info("Prepare for flat-field operations completed successfully.")
