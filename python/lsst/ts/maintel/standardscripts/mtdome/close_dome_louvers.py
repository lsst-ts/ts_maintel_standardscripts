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

__all__ = ["CloseDomeLouvers"]

import yaml
from lsst.ts import salobj
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages
from lsst.ts.xml.enums import MTDome


class CloseDomeLouvers(salobj.BaseScript):
    """Close MTDome louvers.

    Parameters
    ----------
    index : `int`
        Index of Script SAL component.

    Notes
    -----
    **Checkpoints**

    Closing dome louvers: Before commanding dome louvers to be closed.
    """

    def __init__(self, index):
        super().__init__(index=index, descr="Close MTDome louvers.")

        self.mtcs = None

    @classmethod
    def get_schema(cls):
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_maintel_standardscripts/maintel/mtdome/close_dome_louvers.yaml
            title: CloseDomeLouvers v1
            description: Configuration for CloseDomeLouvers.
            type: object
            properties:
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

    def set_metadata(self, metadata):
        metadata.duration = self.mtcs.long_timeout

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

        expected_states = [
            (
                MTDome.MotionState.DISABLED
                if i in disabled_louvers
                else MTDome.MotionState.CLOSED
            )
            for i, l in enumerate(louvers_state.state)
        ]

        # Check if louvers are already closed
        if louvers_state.state == expected_states:
            self.log.info("Dome louvers are already closed.")
        # If not all louvers are closed, issue closeLouvers command
        else:
            await self.checkpoint("Closing dome louvers")
            self.log.info("Closing dome louvers.")
            await self.mtcs.rem.mtdome.cmd_closeLouvers.start(
                timeout=self.mtcs.long_timeout
            )
            louvers_state = await self.mtcs.rem.mtdome.evt_louversMotion.aget(
                timeout=self.mtcs.fast_timeout
            )
            while louvers_state.state != expected_states:
                self.log.debug(f"Louvers state: {louvers_state.state!r}")
                louvers_state = await self.mtcs.rem.mtdome.evt_louversMotion.next(
                    flush=False, timeout=self.mtcs.fast_timeout
                )

            self.log.info("Dome louvers are closed.")
            self.log.debug(
                f"Louvers state: {[MTDome.MotionState(state) for state in louvers_state.state]!r}"
            )
