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
import types
import unittest

from lsst.ts import standardscripts
from lsst.ts.maintel.standardscripts.mtdome import OffsetDome
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages


class TestOffsetDome(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        self.script = OffsetDome(index=index)

        return (self.script,)

    @contextlib.asynccontextmanager
    async def make_dry_script(self):
        async with self.make_script():
            self.script.mtcs = MTCS(
                domain=self.script.domain,
                intended_usage=MTCSUsages.DryTest,
                log=self.script.log,
            )
            self.script.mtcs.disable_checks_for_components = unittest.mock.Mock()
            self.script.mtcs.assert_all_enabled = unittest.mock.AsyncMock()
            self.script.mtcs.slew_dome_to = unittest.mock.AsyncMock()
            self.script.mtcs.rem = types.SimpleNamespace(
                mtdome=unittest.mock.AsyncMock()
            )
            self.script.mtcs.rem.mtdome.configure_mock(
                **{"tel_azimuth.aget.side_effect": self.get_tel_azimuth}
            )

            yield

    async def test_run(self):
        async with self.make_dry_script():
            await self.configure_script(offset=15.0)

            await self.run_script()
            self.script.mtcs.assert_all_enabled.assert_awaited_once()
            self.script.mtcs.slew_dome_to.assert_called_once_with(az=315.0)

    async def test_config(self):
        async with self.make_dry_script():
            components = ["mtptg"]
            await self.configure_script(offset=15.0, ignore=components)
            assert self.script.offset == 15.0
            self.script.mtcs.disable_checks_for_components.assert_called_once_with(
                components=components
            )

    async def test_wrap_angle(self):
        async with self.make_dry_script():
            await self.configure_script(offset=75.0)

            await self.run_script()
            self.script.mtcs.assert_all_enabled.assert_awaited_once()
            self.script.mtcs.slew_dome_to.assert_called_once_with(az=15.0)

    async def test_wrap_negative_angle(self):
        async with self.make_dry_script():
            await self.configure_script(offset=-310.0)

            await self.run_script()
            self.script.mtcs.assert_all_enabled.assert_awaited_once()
            self.script.mtcs.slew_dome_to.assert_called_once_with(az=350.0)

    async def get_tel_azimuth(self, timeout):
        return types.SimpleNamespace(positionActual=300.0)
