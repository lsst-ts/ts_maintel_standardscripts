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

__all__ = ["ExitFaultDome"]

import operator
from functools import reduce

import yaml
from lsst.ts import salobj
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages
from lsst.ts.xml.enums.MTDome import SubSystemId


class ExitFaultDome(salobj.BaseScript):
    """Sends the exitFault command to the MTDome.

    Parameters
    ----------
    index : `int`
        Index of Script SAL component.
    """

    def __init__(self, index):
        super().__init__(
            index=index, descr="Sends the exitFault command to the MTDome."
        )
        self.mtcs = None

    @classmethod
    def get_schema(cls):
        schema_yaml = f"""
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_maintel_standardscripts/maintel/mtdome/exit_fault_dome.yaml
            title: ExitFaultDome v1
            description: Configuration for ExitFaultDome.
            type: object
            properties:
              subsystems:
                description: The target subsystems.
                type: array
                items:
                  type: string
                  enum: {[subsystem.name for subsystem in SubSystemId]}
                default: ['AMCS']
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
            self.log.debug("Creating MTCS.")
            self.mtcs = MTCS(
                domain=self.domain,
                intended_usage=MTCSUsages.Slew,
                log=self.log,
            )
            await self.mtcs.start_task

        self.subsystems_mask = reduce(
            operator.or_, [SubSystemId[name] for name in config.subsystems]
        )

    def set_metadata(self, metadata):
        metadata.duration = self.mtcs.fast_timeout

    async def run(self):
        await self.mtcs.rem.mtdome.cmd_exitFault.set_start(
            subSystemIds=self.subsystems_mask,
            timeout=self.mtcs.fast_timeout,
        )
