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
import unittest.mock as mock

import pytest
from lsst.ts import salobj, standardscripts
from lsst.ts.maintel.standardscripts import TakeImageLSSTCam


class TestTakeImageLSSTCam(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        self.script = TakeImageLSSTCam(index=index)

        self.script.mtcs = mock.MagicMock()
        self.script.mtcs.long_timeout = 30.0
        self.script.mtcs.ready_to_take_data = mock.AsyncMock()

        self.script.mtcs.rem = mock.MagicMock()
        self.script.mtcs.rem.mtdometrajectory = mock.MagicMock()
        self.script.mtcs.rem.mtdome = mock.MagicMock()

        self.script._lsstcam = mock.MagicMock()
        self.script._lsstcam.filter_change_timeout = 0.0
        self.script._lsstcam.read_out_time = 0.0
        self.script._lsstcam.shutter_time = 0.0

        return (self.script,)

    async def _inject_mtcs_check_mocks(self):
        """Mock the .check attribute of mtcs for ignore functionality"""
        self.script.mtcs.check = mock.MagicMock()
        self.script.mtcs.check.mtdometrajectory = True
        self.script.mtcs.check.mtdome = True

    async def _set_summary_states(self, traj_state, dome_state):
        """Set up mock summary states for dome components"""
        self.script.mtcs.rem.mtdometrajectory.evt_summaryState.aget = mock.AsyncMock(
            return_value=type("Evt", (), {"summaryState": traj_state})()
        )
        self.script.mtcs.rem.mtdome.evt_summaryState.aget = mock.AsyncMock(
            return_value=type("Evt", (), {"summaryState": dome_state})()
        )

    async def test_assert_feasibility_flats_ok(self):
        """Test that feasibility check passes when dome components are in
        correct states"""
        async with self.make_script():
            await self.configure_script(exp_times=1, image_type="FLAT")
            await self._inject_mtcs_check_mocks()
            await self._set_summary_states(salobj.State.ENABLED, salobj.State.DISABLED)
            await self.script.assert_feasibility()  # Should not raise

    async def test_assert_feasibility_flats_bad_dome_trajectory(self):
        """Test that feasibility check fails when MTDomeTrajectory is not
        ENABLED"""
        async with self.make_script():
            await self.configure_script(exp_times=1, image_type="FLAT")
            await self._inject_mtcs_check_mocks()
            await self._set_summary_states(salobj.State.DISABLED, salobj.State.ENABLED)
            with pytest.raises(RuntimeError, match="MTDomeTrajectory must be ENABLED"):
                await self.script.assert_feasibility()

    async def test_assert_feasibility_flats_bad_dome(self):
        """Test that feasibility check fails when MTDome is in invalid
        state"""
        async with self.make_script():
            await self.configure_script(exp_times=1, image_type="FLAT")
            await self._inject_mtcs_check_mocks()
            await self._set_summary_states(salobj.State.ENABLED, salobj.State.OFFLINE)
            with pytest.raises(RuntimeError, match="MTDome must be in"):
                await self.script.assert_feasibility()

    async def test_assert_feasibility_non_flats_noop(self):
        """Test that feasibility check does nothing for non-FLAT image types"""
        async with self.make_script():
            await self.configure_script(exp_times=1, image_type="OBJECT")
            await self.script.assert_feasibility()

    async def test_assert_feasibility_trajectory_and_dome_ignored(self):
        """Test that feasibility check passes when both dome components
        are ignored"""
        async with self.make_script():
            await self.configure_script(
                exp_times=1, image_type="FLAT", ignore=["mtdometrajectory", "mtdome"]
            )
            await self._inject_mtcs_check_mocks()
            self.script.mtcs.check.mtdometrajectory = False
            self.script.mtcs.check.mtdome = False
            await self._set_summary_states(salobj.State.DISABLED, salobj.State.OFFLINE)
            await self.script.assert_feasibility()

    async def test_assert_feasibility_trajectory_not_ignored_bad_state(self):
        """Test that feasibility check fails when MTDomeTrajectory is
        not ignored but in bad state"""
        async with self.make_script():
            await self.configure_script(exp_times=1, image_type="FLAT")
            await self._inject_mtcs_check_mocks()
            self.script.mtcs.check.mtdometrajectory = True
            self.script.mtcs.check.mtdome = False
            await self._set_summary_states(salobj.State.DISABLED, salobj.State.OFFLINE)
            with pytest.raises(RuntimeError, match="MTDomeTrajectory must be ENABLED"):
                await self.script.assert_feasibility()

    async def test_assert_feasibility_dome_not_ignored_bad_state(self):
        """Test that feasibility check fails when MTDome is not ignored
        but in bad state"""
        async with self.make_script():
            await self.configure_script(exp_times=1, image_type="FLAT")
            await self._inject_mtcs_check_mocks()
            self.script.mtcs.check.mtdometrajectory = False
            self.script.mtcs.check.mtdome = True
            await self._set_summary_states(salobj.State.ENABLED, salobj.State.OFFLINE)
            with pytest.raises(RuntimeError, match="MTDome must be in"):
                await self.script.assert_feasibility()

    async def test_configure_ignore(self):
        """Test that ignore functionality works correctly in configure"""
        async with self.make_script():
            self.script.mtcs.disable_checks_for_components = mock.MagicMock()

            config = type(
                "Config",
                (),
                {
                    "ignore": ["mtmount", "mtptg"],
                    "nimages": 1,
                    "exp_times": [1.0],
                    "image_type": "OBJECT",
                    "filter": None,
                    "roi_spec": None,
                },
            )()
            await self.script.configure(config)

            self.script.mtcs.disable_checks_for_components.assert_any_call(
                components=["mtmount", "mtptg"]
            )


if __name__ == "__main__":
    unittest.main()
