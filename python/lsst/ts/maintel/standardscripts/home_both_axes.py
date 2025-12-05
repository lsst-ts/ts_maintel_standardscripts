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
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages
from lsst.ts.xml.enums.MTM1M3 import DetailedStates
from lsst.ts.xml.enums.Script import ScriptState


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
                    description: >-
                        Disable the M1M3 force balance system before homing.
                        This configuration option is deprecated and will be
                        removed in a future release; the script now always
                        ensures the force balance system is enabled before
                        homing.
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
                " in future releases.",
                stacklevel=2,
                exc_info=DeprecationWarning(),
            )
        if hasattr(config, "disable_m1m3_force_balance"):
            self.log.warning(
                "The 'disable_m1m3_force_balance' configuration property is deprecated "
                "and will be removed in future releases. The script now always enables "
                "the M1M3 force balance system before homing.",
                stacklevel=2,
                exc_info=DeprecationWarning(),
            )

        if hasattr(config, "final_home_position"):
            self.final_home_position = config.final_home_position

    def set_metadata(self, metadata):
        metadata.duration = self.home_both_axes_timeout

    async def assert_m1m3_raised(self) -> None:
        """Assert that M1M3 is raised (ACTIVE or ACTIVEENGINEERING).

        Raises
        ------
        RuntimeError
            If M1M3 is not in a raised detailed state.
        """
        detailed_state = DetailedStates(
            (
                await self.mtcs.rem.mtm1m3.evt_detailedState.aget(
                    timeout=self.mtcs.fast_timeout
                )
            ).detailedState
        )
        if detailed_state not in {
            DetailedStates.ACTIVE,
            DetailedStates.ACTIVEENGINEERING,
        }:
            raise RuntimeError(
                "M1M3 mirror is not raised (detailed state is "
                f"{detailed_state.name}). Please raise M1M3 before homing MTMount. "
                "If you are unable to raise M1M3 at the current TMA position, you "
                "might have to move TMA to an appropriate range and raise the mirror "
                "before homing. See BLOCK-T250 for more information."
            )

    async def get_current_azimuth(self):
        mount_az = await self.mtcs.rem.mtmount.tel_azimuth.next(
            flush=True,
            timeout=self.mtcs.fast_timeout,
        )
        return mount_az.actualPosition

    async def get_current_elevation(self):
        mount_el = await self.mtcs.rem.mtmount.tel_elevation.next(
            flush=True,
            timeout=self.mtcs.fast_timeout,
        )
        return mount_el.actualPosition

    async def run(self):
        await self.assert_m1m3_raised()

        self.log.info("Ensuring M1M3 force balance system is enabled before homing.")
        await self.mtcs.enable_m1m3_balance_system()

        await self.checkpoint("Homing Both Axes at current position")
        start_time = time.time()
        async with self.mtcs.m1m3_booster_valve():
            await self.mtcs.rem.mtmount.cmd_homeBothAxes.start(
                timeout=self.home_both_axes_timeout
            )
        end_time = time.time()
        elapsed_time = end_time - start_time
        self.log.info(f"Homing both axes took {elapsed_time:.2f} seconds")

        if self.final_home_position is not None:

            self.log.info(
                f"Slewing azimuth only to: {self.final_home_position['az']} deg."
            )
            current_el = await self.get_current_elevation()
            await self.mtcs.point_azel(
                az=self.final_home_position["az"],
                el=current_el,
                wait_dome=False,
            )

            self.log.info(
                f"Slewing elevation only to: {self.final_home_position['el']} deg."
            )
            current_az = await self.get_current_azimuth()
            await self.mtcs.point_azel(
                az=current_az,
                el=self.final_home_position["el"],
                wait_dome=False,
            )

            await self.mtcs.stop_tracking()

            await self.checkpoint("Homing Both Axes at final position")
            start_time = time.time()
            async with self.mtcs.m1m3_booster_valve():
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
