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

import contextlib
import types
import unittest

from lsst.ts import standardscripts
from lsst.ts.maintel.standardscripts import (
    BaseLsstCamCheckout,
    LsstCamNightIngestionCheckout,
)
from lsst.ts.observatory.control.maintel.lsstcam import LSSTCam, LSSTCamUsages


class TestLsstCamNightIngestionCheckout(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        self.script = LsstCamNightIngestionCheckout(index=index)
        self.script.lsstcam = LSSTCam(
            domain=self.script.domain,
            intended_usage=LSSTCamUsages.DryTest,
            log=self.script.log,
        )
        self.script.lsstcam.disable_checks_for_components = unittest.mock.Mock()
        self.script.wfoods = types.SimpleNamespace()
        return (self.script,)

    async def test_configure(self):
        async with self.make_script():
            await self.configure_script()

            schema = self.script.get_schema()
            assert isinstance(self.script, BaseLsstCamCheckout)
            assert schema["$id"].endswith("/lsstcam_night_ingestion_checkout.yaml")
            assert schema["title"] == "LsstCamNightIngestionCheckout v1"
            assert "nighttime" in schema["description"]
            assert "default" not in schema["properties"]["note"]
            assert self.script.dark_exptime == 5.0
            assert self.script.ndarks == 1

    async def test_run(self):
        async with self.make_script():
            await self.configure_script()

            self.script.lsstcam.assert_all_enabled = unittest.mock.AsyncMock()
            self.script.lsstcam.get_current_filter = unittest.mock.AsyncMock(
                return_value="i_39"
            )
            self.script.lsstcam.get_available_filters = unittest.mock.AsyncMock(
                return_value=["i_39"]
            )
            self.script.lsstcam.take_darks = unittest.mock.AsyncMock(
                return_value=[2026091500001]
            )
            ingestion_arguments = []

            @contextlib.asynccontextmanager
            async def ingested_image(**kwargs):
                ingestion_arguments.append(kwargs)
                yield

            self.script.ingested_image = ingested_image

            await self.run_script()

            self.script.lsstcam.take_darks.assert_awaited_once_with(
                exptime=5.0,
                ndarks=1,
                program=self.script.program,
                reason=self.script.reason,
                note=None,
            )
            assert ingestion_arguments == [
                {
                    "expected_science": 189,
                    "expected_wfs": 8,
                    "image_label": "dark",
                }
            ]


if __name__ == "__main__":
    unittest.main()
