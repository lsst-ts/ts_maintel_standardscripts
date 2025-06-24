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

import pytest
from lsst.ts import salobj, standardscripts
from lsst.ts.maintel.standardscripts.mtdome import RecoverFromControllerFault
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages
from lsst.ts.xml.enums.MTDome import SubSystemId


class TestRecoverFromControllerFault(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        self.script = RecoverFromControllerFault(index=index)

        return (self.script,)

    @contextlib.asynccontextmanager
    async def make_dry_script(self):
        async with self.make_script():
            mtcs = MTCS(
                domain=self.script.domain,
                intended_usage=MTCSUsages.DryTest,
                log=self.script.log,
            )
            mtcs.rem.mtdome = unittest.mock.AsyncMock()
            mtcs.check_dome_following = unittest.mock.AsyncMock(return_value=True)
            mtcs.disable_dome_following = unittest.mock.AsyncMock()
            mtcs.slew_dome_to = unittest.mock.AsyncMock()
            mtcs.enable_dome_following = unittest.mock.AsyncMock()
            self.script.mtcs = mtcs

            self.start_az = mtcs.home_dome_az
            yield

    async def test_configure(self):
        async with self.make_dry_script():
            valid_delta_move = float(self.script.mtcs.dome_slew_tolerance.degree * 2)
            await self.configure_script(delta_move=valid_delta_move)
            assert self.script.config.delta_move == valid_delta_move

    async def test_configure_fail(self):
        async with self.make_dry_script():
            invalid_delta_move = float(
                self.script.mtcs.dome_slew_tolerance.degree * 0.8
            )
            with pytest.raises(salobj.ExpectedError):
                await self.configure_script(delta_move=invalid_delta_move)

    async def test_run_success_dome_following_enabled(self):
        async with self.make_dry_script():
            await self.configure_script()

            start_az = self.start_az
            target_az = self.start_az + self.script.config.delta_move
            resulting_az = target_az + self.script.mtcs.dome_slew_tolerance.degree * 0.5

            self.script.mtcs.rem.mtdome.configure_mock(
                **{
                    "tel_azimuth.next.side_effect": [
                        unittest.mock.Mock(positionActual=start_az),
                        unittest.mock.Mock(positionActual=resulting_az),
                    ],
                }
            )

            await self.run_script()

            self.script.mtcs.check_dome_following.assert_awaited_once()
            self.script.mtcs.disable_dome_following.assert_awaited_once()
            self.script.mtcs.rem.mtdome.cmd_exitFault.set.assert_awaited_once_with(
                subSystemIds=SubSystemId.AMCS, timeout=self.script.mtcs.fast_timeout
            )
            self.script.mtcs.slew_dome_to.assert_awaited_once_with(az=target_az)
            self.script.mtcs.enable_dome_following.assert_awaited_once()

    async def test_run_success_dome_following_disabled(self):
        async with self.make_dry_script():
            await self.configure_script()

            start_az = self.start_az
            target_az = self.start_az + self.script.config.delta_move
            resulting_az = target_az + self.script.mtcs.dome_slew_tolerance.degree * 0.5

            self.script.mtcs.rem.mtdome.configure_mock(
                **{
                    "tel_azimuth.next.side_effect": [
                        unittest.mock.Mock(positionActual=start_az),
                        unittest.mock.Mock(positionActual=resulting_az),
                    ],
                }
            )
            self.script.mtcs.check_dome_following.configure_mock(return_value=False)

            await self.run_script()

            self.script.mtcs.check_dome_following.assert_awaited_once()
            self.script.mtcs.disable_dome_following.assert_not_awaited()
            self.script.mtcs.rem.mtdome.cmd_exitFault.set.assert_awaited_once_with(
                subSystemIds=SubSystemId.AMCS, timeout=self.script.mtcs.fast_timeout
            )
            self.script.mtcs.slew_dome_to.assert_awaited_once_with(az=target_az)
            self.script.mtcs.enable_dome_following.assert_awaited_once()

    async def test_run_fail_not_moving(self):
        async with self.make_dry_script():
            await self.configure_script()

            start_az = self.start_az
            target_az = self.start_az + self.script.config.delta_move
            resulting_az = start_az

            self.script.mtcs.rem.mtdome.configure_mock(
                **{
                    "tel_azimuth.next.side_effect": [
                        unittest.mock.Mock(positionActual=start_az),
                        unittest.mock.Mock(positionActual=resulting_az),
                    ],
                }
            )

            with pytest.raises(AssertionError):
                await self.run_script()

            self.script.mtcs.check_dome_following.assert_awaited_once()
            self.script.mtcs.disable_dome_following.assert_awaited_once()
            self.script.mtcs.rem.mtdome.cmd_exitFault.set.assert_awaited_once_with(
                subSystemIds=SubSystemId.AMCS, timeout=self.script.mtcs.fast_timeout
            )
            self.script.mtcs.slew_dome_to.assert_awaited_once_with(az=target_az)
            self.script.mtcs.enable_dome_following.assert_awaited_once()

    async def test_run_fail_moving(self):
        async with self.make_dry_script():
            await self.configure_script()

            start_az = self.start_az
            target_az = self.start_az + self.script.config.delta_move
            resulting_az = target_az + self.script.mtcs.dome_slew_tolerance.degree * 1.5

            self.script.mtcs.rem.mtdome.configure_mock(
                **{
                    "tel_azimuth.next.side_effect": [
                        unittest.mock.Mock(positionActual=start_az),
                        unittest.mock.Mock(positionActual=resulting_az),
                    ],
                }
            )

            with pytest.raises(AssertionError):
                await self.run_script()

            self.script.mtcs.check_dome_following.assert_awaited_once()
            self.script.mtcs.disable_dome_following.assert_awaited_once()
            self.script.mtcs.rem.mtdome.cmd_exitFault.set.assert_awaited_once_with(
                subSystemIds=SubSystemId.AMCS, timeout=self.script.mtcs.fast_timeout
            )
            self.script.mtcs.slew_dome_to.assert_awaited_once_with(az=target_az)
            self.script.mtcs.enable_dome_following.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
