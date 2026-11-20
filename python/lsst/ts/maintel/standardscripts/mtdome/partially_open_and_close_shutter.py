# This file is part of ts_standardscripts
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

__all__ = ["PartiallyOpenAndCloseShutter"]

import asyncio
import types

import yaml
from lsst.ts import salobj
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages
from lsst.ts.xml.enums import MTDome, MTMount
from lsst.ts.xml.enums.Script import ScriptState


class PartiallyOpenAndCloseShutter(salobj.BaseScript):
    """Partially open and close the dome shutter.

    This script is part of the MTDome handover procedure. It performs the
    following steps:

    - Open the shutter.
    - Wait until the shutter reaches the specified partial aperture level.
    - Stop the shutter.
    - Close the shutter.

    Parameters
    ----------
    index : `int`
        Index of the Script SAL component.
    """

    SHUTTER_FULL_APERTURE = 11.0  # meters

    def __init__(self, index: int) -> None:
        super().__init__(
            index=index,
            descr="Partially open and close the dome shutter.",
        )

        self.mtcs = None

        self.opening_started = False
        self.sleep_time_before_close = 1.0  # segs
        self.telescope_horizon_elevation = 15.0  # deg

    @classmethod
    def get_schema(cls) -> dict:
        url = "https://github.com/lsst-ts/"
        path = "ts_maintel_standardscripts/maintel/mtdome/partially_open_and_close_shutter.yaml"
        schema_yaml = f"""
            $schema: http://json-schema.org/draft-07/schema#
            $id: {url}{path}
            title: PartiallyOpenAndCloseShutter v1
            description: Configuration for PartiallyOpenAndCloseShutter.
            type: object
            properties:
              target_aperture_level:
                type: number
                maximum: {cls.SHUTTER_FULL_APERTURE}
                description: >-
                  The desired target aperture level (in meters) that the shutter
                  doors must reach before being stopped and closed again.
                default: 0.6
            additionalProperties: false
            """
        return yaml.safe_load(schema_yaml)

    async def configure(self, config: types.SimpleNamespace) -> None:
        """Configure the script.

        Parameters
        ----------
        config : `types.SimpleNamespace`
            Configuration.
        """

        self.config = config
        if self.mtcs is None:
            self.log.debug("Creating MTCS.")
            self.mtcs = MTCS(
                domain=self.domain,
                intended_usage=MTCSUsages.Slew,
                log=self.log,
            )
            await self.mtcs.start_task
        # Convert aperture from meters to percentage
        self.target_position = (
            self.config.target_aperture_level / self.SHUTTER_FULL_APERTURE
        ) * 100

    def set_metadata(self, metadata) -> None:
        shutter_speed_fast = 0.04  # m/s
        shutter_speed_slow = 0.01  # m/s
        shutter_speed_avg = (shutter_speed_fast + shutter_speed_slow) * 0.5
        metadata.duration = (
            self.config.target_aperture_level / shutter_speed_avg
            + self.sleep_time_before_close
            + self.mtcs.fast_timeout
        )

    async def mtmount_is_parked_at_horizon(self) -> bool:
        """Checks whether the TMA is parked at horizon.

        The check is based on the telescope elevation operational limit.

        """
        mtmount_elevation = await self.mtcs.rem.mtmount.tel_elevation.aget(
            timeout=self.mtcs.fast_timeout
        )
        return mtmount_elevation.actualPosition <= self.telescope_horizon_elevation

    async def mirror_covers_are_in_state(
        self, state: MTMount.DeployableMotionState
    ) -> bool:
        """Check whether the M1M3 mirror covers are in the specified state.

        Parameters
        ----------
        state : `MTMount.DeployableMotionState`
            State to compare against the current mirror covers state.

        Returns
        -------
        match : `bool`
            `True` if the current mirror covers state matches ``state``,
            otherwise `False`.
        """
        covers_state = await self.mtcs.rem.mtmount.evt_mirrorCoversMotionState.aget(
            timeout=self.mtcs.fast_timeout
        )
        return covers_state.state == state

    async def assert_mtdome_open_safety_conditions(self) -> None:
        """Assert that the safety conditions to open the dome shutter are met.

        The dome shutter can be safely opened in one of the following
        scenarios:
        - The mirror covers are deployed (closed).
        - The mirror covers are retracted (open) and the TMA is parked at the
          horizon.
        """
        if await self.mirror_covers_are_in_state(
            MTMount.DeployableMotionState.RETRACTED
        ):
            assert (
                await self.mtmount_is_parked_at_horizon()
            ), "The TMA must be parked at the horizon to open the dome with the mirror covers retracted."
        else:
            assert await self.mirror_covers_are_in_state(
                MTMount.DeployableMotionState.DEPLOYED
            ), "Mirror covers needs to be eather retracted or deployed."

    async def assert_shutter_fully_closed(self) -> None:
        """Assert that both doors of the dome shutter are closed."""
        shutter_state = await self.mtcs.rem.mtdome.evt_shutterMotion.aget(
            timeout=self.mtcs.fast_timeout
        )
        shutter_state.state = [
            MTDome.MotionState(value) for value in shutter_state.state
        ]
        assert all(
            state == MTDome.MotionState.CLOSED for state in shutter_state.state
        ), f"The shutter must be fully closed. Shutter state: {shutter_state!r}."

    async def start_shutter_opening(self) -> None:
        """Initiate the opening of the shutter."""
        self.opening_started = True
        await self.mtcs.rem.mtdome.cmd_openShutter.start(timeout=self.mtcs.long_timeout)

    async def wait_for_shutter_to_reach_aperture_level(self) -> None:
        """Wait for both dome shutter doors to reach the target position"""
        self.log.info(
            f"Waiting for the shutter doors to reach {self.target_position}% aperture."
        )
        doors_position = await self.mtcs.rem.mtdome.tel_apertureShutter.next(
            flush=True,
            timeout=self.mtcs.fast_timeout,
        )
        while all(
            position < self.target_position
            for position in doors_position.positionActual
        ):
            doors_position = await self.mtcs.rem.mtdome.tel_apertureShutter.next(
                timeout=self.mtcs.fast_timeout,
            )

    async def stop_and_close_shutter(self) -> None:
        """Stop the dome shutter and close."""
        self.log.info("Closing the dome shutter.")
        # Send the stop command to abort the opening process
        await self.mtcs.rem.mtdome.cmd_stop.set_start(
            engageBrakes=False,
            subSystemIds=MTDome.SubSystemId.APSCS,
            timeout=self.mtcs.fast_timeout,
        )
        # Close the shutter
        await asyncio.sleep(self.sleep_time_before_close)
        await self.mtcs.rem.mtdome.cmd_closeShutter.start(
            timeout=self.mtcs.long_timeout
        )

    async def run(self) -> None:
        await self.assert_shutter_fully_closed()
        await self.assert_mtdome_open_safety_conditions()

        await self.start_shutter_opening()
        await self.wait_for_shutter_to_reach_aperture_level()
        await self.stop_and_close_shutter()

    async def cleanup(self) -> None:
        if self.state.state != ScriptState.ENDING:
            # abnormal termination
            if self.opening_started:
                self.log.warning(
                    f"Terminating with state={self.state.state}: stop and close dome shutter."
                )
                try:
                    await asyncio.wait_for(
                        self.stop_and_close_shutter(),
                        timeout=self.mtcs.fast_timeout + self.mtcs.long_timeout,
                    )
                except asyncio.TimeoutError:
                    self.log.exception(
                        "Stop and close shutter operations timed out during the cleanup procedure."
                    )
                except Exception:
                    self.log.exception(
                        "Unexpected exception while stopping and closing the dome shutter."
                    )
