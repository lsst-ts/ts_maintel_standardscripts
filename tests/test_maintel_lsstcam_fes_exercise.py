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
from lsst.ts.maintel.standardscripts.daytime_checkout import LsstCamFesExercise
from lsst.ts.observatory.control.maintel.lsstcam import LSSTCam, LSSTCamUsages
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages


class TestLsstCamFesExercise(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    def setUp(self) -> None:
        self.current_filter = "u_24"
        self.available_filters = ["u_24", "g_6", "i_39", "NONE"]
        self.mtcs_states = {
            "mtptg": salobj.State.ENABLED,
            "mtrotator": salobj.State.ENABLED,
            "mtmount": salobj.State.ENABLED,
        }
        return super().setUp()

    async def basic_make_script(self, index):
        self.script = LsstCamFesExercise(index=index)
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

        self.script.mtcs.disable_checks_for_components = unittest.mock.Mock()
        self.script.mtcs.assert_all_enabled = unittest.mock.AsyncMock()

        async def _get_state(name):
            return self.mtcs_states.get(name, salobj.State.ENABLED)

        self.script.mtcs.get_state = unittest.mock.AsyncMock(side_effect=_get_state)

        self.script.lsstcam.disable_checks_for_components = unittest.mock.Mock()
        self.script.lsstcam.assert_all_enabled = unittest.mock.AsyncMock()
        self.script.lsstcam.filter_change_timeout = 30.0

        async def _setup_instrument(*, filter: str, **kwargs):
            # Simulate camera state changing after a successful filter move.
            self.current_filter = filter

        self.script.lsstcam.setup_instrument = unittest.mock.AsyncMock(
            side_effect=_setup_instrument
        )

        async def _get_current_filter():
            return self.current_filter

        async def _get_available_filters():
            return list(self.available_filters)

        self.script.lsstcam.get_current_filter = unittest.mock.AsyncMock(
            side_effect=_get_current_filter
        )
        self.script.lsstcam.get_available_filters = unittest.mock.AsyncMock(
            side_effect=_get_available_filters
        )

        return (self.script,)

    async def test_configure_maps_final_filter(self):
        async with self.make_script():
            await self.configure_script(final_filter="i")

            assert self.script.final_filter == "i_39"

    async def test_configure_filters_ignore_list(self):
        async with self.make_script():
            ignore_components = ["mtrotator", "mtheaderservice"]

            await self.configure_script(ignore=ignore_components)

            expected = ["mtheaderservice"]
            self.script.mtcs.disable_checks_for_components.assert_called_once_with(
                components=expected
            )
            self.script.lsstcam.disable_checks_for_components.assert_called_once_with(
                components=expected
            )

    async def test_run(self):
        """Test most common scenario."""
        async with self.make_script():
            await self.configure_script()

            with mock.patch(
                "lsst.ts.maintel.standardscripts.daytime_checkout.lsstcam_fes_exercise.random.choice",
                return_value="g_6",
            ), mock.patch(
                "lsst.ts.maintel.standardscripts.daytime_checkout."
                "lsstcam_fes_exercise.SLEEP_BETWEEN_FILTER_CHANGES",
                2,
            ):
                await self.run_script()

            expected_calls = [
                unittest.mock.call(filter="g_6"),
                unittest.mock.call(filter="i_39"),
            ]
            self.script.lsstcam.setup_instrument.assert_has_calls(expected_calls)

    async def test_run_handles_none_current_filter(self):
        """Test that the script handles a 'NONE' current filter gracefully."""
        self.current_filter = "NONE"
        async with self.make_script():
            await self.configure_script()

            with mock.patch(
                "lsst.ts.maintel.standardscripts.daytime_checkout.lsstcam_fes_exercise.random.choice",
                return_value="g_6",
            ), mock.patch(
                "lsst.ts.maintel.standardscripts.daytime_checkout."
                "lsstcam_fes_exercise.SLEEP_BETWEEN_FILTER_CHANGES",
                2,
            ):
                await self.run_script()

            expected_calls = [
                unittest.mock.call(filter="g_6"),
                unittest.mock.call(filter="i_39"),
            ]
            self.script.lsstcam.setup_instrument.assert_has_calls(expected_calls)

    async def test_run_warns_when_only_one_filter_available(self):
        """Test that the script logs a warning and proceeds without
        intermediate filter change if only one physical filter is available."""
        self.available_filters = ["i_39"]
        self.current_filter = "NONE"
        async with self.make_script():
            await self.configure_script()

            with self.assertLogs(self.script.log, level="WARNING") as log_cm:
                await self.run_script()

            self.script.lsstcam.setup_instrument.assert_awaited_once_with(filter="i_39")
            assert any("Only one physical filter" in msg for msg in log_cm.output)

    async def test_run_warns_and_skips_intermediate_if_no_distinct_candidate(self):
        self.available_filters = ["u_24", "i_39"]
        self.current_filter = "u_24"
        async with self.make_script():
            await self.configure_script()

            with mock.patch(
                "lsst.ts.maintel.standardscripts.daytime_checkout.lsstcam_fes_exercise.random.choice",
                new=unittest.mock.Mock(),
            ) as choice_mock, self.assertLogs(
                self.script.log, level="WARNING"
            ) as log_cm:
                await self.run_script()

            choice_mock.assert_not_called()
            self.script.lsstcam.setup_instrument.assert_awaited_once_with(filter="i_39")
            assert any(
                "No distinct intermediate filter" in msg for msg in log_cm.output
            )

    async def test_run_single_filter_no_move_if_already_in_beam(self):
        self.available_filters = ["i_39"]
        self.current_filter = "i_39"
        async with self.make_script():
            await self.configure_script()

            with self.assertLogs(self.script.log, level="WARNING") as log_cm:
                await self.run_script()

            self.script.lsstcam.setup_instrument.assert_not_awaited()
            assert any("Only one physical filter" in msg for msg in log_cm.output)

    async def test_run_fails_when_final_filter_missing(self):
        self.available_filters = ["u_24", "g_6"]
        async with self.make_script():
            await self.configure_script(final_filter="i")

            with pytest.raises(AssertionError):
                await self.run_script()

    async def test_run_requires_enabled_mtcs_components(self):
        """Test the script fails if critical MTCS comp. are not enabled."""
        self.mtcs_states["mtptg"] = salobj.State.DISABLED
        async with self.make_script():
            await self.configure_script()

            with pytest.raises(AssertionError):
                await self.run_script()

    async def test_run_fails_if_cannot_read_current_filter(self):
        """Test the script raises if it cannot read the current filter."""
        async with self.make_script():
            await self.configure_script()

            self.script.lsstcam.get_current_filter = unittest.mock.AsyncMock(
                side_effect=RuntimeError("boom")
            )

            with pytest.raises(AssertionError):
                await self.run_script()

            self.script.lsstcam.setup_instrument.assert_not_awaited()

    async def test_run_fails_if_cannot_read_available_filters(self):
        """Test the script raises if it cannot read the available filters."""
        async with self.make_script():
            await self.configure_script()

            self.script.lsstcam.get_available_filters = unittest.mock.AsyncMock(
                side_effect=RuntimeError("boom")
            )

            with pytest.raises(AssertionError):
                await self.run_script()

            self.script.lsstcam.setup_instrument.assert_not_awaited()
