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
        self.current_filter = "u"
        self.available_filters = ["u", "g", "r", "i", "z"]
        # Fixed synthetic DAYOBS used to build realistic LSSTCam obsids
        self.dayobs = 20251101

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
        """Mock OODS ingestion events - return event for expected obsid"""
        if flush:
            await asyncio.sleep(timeout / 2.0)

        # Use current time to avoid stale event warnings
        current_time = utils.current_tai()

        obsid = getattr(self, "current_expected_obsid", f"MC_O_{self.dayobs}_000001")

        # Track how many events we've returned for this obsid
        event_count_key = f"event_count_{obsid}"
        current_count = getattr(self, event_count_key, 0)

        # Return a reasonable number of events to simulate multiple raft/sensor
        # combinations but then raise TimeoutError to stop the collection loop
        if current_count >= 5:  # Return 5 events then timeout to end collection
            raise asyncio.TimeoutError("No more events")

        # Increment counter
        setattr(self, event_count_key, current_count + 1)

        # Return a representative raft/sensor event with different IDs
        return types.SimpleNamespace(
            statusCode=self.ingest_event_status,
            private_sndStamp=current_time,
            obsid=obsid,
            raft=f"R{current_count:02d}",
            sensor=f"S{current_count:02d}",
            description="file ingested",
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

        self.script.lsstcam.rem = types.SimpleNamespace(
            mtoods=unittest.mock.AsyncMock(),
        )
        self.script.lsstcam.rem.mtoods.configure_mock(
            **{
                "evt_imageInOODS.next.side_effect": self.get_mtoods_ingest_event,
                "evt_imageInOODS.flush": unittest.mock.Mock(),
            }
        )

        # Reset the expected obsid and raft/sensor counter on each flush so
        # that each exposure's ingestion is tracked independently.
        self.flush_count = 0

        def _flush_side_effect():
            self.flush_count += 1
            # LSSTCam obsid: MC_O_<DAYOBS>_<VISIT>
            obsid = f"MC_O_{self.dayobs}_{self.flush_count:06d}"
            self.current_expected_obsid = obsid
            setattr(self, f"event_count_{obsid}", 0)

        self.script.lsstcam.rem.mtoods.evt_imageInOODS.flush.side_effect = (
            _flush_side_effect
        )

        yield

    async def get_state_side_effect(self, name):
        if name == "mtptg":
            return salobj.State.ENABLED
        if name == "mtrotator":
            return salobj.State.ENABLED
        if name == "mtmount":
            return salobj.State.DISABLED
        return salobj.State.ENABLED

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
            # New strict checks require querying states

            mock_mtcs.get_state = unittest.mock.AsyncMock(
                side_effect=self.get_state_side_effect
            )

            with patch(
                "lsst.ts.maintel.standardscripts.daytime_checkout.lsstcam_checkout.MTCS",
                return_value=mock_mtcs,
            ):
                await self.configure_script(exercise_filters=True)

                assert self.script.exercise_filters
                assert self.script.mtcs is not None

    async def test_configure_filter_only_validation(self):
        """Test that filter_only forces exercise_filters with a warning"""

        exercise_filters = False
        filter_only = True

        async with self.make_script():
            mock_mtcs = unittest.mock.AsyncMock()
            mock_mtcs.start_task = utils.make_done_future()
            mock_mtcs.disable_checks_for_components = unittest.mock.Mock()
            mock_mtcs.get_state = unittest.mock.AsyncMock(
                side_effect=self.get_state_side_effect
            )

            with patch(
                "lsst.ts.maintel.standardscripts.daytime_checkout.lsstcam_checkout.MTCS",
                return_value=mock_mtcs,
            ):
                await self.configure_script(
                    exercise_filters=exercise_filters,
                    filter_only=filter_only,
                )

                # exercise_filters should have been forced True
                assert self.script.exercise_filters is True
                assert self.script.filter_only is True
                assert self.script.mtcs is not None

    async def test_configure_ignore_components(self):
        """Test ignore parameter functionality"""
        async with self.make_script():

            ignore_components = ["mtheaderservice", "no_csc"]
            exercise_filters = True
            exercise_filters_only = False

            mock_mtcs = unittest.mock.AsyncMock()
            mock_mtcs.start_task = utils.make_done_future()
            mock_mtcs.disable_checks_for_components = unittest.mock.Mock()

            mock_mtcs.get_state = unittest.mock.AsyncMock(
                side_effect=self.get_state_side_effect
            )

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

    async def test_configure_ignore_mtrotator_auto_removal(self):
        """Critical 'mtrotator' is auto-removed from ignore when
        exercising filters."""

        exercise_filters = True
        ignore_components = ["mtrotator"]

        async with self.make_script():
            mock_mtcs = unittest.mock.AsyncMock()
            mock_mtcs.start_task = utils.make_done_future()
            mock_mtcs.disable_checks_for_components = unittest.mock.Mock()
            mock_mtcs.get_state = unittest.mock.AsyncMock(
                side_effect=self.get_state_side_effect
            )
            with patch(
                "lsst.ts.maintel.standardscripts.daytime_checkout.lsstcam_checkout.MTCS",
                return_value=mock_mtcs,
            ):
                await self.configure_script(
                    exercise_filters=exercise_filters,
                    ignore=ignore_components,
                )

                # Critical component should be removed; resulting list is empty
                self.script.lsstcam.disable_checks_for_components.assert_called_once_with(
                    components=[]
                )
                self.script.mtcs.disable_checks_for_components.assert_called_once_with(
                    components=[]
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

            # Verify ingestion helper was triggered for each exposure
            flush_mock = self.script.lsstcam.rem.mtoods.evt_imageInOODS.flush
            assert flush_mock.call_count == 2
            next_mock = self.script.lsstcam.rem.mtoods.evt_imageInOODS.next
            assert next_mock.await_count > 0

    async def test_run_with_filter_exercise(self):
        """Test checkout with filter exercise"""

        exercise_filters = True
        filter_only = False

        async with self.make_script(), self.setup_mocks():
            mock_mtcs = unittest.mock.AsyncMock()
            mock_mtcs.start_task = utils.make_done_future()
            mock_mtcs.assert_all_enabled = unittest.mock.AsyncMock()
            mock_mtcs.disable_checks_for_components = unittest.mock.Mock()
            self.script.lsstcam.setup_instrument = unittest.mock.AsyncMock()

            mock_mtcs.get_state = unittest.mock.AsyncMock(
                side_effect=self.get_state_side_effect
            )

            # Mock random.choice to return a predictable but different filter
            expected_intermediate_filter = "g"

            with patch(
                "lsst.ts.maintel.standardscripts.daytime_checkout.lsstcam_checkout.MTCS",
                return_value=mock_mtcs,
            ), patch(
                "lsst.ts.maintel.standardscripts.daytime_checkout.lsstcam_checkout.random.choice",
                return_value=expected_intermediate_filter,
            ):
                await self.configure_script(
                    exercise_filters=exercise_filters,
                    filter_only=filter_only,
                )
                self.script.mtcs = mock_mtcs

                await self.run_script()

                # Verify both image taking and filter exercise were called
                self.script.lsstcam.take_bias.assert_awaited_once()
                self.script.lsstcam.take_engtest.assert_awaited_once()
                self.script.lsstcam.assert_all_enabled.assert_called_once()
                self.script.mtcs.assert_all_enabled.assert_called_once()

                # Verify filter changes via camera (current -> expected ->
                # original)
                expected_calls = [
                    unittest.mock.call(filter=expected_intermediate_filter),
                    unittest.mock.call(filter=self.current_filter),
                ]
                self.script.lsstcam.setup_instrument.assert_has_calls(expected_calls)

    async def test_run_filter_only(self):
        """Test filter-only mode (skip image checks)"""
        async with self.make_script(), self.setup_mocks():
            mock_mtcs = unittest.mock.AsyncMock()
            mock_mtcs.start_task = utils.make_done_future()
            mock_mtcs.assert_all_enabled = unittest.mock.AsyncMock()
            mock_mtcs.disable_checks_for_components = unittest.mock.Mock()
            self.script.lsstcam.setup_instrument = unittest.mock.AsyncMock()

            mock_mtcs.get_state = unittest.mock.AsyncMock(
                side_effect=self.get_state_side_effect
            )

            # Mock random.choice to return a predictable but different filter
            expected_intermediate_filter = "r"  # Different from current "u"

            with patch(
                "lsst.ts.maintel.standardscripts.daytime_checkout.lsstcam_checkout.MTCS",
                return_value=mock_mtcs,
            ), patch(
                "lsst.ts.maintel.standardscripts.daytime_checkout.lsstcam_checkout.random.choice",
                return_value=expected_intermediate_filter,
            ):
                await self.configure_script(exercise_filters=True, filter_only=True)
                self.script.mtcs = mock_mtcs

                await self.run_script()

                # Verify image taking was NOT called
                self.script.lsstcam.take_bias.assert_not_awaited()
                self.script.lsstcam.take_engtest.assert_not_awaited()

                # Verify filter exercise was called with expected sequence
                expected_calls = [
                    unittest.mock.call(filter=expected_intermediate_filter),
                    unittest.mock.call(filter=self.current_filter),
                ]
                self.script.lsstcam.setup_instrument.assert_has_calls(expected_calls)

    async def test_run_with_ingest_failure(self):
        """Test script with OODS ingestion failure"""
        async with self.make_script(), self.setup_mocks():
            await self.configure_script()

            @contextlib.asynccontextmanager
            async def failing_ingestion(*args, **kwargs):
                self.script.lsstcam.rem.mtoods.evt_imageInOODS.flush()
                # Simulate taking the image inside the context
                yield
                raise RuntimeError("No ingestion events received for expected obsid")

            self.script.ingested_image = failing_ingestion

            with pytest.raises(AssertionError):
                await self.run_script()

            # Verify bias was taken but engtest was not
            self.script.lsstcam.take_bias.assert_awaited_once()
            self.script.lsstcam.take_engtest.assert_not_awaited()

    async def test_run_with_failed_ingestion_status(self):
        """Test script with failed ingestion status codes"""
        async with self.make_script(), self.setup_mocks():
            await self.configure_script()

            # Set up failed ingestion status
            self.ingest_event_status = 1

            with pytest.raises(AssertionError):
                await self.run_script()

            self.script.lsstcam.take_bias.assert_awaited_once()
            self.script.lsstcam.take_engtest.assert_not_awaited()

    async def test_filter_exercise_change_failure(self):
        """Test filter exercise with filter change failure"""

        exercise_filters = True
        filter_only = True

        async with self.make_script(), self.setup_mocks():
            mock_mtcs = unittest.mock.AsyncMock()
            mock_mtcs.start_task = utils.make_done_future()
            mock_mtcs.assert_all_enabled = unittest.mock.AsyncMock()
            mock_mtcs.disable_checks_for_components = unittest.mock.Mock()

            mock_mtcs.get_state = unittest.mock.AsyncMock(
                side_effect=self.get_state_side_effect
            )
            # Fail the camera's setup_instrument during filter exercise
            self.script.lsstcam.setup_instrument = unittest.mock.AsyncMock(
                side_effect=Exception("Filter change failed")
            )

            # Mock random.choice to return a predictable but different filter
            expected_intermediate_filter = "i"

            with patch(
                "lsst.ts.maintel.standardscripts.daytime_checkout.lsstcam_checkout.MTCS",
                return_value=mock_mtcs,
            ), patch(
                "lsst.ts.maintel.standardscripts.daytime_checkout.lsstcam_checkout.random.choice",
                return_value=expected_intermediate_filter,
            ):
                await self.configure_script(
                    exercise_filters=exercise_filters, filter_only=filter_only
                )
                self.script.mtcs = mock_mtcs

                with pytest.raises(AssertionError):
                    await self.run_script()
