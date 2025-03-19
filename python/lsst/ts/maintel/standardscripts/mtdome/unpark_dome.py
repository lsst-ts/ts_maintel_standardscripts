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

__all__ = ["UnparkDome"]

import yaml
from lsst.ts import salobj
from lsst.ts.observatory.control.maintel.mtcs import MTCS


class UnparkDome(salobj.BaseScript):
    """Unpark Dome for the MTDome.

    Parameters
    ----------
    index : `int`
        Index of Script SAL component.

    Notes
    -----
    **Checkpoints**

    None

    """

    def __init__(self, index):
        super().__init__(index=index, descr="Unpark Dome for the MTDome.")

        self.mtcs = None

    @classmethod
    def get_schema(cls):
        schema_yaml = """
            $schema: http://json-schema/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_standardscripts/maintel/mtdome/unpark_dome.yaml
            title: UnparkDome v1
            description: Configuration for UnparkDome.
            type: object
            properties:
              ignore:
                  description: >-
                    CSCs from the group to ignore in status check. Name must
                    match those in self.group.components, e.g.; hexapod_1.
                  type: array
                  items:
                    type: string
            additionalProperties: false
        """
        return yaml.safe_load(schema_yaml)

    async def configure(self, config):
        if self.mtcs is None:
            self.mtcs = MTCS(domain=self.domain, log=self.log)
            await self.mtcs.start_task

        if hasattr(config, "ignore"):
            self.mtcs.disable_checks_for_components(components=config.ignore)

    def set_metadata(self, metadata):
        metadata.duration = 5.0

    async def run(self):
        await self.mtcs.assert_all_enabled()
        await self.mtcs.unpark_dome()
