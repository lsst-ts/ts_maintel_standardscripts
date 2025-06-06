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

import unittest

from lsst.ts import standardscripts
from lsst.ts.maintel.standardscripts import DisableAOSClosedLoop
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages


class TestDisableAOSClosedLoop(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        self.script = DisableAOSClosedLoop(index=index)

        # Mock the MTCS
        self.script.mtcs = MTCS(
            domain=self.script.domain,
            intended_usage=MTCSUsages.DryTest,
            log=self.script.log,
        )
        self.script.mtcs.rem.mtaos = unittest.mock.AsyncMock()

        return (self.script,)

    async def test_run(self) -> None:
        # Start the test itself
        async with self.make_script():
            await self.configure_script()

            await self.run_script()

            self.script.mtcs.rem.mtaos.cmd_stopClosedLoop.start.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
