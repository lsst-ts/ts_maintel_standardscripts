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

import asyncio
import contextlib
import time
import types
import unittest
from unittest.mock import patch

import pytest
from lsst.ts import salobj, standardscripts, utils
from lsst.ts.maintel.standardscripts.daytime_checkout import LsstCamCheckout
from lsst.ts.observatory.control.maintel.lsstcam import LSSTCam, LSSTCamUsages


class TestLsstCamCheckout(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    def setUp(self) -> None:
        # Test data for OODS ingestion events
        self.ingest_event_status = 0
        self.ingest_time = time.time()
        self.expected_obsid = "MC_O_20250101_000001"
        self.current_filter = "r"
        self.available_filters = ["u", "g", "r", "i", "z"]
        return super().setUp()

    async def basic_make_script(self, index):
        self.script = LsstCamCheckout(index=index)

        self.script.lsstcam = LSSTCam(
            domain=self.script.domain,
            intended_usage=LSSTCamUsages.DryTest,
            log=self.script.log,
        )

        self.script.lsstcam.disable_checks_for_components = unittest.mock.Mock()

        return (self.script,)

    async def get_mtoods_ingest_event(self, flush, timeout):
        """Mock OODS ingestion events - return single event per call"""
        if flush:
            await asyncio.sleep(timeout / 2.0)
        # Return a representative raft/sensor event
        return types.SimpleNamespace(
            statusCode=self.ingest_event_status,
            private_sndStamp=self.ingest_time,
            obsid=self.expected_obsid,
            raft="R00",
            sensor="S00",
            description="Success",
        )

    @contextlib.asynccontextmanager
    async def setup_mocks(self):
        """Setup all necessary mocks"""
        # Mock LSSTCam methods
        self.script.lsstcam.take_bias = unittest.mock.AsyncMock(
            return_value=[20250101000001]
        )
        self.script.lsstcam.take_engtest = unittest.mock.AsyncMock(
            return_value=[20250101000002]
        )
        self.script.lsstcam.get_current_filter = unittest.mock.AsyncMock(
            return_value=self.current_filter
        )
        self.script.lsstcam.get_available_filters = unittest.mock.AsyncMock(
            return_value=self.available_filters
        )
        self.script.lsstcam.assert_all_enabled = unittest.mock.AsyncMock()
        self.script.lsstcam.disable_checks_for_components = unittest.mock.Mock()

        # Mock OODS remote
        self.script.lsstcam.rem = types.SimpleNamespace(
            mtoods=types.SimpleNamespace(evt_imageInOODS=unittest.mock.AsyncMock()),
        )
        self.script.lsstcam.rem.mtoods.evt_imageInOODS.flush = unittest.mock.Mock()
        self.script.lsstcam.rem.mtoods.evt_imageInOODS.next = unittest.mock.AsyncMock(
            side_effect=self.get_mtoods_ingest_event
        )

        yield

    async def test_configure_basic(self):
        """Test basic configuration without filter exercise"""
        async with self.make_script():
            await self.configure_script()

            assert not self.script.exercise_filters
            assert not self.script.filter_only
            assert self.script.mtcs is None

    async def test_configure_with_filter_exercise(self):
        """Test configuration with filter exercise enabled"""
        async with self.make_script():
            mock_mtcs = unittest.mock.AsyncMock()
            mock_mtcs.start_task = utils.make_done_future()
            mock_mtcs.disable_checks_for_components = unittest.mock.Mock()

            with patch(
                "lsst.ts.maintel.standardscripts.daytime_checkout.lsstcam_checkout.MTCS",
                return_value=mock_mtcs,
            ):
                await self.configure_script(exercise_filters=True)

                assert self.script.exercise_filters
                assert self.script.mtcs is not None

    async def test_configure_filter_only_validation(self):
        """Test validation that filter_only requires exercise_filters"""

        exercise_filters = False
        filter_only = True

        async with self.make_script():
            with self.assertRaises(salobj.ExpectedError):
                await self.configure_script(
                    exercise_filters=exercise_filters,
                    filter_only=filter_only,
                )

    async def test_configure_ignore_components(self):
        """Test ignore parameter functionality"""
        async with self.make_script():
            ignore_components = ["mtheaderservice", "mtmount", "no_csc"]
            exercise_filters = True
            exercise_filters_only = False

            mock_mtcs = unittest.mock.AsyncMock()
            mock_mtcs.start_task = utils.make_done_future()
            mock_mtcs.disable_checks_for_components = unittest.mock.Mock()

            with patch(
                "lsst.ts.maintel.standardscripts.daytime_checkout.lsstcam_checkout.MTCS",
                return_value=mock_mtcs,
            ):
                await self.configure_script(
                    exercise_filters=exercise_filters,
                    filter_only=exercise_filters_only,
                    ignore=ignore_components,
                )

            # Verify that disable_checks_for_components was called on MTCS
            self.script.mtcs.disable_checks_for_components.assert_called_once_with(
                components=ignore_components
            )

            # Verify that disable_checks_for_components was called on LSSTCam
            self.script.lsstcam.disable_checks_for_components.assert_called_once_with(
                components=ignore_components
            )

    async def test_configure_ignore_mtrotator_validation(self):
        """Test validation that mtrotator cannot be ignored with filters"""

        exercise_filters = True
        ignore_components = ["mtrotator"]

        async with self.make_script():
            with self.assertRaises(salobj.ExpectedError):
                await self.configure_script(
                    exercise_filters=exercise_filters,
                    ignore=ignore_components,
                )

    async def test_run_basic_checkout(self):
        """Test basic checkout without filter exercise"""
        async with self.make_script(), self.setup_mocks():
            await self.configure_script()

            await self.run_script()

            # Verify image taking was called
            self.script.lsstcam.take_bias.assert_awaited_once()
            self.script.lsstcam.take_engtest.assert_awaited_once()
            self.script.lsstcam.assert_all_enabled.assert_called_once()

    async def test_run_with_filter_exercise(self):
        """Test checkout with filter exercise"""
        async with self.make_script(), self.setup_mocks():
            mock_mtcs = unittest.mock.AsyncMock()
            mock_mtcs.start_task = utils.make_done_future()
            mock_mtcs.assert_all_enabled = unittest.mock.AsyncMock()
            mock_mtcs.change_filter = unittest.mock.AsyncMock()
            mock_mtcs.disable_checks_for_components = unittest.mock.Mock()

            with patch(
                "lsst.ts.maintel.standardscripts.daytime_checkout.lsstcam_checkout.MTCS",
                return_value=mock_mtcs,
            ):
                await self.configure_script(exercise_filters=True)
                self.script.mtcs = mock_mtcs

                await self.run_script()

                # Verify both image taking and filter exercise were called
                self.script.lsstcam.take_bias.assert_awaited_once()
                self.script.lsstcam.take_engtest.assert_awaited_once()
                self.script.lsstcam.assert_all_enabled.assert_called_once()
                self.script.mtcs.assert_all_enabled.assert_called_once()

                # Verify filter changes (current -> third -> original)
                expected_calls = [
                    unittest.mock.call(self.available_filters[2]),  # Third filter
                    unittest.mock.call(self.current_filter),  # Back to original
                ]
                self.script.mtcs.change_filter.assert_has_calls(expected_calls)

    async def test_run_filter_only(self):
        """Test filter-only mode (skip image checks)"""
        async with self.make_script(), self.setup_mocks():
            mock_mtcs = unittest.mock.AsyncMock()
            mock_mtcs.start_task = utils.make_done_future()
            mock_mtcs.assert_all_enabled = unittest.mock.AsyncMock()
            mock_mtcs.change_filter = unittest.mock.AsyncMock()
            mock_mtcs.disable_checks_for_components = unittest.mock.Mock()

            with patch(
                "lsst.ts.maintel.standardscripts.daytime_checkout.lsstcam_checkout.MTCS",
                return_value=mock_mtcs,
            ):
                await self.configure_script(exercise_filters=True, filter_only=True)
                self.script.mtcs = mock_mtcs

                await self.run_script()

                # Verify image taking was NOT called
                self.script.lsstcam.take_bias.assert_not_awaited()
                self.script.lsstcam.take_engtest.assert_not_awaited()

                # Verify filter exercise was called
                self.script.mtcs.change_filter.assert_called()

    async def test_run_script_with_ingest_failure(self):
        """Test script with OODS ingestion failure"""
        async with self.make_script(), self.setup_mocks():
            await self.configure_script()

            # Mock timeout error for OODS ingestion
            self.script.lsstcam.rem.mtoods.evt_imageInOODS.next = (
                unittest.mock.AsyncMock(side_effect=asyncio.TimeoutError)
            )

            with pytest.raises(RuntimeError, match="No ingestion events received"):
                await self.run_script()

            # Verify bias was taken but engtest was not
            # (failure happened during bias verification)
            self.script.lsstcam.take_bias.assert_awaited_once()
            self.script.lsstcam.take_engtest.assert_not_awaited()

    async def test_run_script_with_failed_ingestion_status(self):
        """Test script with failed ingestion status codes"""
        async with self.make_script(), self.setup_mocks():
            await self.configure_script()

            # Set up failed ingestion status
            self.ingest_event_status = 1  # Non-zero status indicates failure

            with pytest.raises(RuntimeError, match="Image ingestion failed"):
                await self.run_script()

            self.script.lsstcam.take_bias.assert_awaited_once()
            self.script.lsstcam.take_engtest.assert_not_awaited()

    async def test_filter_exercise_insufficient_filters(self):
        """Test filter exercise with insufficient filters"""
        async with self.make_script(), self.setup_mocks():
            mock_mtcs = unittest.mock.AsyncMock()
            mock_mtcs.start_task = utils.make_done_future()
            mock_mtcs.assert_all_enabled = unittest.mock.AsyncMock()
            mock_mtcs.disable_checks_for_components = unittest.mock.Mock()

            # Set up insufficient filters
            self.available_filters = ["u", "g"]  # Only 2 filters

            with patch(
                "lsst.ts.maintel.standardscripts.daytime_checkout.lsstcam_checkout.MTCS",
                return_value=mock_mtcs,
            ):
                await self.configure_script(exercise_filters=True, filter_only=True)
                self.script.mtcs = mock_mtcs

                with pytest.raises(RuntimeError, match="Need at least 3 filters"):
                    await self.run_script()

    async def test_filter_exercise_change_failure(self):
        """Test filter exercise with filter change failure"""
        async with self.make_script(), self.setup_mocks():
            mock_mtcs = unittest.mock.AsyncMock()
            mock_mtcs.start_task = utils.make_done_future()
            mock_mtcs.assert_all_enabled = unittest.mock.AsyncMock()
            mock_mtcs.change_filter = unittest.mock.AsyncMock(
                side_effect=Exception("Filter change failed")
            )
            mock_mtcs.disable_checks_for_components = unittest.mock.Mock()

            with patch(
                "lsst.ts.maintel.standardscripts.daytime_checkout.lsstcam_checkout.MTCS",
                return_value=mock_mtcs,
            ):
                await self.configure_script(exercise_filters=True, filter_only=True)
                self.script.mtcs = mock_mtcs

                with pytest.raises(RuntimeError, match="Failed to change filter"):
                    await self.run_script()
