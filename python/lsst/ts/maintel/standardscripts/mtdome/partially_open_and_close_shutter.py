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
import logging
import types

import yaml
from lsst.ts import salobj
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages
from lsst.ts.xml.enums import MTDome, MTMount


class PartiallyOpenAndCloseShutter(salobj.BaseScript):
    """Partially open and close the dome shutter.

    This script is part of the MTDome handover procedure. It performs the
    following steps:

    - Open the shutter.
    - Wait some seconds (depending on the MTDome operational mode) to reach an
      aperture level of ~ 60 cm.
    - Stop the shutter.
    - Close the shutter.

    Parameters
    ----------
    index : `int`
        Index of the Script SAL component.
    """

    def __init__(self, index: int) -> None:
        super().__init__(
            index=index,
            descr="Partially open and close the dome shutter.",
        )

        self.mtcs = None

        self.partially_open_target_level = 0.6  # in meters
        # Shutter opening speeds for each dome operational mode
        self.shutter_speed = {
            "NORMAL": 0.04,  # m/s
            "DEGRADED": 0.01,  # m/s
        }
        self.script_queue_latency = 5.0  # segs
        self.sleep_time_before_close = 1.0  # segs
        self.telescope_horizon_elevation = 15.0  # deg
        self.sleep_time = None

    @classmethod
    def get_schema(cls):
        url = "https://github.com/lsst-ts/"
        path = "ts_maintel_standardscripts/maintel/mtdome/partially_open_and_close_shutter.yaml"
        schema_yaml = f"""
            $schema: http://json-schema.org/draft-07/schema#
            $id: {url}{path}
            title: PartiallyOpenAndCloseShutter v1
            description: Configuration for PartiallyOpenAndCloseShutter.
            type: object
            properties:
              override_sleep_time:
                type: number
                description: >-
                  If this parameter is provided, forces a wait of the specified
                  number of seconds before sending the shutter stop command. If
                  this parameter is not provided, the sleep time is determined
                  based on the current operational mode of the MTDome.
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

        if self.mtcs is None:
            self.log.debug("Creating MTCS.")
            self.mtcs = MTCS(
                domain=self.domain,
                intended_usage=MTCSUsages.Slew,
                log=self.log,
            )
            await self.mtcs.start_task

        if not hasattr(config, "override_sleep_time"):
            # Get current dome operational mode
            self.mtcs.rem.mtdome.evt_operationalMode.flush()
            operational_mode = await self.mtcs.rem.mtdome.evt_operationalMode.aget(
                timeout=self.mtcs.fast_timeout
            )
            # Use the apropieate shutter speed value
            shutter_current_speed = self.shutter_speed[operational_mode.name]
            # Calculate necesary sleep time
            self.sleep_time = self.calculate_sleep_time(
                aperture_level=self.partially_open_target_level,
                shutter_speed=shutter_current_speed,
                queue_latency=self.script_queue_latency,
            )
            self.log.log(
                level=(
                    logging.INFO
                    if operational_mode == MTDome.OperationalMode.NORMAL
                    else logging.WARNING
                ),
                msg=(
                    f"The dome operational mode is {operational_mode!r}, "
                    f"setting {self.sleep_time} segs for sleep time."
                ),
            )
        else:
            self.log.warning(
                f"Overriding sleep time with value {config.override_sleep_time} segs"
            )
            self.sleep_time = config.override_sleep_time

    @staticmethod
    def calculate_sleep_time(
        aperture_level: float, shutter_speed: float, queue_latency: float
    ) -> float:
        """Calculates the required sleep time before sending the stop command.

        This ensures that the shutter reaches the specified ``aperture_level``
        (in meters), given the shutter opening speed and an estimated script
        queue latency.

        Parameters
        ----------
        aperture_level : `float`
            Target shutter aperture level in meters.
        shutter_speed : `float`
            Current shutter opening speed in meters per second (m/s).
        queue_latency : `float`
            Estimated time, in seconds, for the close command to be executed
            after it is sent.

        Returns
        -------
        sleep_time : `float`
            Time, in seconds, to wait before sending the close command so that
            the shutter reaches ``aperture_level``.
        """
        return aperture_level / shutter_speed - queue_latency

    def set_metadata(self, metadata) -> None:
        metadata.duration = (
            self.sleep_time + self.sleep_time_before_close + self.mtcs.fast_timeout
        )

    async def run(self) -> None:
        # Check TMA status
        mtmount_elevation = await self.mtcs.rem.mtmount.tel_elevation.aget(
            timeout=self.mtcs.fast_timeout
        )
        mtmount_parked_at_horizon = (
            mtmount_elevation.actualPosition <= self.telescope_horizon_elevation
        )
        # Check mirror covers status
        covers_state = await self.mtcs.rem.mtmount.evt_mirrorCoversMotionState.aget(
            timeout=self.mtcs.fast_timeout
        )
        covers_retracted = covers_state.state == MTMount.DeployableMotionState.RETRACTED
        # Check shutter status
        shutter_state = await self.mtcs.rem.mtdome.evt_shutterMotion.aget(
            timeout=self.mtcs.fast_timeout
        )
        shutter_state.state = [
            MTDome.MotionState(value) for value in shutter_state.state
        ]
        shutter_fully_closed = all(
            state == MTDome.MotionState.CLOSED for state in shutter_state.state
        )
        # Check script pre-conditions are met
        if mtmount_parked_at_horizon and covers_retracted and shutter_fully_closed:
            # Initiate the shutter opening
            await self.mtcs.rem.mtdome.cmd_openShutter.start(
                timeout=self.mtcs.long_timeout
            )
            # Wait for the shutter to reach the desired aperture level
            self.log.info(
                f"Sleep for {self.sleep_time} seconds, waiting for the shutter to reach "
                f"~ {self.partially_open_target_level * 100:.0f} cm of aperture level."
            )
            await self.checkpoint(
                f"Sleep for {self.sleep_time} seconds, waiting for the shutter to reach "
                f"~ {self.partially_open_target_level * 100:.0f} cm of aperture level."
            )
            await asyncio.sleep(self.sleep_time)
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
        else:
            raise RuntimeError(
                "The M1M3 mirror covers must be retracted, the TMA must be "
                "parked at horizon, and the dome shutter must be fully closed. "
                f"Current covers state: {MTMount.DeployableMotionState(covers_state.state)!r}. "
                f"Current TMA elevation: {mtmount_elevation.actualPosition} "
                f"Current shutter state: {shutter_state.state!r}."
            )
