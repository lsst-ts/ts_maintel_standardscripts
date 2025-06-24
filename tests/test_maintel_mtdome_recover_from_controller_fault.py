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
from lsst.ts.xml.enums.MTDome import EnabledState, SubSystemId


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

    @contextlib.asynccontextmanager
    async def make_failing_dry_script(self):
        async with self.make_dry_script():
            mock_az_enabled = unittest.mock.Mock(
                state=EnabledState.FAULT,
                faultCode="MOCK ERROR CODE",
            )

            self.script.mtcs.rem.mtdome.configure_mock(
                **{
                    "logevent_azEnabled.next.return_value": mock_az_enabled,
                }
            )
            yield

    def configure_mock_tel_azimuth(self, az_positions):
        mock_tel_azimuth_values = [
            unittest.mock.Mock(positionActual=az) for az in az_positions
        ]

        self.script.mtcs.rem.mtdome.configure_mock(
            **{
                "tel_azimuth.next.side_effect": mock_tel_azimuth_values,
            }
        )

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
            slew_tolerance = self.script.mtcs.dome_slew_tolerance.degree
            delta_move = self.script.config.delta_move

            target_az = start_az + delta_move

            self.configure_mock_tel_azimuth(
                [
                    start_az,
                    target_az + slew_tolerance * 0.5,
                ]
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
            slew_tolerance = self.script.mtcs.dome_slew_tolerance.degree
            delta_move = self.script.config.delta_move

            target_az = start_az + delta_move

            self.configure_mock_tel_azimuth(
                [
                    start_az,
                    target_az + slew_tolerance * 0.5,
                ]
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

    async def test_run_success_after_failing_exitFault(self):
        async with self.make_dry_script():
            await self.configure_script()

            start_az = self.start_az
            delta_move = self.script.config.delta_move
            slew_tolerance = self.script.mtcs.dome_slew_tolerance.degree

            az_positions = [
                start_az,
                start_az + delta_move + slew_tolerance * 0.5,
            ]

            self.configure_mock_tel_azimuth(az_positions)

            self.script.mtcs.rem.mtdome.configure_mock(
                **{
                    "cmd_exitFault.set.side_effect": [
                        Exception("MOCK Exception"),
                        None,
                    ],
                }
            )

            await self.run_script()

            self.script.mtcs.check_dome_following.assert_awaited_once()
            self.script.mtcs.disable_dome_following.assert_awaited_once()
            # Check exitFault command attempts
            expected_exitFalut_calls = [
                unittest.mock.call(
                    subSystemIds=SubSystemId.AMCS, timeout=self.script.mtcs.fast_timeout
                )
                for i in range(2)
            ]
            self.script.mtcs.rem.mtdome.cmd_exitFault.set.assert_has_awaits(
                expected_exitFalut_calls
            )
            # Check slew dome attempts
            expected_slew_dome_to_calls = [
                unittest.mock.call(az=offset_az + delta_move)
                for offset_az in az_positions[:-1]
            ]
            self.script.mtcs.slew_dome_to.assert_has_awaits(expected_slew_dome_to_calls)
            # Check dome following
            self.script.mtcs.enable_dome_following.assert_awaited_once()

    async def test_run_success_after_failing_to_move(self):
        async with self.make_dry_script():
            await self.configure_script()

            start_az = self.start_az
            delta_move = self.script.config.delta_move
            slew_tolerance = self.script.mtcs.dome_slew_tolerance.degree

            az_positions = [
                start_az,
                start_az + slew_tolerance,
                start_az + slew_tolerance + delta_move,
            ]

            self.configure_mock_tel_azimuth(az_positions)

            await self.run_script()

            self.script.mtcs.check_dome_following.assert_awaited_once()
            self.script.mtcs.disable_dome_following.assert_awaited_once()
            # Check exitFault command attempts
            expected_exitFalut_calls = [
                unittest.mock.call(
                    subSystemIds=SubSystemId.AMCS, timeout=self.script.mtcs.fast_timeout
                )
                for i in range(2)
            ]
            self.script.mtcs.rem.mtdome.cmd_exitFault.set.assert_has_awaits(
                expected_exitFalut_calls
            )
            # Check slew dome attempts
            expected_slew_dome_to_calls = [
                unittest.mock.call(az=offset_az + delta_move)
                for offset_az in az_positions[:-1]
            ]
            self.script.mtcs.slew_dome_to.assert_has_awaits(expected_slew_dome_to_calls)
            # Check dome following
            self.script.mtcs.enable_dome_following.assert_awaited_once()

    async def test_run_fail_exitFault(self):
        async with self.make_failing_dry_script():
            await self.configure_script()

            start_az = self.start_az

            az_positions = [start_az]

            self.configure_mock_tel_azimuth(az_positions)

            self.script.mtcs.rem.mtdome.configure_mock(
                **{
                    "cmd_exitFault.set.side_effect": Exception("MOCK Exception"),
                }
            )

            with pytest.raises(AssertionError):
                await self.run_script()

            self.script.mtcs.check_dome_following.assert_awaited_once()
            self.script.mtcs.disable_dome_following.assert_awaited_once()
            # Check exitFault command attempts
            expected_exitFalut_calls = [
                unittest.mock.call(
                    subSystemIds=SubSystemId.AMCS, timeout=self.script.mtcs.fast_timeout
                )
                for i in range(self.script.MAX_ATTEMPTS)
            ]
            self.script.mtcs.rem.mtdome.cmd_exitFault.set.assert_has_awaits(
                expected_exitFalut_calls
            )
            # Check slew dome attempts
            self.script.mtcs.slew_dome_to.assert_not_awaited()
            # Check dome following
            self.script.mtcs.enable_dome_following.assert_awaited_once()

    async def test_run_fail_not_moving(self):
        async with self.make_failing_dry_script():
            await self.configure_script()

            start_az = self.start_az
            delta_move = self.script.config.delta_move

            target_az = start_az + delta_move

            self.configure_mock_tel_azimuth(
                [start_az for attempt in range(self.script.MAX_ATTEMPTS + 1)]
            )

            with pytest.raises(AssertionError):
                await self.run_script()

            self.script.mtcs.check_dome_following.assert_awaited_once()
            self.script.mtcs.disable_dome_following.assert_awaited_once()
            # Check exitFault command attempts
            expected_exitFalut_calls = [
                unittest.mock.call(
                    subSystemIds=SubSystemId.AMCS, timeout=self.script.mtcs.fast_timeout
                )
                for i in range(self.script.MAX_ATTEMPTS)
            ]
            self.script.mtcs.rem.mtdome.cmd_exitFault.set.assert_has_awaits(
                expected_exitFalut_calls
            )
            # Check slew dome attempts
            expected_slew_dome_to_calls = [
                unittest.mock.call(az=target_az)
                for i in range(self.script.MAX_ATTEMPTS)
            ]
            self.script.mtcs.slew_dome_to.assert_has_awaits(expected_slew_dome_to_calls)
            # Check dome following
            self.script.mtcs.enable_dome_following.assert_awaited_once()

    async def test_run_fail_moving(self):
        async with self.make_failing_dry_script():
            await self.configure_script()

            start_az = self.start_az
            delta_move = self.script.config.delta_move
            slew_tolerance = self.script.mtcs.dome_slew_tolerance.degree

            target_az = start_az + delta_move

            az_positions = [start_az, start_az + slew_tolerance]
            # The following positions are within the initial tolerance range
            # but fall outside the updated valid range, and must be rejected.
            az_positions.extend(
                target_az - slew_tolerance * 0.5
                for i in range(self.script.MAX_ATTEMPTS - 1)
            )

            self.configure_mock_tel_azimuth(az_positions)

            with pytest.raises(AssertionError):
                await self.run_script()

            self.script.mtcs.check_dome_following.assert_awaited_once()
            self.script.mtcs.disable_dome_following.assert_awaited_once()
            # Check exitFault command attempts
            expected_exitFalut_calls = [
                unittest.mock.call(
                    subSystemIds=SubSystemId.AMCS, timeout=self.script.mtcs.fast_timeout
                )
                for i in range(self.script.MAX_ATTEMPTS)
            ]
            self.script.mtcs.rem.mtdome.cmd_exitFault.set.assert_has_awaits(
                expected_exitFalut_calls
            )
            # Check slew dome attempts
            expected_slew_dome_to_calls = [
                unittest.mock.call(az=offset_az + delta_move)
                for offset_az in az_positions[:-1]
            ]
            self.script.mtcs.slew_dome_to.assert_has_awaits(expected_slew_dome_to_calls)
            # Check dome following
            self.script.mtcs.enable_dome_following.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
