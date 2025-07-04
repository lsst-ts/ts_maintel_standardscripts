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

__all__ = ["OpenDome"]

import yaml
from lsst.ts import salobj
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages


class OpenDome(salobj.BaseScript):
    """Open MTDome shutter door.

    Parameters
    ----------
    index : `int`
        Index of Script SAL component.

    Notes
    -----
    **Checkpoints**

    Opening dome: Before commanding dome shutter to be opened.
    """

    def __init__(self, index):
        super().__init__(index=index, descr="Open MTDome shutter.")

        self.mtcs = None

    @classmethod
    def get_schema(cls):
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_maintel_standardscripts/maintel/mtdome/open_dome.yaml
            title: OpenDome v1
            description: Configuration for OpenDome.
            type: object
            properties:
              force:
                description: Force opening regardless of conditions.
                type: boolean
                default: false
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
        """Configure script.

        Parameters
        ----------
        config : `types.SimpleNamespace`
            Script configuration, as defined by `schema`.
        """
        self.config = config

        if self.mtcs is None:
            self.mtcs = MTCS(
                domain=self.domain,
                intended_usage=MTCSUsages.Slew | MTCSUsages.StateTransition,
                log=self.log,
            )
            await self.mtcs.start_task

        if hasattr(self.config, "ignore"):
            self.mtcs.disable_checks_for_components(components=config.ignore)

    def set_metadata(self, metadata):
        metadata.duration = self.mtcs.open_dome_shutter_time

    async def run(self):
        await self.mtcs.assert_all_enabled()
        await self.checkpoint("Opening dome")
        await self.mtcs.open_dome_shutter(force=self.config.force)
