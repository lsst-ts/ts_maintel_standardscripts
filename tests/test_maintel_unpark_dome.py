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
from lsst.ts.maintel.standardscripts.mtdome import UnparkDome
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages


class TestUnparkDome(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        self.script = UnparkDome(index=index)
        return (self.script,)

    @contextlib.asynccontextmanager
    async def make_dry_script(self):
        async with self.make_script():
            self.script.mtcs = MTCS(
                domain=self.script.domain,
                intended_usage=MTCSUsages.DryTest,
                log=self.script.log,
            )
            self.script.mtcs.assert_all_enabled = unittest.mock.AsyncMock()
            self.script.mtcs.unpark_dome = unittest.mock.AsyncMock()
            yield

    async def test_config(self):
        async with self.make_dry_script():
            await self.configure_script()

    async def test_configure_ignore(self):
        async with self.make_dry_script():
            components = ["mtmount"]
            await self.configure_script(ignore=components)

            assert self.script.mtcs.check.mtmount is False

    async def test_configure_ignore_not_csc_component(self):
        async with self.make_dry_script():
            components = ["not_csc_comp", "mtmount"]
            await self.configure_script(ignore=components)

            assert hasattr(self.script.mtcs, "not_csc_comp") is False
            assert self.script.mtcs.check.mtmount is False

    async def test_run(self):
        async with self.make_dry_script():
            await self.configure_script(ignore=["mtmount"])
            await self.run_script()
            self.script.mtcs.assert_all_enabled.assert_awaited_once()
            self.script.mtcs.unpark_dome.assert_awaited_once()
