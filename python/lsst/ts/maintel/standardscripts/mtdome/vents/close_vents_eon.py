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

__all__ = ["CloseVentsEON"]

import yaml
from lsst.ts import salobj


class CloseVentsEON(salobj.BaseScript):
    """Close dome vents and stop the fan at the end of night.

    This script:
    - Stops the dome fan
    - Closes all louvers in the dome

    Parameters
    ----------
    index : `int`
        Index of Script SAL component.
    """

    DEFAULT_LOUVERS_TIMEOUT = 60  # seconds
    DEFAULT_FANS_TIMEOUT = 30  # seconds
    DEFAULT_METADATA_DURATION = 300.0  # seconds

    def __init__(self, index):
        super().__init__(
            index=index, descr="Close dome vents and stop fan at end of night."
        )

        self.mtdome = None

        self.louvers_timeout = self.DEFAULT_LOUVERS_TIMEOUT
        self.fans_timeout = self.DEFAULT_FANS_TIMEOUT
        self.metadata_duration = self.DEFAULT_METADATA_DURATION

    @classmethod
    def get_schema(cls):
        url = "https://github.com/lsst-ts/"
        path = (
            "ts_maintel_standardscripts/python/lsst/ts/maintel/standardscripts/"
            "mtdome/vents/close_vents_eon.py"
        )

        schema_yaml = f"""
            $schema: http://json-schema.org/draft-07/schema#
            $id: {url}{path}
            title: CloseVentsEON v1
            description: Configuration for End of Night vent operations
            type: object
            additionalProperties: false
        """

        return yaml.safe_load(schema_yaml)

    def set_metadata(self, metadata):
        metadata.duration = self.metadata_duration

    async def configure(self, config):
        if self.mtdome is None:
            self.mtdome = salobj.Remote(domain=self.domain, name="MTDome")
            await self.mtdome.start_task

    async def run(self):
        self.log.info("Stopping dome fan")
        await self.mtdome.cmd_fans.set_start(speed=0.0, timeout=self.fans_timeout)
        self.log.info("Dome fan stopped")

        self.log.info("Closing all louvers")
        await self.mtdome.cmd_closeLouvers.start(timeout=self.louvers_timeout)
        self.log.info("All louvers closed")

        self.log.info("End of night vent operations completed")
