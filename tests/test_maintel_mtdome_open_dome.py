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

import contextlib
import unittest

from lsst.ts import standardscripts
from lsst.ts.maintel.standardscripts.mtdome import OpenDome
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages


class TestOpenDome(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        self.script = OpenDome(index=index)

        return (self.script,)

    @contextlib.asynccontextmanager
    async def make_dry_script(self):
        async with self.make_script(self):
            self.script.mtcs = MTCS(
                domain=self.script.domain, intended_usage=MTCSUsages.DryTest
            )
            self.script.mtcs.disable_checks_for_components = unittest.mock.AsyncMock()
            self.script.mtcs.assert_all_enabled = unittest.mock.AsyncMock()
            self.script.mtcs.open_dome_shutter = unittest.mock.AsyncMock()
            yield

    async def test_run(self):
        async with self.make_dry_script():
            await self.configure_script()

            await self.run_script()
            self.script.mtcs.assert_all_enabled.assert_awaited_once()
            self.script.mtcs.open_dome_shutter.assert_awaited_once()

    async def test_configure(self):
        async with self.make_dry_script():
            components = ["mtptg"]
            await self.configure_script(force=True, ignore=components)

            assert self.script.config.force is True
            self.script.mtcs.disable_checks_for_components.assert_called_once_with(
                components=components
            )


if __name__ == "__main__":
    unittest.main()
