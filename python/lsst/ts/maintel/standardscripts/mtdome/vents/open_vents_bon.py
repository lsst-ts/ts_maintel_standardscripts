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
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

__all__ = ["OpenVentsBON"]

import yaml
from lsst.ts import salobj
from lsst.ts.xml.enums.MTDome import Louver


class OpenVentsBON(salobj.BaseScript):
    """Open dome vents and start the fan at the beginning of night.

    This script:
    - Opens all louvers in the dome
    - Starts the dome fan at the specified speed (default 25 Hz)

    Parameters
    ----------
    index : `int`
        Index of Script SAL component.
    """

    # Default constants at class level
    DEFAULT_LOUVERS_TIMEOUT = 60  # seconds
    DEFAULT_FANS_TIMEOUT = 30  # seconds
    DEFAULT_METADATA_DURATION = 300.0  # seconds
    DEFAULT_FAN_HZ = 25.0  # Default fan speed in Hz
    MAX_FAN_HZ = 50.0  # Maximum fan speed
    DEFAULT_LOUVER_PERCENT = 100.0

    def __init__(self, index):
        super().__init__(
            index=index, descr="Open dome vents and start fan at beginning of night."
        )

        self.mtdome = None
        self.fan_hz = self.DEFAULT_FAN_HZ
        self.max_fan_hz = self.MAX_FAN_HZ  # TBD, using same value as in
        # ts_atbuilding_vents/python/lsst/ts/vent/
        # controller/config.py
        self.louver_percent = self.DEFAULT_LOUVER_PERCENT

        self.louvers_timeout = self.DEFAULT_LOUVERS_TIMEOUT
        self.fans_timeout = self.DEFAULT_FANS_TIMEOUT
        self.metadata_duration = self.DEFAULT_METADATA_DURATION

    @classmethod
    def get_schema(cls):
        url = "https://github.com/lsst-ts/"
        path = (
            "ts_maintel_standardscripts/python/lsst/ts/maintel/standardscripts/"
            "mtdome/vents/open_vents_bon.py"
        )

        schema_yaml = f"""
            $schema: http://json-schema.org/draft-07/schema#
            $id: {url}{path}
            title: OpenVentsBON v1
            description: Configuration for Beginning of Night vent operations
            type: object
            properties:
                fan_speed_hz:
                    description: Fan speed in Hz. Default = 25 Hz. Maximum = 50 Hz.
                    type: number
                    default: 25.0
                    minimum: 0.0
                    maximum: 50.0
                louver_percent_open:
                    description: Percent to open louvers. Default = 100%.
                    type: number
                    default: 100.0
                    minimum: 0.0
                    maximum: 100.0
            additionalProperties: false
        """

        return yaml.safe_load(schema_yaml)

    def set_metadata(self, metadata):
        metadata.duration = self.metadata_duration

    async def configure(self, config):
        """Configure the script.

        Parameters
        ----------
        config : `types.SimpleNamespace`
            Script configuration, as defined by `get_schema`.
        """
        self.log.info("Configuring script")
        self.config = config

        if hasattr(config, "fan_speed_hz"):
            self.fan_hz = config.fan_speed_hz
            self.log.info(f"Fan speed set to {self.fan_hz} Hz")

        if hasattr(config, "louver_percent_open"):
            self.louver_percent = config.louver_percent_open
            self.log.info(f"Louver percent open set to {self.louver_percent}%")

        if self.mtdome is None:
            self.mtdome = salobj.Remote(domain=self.domain, name="MTDome")
            await self.mtdome.start_task

    async def run(self):
        self.log.info(f"Opening all louvers to {self.louver_percent}%")

        num_louvers = len(Louver.__members__)

        louver_positions = [self.louver_percent] * num_louvers

        await self.mtdome.cmd_setLouvers.set_start(
            position=louver_positions, timeout=self.louvers_timeout
        )
        self.log.info("All louvers opened")

        fan_percent = (self.fan_hz / self.max_fan_hz) * 100.0

        self.log.info(f"Starting dome fan at {self.fan_hz} Hz ({fan_percent:.1f}%)")
        await self.mtdome.cmd_fans.set_start(
            speed=fan_percent, timeout=self.fans_timeout
        )
        self.log.info("Dome fan started")

        self.log.info("Beginning of night vent operations completed")
