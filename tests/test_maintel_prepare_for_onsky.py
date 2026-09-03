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

import logging
import unittest
from unittest import mock

from lsst.ts import salobj, standardscripts
from lsst.ts.maintel.standardscripts.prepare_for import PrepareForOnSky
from lsst.ts.observatory.control.maintel.lsstcam import LSSTCam, LSSTCamUsages
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages
from lsst.ts.xml.enums.Script import ScriptState

logging.basicConfig()


class TestPrepareForOnSky(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        self.script = PrepareForOnSky(index=index)
        self.script.mtcs = MTCS(
            domain=self.script.domain,
            log=self.script.log,
            intended_usage=MTCSUsages.DryTest,
        )
        self.script.lsstcam = LSSTCam(
            domain=self.script.domain,
            log=self.script.log,
            intended_usage=LSSTCamUsages.DryTest,
        )

        # Mock OCPS:101 remote
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

    async def test_configure(self):
        async with self.make_script():
            await self.configure_script()

            assert self.script.filter == "i_39"
            assert self.script.target_az == PrepareForOnSky.DEFAULT_TARGET_AZ
            assert self.script.target_el == PrepareForOnSky.DEFAULT_TARGET_EL
            assert self.script.target_rot == PrepareForOnSky.DEFAULT_TARGET_ROT

    async def test_configure_target_position(self):
        async with self.make_script():
            await self.configure_script(
                target_az=155.0,
                target_el=65.0,
                target_rot=5.0,
            )

            assert self.script.target_az == 155.0
            assert self.script.target_el == 65.0
            assert self.script.target_rot == 5.0

    async def test_configure_invalid_target_el(self):
        async with self.make_script():
            with self.assertRaises(salobj.ExpectedError):
                await self.configure_script(
                    target_el=PrepareForOnSky.MIN_TARGET_EL - 1.0,
                )

            with self.assertRaises(salobj.ExpectedError):
                await self.configure_script(
                    target_el=PrepareForOnSky.MAX_TARGET_EL + 1.0,
                )

    async def test_configure_filter_band(self):
        async with self.make_script():
            await self.configure_script(filter="i")

            assert self.script.filter == "i_39"

    async def test_configure_filter_full_name(self):
        async with self.make_script():
            await self.configure_script(filter="r_57")

            assert self.script.filter == "r_57"

    async def test_configure_invalid_filter(self):
        async with self.make_script():
            with self.assertRaises(salobj.ExpectedError):
                await self.configure_script(filter="not_a_filter")

    async def test_configure_ignore(self):
        async with self.make_script():
            await self.configure_script(
                ignore=["mtdometrajectory", "mthexapod_1", "mthexapod_2"]
            )

            assert not self.script.mtcs.check.mtdometrajectory
            assert not self.script.mtcs.check.mthexapod_1
            assert not self.script.mtcs.check.mthexapod_2

    async def test_configure_ignore_inexistent(self):
        async with self.make_script():
            await self.configure_script(ignore=["inexistent"])

            assert not hasattr(self.script.mtcs.check, "inexistent")
            assert not hasattr(self.script.lsstcam.check, "inexistent")

    async def test_configure_ignore_critical_components(self):
        async with self.make_script():
            # Get the actual critical components from MTCS
            critical_components = (
                self.script.mtcs.get_critical_components_for_prepare_for_onsky()
            )
            if critical_components:
                # One critical component ignored
                with self.assertRaises(salobj.ExpectedError):
                    await self.configure_script(ignore=["mtmount"])
                # Multiple critical components ignored
                with self.assertRaises(salobj.ExpectedError):
                    await self.configure_script(ignore=["mtm1m3", "mtm2", "mtptg"])

    async def test_run(self):
        async with self.make_script():
            await self.configure_script()

            self.script.mtcs.assert_all_enabled = unittest.mock.AsyncMock()
            self.script.lsstcam.assert_all_enabled = unittest.mock.AsyncMock()
            self.script.mtcs.prepare_for_onsky = unittest.mock.AsyncMock()
            self.script.lsstcam.setup_instrument = unittest.mock.AsyncMock()

            await self.run_script()

            # Verify the methods were called
            self.script.mtcs.assert_all_enabled.assert_called_once()
            self.script.lsstcam.assert_all_enabled.assert_called_once()
            self.script.mtcs.prepare_for_onsky.assert_called_once_with(
                homing_attempts=10,
                target_az=PrepareForOnSky.DEFAULT_TARGET_AZ,
                target_el=PrepareForOnSky.DEFAULT_TARGET_EL,
                target_rot=PrepareForOnSky.DEFAULT_TARGET_ROT,
            )
            self.script.lsstcam.setup_instrument.assert_called_once_with(filter="i_39")
            self.script.ocps.evt_summaryState.aget.assert_awaited_once()

    async def test_ensure_ocps_enabled(self):
        async with self.make_script():
            await self.configure_script()

            with mock.patch.object(
                salobj,
                "set_summary_state",
                new_callable=mock.AsyncMock,
            ) as set_summary_state:
                await self.script.ensure_ocps_enabled()

                set_summary_state.assert_not_awaited()

    async def test_ensure_ocps_enabled_from_standby(self):
        async with self.make_script():
            await self.configure_script()

            self.script.ocps.evt_summaryState.aget.return_value = mock.Mock(
                summaryState=salobj.State.STANDBY
            )

            with mock.patch.object(
                salobj,
                "set_summary_state",
                new_callable=mock.AsyncMock,
            ) as set_summary_state:
                await self.script.ensure_ocps_enabled()

                set_summary_state.assert_awaited_once_with(
                    self.script.ocps,
                    salobj.State.ENABLED,
                )

    async def test_run_with_target_position(self):
        async with self.make_script():
            await self.configure_script(
                target_az=155.0,
                target_el=65.0,
                target_rot=5.0,
            )

            self.script.mtcs.assert_all_enabled = unittest.mock.AsyncMock()
            self.script.lsstcam.assert_all_enabled = unittest.mock.AsyncMock()
            self.script.mtcs.prepare_for_onsky = unittest.mock.AsyncMock()
            self.script.lsstcam.setup_instrument = unittest.mock.AsyncMock()

            await self.run_script()

            self.script.mtcs.prepare_for_onsky.assert_called_once_with(
                homing_attempts=10,
                target_az=155.0,
                target_el=65.0,
                target_rot=5.0,
            )

    async def test_abnormal_cleanup_stops_tracking(self):
        async with self.make_script():
            await self.configure_script()

            self.script.mtcs.assert_all_enabled = mock.AsyncMock()
            self.script.mtcs.prepare_for_onsky = mock.AsyncMock(
                side_effect=RuntimeError("Preparation failed.")
            )
            self.script.mtcs.stop_tracking = mock.AsyncMock()

            await self.run_script(expected_final_state=ScriptState.FAILED)

            self.script.mtcs.stop_tracking.assert_awaited_once_with()

    async def test_run_ignore_non_critical_components(self):
        async with self.make_script():
            await self.configure_script(ignore=["mtdometrajectory"])

            self.script.mtcs.assert_all_enabled = unittest.mock.AsyncMock()
            self.script.lsstcam.assert_all_enabled = unittest.mock.AsyncMock()
            self.script.mtcs.prepare_for_onsky = unittest.mock.AsyncMock()
            self.script.lsstcam.setup_instrument = unittest.mock.AsyncMock()

            await self.run_script()

            # Verify the methods were called
            self.script.mtcs.assert_all_enabled.assert_called_once()
            self.script.lsstcam.assert_all_enabled.assert_called_once()
            self.script.mtcs.prepare_for_onsky.assert_called_once_with(
                homing_attempts=10,
                target_az=PrepareForOnSky.DEFAULT_TARGET_AZ,
                target_el=PrepareForOnSky.DEFAULT_TARGET_EL,
                target_rot=PrepareForOnSky.DEFAULT_TARGET_ROT,
            )
            self.script.lsstcam.setup_instrument.assert_called_once_with(filter="i_39")

    async def test_run_mtm1m3ts_not_enabled(self):
        """Test the script fails when MTM1M3TS is not enabled."""
        async with self.make_script():
            await self.configure_script()

            self.script.mtcs.assert_all_enabled = unittest.mock.AsyncMock()
            self.script.lsstcam.assert_all_enabled = unittest.mock.AsyncMock()
            self.script.mtcs.prepare_for_onsky = unittest.mock.AsyncMock()
            self.script.lsstcam.setup_instrument = unittest.mock.AsyncMock()

            # Set MTM1M3TS to STANDBY state
            self.script.mtm1m3ts.evt_summaryState.aget = mock.AsyncMock(
                return_value=mock.Mock(summaryState=salobj.State.STANDBY)
            )

            with self.assertRaises(AssertionError):
                await self.run_script()

    async def test_run_mtm1m3ts_in_engineering_mode(self):
        """Test the script fails when MTM1M3TS is in engineering mode."""
        async with self.make_script():
            await self.configure_script()

            self.script.mtcs.assert_all_enabled = unittest.mock.AsyncMock()
            self.script.lsstcam.assert_all_enabled = unittest.mock.AsyncMock()
            self.script.mtcs.prepare_for_onsky = unittest.mock.AsyncMock()
            self.script.lsstcam.setup_instrument = unittest.mock.AsyncMock()

            # Set MTM1M3TS to engineering mode
            self.script.mtm1m3ts.evt_engineeringMode.aget = mock.AsyncMock(
                return_value=mock.Mock(engineeringMode=True)
            )

            with self.assertRaises(AssertionError):
                await self.run_script()

    async def test_run_mtm1m3ts_check_passes(self):
        """Test the script passes MTM1M3TS check when enabled and not in
        engineering mode."""
        async with self.make_script():
            await self.configure_script()

            self.script.mtcs.assert_all_enabled = unittest.mock.AsyncMock()
            self.script.lsstcam.assert_all_enabled = unittest.mock.AsyncMock()
            self.script.mtcs.prepare_for_onsky = unittest.mock.AsyncMock()
            self.script.lsstcam.setup_instrument = unittest.mock.AsyncMock()

            await self.run_script()

            # Verify MTM1M3TS state was checked
            self.script.mtm1m3ts.evt_summaryState.aget.assert_awaited_once()
            self.script.mtm1m3ts.evt_engineeringMode.aget.assert_awaited_once()
