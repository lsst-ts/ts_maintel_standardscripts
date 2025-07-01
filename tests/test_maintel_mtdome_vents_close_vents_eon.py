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

import contextlib
import types
import unittest
from unittest import mock

from lsst.ts import salobj, standardscripts
from lsst.ts.maintel.standardscripts.mtdome.vents.close_vents_eon import CloseVentsEON


class TestCloseVentsEON(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        self.script = CloseVentsEON(index=index)
        return (self.script,)

    @contextlib.asynccontextmanager
    async def make_dry_script(self):
        async with self.make_script():
            self.script.mtdome = mock.AsyncMock()

            self.script.mtdome.evt_summaryState.aget.return_value = (
                types.SimpleNamespace(summaryState=salobj.State.ENABLED.value)
            )

            yield

    async def test_run(self):
        """Test run"""
        async with self.make_dry_script():
            await self.configure_script()

            await self.run_script()

            expected_fans_calls = [
                mock.call(speed=0.0, timeout=CloseVentsEON.DEFAULT_FANS_TIMEOUT)
            ]
            self.script.mtdome.cmd_fans.set_start.assert_has_awaits(expected_fans_calls)

            expected_louvers_calls = [
                mock.call(timeout=CloseVentsEON.DEFAULT_LOUVERS_TIMEOUT)
            ]
            self.script.mtdome.cmd_closeLouvers.start.assert_has_awaits(
                expected_louvers_calls
            )


if __name__ == "__main__":
    unittest.main()
