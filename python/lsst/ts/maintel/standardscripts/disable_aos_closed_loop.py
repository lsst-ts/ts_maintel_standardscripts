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

__all__ = ["DisableAOSClosedLoop"]


from lsst.ts.observatory.control.maintel.mtcs import MTCS
from lsst.ts.standardscripts.base_block_script import BaseBlockScript


class DisableAOSClosedLoop(BaseBlockScript):
    """Disable AOS Closed Loop task to run in parallel to survey mode imaging.

    Parameters
    ----------
    index : `int`
        Index of Script SAL component.

    Notes
    -----
    **Checkpoints**

    - "Disabling AOS Closed Loop": Disable AOS Closed Loop.
    """

    def __init__(self, index: int) -> None:
        super().__init__(
            index=index,
            descr="Disable AOS Closed Loop.",
        )
        self.mtcs = None

    async def configure_tcs(self) -> None:
        if self.mtcs is None:
            self.log.debug("Creating MTCS.")
            self.mtcs = MTCS(domain=self.domain, log=self.log)
            await self.mtcs.start_task
        else:
            self.log.debug("MTCS already defined, skipping.")

    async def configure(self, config):
        await self.configure_tcs()

        await super().configure(config=config)

    def set_metadata(self, metadata):
        metadata.duration = self.mtcs.aos_closed_loop_timeout

    async def run_block(self):
        """Disable AOS Closed Loop task that runs
        in parallel to survey mode imaging.
        """
        await self.checkpoint("Disabling AOS Closed Loop")
        await self.mtcs.disable_aos_closed_loop()
