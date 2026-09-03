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
        self.script.wfoods = types.SimpleNamespace()

        return (self.script,)

    async def get_mtoods_ingest_event(self, flush, timeout):
        """Mock OODS ingestion events - return event for expected obsid"""
        if flush:
            await asyncio.sleep(timeout / 2.0)

        # Use current time to avoid stale event warnings
        current_time = utils.current_tai()

        obsid = getattr(self, "current_expected_obsid", f"MC_O_{self.dayobs}_000001")

        # Track how many events we've returned for this obsid
        event_count_key = f"mtoods_event_count_{obsid}"
        current_count = getattr(self, event_count_key, 0)

        # Return a reasonable number of events to simulate multiple raft/sensor
        # combinations but then raise TimeoutError to stop the collection loop
        if current_count >= 5:  # Return 5 events then timeout to end collection
            raise asyncio.TimeoutError("No more events")

        # Increment counter
        setattr(self, event_count_key, current_count + 1)

        # Return a representative raft/sensor event with different IDs
        return types.SimpleNamespace(
            private_sndStamp=current_time,
            obsid=obsid,
            raft=f"R{current_count:02d}",
            sensor=f"S{current_count:02d}",
            statusCode=0,
            description="file ingested",
        )

    async def get_wfoods_ingest_event(self, flush, timeout):
        """Mock WFOODS ingestion events for the expected obsid."""
        if flush:
            await asyncio.sleep(timeout / 2.0)

        current_time = utils.current_tai()
        obsid = getattr(self, "current_expected_obsid", f"MC_O_{self.dayobs}_000001")
        event_count_key = f"wfoods_event_count_{obsid}"
        current_count = getattr(self, event_count_key, 0)

        if current_count >= 2:
            raise asyncio.TimeoutError("No more events")

        setattr(self, event_count_key, current_count + 1)

        return types.SimpleNamespace(
            private_sndStamp=current_time,
            obsid=obsid,
            raft="R44",
            sensor=f"SW{current_count}",
            statusCode=0,
            description="file ingested",
        )

    @contextlib.asynccontextmanager
    async def setup_mocks(self):
        """Setup all necessary mocks"""
        # Mock LSSTCam methods
        self.script.lsstcam.take_darks = unittest.mock.AsyncMock(
            side_effect=[[20250101000002], [20250101000003]]
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
        self.script.wfoods = unittest.mock.AsyncMock()
        self.script.wfoods.configure_mock(
            **{
                "evt_imageInOODS.next.side_effect": self.get_wfoods_ingest_event,
                "evt_imageInOODS.flush": unittest.mock.Mock(),
            }
        )

        # Reset the expected obsid and raft/sensor counter on each flush so
        # that each exposure's ingestion is tracked independently.
        self.flush_count = 0
        self.wfoods_flush_count = 0

        def _mtoods_flush_side_effect():
            self.flush_count += 1
            # LSSTCam obsid: MC_O_<DAYOBS>_<VISIT>
            obsid = f"MC_O_{self.dayobs}_{self.flush_count:06d}"
            self.current_expected_obsid = obsid
            setattr(self, f"mtoods_event_count_{obsid}", 0)

        def _wfoods_flush_side_effect():
            self.wfoods_flush_count += 1
            setattr(self, f"wfoods_event_count_{self.current_expected_obsid}", 0)

        self.script.lsstcam.rem.mtoods.evt_imageInOODS.flush.side_effect = (
            _mtoods_flush_side_effect
        )
        self.script.wfoods.evt_imageInOODS.flush.side_effect = _wfoods_flush_side_effect

        yield

    async def test_configure(self):
        """Test basic configuration without ignore overrides."""
        async with self.make_script():
            await self.configure_script()

            assert self.script.lsstcam is not None
            assert self.script.program == "BLOCK-T594"
            assert self.script.reason == "LSSTCamCheckout"
            assert self.script.dark_exptime == 30.0
            assert self.script.ndarks == 2
            assert self.script.expected_dark_ingest_science == 189
            assert self.script.expected_dark_ingest_wfs == 8

    async def test_configure_metadata_overrides(self):
        """Ensure exposure metadata configuration can be overridden."""
        async with self.make_script():
            await self.configure_script(
                program="TestProgram",
                reason="TestReason",
            )

            assert self.script.program == "TestProgram"
            assert self.script.reason == "TestReason"

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

            # Override expected counts to match mock output: five MTOODS
            # science sensors and two WFOODS wavefront sensors.
            self.script.expected_dark_ingest_science = 5
            self.script.expected_dark_ingest_wfs = 2

            await self.run_script()

            # Verify image taking was called
            assert self.script.lsstcam.take_darks.await_count == 2
            self.script.lsstcam.take_darks.assert_has_awaits(
                [
                    unittest.mock.call(
                        exptime=30.0,
                        ndarks=1,
                        program="BLOCK-T594",
                        reason="LSSTCamCheckout",
                        note=None,
                    ),
                    unittest.mock.call(
                        exptime=30.0,
                        ndarks=1,
                        program="BLOCK-T594",
                        reason="LSSTCamCheckout",
                        note=None,
                    ),
                ]
            )
            self.script.lsstcam.assert_all_enabled.assert_called_once()

            # Verify ingestion helper was triggered for each exposure
            flush_mock = self.script.lsstcam.rem.mtoods.evt_imageInOODS.flush
            assert flush_mock.call_count == 2
            next_mock = self.script.lsstcam.rem.mtoods.evt_imageInOODS.next
            assert next_mock.await_count > 0
            wfoods_flush_mock = self.script.wfoods.evt_imageInOODS.flush
            assert wfoods_flush_mock.call_count == 2
            wfoods_next_mock = self.script.wfoods.evt_imageInOODS.next
            assert wfoods_next_mock.await_count > 0

    async def test_run_with_ingest_failure(self):
        """Test script with OODS ingestion failure"""
        async with self.make_script(), self.setup_mocks():
            await self.configure_script()

            @contextlib.asynccontextmanager
            async def failing_ingestion(*args, **kwargs):
                self.script.lsstcam.rem.mtoods.evt_imageInOODS.flush()
                self.script.wfoods.evt_imageInOODS.flush()
                # Simulate taking the image inside the context
                yield
                raise RuntimeError("No ingestion events received for expected obsid")

            self.script.ingested_image = failing_ingestion

            with pytest.raises(AssertionError):
                await self.run_script()

            # The first dark was taken before its ingestion check failed.
            assert self.script.lsstcam.take_darks.await_count == 1

    async def test_run_with_incomplete_ingestion(self):
        """Test script raises when fewer events than expected.

        The mocks return only five MTOODS science events and two WFOODS
        WFS events, but the real expected counts are 189 + 8 for a dark,
        so ingestion validation must raise RuntimeError.
        """
        async with self.make_script(), self.setup_mocks():
            await self.configure_script()

            # Keep real expected counts (189 science + 8 WFS for a dark).
            with pytest.raises(AssertionError):
                await self.run_script()

            assert self.script.lsstcam.take_darks.await_count == 1

    async def test_count_sensor_types(self):
        """Test _count_sensor_types classifies science, guider,
        wfs and other sensors correctly."""
        async with self.make_script():
            await self.configure_script()

            events = [
                types.SimpleNamespace(raft="R01", sensor="S00", statusCode=0),
                types.SimpleNamespace(raft="R01", sensor="S01", statusCode=0),
                types.SimpleNamespace(raft="R01", sensor="S10", statusCode=0),
                types.SimpleNamespace(raft="R00", sensor="SG0", statusCode=0),
                types.SimpleNamespace(raft="R00", sensor="SG1", statusCode=0),
                types.SimpleNamespace(raft="R44", sensor="SW0", statusCode=0),
                types.SimpleNamespace(raft="R44", sensor="SW1", statusCode=0),
            ]

            science, guider, wfs = self.script._count_sensor_types(events)

            assert science == {
                ("R01", "S00"),
                ("R01", "S01"),
                ("R01", "S10"),
            }
            assert guider == {
                ("R00", "SG0"),
                ("R00", "SG1"),
            }
            assert wfs == {
                ("R44", "SW0"),
                ("R44", "SW1"),
            }

    async def test_validate_ingestion_does_not_require_guider(self):
        """Guider events are informational and excluded from required math."""
        async with self.make_script():
            await self.configure_script()

            obsid = f"MC_O_{self.dayobs}_000001"
            event_time = utils.current_tai()
            mtoods_events = [
                types.SimpleNamespace(
                    private_sndStamp=event_time,
                    obsid=obsid,
                    raft="R01",
                    sensor="S00",
                    statusCode=0,
                ),
                types.SimpleNamespace(
                    private_sndStamp=event_time,
                    obsid=obsid,
                    raft="R00",
                    sensor="SG0",
                    statusCode=0,
                ),
            ]
            wfoods_events = [
                types.SimpleNamespace(
                    private_sndStamp=event_time,
                    obsid=obsid,
                    raft="R44",
                    sensor="SW0",
                    statusCode=0,
                )
            ]

            self.script._validate_ingestion(
                mtoods_events=mtoods_events,
                mtoods_obsid=obsid,
                wfoods_events=wfoods_events,
                wfoods_obsid=obsid,
                expected_science=1,
                expected_wfs=1,
                image_label="dark",
            )

    async def test_validate_ingestion_ignores_failed_status(self):
        """An OODS event with nonzero status does not satisfy the count."""
        async with self.make_script():
            await self.configure_script()

            obsid = f"MC_O_{self.dayobs}_000001"
            event_time = utils.current_tai()
            mtoods_events = [
                types.SimpleNamespace(
                    private_sndStamp=event_time,
                    obsid=obsid,
                    raft="R01",
                    sensor="S00",
                    statusCode=0,
                )
            ]
            wfoods_events = [
                types.SimpleNamespace(
                    private_sndStamp=event_time,
                    obsid=obsid,
                    raft="R44",
                    sensor="SW0",
                    statusCode=1,
                )
            ]

            with pytest.raises(RuntimeError, match=r"0/1 WFS sensors"):
                self.script._validate_ingestion(
                    mtoods_events=mtoods_events,
                    mtoods_obsid=obsid,
                    wfoods_events=wfoods_events,
                    wfoods_obsid=obsid,
                    expected_science=1,
                    expected_wfs=1,
                    image_label="dark",
                )

    async def test_validate_ingestion_warns_only_for_incomplete_sensor_type(self):
        """Do not warn about a sensor type whose ingestion is complete."""
        async with self.make_script():
            await self.configure_script()

            obsid = f"MC_O_{self.dayobs}_000001"
            event_time = utils.current_tai()
            mtoods_events = [
                types.SimpleNamespace(
                    private_sndStamp=event_time,
                    obsid=obsid,
                    raft="R01",
                    sensor="S00",
                    statusCode=0,
                )
            ]
            wfoods_events = [
                types.SimpleNamespace(
                    private_sndStamp=event_time,
                    obsid=obsid,
                    raft="R44",
                    sensor="SW0",
                    statusCode=0,
                )
            ]

            with unittest.mock.patch.object(self.script.log, "warning") as warning:
                with pytest.raises(RuntimeError, match=r"1/2 science sensors"):
                    self.script._validate_ingestion(
                        mtoods_events=mtoods_events,
                        mtoods_obsid=obsid,
                        wfoods_events=wfoods_events,
                        wfoods_obsid=obsid,
                        expected_science=2,
                        expected_wfs=1,
                        image_label="dark",
                    )

            warning.assert_called_once()
            assert "science-sensor ingestion" in warning.call_args.args[0]

    async def test_validate_ingestion_requires_matching_obsids(self):
        """MTOODS and WFOODS events cannot be mixed across exposures."""
        async with self.make_script():
            await self.configure_script()

            event_time = utils.current_tai()
            mtoods_obsid = f"MC_O_{self.dayobs}_000001"
            wfoods_obsid = f"MC_O_{self.dayobs}_000002"
            mtoods_events = [
                types.SimpleNamespace(
                    private_sndStamp=event_time,
                    obsid=mtoods_obsid,
                    raft="R01",
                    sensor="S00",
                    statusCode=0,
                )
            ]
            wfoods_events = [
                types.SimpleNamespace(
                    private_sndStamp=event_time,
                    obsid=wfoods_obsid,
                    raft="R44",
                    sensor="SW0",
                    statusCode=0,
                )
            ]

            with pytest.raises(RuntimeError, match="different obsids"):
                self.script._validate_ingestion(
                    mtoods_events=mtoods_events,
                    mtoods_obsid=mtoods_obsid,
                    wfoods_events=wfoods_events,
                    wfoods_obsid=wfoods_obsid,
                    expected_science=1,
                    expected_wfs=1,
                    image_label="dark",
                )
