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
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import unittest
from types import SimpleNamespace
from unittest.mock import call, patch

from lsst.ts import standardscripts
from lsst.ts.maintel.standardscripts import HomeBothAxes
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages
from lsst.ts.xml.enums.MTM1M3 import DetailedStates


class TestHomeBothAxes(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        self.script = HomeBothAxes(index=index)

        self.script.mtcs = MTCS(
            domain=self.script.domain,
            intended_usage=MTCSUsages.DryTest,
            log=self.script.log,
        )
        self.script.mtcs.rem.mtmount = unittest.mock.AsyncMock()
        self.script.mtcs.rem.mtm1m3 = unittest.mock.AsyncMock()
        self.script.mtcs.rem.mtm1m3.evt_detailedState = unittest.mock.AsyncMock()
        self.script.mtcs.rem.mtm1m3.evt_detailedState.aget = unittest.mock.AsyncMock()
        self.script.mtcs.disable_m1m3_balance_system = unittest.mock.AsyncMock()
        self.script.mtcs.enable_m1m3_balance_system = unittest.mock.AsyncMock()
        self.script.mtcs.m1m3_booster_valve = unittest.mock.MagicMock()
        self.script.mtcs.m1m3_booster_valve.return_value.__aenter__ = (
            unittest.mock.AsyncMock(return_value=None)
        )
        self.script.mtcs.m1m3_booster_valve.return_value.__aexit__ = (
            unittest.mock.AsyncMock(return_value=None)
        )
        self.script.mtcs.point_azel = unittest.mock.AsyncMock()
        self.script.mtcs.stop_tracking = unittest.mock.AsyncMock()
        self.script.mtcs.fast_timeout = 1.0

        return (self.script,)

    async def test_run(self):
        async with self.make_script():
            # Simulate M1M3 raised (ACTIVE state).
            self.script.mtcs.rem.mtm1m3.evt_detailedState.aget.return_value = (
                SimpleNamespace(detailedState=DetailedStates.ACTIVE)
            )
            await self.configure_script()

            await self.run_script()

            self.script.mtcs.disable_m1m3_balance_system.assert_not_called()
            self.script.mtcs.rem.mtmount.cmd_homeBothAxes.start.assert_awaited_once_with(
                timeout=self.script.home_both_axes_timeout
            )
            self.script.mtcs.enable_m1m3_balance_system.assert_awaited_once()
            self.script.mtcs.m1m3_booster_valve.assert_called()

    async def test_run_with_balance_disabled(self):
        async with self.make_script():
            self.script.mtcs.rem.mtm1m3.evt_detailedState.aget.return_value = (
                SimpleNamespace(detailedState=DetailedStates.ACTIVE)
            )
            await self.configure_script(disable_m1m3_force_balance=True)

            await self.run_script()

            # disable_m1m3_force_balance is deprecated and ignored; the
            # script always enables the force balance system before
            # homing and never disables it.
            self.script.mtcs.disable_m1m3_balance_system.assert_not_called()

            self.script.mtcs.rem.mtmount.cmd_homeBothAxes.start.assert_awaited_once_with(
                timeout=self.script.home_both_axes_timeout
            )
            self.script.mtcs.enable_m1m3_balance_system.assert_awaited_once()

    async def test_deprecated_ignore_m1m3_usage(self):
        async with self.make_script():
            self.script.mtcs.rem.mtm1m3.evt_detailedState.aget.return_value = (
                SimpleNamespace(detailedState=DetailedStates.ACTIVE)
            )
            with patch.object(self.script.log, "warning") as mock_log_warning:
                await self.configure_script(ignore_m1m3=True)

                # Both 'ignore_m1m3' and 'disable_m1m3_force_balance' are
                # deprecated and emit warnings during configure; ensure at
                # least one warning was issued mentioning ignore_m1m3.
                assert mock_log_warning.call_count >= 1
                assert any(
                    "ignore_m1m3" in str(call.args[0])
                    for call in mock_log_warning.call_args_list
                )

            await self.run_script()

            self.script.mtcs.disable_m1m3_balance_system.assert_not_called()

            self.script.mtcs.rem.mtmount.cmd_homeBothAxes.start.assert_awaited_once_with(
                timeout=self.script.home_both_axes_timeout
            )
            self.script.mtcs.enable_m1m3_balance_system.assert_awaited_once()

    async def test_run_with_final_home_position_enabled(self):
        async with self.make_script():
            self.script.mtcs.rem.mtm1m3.evt_detailedState.aget.return_value = (
                SimpleNamespace(detailedState=DetailedStates.ACTIVE)
            )
            await self.configure_script(final_home_position={"az": 1, "el": 46})

            await self.run_script()

            self.script.mtcs.point_azel.assert_has_awaits(
                [
                    call(az=1, el=unittest.mock.ANY, wait_dome=False),
                    call(az=unittest.mock.ANY, el=46, wait_dome=False),
                ]
            )

            self.script.mtcs.rem.mtmount.cmd_homeBothAxes.start.assert_has_awaits(
                [
                    call(timeout=self.script.home_both_axes_timeout),
                    call(timeout=self.script.home_both_axes_timeout),
                ]
            )

            # Force balance remains enabled; disable_m1m3_force_balance is
            # deprecated and ignored by the script.

            self.script.mtcs.disable_m1m3_balance_system.assert_not_called()
            self.script.mtcs.enable_m1m3_balance_system.assert_awaited_once()
            self.script.mtcs.m1m3_booster_valve.assert_called()


if __name__ == "__main__":
    unittest.main()
