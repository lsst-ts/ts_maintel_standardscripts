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

import asyncio
import unittest
from types import SimpleNamespace

from lsst.ts import standardscripts
from lsst.ts.maintel.standardscripts.mtdome import CloseDomeLouvers
from lsst.ts.xml.enums import MTDome


class TestCloseDomeLouvers(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        self.script = CloseDomeLouvers(index=index)

        self.script.mtcs = unittest.mock.AsyncMock()
        self.script.mtcs.assert_all_enabled = unittest.mock.AsyncMock()
        self.script.mtcs.rem.mtdome.configure_mock(
            **{
                "evt_louversMotion.aget.side_effect": self.mtdome_evt_louvers_motion,
                "evt_louversMotion.next.side_effect": self.mtdome_evt_louvers_motion,
                "cmd_closeLouvers.start.side_effect": self.mock_mtdome_cmd_close_louvers,
            },
        )
        self.louvers_state = SimpleNamespace(state=[MTDome.MotionState.ENABLED] * 34)

        return (self.script,)

    async def mtdome_evt_louvers_motion(self, timeout=0.0, flush=False):
        await asyncio.sleep(1.0)
        return self.louvers_state

    async def mock_mtdome_cmd_close_louvers(self, timeout=0.0):
        self._mock_mtdome_cmd_close_louvers = asyncio.create_task(
            self._mock_mtdome_cmd_close_louvers()
        )

    async def _mock_mtdome_cmd_close_louvers(self, timeout=0.0):
        disabled_louvers = [
            i
            for i, state in enumerate(self.louvers_state.state)
            if state == MTDome.MotionState.DISABLED
        ]
        await asyncio.sleep(1.0)
        self.louvers_state.state = [
            MTDome.MotionState.CLOSING if i not in disabled_louvers else state
            for i, state in enumerate(self.louvers_state.state)
        ]
        await asyncio.sleep(1.0)
        self.louvers_state.state = [
            MTDome.MotionState.CLOSED if i not in disabled_louvers else state
            for i, state in enumerate(self.louvers_state.state)
        ]

    async def test_run_all_louvers_enabled(self):
        async with self.make_script():
            self.louvers_state.state = [MTDome.MotionState.ENABLED] * 34
            await self.configure_script()
            await self.run_script()

            self.script.mtcs.assert_all_enabled.assert_awaited_once()
            self.script.mtcs.rem.mtdome.cmd_closeLouvers.start.assert_awaited_once()

    async def test_run_all_louvers_closed(self):
        async with self.make_script():
            self.louvers_state.state = [MTDome.MotionState.CLOSED] * 34
            await self.configure_script()
            await self.run_script()

            self.script.mtcs.assert_all_enabled.assert_awaited_once()
            self.script.mtcs.rem.mtdome.cmd_closeLouvers.start.assert_not_awaited()

    async def test_run_some_louvers_disabled(self):
        async with self.make_script():
            self.louvers_state.state = [MTDome.MotionState.ENABLED] * 34
            self.louvers_state.state[0] = MTDome.MotionState.DISABLED
            self.louvers_state.state[20] = MTDome.MotionState.DISABLED
            await self.configure_script()
            await self.run_script()

            self.script.mtcs.assert_all_enabled.assert_awaited_once()
            self.script.mtcs.rem.mtdome.cmd_closeLouvers.start.assert_awaited_once()

    async def test_run_all_louvers_closed_some_disabled(self):
        async with self.make_script():
            self.louvers_state.state = [MTDome.MotionState.CLOSED] * 34
            self.louvers_state.state[0] = MTDome.MotionState.DISABLED
            self.louvers_state.state[20] = MTDome.MotionState.DISABLED
            await self.configure_script()
            await self.run_script()

            self.script.mtcs.assert_all_enabled.assert_awaited_once()
            self.script.mtcs.rem.mtdome.cmd_closeLouvers.start.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
