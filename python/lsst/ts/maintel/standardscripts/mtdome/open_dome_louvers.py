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

__all__ = ["OpenDomeLouvers"]

import yaml
from lsst.ts import salobj
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages
from lsst.ts.xml.enums import MTDome


class OpenDomeLouvers(salobj.BaseScript):
    """Open MTDome louvers.

    Parameters
    ----------
    index : `int`
        Index of Script SAL component.

    Notes
    -----
    **Checkpoints**

    Opening dome louvers: Before commanding dome louvers to be opened.
    """

    def __init__(self, index):
        super().__init__(index=index, descr="Open MTDome louvers.")

        self.mtcs = None
        self.position = None

    @classmethod
    def get_schema(cls):
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_maintel_standardscripts/maintel/mtdome/open_dome_louvers.yaml
            title: OpenDomeLouvers v1
            description: Configuration for OpenDomeLouvers.
            type: object
            properties:
              position:
                description: >-
                  Desired open percentage for each louver: 0 is fully closed, 100 is fully open and -1 keeps
                  the current position as it is. Options include: a single number (applied to all enabled
                  louvers), a dictionary of name/value pairs, or an array of 34 values for individual louvers.
                  Default action is to fully open all enabled louvers.
                anyOf:
                  - type: number
                  - type: object
                  - type: array
                default: 100
              ignore:
                description: >-
                  CSCs from the group to ignore in status check. Name must match those in
                  self.group.components, e.g.; hexapod_1.
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
                intended_usage=MTCSUsages.All,
                log=self.log,
            )
            await self.mtcs.start_task

        if hasattr(self.config, "ignore"):
            self.mtcs.disable_checks_for_components(components=config.ignore)

        match config.position:
            case int() | float() as open_percentage:
                self.position = [open_percentage] * 34
            case list() as open_percentage_list:
                self.position = open_percentage_list
            case dict() as open_percentage_dict:
                self.position = [-1] * 34
                for louver, value in open_percentage_dict.items():
                    self.position[MTDome.Louver[louver] - 1] = value
            case _:
                raise ValueError("Unsupported type for position configuration.")

    def set_metadata(self, metadata):
        metadata.duration = self.mtcs.long_timeout

    async def _get_enabled_louvers_in_position(self, disabled_louvers):
        louvers_state = await self.mtcs.rem.mtdome.evt_louversMotion.aget(
            timeout=self.mtcs.fast_timeout
        )
        enabled_louvers_in_position = [
            in_position
            for i, in_position in enumerate(louvers_state.inPosition)
            if i not in disabled_louvers
        ]

        return enabled_louvers_in_position

    async def run(self):
        await self.mtcs.assert_all_enabled()
        self.mtcs.rem.mtdome.evt_louversMotion.flush()
        louvers_state = await self.mtcs.rem.mtdome.evt_louversMotion.aget(
            timeout=self.mtcs.fast_timeout
        )

        # Check for disabled louvers
        disabled_louvers = [
            i
            for i, state in enumerate(louvers_state.state)
            if state == MTDome.MotionState.DISABLED
        ]
        if disabled_louvers:
            self.log.info(
                f"{[MTDome.Louver(louver + 1) for louver in disabled_louvers]} are disabled."
            )
            # Disabled louvers should not be commanded according to CSC
            # implementation
            self.position = [
                (-1 if i in disabled_louvers else position)
                for i, position in enumerate(self.position)
            ]

        await self.checkpoint("Opening dome louvers")
        self.log.info("Opening dome louvers.")
        await self.mtcs.rem.mtdome.cmd_setLouvers.set_start(
            position=self.position, timeout=self.mtcs.long_timeout
        )
        enabled_louvers_in_position = await self._get_enabled_louvers_in_position(
            disabled_louvers
        )
        while not all(enabled_louvers_in_position):
            enabled_louvers_in_position = await self._get_enabled_louvers_in_position(
                disabled_louvers
            )

        self.log.info("Dome louvers are open.")
