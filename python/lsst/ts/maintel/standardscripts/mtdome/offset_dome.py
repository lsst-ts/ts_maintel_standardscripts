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


__all__ = ["OffsetDome"]

import yaml
from lsst.ts import salobj
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages


class OffsetDome(salobj.BaseScript):
    """Script that executes relative movements with MTDome.

    This script will offset the dome by a user provided value.
    """

    def __init__(self, index):
        super().__init__(index=index, descr="MTDome OffsetDome.")

        self.mtcs = None
        self.slew_time_guess = 180

    @classmethod
    def get_schema(cls):
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_maintel_standardscripts/maintel/mtdome/offset_dome.py
            title: OffsetDome v1
            description: Configuration for OffsetDome
            type: object
            properties:
                offset:
                    description: Target offset (in degrees) to move the dome to.
                    type: number
                ignore:
                    description: >-
                      CSCs from the group to ignore in status check. Name must
                      match those in self.group.components, e.g.; hexapod_1.
                    type: array
                    items:
                      type: string
            additionalProperties: false
            required: [offset]
        """
        return yaml.safe_load(schema_yaml)

    async def configure(self, config):
        self.config = config
        self.offset = config.offset

        if self.mtcs is None:
            self.mtcs = MTCS(
                domain=self.domain,
                intended_usage=MTCSUsages.Slew,
                log=self.log,
            )
            await self.mtcs.start_task

        if hasattr(self.config, "ignore"):
            self.mtcs.disable_checks_for_components(components=config.ignore)

    def set_metadata(self, metadata) -> None:
        """Set script metadata.

        Parameters
        ----------
        metadata : `lsst.ts.salobj.base.ScriptMetadata`
            Script metadata.
        """
        metadata.duration = self.slew_time_guess

    async def run(self):
        if await self.mtcs.check_dome_following():
            raise RuntimeError(
                "Cannot proceed while dome following is enabled. "
                "Disable dome following before running this operation."
            )

        await self.mtcs.assert_all_enabled()

        current_position = await self.mtcs.rem.mtdome.tel_azimuth.aget(
            timeout=self.mtcs.fast_timeout
        )
        target_az = (current_position.positionActual + self.offset) % 360

        self.log.info(
            f"Applying MTDome offset by: {self.offset} deg. "
            f"Current position: {current_position.positionActual} deg. "
            f"Final position: {target_az} deg."
        )
        await self.mtcs.slew_dome_to(az=target_az)
