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
import logging
import types
import unittest

from lsst.ts import salobj, standardscripts
from lsst.ts.maintel.standardscripts import EnableLSSTCam

logging.basicConfig()


class SimpleEvtSummaryState:
    def __init__(self, state):
        self.data = types.SimpleNamespace(summaryState=state)


class SimpleController:
    def __init__(self, state):
        self.evt_summaryState = SimpleEvtSummaryState(state)
        self.cmd_enable = types.SimpleNamespace(callback=None)


class LSSTCamMock:
    """Pure mock for LSSTCam group (no Kafka, no BaseGroupMock)."""

    def __init__(self):
        self.components = ("mtcamera", "mtheaderservice", "mtoods")
        # Provide controllers with the minimal interface needed
        self.controllers = types.SimpleNamespace(
            mtcamera=SimpleController(salobj.State.STANDBY),
            mtheaderservice=SimpleController(salobj.State.STANDBY),
            mtoods=SimpleController(salobj.State.STANDBY),
        )
        # Set up a mock check attribute
        self.check = types.SimpleNamespace(**{comp: True for comp in self.components})
        # Simulate a start_task attribute for compatibility
        self.start_task = asyncio.sleep(0)

    @property
    def mtcamera(self):
        return self.controllers.mtcamera

    @property
    def mtheaderservice(self):
        return self.controllers.mtheaderservice

    @property
    def mtoods(self):
        return self.controllers.mtoods

    async def enable(self, overrides=None):
        """Simulate enabling all components."""
        for comp in self.components:
            controller = getattr(self.controllers, comp)
            controller.evt_summaryState.data.summaryState = salobj.State.ENABLED
        await asyncio.sleep(0.01)


class TestEnableLSSTCam(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        self.script = EnableLSSTCam(index=index)

        # Use LSSTCamMock instead of the real LSSTCam
        self.script._lsstcam = LSSTCamMock()

        return (self.script,)

    async def test_components(self):
        async with self.make_script():
            await self.configure_script()
            for component in self.script._lsstcam.components:
                with self.subTest(f"Check {component}", component=component):
                    # Use lowercase attribute names for the check
                    if getattr(self.script._lsstcam.check, component):
                        assert component in self.script.components()

    async def test_run(self):
        async with self.make_script():
            await self.configure_script()

            await self.run_script()

            for comp in self.script._lsstcam.components:
                if getattr(self.script._lsstcam.check, comp):
                    with self.subTest(f"{comp} summary state", comp=comp):
                        assert (
                            getattr(
                                getattr(self.script._lsstcam.controllers, comp),
                                "evt_summaryState",
                            ).data.summaryState
                            == salobj.State.ENABLED
                        )
