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

import numpy as np
import yaml
from lsst.ts import standardscripts
from lsst.ts.maintel.standardscripts import EnableAOSClosedLoop
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages


class TestEnableAOSClosedLoop(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        self.script = EnableAOSClosedLoop(index=index)

        # Mock the MTCS
        self.script.mtcs = MTCS(
            domain=self.script.domain,
            intended_usage=MTCSUsages.DryTest,
            log=self.script.log,
        )
        self.script.mtcs.enable_aos_closed_loop = unittest.mock.AsyncMock()

        return (self.script,)

    async def test_configure(self) -> None:
        # Try configure with minimum set of parameters declared
        async with self.make_script():
            config = {
                "used_dofs": [0, 1, 2, 3, 4],
                "truncation_index": 5,
            }

            await self.configure_script(**config)

            configured_dofs = np.zeros(50)
            configured_dofs[:5] += 1
            np.testing.assert_array_equal(self.script.used_dofs, configured_dofs)
            assert self.script.truncation_index == 5

    async def test_run(self) -> None:
        # Start the test itself
        async with self.make_script():
            config = {
                "used_dofs": [0, 1, 2, 3, 4],
                "truncation_index": 5,
                "zn_selected": [
                    4,
                    5,
                    6,
                    7,
                    8,
                    9,
                    10,
                    11,
                    12,
                    13,
                    14,
                    15,
                    20,
                    21,
                    22,
                    27,
                    28,
                ],
            }
            await self.configure_script(**config)

            # Run the script
            await self.run_script()

            configured_dofs = np.zeros(50)
            configured_dofs[:5] += 1
            task_config = {
                "truncation_index": config["truncation_index"],
                "comp_dof_idx": {
                    "m2HexPos": [float(val) for val in configured_dofs[:5]],
                    "camHexPos": [float(val) for val in configured_dofs[5:10]],
                    "M1M3Bend": [float(val) for val in configured_dofs[10:30]],
                    "M2Bend": [float(val) for val in configured_dofs[30:]],
                },
                "zn_selected": config["zn_selected"],
            }
            self.script.mtcs.enable_aos_closed_loop.assert_awaited_once_with(
                config=yaml.safe_dump(task_config),
            )


if __name__ == "__main__":
    unittest.main()
