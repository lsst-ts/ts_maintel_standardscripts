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

__all__ = ["SetThermalLoopTargets"]

import yaml
from lsst.ts.observatory.control.maintel.mtcs import MTCS
from lsst.ts.standardscripts.base_block_script import BaseBlockScript

CMD_TIMEOUT = 100


class SetThermalLoopTargets(BaseBlockScript):
    """Set M1M3 setpoint targets for the thermal loop.

    Parameters
    ----------
    index : `int`
        Index of Script SAL component.
    """

    def __init__(self, index: int) -> None:
        super().__init__(
            index=index,
            descr="Set M1M3 setpoint targets for the thermal loop.",
        )
        self.mtcs = None

    async def configure_tcs(self) -> None:
        if self.mtcs is None:
            self.log.debug("Creating MTCS.")
            self.mtcs = MTCS(domain=self.domain, log=self.log)
            await self.mtcs.start_task
        else:
            self.log.debug("MTCS already defined, skipping.")

    @classmethod
    def get_schema(cls):
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_standardscripts/maintel/enable_aos_closed_loop.yaml
            title: SetThermalLoopTargets v1
            description: Configuration for SetThermalLoopTargets
            type: object
            properties:
                glycol_setpoint:
                    description: Glycol setpoint temperature in Celsius.
                    type: number
                heater_setpoint:
                    description: Heater setpoint temperature in Celsius.
                    type: number
            additionalProperties: false
            required:
              - glycol_setpoint
              - heater_setpoint
        """
        schema_dict = yaml.safe_load(schema_yaml)

        base_schema_dict = super().get_schema()

        for properties in base_schema_dict["properties"]:
            schema_dict["properties"][properties] = base_schema_dict["properties"][
                properties
            ]

        return schema_dict

    async def configure(self, config):
        await self.configure_tcs()

        self.glycol_setpoint = config.get("glycol_setpoint", None)
        self.heater_setpoint = config.get("heater_setpoint", None)

        await super().configure(config=config)

    def set_metadata(self, metadata):
        metadata.duration = CMD_TIMEOUT

    async def run_block(self):
        """Set M1M3 setpoint targets for the thermal loop."""
        await self.checkpoint("Setting M1M3TS thermal setpoint targets")
        await self.mtcs.rem.mtm1m3ts.cmd_applySetpoints.set_start(
            glycolSetpoint=self.glycol_setpoint,
            heaterSetpoint=self.heater_setpoint,
            timeout=CMD_TIMEOUT,
        )
