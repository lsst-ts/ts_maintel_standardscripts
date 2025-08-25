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
# along with this program.  If not, see <https://www.gnu.org/licenses/>.``

__all__ = ["HomeBothAxes"]

import asyncio
import time

import yaml
from lsst.ts import salobj
from lsst.ts.idl.enums.Script import ScriptState
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages


class HomeBothAxes(salobj.BaseScript):
    """Home azimuth and elevation axes of the MTMount.
    Must call this after powering on the main axis and
    BEFORE you move them.

    Parameters
    ----------
    index : `int`
        Index of Script SAL component.

    Notes
    -----
    **Checkpoints**

    - "Homing Both Axes": Before commanding both axes to be homed.

    **Details**

    This script homes both aximuth and elevation axes of
    the Simonyi Main Telescope mount.


    """

    def __init__(self, index, add_remotes: bool = True):
        super().__init__(index=index, descr="Home both TMA axis.")

        self.disable_m1m3_force_balance = False
        self.home_both_axes_timeout = 300.0  # timeout to home both MTMount axes.
        self.mtcs = None
        self.final_home_position = None

    @classmethod
    def get_schema(cls):
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_standardscripts/maintel/enable_mtcs.yaml
            title: HomeBothAxes v1
            description: Configuration for HomeBothAxes.
            type: object
            properties:
                ignore_m1m3:
                    description: Ignore the m1m3 component? (Deprecated property)
                    type: boolean
                disable_m1m3_force_balance:
                    description: Disable m1m3 force balance?
                    type: boolean
                    default: false
                final_home_position:
                    description: >-
                        Azimuth and Elevation position to home the axes at. If provided, the script will first
                        home both axes at the current Az/El position of the MTMount, then slew to the provided
                        az/el values in the final_home_position, and then home both axes a second time. If not
                        provided, the script will only home the axes once at its current position.
                    type: object
                    required:
                        - az
                        - el
                    properties:
                        az:
                            description: Azimuth to do final home at (deg).
                            anyOf:
                            - type: number
                        el:
                            description: Elevation to do final home at (deg).
                            anyOf:
                            - type: number
                              minimum: 0
                              maximum: 90

            additionalProperties: false
        """
        return yaml.safe_load(schema_yaml)

    async def configure(self, config):
        if self.mtcs is None:
            self.mtcs = MTCS(
                domain=self.domain, intended_usage=MTCSUsages.Slew, log=self.log
            )
            await self.mtcs.start_task

        if hasattr(config, "ignore_m1m3"):
            self.log.warning(
                "The 'ignore_m1m3' configuration property is deprecated and will be removed"
                " in future releases. Please use 'disable_m1m3_force_balance' instead.",
                DeprecationWarning,
                stacklevel=2,
            )
        self.disable_m1m3_force_balance = config.disable_m1m3_force_balance

        if hasattr(config, "final_home_position"):
            self.final_home_position = config.final_home_position

        if self.disable_m1m3_force_balance and (self.final_home_position is not None):
            raise ValueError(
                "Both 'disable_m1m3_force_balance' and 'final_home_position' are set. "
                "These options are not intended to be used together."
            )

    def set_metadata(self, metadata):
        metadata.duration = self.home_both_axes_timeout

    async def run(self):
        if self.disable_m1m3_force_balance:
            await self.checkpoint("Disable M1M3 balance system.")
            await self.mtcs.disable_m1m3_balance_system()

        await self.checkpoint("Homing Both Axes at current position")
        start_time = time.time()
        await self.mtcs.rem.mtmount.cmd_homeBothAxes.start(
            timeout=self.home_both_axes_timeout
        )
        end_time = time.time()
        elapsed_time = end_time - start_time

        self.log.info(f"Homing both axes took {elapsed_time:.2f} seconds")

        if not self.disable_m1m3_force_balance:
            self.log.info("Enabling M1M3 balance system.")
            await self.mtcs.enable_m1m3_balance_system()

        if self.final_home_position is not None:
            await self.checkpoint("Slewing TMA to final home position")
            await self.mtcs.point_azel(
                az=self.final_home_position["az"],
                el=self.final_home_position["el"],
                wait_dome=False,
            )

            await self.mtcs.stop_tracking()

            await self.checkpoint("Homing Both Axes at final position")
            start_time = time.time()
            await self.mtcs.rem.mtmount.cmd_homeBothAxes.start(
                timeout=self.home_both_axes_timeout
            )
            end_time = time.time()
            elapsed_time = end_time - start_time

            self.log.info(f"Homing both axes took {elapsed_time:.2f} seconds")

    async def cleanup(self):
        if self.state.state != ScriptState.STOPPING:
            # abnormal termination
            self.log.warning(
                f"Terminating with state={self.state.state}: stop telescope."
            )
            try:
                await self.mtcs.stop_tracking()
            except asyncio.TimeoutError:
                self.log.exception(
                    "Stop tracking command timed out during cleanup procedure."
                )
            except Exception:
                self.log.exception("Unexpected exception while stopping telescope.")
