# This file is part of ts_maintel_standardscripts.
#
# Developed for the Vera C. Rubin Observatory Telescope and Site Systems.
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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

import types
import unittest
from unittest import mock

from lsst.ts import salobj, standardscripts
from lsst.ts.maintel.standardscripts.daytime_checkout import (
    BaseTelescopeCheckout,
    TelescopeAndDomeCheckout,
    TelescopeCheckout,
)
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages
from lsst.ts.observatory.control.utils.enums import RotType
from lsst.ts.xml.enums.Script import ScriptState


class TestTelescopeAndDomeCheckout(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    script_class: type[BaseTelescopeCheckout] = TelescopeAndDomeCheckout

    async def basic_make_script(self, index):
        self.script = self.script_class(index=index)
        self.script.mtcs = MTCS(
            domain=self.script.domain,
            intended_usage=MTCSUsages.DryTest,
            log=self.script.log,
        )
        self.script.mtcs.reset_checks()

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

        self.configure_run_mocks()
        return (self.script,)

    def configure_run_mocks(self):
        self.script.mtcs.assert_all_enabled = mock.AsyncMock()
        self.script.mtcs.enable = mock.AsyncMock()
        self.script.mtcs.prepare_for_telescope_and_dome_checkout = mock.AsyncMock(
            return_value=[]
        )
        self.script.mtcs.set_telescope_and_dome_checkout_final_state = mock.AsyncMock()
        self.script.mtcs.radec_from_azel = mock.Mock(
            return_value=types.SimpleNamespace(ra=1.0, dec=-2.0)
        )
        self.script.mtcs.slew_icrs = mock.AsyncMock()
        self.script.mtcs.check_tracking = mock.AsyncMock()
        self.script.mtcs.stop_tracking = mock.AsyncMock()
        self.script.mtcs.disable_dome_following = mock.AsyncMock()
        self.script.mtcs.disable_dome_following_if_dome_enabled = mock.AsyncMock()

    async def test_configure_defaults(self):
        async with self.make_script():
            await self.configure_script()

            schema = self.script.get_schema()
            assert schema["$id"].endswith("/telescope_and_dome_checkout.yaml")
            assert schema["title"] == "TelescopeAndDomeCheckout v1"
            assert "Telescope and MTDome" in schema["description"]
            assert set(schema["properties"]) == {
                "homing_attempts",
                "ignore",
            }
            assert "enum" not in schema["properties"]["ignore"]["items"]
            ignore_description = schema["properties"]["ignore"]["description"]
            assert "The combined checkout also requires" in ignore_description
            assert '"mtdome" and "mtdometrajectory"' in ignore_description
            documented_critical_components = (
                MTCS.get_critical_components_for_daytime_checkout(check_dome=True)
            )
            for component in documented_critical_components:
                assert component in ignore_description
            assert self.script.include_dome
            assert self.script.delta_az == 15.0
            assert self.script.delta_el == 15.0
            assert self.script.delta_rot == 15.0
            assert self.script.track_duration == 30.0

    async def test_configure_telescope_only(self):
        self.script_class = TelescopeCheckout
        async with self.make_script():
            await self.configure_script()

            schema = self.script.get_schema()
            assert not self.script.include_dome
            assert schema["$id"].endswith("/telescope_checkout.yaml")
            assert schema["title"] == "TelescopeCheckout v1"
            assert "Telescope daytime checkout" in schema["description"]
            assert "MTDome is not checked or commanded" in schema["description"]
            assert "check_dome" not in schema["properties"]
            assert (
                "telescope-only checkout automatically skips"
                in schema["properties"]["ignore"]["description"]
            )
            assert not self.script.mtcs.check.mtdome
            assert not self.script.mtcs.check.mtdometrajectory

    async def test_configure_rejects_check_dome(self):
        async with self.make_script():
            with self.assertRaises(salobj.ExpectedError):
                await self.configure_script(check_dome=False)

    async def test_configure_ignore_optional_components(self):
        async with self.make_script():
            await self.configure_script(ignore=["mtaos", "mthexapod_1", "mthexapod_2"])

            assert not self.script.mtcs.check.mtaos
            assert not self.script.mtcs.check.mthexapod_1
            assert not self.script.mtcs.check.mthexapod_2

    async def test_configure_rejects_ignored_critical_component(self):
        async with self.make_script():
            with self.assertRaises(salobj.ExpectedError):
                await self.configure_script(ignore=["mtmount"])

    async def test_configure_rejects_dome_ignore_when_checking_dome(self):
        async with self.make_script():
            with self.assertRaises(salobj.ExpectedError):
                await self.configure_script(ignore=["mtdome"])

    async def test_configure_rejects_unknown_ignore_component(self):
        async with self.make_script():
            with self.assertRaises(salobj.ExpectedError):
                await self.configure_script(ignore=["not_a_component"])

    async def test_ensure_group_all_enabled_enables_group(self):
        async with self.make_script():
            await self.configure_script()
            self.script.mtcs.assert_all_enabled.side_effect = [
                AssertionError("not enabled"),
                None,
            ]

            await self.script.ensure_group_all_enabled(self.script.mtcs, "MTCS")

            self.script.mtcs.enable.assert_awaited_once_with()
            assert self.script.mtcs.assert_all_enabled.await_count == 2

    async def test_run(self):
        async with self.make_script():
            await self.configure_script()
            await self.run_script()

            self.script.mtcs.assert_all_enabled.assert_awaited_once_with()
            self.script.mtcs.prepare_for_telescope_and_dome_checkout.assert_awaited_once_with(
                check_dome=True,
                homing_attempts=10,
            )
            self.script.mtcs.radec_from_azel.assert_called_once_with(
                az=self.script.mtcs.tel_park_az - self.script.delta_az,
                el=self.script.mtcs.tel_park_el - self.script.delta_el,
            )
            self.script.mtcs.slew_icrs.assert_awaited_once_with(
                ra=1.0,
                dec=-2.0,
                rot=self.script.mtcs.tel_park_rot + self.script.delta_rot,
                rot_type=RotType.PhysicalSky,
                target_name="Daytime checkout tracking target",
            )
            self.script.mtcs.check_tracking.assert_awaited_once_with(
                track_duration=30.0
            )
            self.script.mtcs.set_telescope_and_dome_checkout_final_state.assert_awaited_once_with(
                check_dome=True
            )
            self.script.mtm1m3ts.evt_summaryState.aget.assert_awaited_once()
            self.script.mtm1m3ts.evt_engineeringMode.aget.assert_awaited_once()

    async def test_run_without_dome(self):
        self.script_class = TelescopeCheckout
        async with self.make_script():
            await self.configure_script()
            await self.run_script()

            self.script.mtcs.prepare_for_telescope_and_dome_checkout.assert_awaited_once_with(
                check_dome=False,
                homing_attempts=10,
            )
            self.script.mtcs.set_telescope_and_dome_checkout_final_state.assert_awaited_once_with(
                check_dome=False
            )

    async def test_run_fails_mtm1m3ts_after_finalization(self):
        async with self.make_script():
            await self.configure_script()
            self.script.mtm1m3ts.evt_summaryState.aget.return_value = mock.Mock(
                summaryState=salobj.State.STANDBY
            )
            call_order = mock.Mock()
            call_order.attach_mock(
                self.script.mtcs.set_telescope_and_dome_checkout_final_state,
                "set_final_state",
            )
            call_order.attach_mock(
                self.script.mtm1m3ts.evt_summaryState.aget,
                "get_mtm1m3ts_summary_state",
            )

            with self.assertRaises(AssertionError):
                await self.run_script()

            self.script.mtcs.set_telescope_and_dome_checkout_final_state.assert_awaited_once()
            assert call_order.mock_calls[:2] == [
                mock.call.set_final_state(check_dome=True),
                mock.call.get_mtm1m3ts_summary_state(
                    timeout=self.script.mtcs.fast_timeout
                ),
            ]

    async def test_assert_mtm1m3ts_not_enabled_error(self):
        async with self.make_script():
            await self.configure_script()
            self.script.mtm1m3ts.evt_summaryState.aget.return_value = mock.Mock(
                summaryState=salobj.State.STANDBY
            )

            with self.assertRaisesRegex(
                RuntimeError,
                "MTM1M3TS is not enabled",
            ) as context:
                await self.script.assert_mtm1m3ts_not_in_engineering_mode()

            error_message = str(context.exception)
            assert "enable it before proceeding" in error_message
            assert "No need to repeat it due to this failure" in error_message

    async def test_assert_mtm1m3ts_engineering_mode_error(self):
        async with self.make_script():
            await self.configure_script()
            self.script.mtm1m3ts.evt_engineeringMode.aget.return_value = mock.Mock(
                engineeringMode=True
            )

            with self.assertRaisesRegex(
                RuntimeError,
                "MTM1M3TS is in engineering mode",
            ) as context:
                await self.script.assert_mtm1m3ts_not_in_engineering_mode()

            assert "No need to repeat it due to this failure" in str(context.exception)

    async def test_abnormal_cleanup_is_minimal(self):
        async with self.make_script():
            await self.configure_script()
            self.script.mtcs.slew_icrs.side_effect = RuntimeError("slew failed")

            await self.run_script(expected_final_state=ScriptState.FAILED)

            self.script.mtcs.stop_tracking.assert_awaited_once_with()
            self.script.mtcs.disable_dome_following.assert_awaited_once_with()
            self.script.mtcs.set_telescope_and_dome_checkout_final_state.assert_not_awaited()

    async def test_telescope_only_abnormal_cleanup_is_minimal(self):
        self.script_class = TelescopeCheckout
        async with self.make_script():
            await self.configure_script()
            self.script.mtcs.slew_icrs.side_effect = RuntimeError("slew failed")

            await self.run_script(expected_final_state=ScriptState.FAILED)

            self.script.mtcs.stop_tracking.assert_awaited_once_with()
            self.script.mtcs.disable_dome_following.assert_not_awaited()
            self.script.mtcs.disable_dome_following_if_dome_enabled.assert_awaited_once_with()
            self.script.mtcs.set_telescope_and_dome_checkout_final_state.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
