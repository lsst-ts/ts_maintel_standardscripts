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

import numpy as np
import yaml
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages
from lsst.ts.observatory.control.utils.enums import DOFName
from lsst.ts.standardscripts.base_block_script import BaseBlockScript


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
        schema_yaml = f"""
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_standardscripts/maintel/enable_aos_closed_loop.yaml
            title: EnableAOSClosedLoop v2
            description: Configuration for EnableAOSClosedLoop
            type: object
            properties:
                used_dofs:
                    oneOf:
                    - type: array
                      items:
                        type: integer
                        minimum: 0
                        maximum: 49
                    - type: array
                      items:
                        type: string
                        enum: {[dof_name.name for dof_name in DOFName]}
                    default: [1, 2, 3, 4, 5]
                truncation_index:
                    description: >-
                        Truncation index to use for the estimating the state.
                    type: integer
                    default: 20
                zn_selected:
                    description: >-
                        Zernike coefficients to use.
                    type: array
                    default: []
                    items:
                        type: integer
                        minimum: 0
                        maximum: 28
                    default: [4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 20, 21, 22, 27, 28]
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
        await self.configure_tcs()

        self.truncation_index = config.truncation_index
        self.zn_selected = config.zn_selected

        selected_dofs = config.used_dofs
        if isinstance(selected_dofs[0], str):
            selected_dofs = [getattr(DOFName, dof) for dof in selected_dofs]
        self.used_dofs = np.zeros(50)
        self.used_dofs[selected_dofs] = 1

        await super().configure(config=config)

    def set_metadata(self, metadata):
        metadata.duration = self.mtcs.aos_closed_loop_timeout

    async def run_block(self):
        """Enable AOS Closed Loop task to run
        in parallel to survey mode imaging.
        """
        await self.checkpoint("Enabling AOS Closed Loop")
        config = {
            "zn_selected": self.zn_selected,
            "truncation_index": self.truncation_index,
            "comp_dof_idx": {
                "m2HexPos": [float(val) for val in self.used_dofs[:5]],
                "camHexPos": [float(val) for val in self.used_dofs[5:10]],
                "M1M3Bend": [float(val) for val in self.used_dofs[10:30]],
                "M2Bend": [float(val) for val in self.used_dofs[30:]],
            },
        }
        config_yaml = yaml.safe_dump(config)

        await self.mtcs.enable_aos_closed_loop(config=config_yaml)
