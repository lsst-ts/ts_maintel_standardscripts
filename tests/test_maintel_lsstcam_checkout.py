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

import pytest
from lsst.ts import standardscripts, utils
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

    async def test_configure(self):
        """Test basic configuration without ignore overrides."""
        async with self.make_script():
            await self.configure_script()

            assert self.script.lsstcam is not None

    async def test_configure_ignore_components(self):
        """Ensure ignore list is forwarded to LSSTCam."""
        async with self.make_script():
            ignore_components = ["mtheaderservice", "no_csc"]

            await self.configure_script(ignore=ignore_components)

            self.script.lsstcam.disable_checks_for_components.assert_called_once_with(
                components=ignore_components
            )

    async def test_run(self):
        """Test the standard checkout flow."""
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
