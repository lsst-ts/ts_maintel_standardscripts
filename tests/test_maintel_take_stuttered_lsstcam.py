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

import random
import unittest

from lsst.ts import standardscripts
from lsst.ts.maintel.standardscripts import TakeStutteredLSSTCam

random.seed(47)  # for set_random_lsst_dds_partition_prefix


class TestTakeStutteredLSSTCam(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        self.script = TakeStutteredLSSTCam(index=index)

        return self.script

    def test_schema_inherits_base_required(self):
        """Test that the schema inherits 'required' fields from the
        base class."""
        from lsst.ts.standardscripts.base_take_stuttered import BaseTakeStuttered

        base_schema = BaseTakeStuttered.get_schema()
        derived_schema = TakeStutteredLSSTCam.get_schema()

        self.assertIn("required", base_schema)

        self.assertIn("required", derived_schema)

        base_required = set(base_schema["required"])
        derived_required = set(derived_schema["required"])
        self.assertTrue(
            base_required.issubset(derived_required),
            f"Derived schema is missing base required fields: "
            f"{base_required - derived_required}",
        )


if __name__ == "__main__":
    unittest.main()
