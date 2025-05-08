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

__all__ = ["WaitAOSClosedLoopReady"]

import asyncio

import yaml
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages
from lsst.ts.standardscripts.base_block_script import BaseBlockScript
from lsst.ts.xml.enums.MTAOS import ClosedLoopState

CLOSED_LOOP_STATE_TIMEOUT = 120


class WaitAOSClosedLoopReady(BaseBlockScript):
    """Wait for AOS Closed Loop task to be ready.

    Parameters
    ----------
    index : `int`
        Index of Script SAL component.

    Notes
    -----
    **Checkpoints**

    - "Waiting AOS Closed Loop": Waiting for AOS Closed Loop to be ready.
    """

    def __init__(self, index: int) -> None:
        super().__init__(
            index=index,
            descr="Wait AOS Closed Loop ready.",
        )
        self.mtcs = None
        self.config = None

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
            $id: https://github.com/lsst-ts/ts_standardscripts/maintel/wait_aos_closed_loop_ready.yaml
            title: WaitAOSClosedLoop v1
            description: Configuration for WaitAOSClosedLoopReady
            type: object
            properties:
                sleep_for:
                    description: >-
                        How long to wait before starting the wait loop (in seconds)?
                    type: number
                    minimum: 0
                    default: 0
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

        self.config = config

        await super().configure(config=config)

    def set_metadata(self, metadata):
        metadata.duration = CLOSED_LOOP_STATE_TIMEOUT + self.config.sleep_for

    async def run_block(self):
        """Enable AOS Closed Loop task to run
        in parallel to survey mode imaging.
        """
        if self.config.sleep_for > 0:
            await self.checkpoint(f"Waiting {self.config.sleep_for}s before proceeding")
            await asyncio.sleep(self.config.sleep_for)

        self.mtcs.rem.mtaos.evt_closedLoopState.flush()

        closed_loop_state = ClosedLoopState(
            await self.mtcs.rem.mtaos.evt_closedLoopState.aget(
                timeout=CLOSED_LOOP_STATE_TIMEOUT
            ).state
        )

        while closed_loop_state != ClosedLoopState.WAITING_IMAGE:

            await self.checkpoint(
                "Waiting for Closed Loop State to be WAITING_IMAGE, currently {closed_loop_state.name}"
            )

            if closed_loop_state == ClosedLoopState.ERROR:
                raise RuntimeError("Closed loop in ERROR state.")
            else:
                self.log.info(f"Closed loop state: {closed_loop_state.name}.")

            closed_loop_state = await self.mtcs.rem.mtaos.evt_closedLoopState.next(
                flush=False, timeout=CLOSED_LOOP_STATE_TIMEOUT
            )
