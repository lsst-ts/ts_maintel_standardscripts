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
from lsst.ts.maintel.standardscripts import Shutdown
from lsst.ts.xml.enums import MTMount


class TestShutdown(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        self.script = Shutdown(index=index)
        self.script.mtcs = unittest.mock.AsyncMock()
        return (self.script,)

    async def test_configure_defaults(self):
        async with self.make_script():
            await self.configure_script()

            self.script.mtcs.set_park_position.assert_called_with(
                azimuth=None,
                elevation=None,
                position=None,
            )

            self.script.mtcs.set_dome_park_position.assert_called_with(
                azimuth=None,
                elevation=None,
            )

    async def test_configure(self):
        async with self.make_script():
            park_az = 0.0
            park_el = 10.0
            park_pos = "HORIZON"

            dome_park_az = 2.0
            dome_park_el = 25.0

            await self.configure_script(
                park_azimuth=park_az,
                park_elevation=park_el,
                park_position=park_pos,
                dome_park_azimuth=dome_park_az,
                dome_park_elevation=dome_park_el,
            )

            self.script.mtcs.set_park_position.assert_called_with(
                azimuth=park_az,
                elevation=park_el,
                position=MTMount.ParkPosition[park_pos],
            )

            self.script.mtcs.set_dome_park_position.assert_called_with(
                azimuth=dome_park_az,
                elevation=dome_park_el,
            )

    async def test_configure_ignore(self):
        async with self.make_script():
            components = ["mtrotator", "mthexapod_1"]

            await self.configure_script(ignore=components)

            assert self.script.mtcs.disable_checks_for_components(components=components)

    async def test_run(self):
        async with self.make_script():
            await self.configure_script()

            await self.run_script()

            self.script.mtcs.shutdown.assert_awaited_once()
