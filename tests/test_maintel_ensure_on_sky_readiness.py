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
from unittest import mock

from lsst.ts import standardscripts
from lsst.ts.maintel.standardscripts import EnsureOnSkyReadiness
from lsst.ts.observatory.control.maintel.lsstcam import LSSTCam, LSSTCamUsages
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages
from lsst.ts.xml.enums import MTAOS, MTM1M3, MTDome


class TestEnsureOnSkyReadiness(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        self.script = EnsureOnSkyReadiness(index=index)

        # Mock mtcs and camera with DryTest usage
        self.script.mtcs = MTCS(
            domain=self.script.domain,
            intended_usage=MTCSUsages.DryTest,
            log=self.script.log,
        )
        self.script.lsstcam = LSSTCam(
            domain=self.script.domain,
            intended_usage=LSSTCamUsages.DryTest,
            log=self.script.log,
        )
        # Mock all methods/events used in the script
        self.script.mtcs.start_task = mock.AsyncMock()
        self.script.lsstcam.start_task = mock.AsyncMock()
        self.script.mtcs.assert_all_enabled = mock.AsyncMock()
        self.script.lsstcam.assert_all_enabled = mock.AsyncMock()
        self.script.mtcs.enable_m2_balance_system = mock.AsyncMock()
        self.script.mtcs.raise_m1m3 = mock.AsyncMock()
        self.script.mtcs.enable_m1m3_balance_system = mock.AsyncMock()
        self.script.mtcs.set_m1m3_slew_controller_settings = mock.AsyncMock()
        self.script.mtcs.open_m1_cover = mock.AsyncMock()
        self.script.mtcs.enable_compensation_mode = mock.AsyncMock()
        self.script.mtcs.enable_ccw_following = mock.AsyncMock()
        self.script.mtcs.enable_dome_following = mock.AsyncMock()

        # Mock remotes/events
        self.script.mtcs.rem = mock.Mock()
        self.script.mtcs.rem.mtmount = mock.Mock()
        self.script.mtcs.rem.mtmount.evt_azimuthHomed = mock.Mock()
        self.script.mtcs.rem.mtmount.evt_azimuthHomed.aget = mock.AsyncMock(
            return_value=mock.Mock(homed=True)
        )
        self.script.mtcs.rem.mtmount.evt_elevationHomed = mock.Mock()
        self.script.mtcs.rem.mtmount.evt_elevationHomed.aget = mock.AsyncMock(
            return_value=mock.Mock(homed=True)
        )
        self.script.mtcs.rem.mtmount.tel_elevation = mock.Mock()
        self.script.mtcs.rem.mtmount.tel_elevation.aget = mock.AsyncMock(
            return_value=mock.Mock(actualPosition=75.0)
        )
        self.script.mtcs.rem.mtmount.cmd_homeBothAxes = mock.Mock()
        self.script.mtcs.rem.mtmount.cmd_homeBothAxes.start = mock.AsyncMock()
        self.script.mtcs.rem.mtm1m3 = mock.Mock()
        self.script.mtcs.rem.mtm1m3.evt_detailedState = mock.Mock()
        self.script.mtcs.rem.mtm1m3.evt_detailedState.aget = mock.AsyncMock(
            return_value=mock.Mock(detailedState=MTM1M3.DetailedState.ACTIVE)
        )
        self.script.mtcs.rem.mtdome = mock.Mock()
        self.script.mtcs.rem.mtdome.evt_shutterMotion = mock.Mock()
        self.script.mtcs.rem.mtdome.evt_shutterMotion.flush = mock.Mock()
        self.script.mtcs.rem.mtdome.evt_shutterMotion.aget = mock.AsyncMock(
            return_value=mock.Mock(
                state=[MTDome.MotionState.OPEN, MTDome.MotionState.OPEN]
            )
        )
        self.script.mtcs.rem.mtaos = mock.Mock()
        self.script.mtcs.rem.mtaos.evt_closedLoopState = mock.Mock()
        self.script.mtcs.rem.mtaos.evt_closedLoopState.flush = mock.Mock()
        self.script.mtcs.rem.mtaos.evt_closedLoopState.aget = mock.AsyncMock(
            return_value=mock.Mock(state=MTAOS.ClosedLoopState.WAITING_IMAGE)
        )
        return (self.script,)

    async def test_configure_default(self):
        async with self.make_script():
            await self.configure_script(slew_flags="default")
            default_flags, default_enables = self.script._get_default_m1m3_slew_flags()
            assert self.script.config.slew_flags == default_flags
            assert self.script.config.enable_flags == default_enables

    async def test_configure_custom_flags(self):
        async with self.make_script():
            slew_flags = [
                "ACCELERATIONFORCES",
                "BALANCEFORCES",
                "VELOCITYFORCES",
                "BOOSTERVALVES",
            ]
            enable_flags = [True, True, True, False]
            await self.configure_script(
                slew_flags=slew_flags, enable_flags=enable_flags
            )
            enum_flags = self.script._convert_m1m3_slew_flag_names_to_enum(slew_flags)
            assert self.script.config.slew_flags == enum_flags
            assert self.script.config.enable_flags == enable_flags

    async def test_run_ready_for_on_sky(self):
        async with self.make_script():
            await self.configure_script(slew_flags="default")
            await self.run_script()

            # Assert all main methods were called exactly once
            self.script.mtcs.assert_all_enabled.assert_awaited_once()
            self.script.lsstcam.assert_all_enabled.assert_awaited_once()
            self.script.mtcs.enable_m2_balance_system.assert_awaited_once()
            self.script.mtcs.raise_m1m3.assert_not_called()  # Not called if already ACTIVE
            self.script.mtcs.enable_m1m3_balance_system.assert_awaited_once()
            self.script.mtcs.set_m1m3_slew_controller_settings.assert_has_awaits(
                [
                    mock.call(flag, enable)
                    for flag, enable in zip(
                        self.script.config.slew_flags, self.script.config.enable_flags
                    )
                ]
            )
            self.script.mtcs.open_m1_cover.assert_awaited_once()
            self.script.mtcs.enable_ccw_following.assert_awaited_once()
            self.script.mtcs.enable_compensation_mode.assert_has_awaits(
                [mock.call("mthexapod_1"), mock.call("mthexapod_2")]
            )
            self.script.mtcs.enable_dome_following.assert_awaited_once()

            # Assert that the assert methods were called
            # (dome shutter and aos closed loop)
            dome_ok, dome_msg = await self.script.assert_dome_shutter_opened()
            assert dome_ok is True
            assert dome_msg == ""

            aos_ok, aos_msg = await self.script.assert_aos_closed_loop_enabled()
            assert aos_ok is True
            assert aos_msg == ""
