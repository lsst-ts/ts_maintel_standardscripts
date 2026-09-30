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

import contextlib
import unittest

from lsst.ts import standardscripts
from lsst.ts.maintel.standardscripts.mtdome import SetOperationalModeDome
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages
from lsst.ts.xml.enums.MTDome import OperationalMode, SubSystemId


class TestSetOperationalModeDome(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        self.script = SetOperationalModeDome(index=index)
        return (self.script,)

    @contextlib.asynccontextmanager
    async def make_dry_script(self):
        async with self.make_script(self):
            self.script.mtcs = MTCS(
                domain=self.script.domain,
                intended_usage=MTCSUsages.DryTest,
                log=self.script.log,
            )
            self.script.mtcs.rem.mtdome = unittest.mock.AsyncMock()
            yield

    async def test_configure_default(self):
        async with self.make_dry_script():
            await self.configure_script()

            assert self.script.target_mode == OperationalMode["NORMAL"]
            assert self.script.subsystems_mask == SubSystemId["APSCS"]

    async def test_configure_amcs_rad(self):
        async with self.make_dry_script():
            subsystems = ["AMCS", "RAD"]
            await self.configure_script(mode="DEGRADED", subsystems=subsystems)

            assert self.script.target_mode == OperationalMode["DEGRADED"]
            assert (
                self.script.subsystems_mask == SubSystemId["AMCS"] | SubSystemId["RAD"]
            )

    async def test_run(self):
        async with self.make_dry_script():
            mask = SubSystemId["APSCS"]
            target_mode = OperationalMode["NORMAL"]

            await self.configure_script()
            await self.run_script()

            self.script.mtcs.rem.mtdome.cmd_setOperationalMode.set_start.assert_awaited_with(
                operationalMode=target_mode,
                subSystemIds=mask,
                timeout=self.script.mtcs.fast_timeout,
            )
