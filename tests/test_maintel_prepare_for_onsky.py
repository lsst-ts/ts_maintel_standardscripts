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

import logging
import unittest

from lsst.ts import salobj, standardscripts
from lsst.ts.maintel.standardscripts.prepare_for import PrepareForOnSky
from lsst.ts.observatory.control.maintel.lsstcam import LSSTCam, LSSTCamUsages
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages

logging.basicConfig()


class TestPrepareForOnSky(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        self.script = PrepareForOnSky(index=index)
        self.script.mtcs = MTCS(
            domain=self.script.domain,
            log=self.script.log,
            intended_usage=MTCSUsages.DryTest,
        )
        self.script.lsstcam = LSSTCam(
            domain=self.script.domain,
            log=self.script.log,
            intended_usage=LSSTCamUsages.DryTest,
        )

        return (self.script,)

    async def test_configure(self):
        async with self.make_script():
            await self.configure_script()

            assert self.script.filter == "i_39"

    async def test_configure_filter_band(self):
        async with self.make_script():
            await self.configure_script(filter="i")

            assert self.script.filter == "i_39"

    async def test_configure_filter_full_name(self):
        async with self.make_script():
            await self.configure_script(filter="r_57")

            assert self.script.filter == "r_57"

    async def test_configure_invalid_filter(self):
        async with self.make_script():
            with self.assertRaises(salobj.ExpectedError):
                await self.configure_script(filter="not_a_filter")

    async def test_configure_ignore(self):
        async with self.make_script():
            await self.configure_script(
                ignore=["mtdometrajectory", "mthexapod_1", "mthexapod_2"]
            )

            assert not self.script.mtcs.check.mtdometrajectory
            assert not self.script.mtcs.check.mthexapod_1
            assert not self.script.mtcs.check.mthexapod_2

    async def test_configure_ignore_inexistent(self):
        async with self.make_script():
            await self.configure_script(ignore=["inexistent"])

            assert not hasattr(self.script.mtcs.check, "inexistent")
            assert not hasattr(self.script.lsstcam.check, "inexistent")

    async def test_configure_ignore_critical_components(self):
        async with self.make_script():

            # Get the actual critical components from MTCS
            critical_components = (
                self.script.mtcs.get_critical_components_for_prepare_for_onsky()
            )
            if critical_components:
                # One critical component ignored
                with self.assertRaises(salobj.ExpectedError):
                    await self.configure_script(ignore=["mtmount"])
                # Multiple critical components ignored
                with self.assertRaises(salobj.ExpectedError):
                    await self.configure_script(ignore=["mtm1m3", "mtm2", "mtptg"])

    async def test_run(self):
        async with self.make_script():
            await self.configure_script()

            self.script.mtcs.assert_all_enabled = unittest.mock.AsyncMock()
            self.script.lsstcam.assert_all_enabled = unittest.mock.AsyncMock()
            self.script.mtcs.prepare_for_onsky = unittest.mock.AsyncMock()
            self.script.lsstcam.setup_instrument = unittest.mock.AsyncMock()

            await self.run_script()

            # Verify the methods were called
            self.script.mtcs.assert_all_enabled.assert_called_once()
            self.script.lsstcam.assert_all_enabled.assert_called_once()
            self.script.mtcs.prepare_for_onsky.assert_called_once()
            self.script.lsstcam.setup_instrument.assert_called_once_with(filter="i_39")

    async def test_run_ignore_non_critical_components(self):
        async with self.make_script():
            await self.configure_script(ignore=["mtdometrajectory"])

            self.script.mtcs.assert_all_enabled = unittest.mock.AsyncMock()
            self.script.lsstcam.assert_all_enabled = unittest.mock.AsyncMock()
            self.script.mtcs.prepare_for_onsky = unittest.mock.AsyncMock()
            self.script.lsstcam.setup_instrument = unittest.mock.AsyncMock()

            await self.run_script()

            # Verify the methods were called
            self.script.mtcs.assert_all_enabled.assert_called_once()
            self.script.lsstcam.assert_all_enabled.assert_called_once()
            self.script.mtcs.prepare_for_onsky.assert_called_once()
            self.script.lsstcam.setup_instrument.assert_called_once_with(filter="i_39")
