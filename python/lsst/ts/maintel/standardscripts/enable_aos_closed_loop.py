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

__all__ = ["EnableAOSClosedLoop"]

import yaml
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages
from lsst.ts.standardscripts.base_block_script import BaseBlockScript

CMD_TIMEOUT = 100


class EnableAOSClosedLoop(BaseBlockScript):
    """Enable AOS Closed Loop task to run in parallel to survey mode imaging.

    Parameters
    ----------
    index : `int`
        Index of Script SAL component.

    Notes
    -----
    **Checkpoints**

    - "Enabling AOS Closed Loop": Enable AOS Closed Loop.
    """

    def __init__(self, index: int) -> None:
        super().__init__(
            index=index,
            descr="Enable AOS Closed Loop.",
        )
        self.mtcs = None

    async def configure_tcs(self) -> None:
        if self.mtcs is None:
            self.log.debug("Creating MTCS.")
            self.mtcs = MTCS(
                domain=self.domain, log=self.log, intended_usage=MTCSUsages.Slew
            )
            await self.mtcs.start_task
        else:
            self.log.debug("MTCS already defined, skipping.")

    @classmethod
    def get_schema(cls):
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_standardscripts/maintel/enable_aos_closed_loop.yaml
            title: EnableAOSClosedLoop v1
            description: Configuration for EnableAOSClosedLoop
            type: object
            properties:
                mtaos_config:
                    description: Configuration for MTAOS closed loop. Optional.
                    type: object
                    additionalProperties: true
            additionalProperties: false
        """
        schema_dict = yaml.safe_load(schema_yaml)

        base_schema_dict = super().get_schema()

        for properties in base_schema_dict["properties"]:
            schema_dict["properties"][properties] = base_schema_dict["properties"][
                properties
            ]

        return schema_dict

    async def configure(self, config):
        self.config = yaml.dump(getattr(config, "mtaos_config", {}))
        await self.configure_tcs()

        await super().configure(config=config)

    def set_metadata(self, metadata):
        metadata.duration = CMD_TIMEOUT

    async def run_block(self):
        """Enable AOS Closed Loop task to run
        in parallel to survey mode imaging.
        """
        await self.checkpoint("Enabling AOS Closed Loop")
        await self.mtcs.rem.mtaos.cmd_startClosedLoop.set_start(
            config=self.config, timeout=CMD_TIMEOUT
        )
