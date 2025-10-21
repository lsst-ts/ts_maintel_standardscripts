# This file is part of ts_maintel_standardscripts
#
# Developed for the Vera Rubin Observatory.
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

__all__ = ["PrepareForOnSky"]

import yaml
from lsst.ts import salobj
from lsst.ts.observatory.control.maintel.lsstcam import LSSTCam, LSSTCamUsages
from lsst.ts.observatory.control.maintel.mtcs import MTCS


class PrepareForOnSky(salobj.BaseScript):
    """Run MTCS prepare for on-sky operations.

    Parameters
    ----------
    index : `int`
        Index of Script SAL component.

    Notes
    -----
    **Checkpoints**

    None

    """

    def __init__(self, index):
        super().__init__(index=index, descr="Run MTCS prepare for on-sky operations.")

        self.config = None

        self.mtcs = None
        self.lsstcam = None

    @classmethod
    def get_schema(cls):
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_maintel_standardscripts/prepare_for/onsky.yaml
            title: PrepareForOnSky v1
            description: >-
                Configuration for PrepareForOnSky. This script prepares the
                telescope for on-sky operations by enabling the required
                components and setting them to the appropriate states.
            type: object
            properties:
                ignore:
                    description: >-
                        CSCs from the group to ignore, e.g.; mtdometrajectory.
                        Note: Critical components required for on-sky operations
                        cannot be ignored (e.g., mtmount, mtrotator, mtm1m3, mtm2
                        and mtptg).
                    type: array
                    items:
                        type: string
            additionalProperties: false
        """
        return yaml.safe_load(schema_yaml)

    async def configure(self, config):

        if self.mtcs is None:
            self.mtcs = MTCS(
                self.domain,
                log=self.log,
            )
            await self.mtcs.start_task

        if self.lsstcam is None:
            self.lsstcam = LSSTCam(
                self.domain, intended_usage=LSSTCamUsages.All, log=self.log
            )
            await self.lsstcam.start_task

        # CSCs that are critical for on-sky operations (cannot be ignored).
        critical_cscs = self.mtcs.get_critical_components_for_prepare_for_onsky()

        # Check that critical components are not ignored.
        if hasattr(config, "ignore") and any(
            component in critical_cscs for component in config.ignore
        ):
            raise ValueError(
                "Cannot ignore critical components: {}".format(config.ignore)
            )

        if hasattr(config, "ignore"):
            self.mtcs.disable_checks_for_components(components=config.ignore)
            self.lsstcam.disable_checks_for_components(components=config.ignore)

    def set_metadata(self, metadata):
        metadata.duration = 600.0

    async def run(self):

        await self.checkpoint("Preparing for on-sky operations.")

        await self.mtcs.assert_all_enabled(
            message="All MTCS components need to be enabled to prepare for on-sky observations."
        )

        await self.lsstcam.assert_all_enabled(
            message="All LSSTCam components need to be enabled to prepare for on-sky observations."
        )
        await self.mtcs.prepare_for_onsky()
