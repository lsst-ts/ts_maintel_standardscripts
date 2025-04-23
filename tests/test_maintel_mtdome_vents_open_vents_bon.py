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
import unittest
from unittest import mock

import pytest
from lsst.ts import salobj, standardscripts
from lsst.ts.maintel.standardscripts.mtdome.vents.open_vents_bon import OpenVentsBON
from lsst.ts.xml.enums.MTDome import Louver


class TestOpenVentsBON(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        self.script = OpenVentsBON(index=index)

        return (self.script,)

    @contextlib.asynccontextmanager
    async def make_dry_script(self):
        async with self.make_script():
            self.script.mtdome = mock.AsyncMock()
            yield

    async def test_configure_default(self):
        """Test the default configuration"""
        async with self.make_dry_script():
            await self.configure_script()

            self.assertEqual(self.script.fan_hz, 25.0)
            self.assertEqual(self.script.louver_percent, 100.0)

    async def test_configure_custom_fan_speed(self):
        """Test configuration with custom fan speed"""
        async with self.make_dry_script():
            await self.configure_script(fan_speed_hz=30.0)

            self.assertEqual(self.script.fan_hz, 30.0)
            self.assertEqual(self.script.louver_percent, 100.0)

    async def test_configure_custom_louver_percent(self):
        """Test configuration with custom louver percent"""
        async with self.make_dry_script():
            await self.configure_script(louver_percent_open=80.0)

            self.assertEqual(self.script.fan_hz, 25.0)
            self.assertEqual(self.script.louver_percent, 80.0)

    async def test_configure_invalid_fan_speed(self):
        """Test configuration with invalid fan speed"""
        async with self.make_dry_script():
            with pytest.raises(
                salobj.ExpectedError,
                match="failed: 60.0 is greater than the maximum of 50.0",
            ):
                await self.configure_script(fan_speed_hz=60.0)

    async def test_configure_invalid_louver_percent(self):
        """Test configuration with invalid louver percent"""
        async with self.make_dry_script():
            with pytest.raises(
                salobj.ExpectedError,
                match="failed: 120.0 is greater than the maximum of 100.0",
            ):
                await self.configure_script(louver_percent_open=120.0)

    async def test_run_default(self):
        """Test run with default configuration"""
        async with self.make_dry_script():
            await self.configure_script()

            await self.run_script()

            expected_fan_percent = (
                OpenVentsBON.DEFAULT_FAN_HZ / OpenVentsBON.MAX_FAN_HZ
            ) * 100.0

            num_louvers = len(Louver.__members__)

            expected_louvers_calls = [
                mock.call(
                    position=[OpenVentsBON.DEFAULT_LOUVER_PERCENT] * num_louvers,
                    timeout=OpenVentsBON.DEFAULT_LOUVERS_TIMEOUT,
                )
            ]
            self.script.mtdome.cmd_setLouvers.set_start.assert_has_awaits(
                expected_louvers_calls
            )

            expected_fans_calls = [
                mock.call(
                    speed=expected_fan_percent,
                    timeout=OpenVentsBON.DEFAULT_FANS_TIMEOUT,
                )
            ]
            self.script.mtdome.cmd_fans.set_start.assert_has_awaits(expected_fans_calls)

    async def test_run_custom(self):
        """Test run with custom configuration"""
        async with self.make_dry_script():
            custom_fan_hz = 30.0
            custom_louver_percent = 80.0
            await self.configure_script(
                fan_speed_hz=custom_fan_hz, louver_percent_open=custom_louver_percent
            )

            await self.run_script()

            expected_fan_percent = (custom_fan_hz / OpenVentsBON.MAX_FAN_HZ) * 100.0

            num_louvers = len(Louver.__members__)

            expected_louvers_calls = [
                mock.call(
                    position=[custom_louver_percent] * num_louvers,
                    timeout=OpenVentsBON.DEFAULT_LOUVERS_TIMEOUT,
                )
            ]
            self.script.mtdome.cmd_setLouvers.set_start.assert_has_awaits(
                expected_louvers_calls
            )

            expected_fans_calls = [
                mock.call(
                    speed=expected_fan_percent,
                    timeout=OpenVentsBON.DEFAULT_FANS_TIMEOUT,
                )
            ]
            self.script.mtdome.cmd_fans.set_start.assert_has_awaits(expected_fans_calls)


if __name__ == "__main__":
    unittest.main()
