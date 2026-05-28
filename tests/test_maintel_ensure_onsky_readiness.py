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

import pytest
from lsst.ts import salobj, standardscripts
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
        self.script.mtcs.enable = mock.AsyncMock()
        self.script.lsstcam.assert_all_enabled = mock.AsyncMock()
        self.script.lsstcam.enable = mock.AsyncMock()
        self.script.mtcs.enable_m2_balance_system = mock.AsyncMock()
        self.script.mtcs.raise_m1m3 = mock.AsyncMock()
        self.script.mtcs.assert_m1m3_force_balance_system_enabled = mock.AsyncMock()
        self.script.mtcs.assert_m1m3_slew_controller_settings = mock.AsyncMock(
            return_value=[]
        )
        self.script.mtcs.open_m1_cover = mock.AsyncMock()
        self.script.mtcs.enable_compensation_mode = mock.AsyncMock()
        self.script.mtcs.enable_ccw_following = mock.AsyncMock()
        self.script.mtcs.unpark_dome = mock.AsyncMock()
        self.script.mtcs.enable_dome_following = mock.AsyncMock()

        # Mock m1m3_booster_valve as an async context manager
        self.script.mtcs.m1m3_booster_valve = mock.MagicMock(
            return_value=mock.AsyncMock()
        )

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
            return_value=mock.Mock(detailedState=MTM1M3.DetailedStates.ACTIVE)
        )
        self.script.mtcs.rem.mtdome = mock.Mock()
        self.script.mtcs.rem.mtdome.evt_azMotion = mock.Mock()
        # Default: not parked, so the script should not attempt to unpark.
        self.script.mtcs.rem.mtdome.evt_azMotion.aget = mock.AsyncMock(
            return_value=mock.Mock(state=MTDome.MotionState.MOVING)
        )
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

        # Mock OCPS remote
        self.script.ocps = mock.Mock()
        self.script.ocps.start_task = mock.AsyncMock()
        self.script.ocps.evt_summaryState = mock.Mock()
        self.script.ocps.evt_summaryState.aget = mock.AsyncMock(
            return_value=mock.Mock(summaryState=salobj.State.ENABLED)
        )

        # Mock MTM1M3TS remote
        self.script.mtm1m3ts = mock.Mock()
        self.script.mtm1m3ts.start_task = mock.AsyncMock()
        self.script.mtm1m3ts.evt_summaryState = mock.Mock()
        self.script.mtm1m3ts.evt_summaryState.aget = mock.AsyncMock(
            return_value=mock.Mock(summaryState=salobj.State.ENABLED)
        )
        self.script.mtm1m3ts.evt_engineeringMode = mock.Mock()
        self.script.mtm1m3ts.evt_engineeringMode.flush = mock.Mock()
        self.script.mtm1m3ts.evt_engineeringMode.aget = mock.AsyncMock(
            return_value=mock.Mock(engineeringMode=False)
        )

        return (self.script,)

    async def test_run_ready_for_on_sky(self):
        """
        Test the script when all components are already ready for
        on-sky operations.
        """

        async with self.make_script():
            await self.configure_script()
            await self.run_script()
            # Assert all main methods were called exactly once
            self.script.mtcs.assert_all_enabled.assert_awaited_once()
            self.script.lsstcam.assert_all_enabled.assert_awaited_once()
            self.script.mtcs.enable_m2_balance_system.assert_awaited_once()
            self.script.mtcs.raise_m1m3.assert_not_called()  # Not called if already ACTIVE
            self.script.mtcs.assert_m1m3_force_balance_system_enabled.assert_awaited_once()
            self.script.mtcs.assert_m1m3_slew_controller_settings.assert_awaited_once()
            self.script.mtcs.open_m1_cover.assert_awaited_once()
            self.script.mtcs.enable_ccw_following.assert_awaited_once()
            self.script.mtcs.enable_compensation_mode.assert_has_awaits(
                [mock.call("mthexapod_1"), mock.call("mthexapod_2")]
            )
            self.script.mtcs.unpark_dome.assert_awaited_once()
            self.script.mtcs.enable_dome_following.assert_awaited_once()
            # Verify OCPS state was checked
            self.script.ocps.evt_summaryState.aget.assert_awaited_once()

    async def test_run_ensure_ocps_enabled_when_not_enabled(self):
        """Test that the script enables OCPS:101 if it is not enabled."""
        async with self.make_script():
            await self.configure_script()

            # Set OCPS to STANDBY state
            self.script.ocps.evt_summaryState.aget = mock.AsyncMock(
                return_value=mock.Mock(summaryState=salobj.State.STANDBY)
            )

            with mock.patch(
                "lsst.ts.salobj.set_summary_state", new_callable=mock.AsyncMock
            ) as mock_set_state:
                await self.run_script()
                mock_set_state.assert_awaited_once_with(
                    self.script.ocps, salobj.State.ENABLED
                )

    async def test_run_ensure_ocps_enabled_failure(self):
        """Test that the script raises if OCPS:101 cannot be enabled."""
        async with self.make_script():
            await self.configure_script()

            # Set OCPS to STANDBY state
            self.script.ocps.evt_summaryState.aget = mock.AsyncMock(
                return_value=mock.Mock(summaryState=salobj.State.STANDBY)
            )

            with mock.patch(
                "lsst.ts.salobj.set_summary_state",
                new_callable=mock.AsyncMock,
                side_effect=RuntimeError("Failed to enable OCPS:101"),
            ):
                with pytest.raises(AssertionError):
                    await self.run_script()

    async def test_run_unpark_dome_if_parked(self):
        """Test that the script unparks the dome if it is in PARKED state."""

        async with self.make_script():
            await self.configure_script()

            self.script.mtcs.rem.mtdome.evt_azMotion.aget = mock.AsyncMock(
                return_value=mock.Mock(state=MTDome.MotionState.PARKED)
            )

            await self.run_script()

            self.script.mtcs.unpark_dome.assert_awaited_once()

    async def test_components_not_all_enabled(self):
        """Test the script when some components are not enabled."""
        async with self.make_script():
            await self.configure_script()

            # Patch assert_all_enabled to raise AssertionError for mtcs/lsstcam
            self.script.mtcs.assert_all_enabled = mock.AsyncMock(
                side_effect=AssertionError("MTCS not all enabled")
            )
            self.script.mtcs.enable = mock.AsyncMock()
            self.script.lsstcam.assert_all_enabled = mock.AsyncMock(
                side_effect=AssertionError("LSSTCam not all enabled")
            )
            self.script.lsstcam.enable = mock.AsyncMock()

            # Test MTCS group
            with mock.patch.object(self.script.log, "warning") as mock_warning_mtcs:
                await self.script.ensure_group_all_enabled(self.script.mtcs, "MTCS")
                self.script.mtcs.assert_all_enabled.assert_awaited_once()
                self.script.mtcs.enable.assert_awaited_once()
                mock_warning_mtcs.assert_called()
                assert "Some MTCS CSCs are not enabled" in str(
                    mock_warning_mtcs.call_args[0][0]
                )

            # Test LSSTCam group
            with mock.patch.object(self.script.log, "warning") as mock_warning_lsstcam:
                await self.script.ensure_group_all_enabled(
                    self.script.lsstcam, "LSSTCam"
                )
                self.script.lsstcam.assert_all_enabled.assert_awaited_once()
                self.script.lsstcam.enable.assert_awaited_once()
                mock_warning_lsstcam.assert_called()
                assert "Some LSSTCam CSCs are not enabled" in str(
                    mock_warning_lsstcam.call_args[0][0]
                )

    async def test_run_dome_shutter_not_opened(self):
        """Test the script when the dome shutters are not opened."""
        async with self.make_script():
            await self.configure_script()
            # Patch the dome shutter event to return CLOSED states
            self.script.mtcs.rem.mtdome.evt_shutterMotion.aget = mock.AsyncMock(
                return_value=mock.Mock(
                    state=[MTDome.MotionState.CLOSED, MTDome.MotionState.CLOSED]
                )
            )
            with self.assertRaises(AssertionError, msg="Dome shutters are not open"):
                await self.run_script()

    async def test_run_ensure_m2_balance_system_enabled_failure(self):
        """Test the script when it fails to enable M2 balance system."""
        async with self.make_script():
            await self.configure_script()
            self.script.mtcs.enable_m2_balance_system = mock.AsyncMock(
                side_effect=RuntimeError("Failed to enable M2 balance system.")
            )
            with pytest.raises(AssertionError):
                await self.run_script()

    async def test_run_ensure_m1m3_raised_fails_in_low_elevation(self):
        """Test the script fails when mtmount elevation is low."""
        async with self.make_script():
            await self.configure_script()
            self.script.mtcs.rem.mtmount.tel_elevation.aget = mock.AsyncMock(
                return_value=mock.Mock(actualPosition=15.0)
            )
            self.script.mtcs.rem.mtm1m3.evt_detailedState.aget = mock.AsyncMock(
                return_value=mock.Mock(detailedState=MTM1M3.DetailedStates.PARKED)
            )
            with pytest.raises(AssertionError):
                await self.run_script()

    async def test_run_ensure_m1m3_raised_fails_in_fault_state(self):
        """Test the script with M1M3 in FAULT and safe elevation."""
        async with self.make_script():
            await self.configure_script()
            self.script.mtcs.rem.mtmount.tel_elevation.aget = mock.AsyncMock(
                return_value=mock.Mock(actualPosition=75.0)
            )
            self.script.mtcs.rem.mtm1m3.evt_detailedState.aget = mock.AsyncMock(
                return_value=mock.Mock(detailedState=MTM1M3.DetailedStates.FAULT)
            )
            with pytest.raises(AssertionError):
                await self.run_script()

    async def test_run_ensure_m1m3_raised_fails_in_unexpected_state(self):
        """Test the script with M1M3 in unexpected state and safe elevation."""
        async with self.make_script():
            await self.configure_script()
            self.script.mtcs.rem.mtmount.tel_elevation.aget = mock.AsyncMock(
                return_value=mock.Mock(actualPosition=75.0)
            )
            self.script.mtcs.rem.mtm1m3.evt_detailedState.aget = mock.AsyncMock(
                return_value=mock.Mock(detailedState=MTM1M3.DetailedStates.STANDBY)
            )
            with pytest.raises(AssertionError):
                await self.run_script()

    async def test_run_ensure_m1m3_raised_fails_if_raise_fails(self):
        """Test the script when M1M3 is PARKED and raise_m1m3 fails."""
        async with self.make_script():
            await self.configure_script()
            # Simulate safe elevation and PARKED state
            self.script.mtcs.rem.mtmount.tel_elevation.aget = mock.AsyncMock(
                return_value=mock.Mock(actualPosition=75.0)
            )
            self.script.mtcs.rem.mtm1m3.evt_detailedState.aget = mock.AsyncMock(
                return_value=mock.Mock(detailedState=MTM1M3.DetailedStates.PARKED)
            )
            # Simulate raise_m1m3 command failure
            self.script.mtcs.raise_m1m3 = mock.AsyncMock(
                side_effect=RuntimeError("Failed to raise M1M3")
            )
            with pytest.raises(AssertionError):
                await self.run_script()

    async def test_run_ensure_mtmount_is_homed_if_not_homed(self):
        """Test mtmount is homed if not already homed."""
        async with self.make_script():
            await self.configure_script()
            self.script.mtcs.rem.mtmount.evt_azimuthHomed.aget = mock.AsyncMock(
                return_value=mock.Mock(homed=False)
            )
            self.script.mtcs.rem.mtmount.evt_elevationHomed.aget = mock.AsyncMock(
                return_value=mock.Mock(homed=True)
            )
            with mock.patch.object(
                self.script.mtcs.rem.mtmount.cmd_homeBothAxes, "start"
            ) as mock_home:
                await self.run_script()
                mock_home.assert_awaited_once()
                # Verify booster valve context manager was used
                self.script.mtcs.m1m3_booster_valve.assert_called_once()

    async def test_run_ensure_m1m3_raised_when_parked(self):
        """Test that script raised M1M3 if it is PARKED."""
        async with self.make_script():
            await self.configure_script()
            # Patch elevation to be safe and state to PARKED
            self.script.mtcs.rem.mtmount.tel_elevation.aget = mock.AsyncMock(
                return_value=mock.Mock(actualPosition=75.0)
            )
            self.script.mtcs.rem.mtm1m3.evt_detailedState.aget = mock.AsyncMock(
                return_value=mock.Mock(detailedState=MTM1M3.DetailedStates.PARKED)
            )
            with mock.patch.object(self.script.mtcs, "raise_m1m3") as mock_raise:
                await self.run_script()
                mock_raise.assert_awaited_once()

    async def test_run_ensure_mtmount_homed_fails_if_homing_fails(self):
        """Test that script fails if homing command fails."""
        async with self.make_script():
            await self.configure_script()
            # Simulate not homed
            self.script.mtcs.rem.mtmount.evt_azimuthHomed.aget = mock.AsyncMock(
                return_value=mock.Mock(homed=False)
            )
            self.script.mtcs.rem.mtmount.evt_elevationHomed.aget = mock.AsyncMock(
                return_value=mock.Mock(homed=True)
            )
            # Simulate homing command failure
            self.script.mtcs.rem.mtmount.cmd_homeBothAxes.start = mock.AsyncMock(
                side_effect=RuntimeError("Failed to home both axes")
            )
            with pytest.raises(AssertionError):
                await self.run_script()

    async def test_run_ensure_mtmount_homed_fails_if_check_homed_errors(self):
        """Test that script fails for errors while retrieving home status."""
        async with self.make_script():
            await self.configure_script()
            self.script.mtcs.rem.mtmount.evt_azimuthHomed.aget = mock.AsyncMock(
                side_effect=Exception("Some error")
            )
            self.script.mtcs.rem.mtmount.evt_elevationHomed.aget = mock.AsyncMock(
                side_effect=Exception("Some error")
            )
            with mock.patch.object(
                self.script.mtcs.rem.mtmount.cmd_homeBothAxes, "start"
            ) as mock_home:
                with pytest.raises(AssertionError):
                    await self.run_script()
                mock_home.assert_not_called()

    async def test_run_assert_m1m3_force_balance_enabled_failure(self):
        """Test it fails when force balance is not enabled."""
        async with self.make_script():
            await self.configure_script()
            self.script.mtcs.assert_m1m3_force_balance_system_enabled = mock.AsyncMock(
                side_effect=RuntimeError("M1M3 force balance system is not enabled.")
            )
            with pytest.raises(AssertionError):
                await self.run_script()
            # Verify the script stopped before reaching later steps
            self.script.mtcs.open_m1_cover.assert_not_called()

    async def test_run_assert_m1m3_slew_controller_flags_warning(self):
        """Test it collects warning when slew flags are not enabled."""
        async with self.make_script():
            await self.configure_script()
            # Return disabled flags to trigger warning
            self.script.mtcs.assert_m1m3_slew_controller_settings = mock.AsyncMock(
                return_value=["BOOSTERVALVES"]
            )
            with pytest.raises(AssertionError):
                await self.run_script()

            # Verify the slew controller warning was collected
            assert len(self.script.assertion_errors) == 1
            error_msg = str(self.script.assertion_errors[0])
            assert "Some M1M3 slew controller flags are not enabled" in error_msg
            assert "BOOSTERVALVES" in error_msg

    async def test_run_ensure_m1m3_cover_opened_failure(self):
        """Test the script when it fails to open M1M3 mirror covers."""
        async with self.make_script():
            await self.configure_script()
            self.script.mtcs.open_m1_cover = mock.AsyncMock(
                side_effect=RuntimeError("Failed to open M1M3 mirror covers.")
            )
            with pytest.raises(AssertionError):
                await self.run_script()

    async def test_run_ensure_ccw_following_enabled_failure(self):
        """Test the script when it fails to enable CCW following."""
        async with self.make_script():
            await self.configure_script()
            self.script.mtcs.enable_ccw_following = mock.AsyncMock(
                side_effect=RuntimeError("Failed to enable CCW following.")
            )
            with pytest.raises(AssertionError):
                await self.run_script()

    async def test_run_ensure_hexapod_compensation_mode_enabled_failure(self):
        """Test the script when it fails to enable hexapod comp. mode."""
        async with self.make_script():
            await self.configure_script()
            self.script.mtcs.enable_compensation_mode = mock.AsyncMock(
                side_effect=RuntimeError("Failed to enable hexapod compensation mode.")
            )
            with pytest.raises(AssertionError):
                await self.run_script()

    async def test_run_ensure_dome_following_enabled_failure(self):
        """Test the script when it fails to enable dome following."""
        async with self.make_script():
            await self.configure_script()
            self.script.mtcs.enable_dome_following = mock.AsyncMock(
                side_effect=RuntimeError("Failed to enable dome following.")
            )
            with pytest.raises(AssertionError):
                await self.run_script()

    async def test_run_aos_closed_loop_states(self):
        """Test edge cases for AOS closed loop states."""

        # WAITING_IMAGE: should pass without exception
        async with self.make_script():
            await self.configure_script()
            self.script.mtcs.rem.mtaos.evt_closedLoopState.aget = mock.AsyncMock(
                return_value=mock.Mock(state=MTAOS.ClosedLoopState.WAITING_IMAGE)
            )
            await self.run_script()

        # ERROR state: should raise AssertionError
        async with self.make_script():
            await self.configure_script()
            self.script.mtcs.rem.mtaos.evt_closedLoopState.aget = mock.AsyncMock(
                return_value=mock.Mock(state=MTAOS.ClosedLoopState.ERROR)
            )
            with self.assertRaises(
                AssertionError, msg="AOS Closed Loop is not in WAITING_IMAGE state"
            ):
                await self.run_script()

        # IDLE state: should raise AssertionError
        async with self.make_script():
            await self.configure_script()
            self.script.mtcs.rem.mtaos.evt_closedLoopState.aget = mock.AsyncMock(
                return_value=mock.Mock(state=MTAOS.ClosedLoopState.IDLE)
            )
            with self.assertRaises(
                AssertionError, msg="AOS Closed Loop is not in WAITING_IMAGE state"
            ):
                await self.run_script()

    async def test_run_collects_and_raises_assertion_errors(self):
        """Test that the script collects assertion errors and raises
        them at the end."""
        async with self.make_script():
            await self.configure_script()

            # Mock dome shutter to be closed
            self.script.mtcs.rem.mtdome.evt_shutterMotion.aget = mock.AsyncMock(
                return_value=mock.Mock(
                    state=[MTDome.MotionState.CLOSED, MTDome.MotionState.CLOSED]
                )
            )

            # Mock AOS closed loop to be in ERROR state
            self.script.mtcs.rem.mtaos.evt_closedLoopState.aget = mock.AsyncMock(
                return_value=mock.Mock(state=MTAOS.ClosedLoopState.ERROR)
            )

            with self.assertRaises(AssertionError):
                await self.run_script()

            # Verify that the script continued despite the assertion errors
            self.script.mtcs.enable_m2_balance_system.assert_awaited_once()
            self.script.mtcs.open_m1_cover.assert_awaited_once()
            self.script.mtcs.enable_ccw_following.assert_awaited_once()
            self.script.mtcs.enable_dome_following.assert_awaited_once()
            self.script.mtcs.assert_m1m3_force_balance_system_enabled.assert_awaited_once()
            self.script.mtcs.assert_m1m3_slew_controller_settings.assert_awaited_once()
            self.script.mtcs.enable_compensation_mode.assert_has_awaits(
                [mock.call("mthexapod_1"), mock.call("mthexapod_2")]
            )

            # Verify we have exactly 2 assertion errors
            self.assertEqual(len(self.script.assertion_errors), 2)

            # Check dome shutter error message
            dome_error_msg = str(self.script.assertion_errors[0])
            self.assertIn("Dome shutters are not open", dome_error_msg)
            self.assertIn(
                "Reported state: [<MotionState.CLOSED: 2>, <MotionState.CLOSED: 2>]",
                dome_error_msg,
            )
            self.assertIn(
                "Expected state: [<MotionState.OPEN: 6>, <MotionState.OPEN: 6>]",
                dome_error_msg,
            )
            self.assertIn("Please check and open the dome shutters", dome_error_msg)

            # Check AOS error message
            aos_error_msg = str(self.script.assertion_errors[1])
            self.assertIn(
                "AOS Closed Loop is not in WAITING_IMAGE state", aos_error_msg
            )
            self.assertIn("Current state: ERROR", aos_error_msg)
            self.assertIn("Make sure aos closed loop is enabled", aos_error_msg)

    async def test_run_mtm1m3ts_not_enabled(self):
        """Test the script fails when MTM1M3TS is not enabled."""
        async with self.make_script():
            await self.configure_script()

            # Set MTM1M3TS to STANDBY state
            self.script.mtm1m3ts.evt_summaryState.aget = mock.AsyncMock(
                return_value=mock.Mock(summaryState=salobj.State.STANDBY)
            )

            with pytest.raises(AssertionError):
                await self.run_script()

    async def test_run_mtm1m3ts_in_engineering_mode(self):
        """Test the script fails when MTM1M3TS is in engineering mode."""
        async with self.make_script():
            await self.configure_script()

            # Set MTM1M3TS to engineering mode
            self.script.mtm1m3ts.evt_engineeringMode.aget = mock.AsyncMock(
                return_value=mock.Mock(engineeringMode=True)
            )

            with pytest.raises(AssertionError):
                await self.run_script()

    async def test_run_mtm1m3ts_not_in_engineering_mode(self):
        """Test the script passes when MTM1M3TS is enabled and not in
        engineering mode."""
        async with self.make_script():
            await self.configure_script()

            # Verify MTM1M3TS state was checked
            await self.run_script()
            self.script.mtm1m3ts.evt_summaryState.aget.assert_awaited_once()
            self.script.mtm1m3ts.evt_engineeringMode.aget.assert_awaited_once()
