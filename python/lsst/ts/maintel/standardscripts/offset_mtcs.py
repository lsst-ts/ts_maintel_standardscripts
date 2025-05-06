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
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

__all__ = ["OffsetMTCS"]

from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages
from lsst.ts.standardscripts.base_offset_tcs import BaseOffsetTCS


class OffsetMTCS(BaseOffsetTCS):
    """Perform an MTCS offset.

    Parameters
    ----------
    index : `int`
        Index of Script SAL component.
    """

    def __init__(self, index, add_remotes: bool = True):
        super().__init__(
            index=index,
            descr="Perform an MTCS offset",
        )
        self.mtcs = None

    async def configure(self, config):

        if self.mtcs is None:
            self.mtcs = MTCS(
                domain=self.domain, log=self.log, intended_usage=MTCSUsages.Slew
            )
            await self.mtcs.start_task

        await super().configure(config=config)

    @property
    def tcs(self):
        return self.mtcs
