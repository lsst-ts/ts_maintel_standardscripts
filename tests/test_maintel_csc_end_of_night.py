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
import logging
import unittest
from types import SimpleNamespace

import pytest
from lsst.ts import salobj, standardscripts
from lsst.ts.maintel.standardscripts import CscEndOfNight, EndOfNightConfig
from lsst.ts.observatory.control import RemoteGroup
from lsst.ts.observatory.control.maintel.lsstcam import LSSTCam, LSSTCamUsages
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages
from lsst.ts.xml.enums.Script import ScriptState
from lsst.ts.xml.sal_enums import State


class MockSetSummaryState:
    """
    Class for mocking the set_summary_state function.
    """

    def __init__(self, log: logging.Logger):
        self.log = log
        self.fails = []
        self.csc_states = dict()

    def set_fails(self, fails: list[str]):
        """
        Defines the CSCs to raise exceptions
        """
        self.fails = fails

    async def set_summary_state(
        self,
        remote: unittest.mock.AsyncMock,
        state: salobj.State,
        override="",
        timeout=30,
    ):
        """
        Emulates a call to salobj.set_summary_state saving parameters and
        raising exception.
        """
        csc = await remote()
        if csc not in self.fails:
            self.csc_states[csc] = state.name
            self.log.debug(
                f"emulating call: set_sumary_state(remote={csc!r}, state={state.name!r})"
            )
        else:
            # Emulates the exception raised by set_summary_state when it fails.
            self.log.debug(
                f"emulating call: set_sumary_state(remote={csc!r}, state={state.name!r}) [[EMULATE FAILING]]"
            )
            raise asyncio.TimeoutError

        return [state]


class MockEvtSummaryState:
    """
    Class for mocking the evt_summaryState object.
    """

    def __init__(self, states: dict[str, str], component: str, log: logging.Logger):
        self.states = states
        self.comp = component
        self.log = log

    async def aget(self, timeout=0.0, flush=False):
        if self.comp in self.states:
            self.log.debug(
                f"emulating {self.comp}.evt_summaryState.aget(): state={self.states[self.comp]!r})"
            )
            return SimpleNamespace(
                summaryState=getattr(State, self.states[self.comp]).value
            )
        else:
            self.log.debug(
                f"emulating {self.comp}.evt_summaryState.aget(): [[EMULATE FAILING]]"
            )
            raise asyncio.TimeoutError


class TestCscEndOfNight(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        self.script = CscEndOfNight(index=index)
        self.mock_set_summary_state = None

        return (self.script,)

    @contextlib.asynccontextmanager
    async def setup_mocks(self):
        # Mock the `salobj.set_summary_state` function
        self.mock_set_summary_state = MockSetSummaryState(log=self.script.log)
        with unittest.mock.patch(
            "lsst.ts.salobj.set_summary_state",
            side_effect=self.mock_set_summary_state.set_summary_state,
        ):
            # Mock remotes
            self.setup_group_mocks(self.script.mtcs)
            self.setup_group_mocks(self.script.lsstcam)

            yield

    def setup_group_mocks(self, group: RemoteGroup):
        for comp in group.components_attr:
            comp_mock = unittest.mock.AsyncMock()
            mock_evt_summaryState = MockEvtSummaryState(
                states=self.mock_set_summary_state.csc_states,
                component=comp,
                log=self.script.log,
            )
            comp_mock.configure_mock(
                **{
                    "return_value": comp,
                    "evt_summaryState": mock_evt_summaryState,
                },
            )
            setattr(group.rem, comp, comp_mock)

    @contextlib.asynccontextmanager
    async def make_dry_script(self):
        async with self.make_script():
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
            # Enable checks for MTCS components
            for cmp in self.script.mtcs.components_attr:
                setattr(self.script.mtcs.check, cmp, True)
            # Enable checks for LSSTCam components
            for cmp in self.script.lsstcam.components_attr:
                setattr(self.script.lsstcam.check, cmp, True)
            yield

    async def test_components(self):
        async with self.make_dry_script():
            mtcs_components = self.script.mtcs.components_attr
            lsstcam_components = self.script.lsstcam.components_attr

            assert set(mtcs_components) == set(EndOfNightConfig.MTCS)
            assert set(lsstcam_components) == set(EndOfNightConfig.LSSTCam)

    async def test_configure_override(self):
        async with self.make_dry_script():
            # Take settings for end-of-night state of MTCS and LSSTCam
            before_override_settings = dict(
                list(EndOfNightConfig.MTCS.items())
                + list(EndOfNightConfig.LSSTCam.items())
            )
            # Set overrides
            mtcs_csc, mtcs_override_state = "mtrotator", "DISABLED"
            lsstcam_csc, lsstcam_override_state = "mtheaderservice", "STANDBY"

            await self.configure_script(
                csc=[mtcs_csc, lsstcam_csc],
                state=[mtcs_override_state, lsstcam_override_state],
            )

            # Retrive new configurations
            after_override_settings = self.script.end_of_night_csc_states
            # Check that the CSCs are the same before and after
            assert set(before_override_settings) == set(after_override_settings)
            # Check overrides
            assert after_override_settings[mtcs_csc] == mtcs_override_state
            assert after_override_settings[lsstcam_csc] == lsstcam_override_state
            # Check that there are no changes in non-overridden CSCs
            assert all(
                before_override_settings[csc] == after_override_settings[csc]
                for csc in after_override_settings
                if csc != mtcs_csc and csc != lsstcam_csc
            )

    async def test_configure_override_bad(self):
        async with self.make_dry_script():
            with pytest.raises(salobj.ExpectedError):
                await self.configure_script(
                    csc=["mtrotator", "mtheaderservice"], state=["DISABLED"]
                )

                assert self.state.state == ScriptState.CONFIGURE_FAILED

    async def test_configure_ignore(self):
        async with self.make_dry_script():
            components = ["mtrotator", "mtheaderservice", "no_comp"]
            self.script.mtcs.disable_checks_for_components = unittest.mock.Mock()
            self.script.lsstcam.disable_checks_for_components = unittest.mock.Mock()
            await self.configure_script(ignore=components)

            self.script.mtcs.disable_checks_for_components.assert_called_once_with(
                components=components
            )

            self.script.lsstcam.disable_checks_for_components.assert_called_once_with(
                components=components
            )

    async def test_run(self):
        async with self.make_dry_script(), self.setup_mocks():

            await self.configure_script()

            await self.run_script()

            self.script.log.debug(
                f"csc_states: {self.mock_set_summary_state.csc_states}"
            )

            csc_states = self.mock_set_summary_state.csc_states
            end_of_night_csc_states = self.script.end_of_night_csc_states

            # Check CSCs
            assert set(csc_states) == set(end_of_night_csc_states)
            # Check end-of-night state for each CSC
            assert all(
                csc_states[csc] == end_of_night_state
                for (csc, end_of_night_state) in end_of_night_csc_states.items()
            )

    async def test_run_with_fail_transitions(self):
        async with self.make_dry_script(), self.setup_mocks():

            # Set up CSCs to fail transitions.
            csc_fails = ["mtrotator", "mtheaderservice", "mthexapod_2"]
            self.mock_set_summary_state.set_fails(csc_fails)

            await self.configure_script()

            with pytest.raises(AssertionError):
                await self.run_script()

            self.script.log.debug(
                f"csc_states: {self.mock_set_summary_state.csc_states}"
            )

            csc_states = self.mock_set_summary_state.csc_states
            end_of_night_csc_states = self.script.end_of_night_csc_states

            # Check non-failing CSCs.
            assert set(csc_states) == set(end_of_night_csc_states) - set(csc_fails)
            # Check end-of-night state for non-failing components
            assert all(
                csc_states[csc] == end_of_night_state
                for (csc, end_of_night_state) in end_of_night_csc_states.items()
                if csc not in csc_fails
            )

    async def test_run_with_ignore_transitions(self):
        async with self.make_dry_script(), self.setup_mocks():

            # Set up CSCs to fail transitions.
            csc_ignores = ["mtrotator", "mtheaderservice"]

            await self.configure_script(ignore=csc_ignores)

            await self.run_script()

            self.script.log.debug(
                f"csc_states: {self.mock_set_summary_state.csc_states}"
            )

            csc_states = self.mock_set_summary_state.csc_states
            end_of_night_csc_states = self.script.end_of_night_csc_states

            # Check non-failing CSCs.
            assert set(csc_states) == set(end_of_night_csc_states) - set(csc_ignores)
            # Check end-of-night state for non-failing components
            assert all(
                csc_states[csc] == end_of_night_state
                for (csc, end_of_night_state) in end_of_night_csc_states.items()
                if csc not in csc_ignores
            )


if __name__ == "__main__":
    unittest.main()
