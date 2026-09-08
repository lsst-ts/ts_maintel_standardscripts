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

__all__ = ["SetOperationalModeDome"]

import operator
from functools import reduce

import yaml
from lsst.ts import salobj
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages
from lsst.ts.xml.enums.MTDome import OperationalMode, SubSystemId


class SetOperationalModeDome(salobj.BaseScript):
    """Sets the MTDome operational mode.

    Parameters
    ----------
    index : `int`
        Index of Script SAL component.
    """

    def __init__(self, index):
        super().__init__(index=index, descr="Sets the MTDome operational mode.")
        self.mtcs = None

    @classmethod
    def get_schema(cls):
        url = "https://github.com/lsst-ts/"
        path = (
            "ts_maintel_standardscripts/maintel/mtdome/set_operational_mode_dome.yaml"
        )
        schema_yaml = f"""
            $schema: http://json-schema.org/draft-07/schema#
            $id: {url}{path}
            title: ExitFaultDome v1
            description: Configuration for SetOperationalModeDome.
            type: object
            properties:
              mode:
                description: The target operational mode.
                type: string
                enum: {[mode.name for mode in OperationalMode]}
                default: NORMAL
              subsystems:
                description: The target subsystems.
                type: array
                items:
                  type: string
                  enum: {[subsystem.name for subsystem in SubSystemId]}
                default: ['APSCS']
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

        self.target_mode = OperationalMode[config.mode]

        self.subsystems_mask = reduce(
            operator.or_, [SubSystemId[name] for name in config.subsystems]
        )

    def set_metadata(self, metadata):
        metadata.duration = self.mtcs.fast_timeout

    async def run(self):
        await self.mtcs.rem.mtdome.cmd_setOperationalMode.set_start(
            operationalMode=self.target_mode,
            subSystemIds=self.subsystems_mask,
            timeout=self.mtcs.fast_timeout,
        )
