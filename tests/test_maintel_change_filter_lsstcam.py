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
from unittest.mock import patch

from lsst.ts import standardscripts, utils
from lsst.ts.maintel.standardscripts import ChangeFilterLSSTCam
from lsst.ts.observatory.control.maintel.lsstcam import LSSTCam, LSSTCamUsages


class TestChangeFilterLSSTCam(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        self.script = ChangeFilterLSSTCam(index=index)

        self.script.lsstcam = LSSTCam(
            domain=self.script.domain,
            intended_usage=LSSTCamUsages.DryTest,
            log=self.script.log,
        )

        self.script.lsstcam.setup_instrument = unittest.mock.AsyncMock()
        self.script.lsstcam.assert_all_enabled = unittest.mock.AsyncMock()
        self.script.lsstcam.disable_checks_for_components = unittest.mock.Mock()

        return (self.script,)

    async def test_configure_with_mtcs(self):
        async with self.make_script():
            filter = "r"
            mock_mtcs = unittest.mock.AsyncMock()
            mock_mtcs.start_task = utils.make_done_future()
            with patch(
                "lsst.ts.maintel.standardscripts.change_filter_lsstcam.MTCS",
                return_value=mock_mtcs,
            ):
                await self.configure_script(
                    filter=filter,
                    config_tcs=True,
                )

                assert self.script.filter == filter
                assert self.script.config.config_tcs
                assert self.script.mtcs is not None

    async def test_configure_without_mtcs(self):
        async with self.make_script():
            filter = "r"

            await self.configure_script(
                filter=filter,
                config_tcs=False,
            )

            assert self.script.filter == filter
            assert not self.script.config.config_tcs
            assert self.script.mtcs is None

    async def test_configure_ignore(self):
        async with self.make_script():
            ignore = ["mtheaderservice", "mtrotator", "no_comp"]

            # Mock MTCS
            self.script.mtcs = unittest.mock.Mock()
            self.script.mtcs.disable_checks_for_components = unittest.mock.AsyncMock()

            await self.configure_script(filter="r", config_tcs=True, ignore=ignore)

            self.script.lsstcam.disable_checks_for_components.assert_called_once_with(
                components=ignore
            )

            self.script.mtcs.disable_checks_for_components.assert_called_once_with(
                components=ignore
            )

    async def test_run_with_mtcs(self):
        async with self.make_script():
            filter = "r"

            # Mock MTCS
            self.script.mtcs = unittest.mock.AsyncMock()
            self.script.mtcs.assert_all_enabled = unittest.mock.AsyncMock()

            await self.configure_script(
                filter=filter,
                config_tcs=True,
            )

            # Run the script
            await self.run_script()

            self.script.mtcs.assert_all_enabled.assert_called_once()
            self.script.lsstcam.assert_all_enabled.assert_called_once()
            self.script.lsstcam.setup_instrument.assert_called_once_with(filter=filter)

    async def test_run_without_mtcs(self):
        async with self.make_script():
            filter = "r"

            await self.configure_script(
                filter=filter,
                config_tcs=False,
            )

            # Run the script
            await self.run_script()

            self.script.mtcs is None
            self.script.lsstcam.assert_all_enabled.assert_called_once()
            self.script.lsstcam.setup_instrument.assert_called_once_with(filter=filter)


if __name__ == "__main__":
    unittest.main()
