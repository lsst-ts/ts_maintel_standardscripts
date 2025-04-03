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

__all__ = ["ChangeFilterLSSTCam"]

import yaml
from lsst.ts import salobj
from lsst.ts.observatory.control.maintel.lsstcam import LSSTCam, LSSTCamUsages
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages


class ChangeFilterLSSTCam(salobj.BaseScript):
    """Change filter of the LSSTCam.

    Parameters
    ----------
    index : `int`
        Index of Script SAL component.
    """

    def __init__(self, index):
        super().__init__(index=index, descr="Change filter of LSSTCam.")
        self.mtcs = None
        self.lsstcam = None

    @classmethod
    def get_schema(cls):
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_maintel_standardscripts/maintel/change_filter_lsstcam.yaml
            title: ChangeFilterLSSTCam v1
            description: Configuration for ChangeFilterLSSTCam.
            type: object
            properties:
              filter:
                description: Name of the filter to be set up.
                type: string
              config_tcs:
                description: Specifies whether an instance of MTCS should be created.
                             If True then it will be used to take the steps
                             required to set it up the telescope for changing
                             the filter.
                             If False, the filter change operation will be
                             attempted without any prior telescope setup,
                             which may result in failure.
                type: boolean
                default: True
              ignore:
                  description: >-
                    CSCs from the LSSTCam or MTCS group to ignore in status check.
                    Name must match those in self.lsstcam.components or
                    self.mtcs.components, e.g.; mtrotator, mtmount,
                    mtheaderservice, etc.
                  type: array
                  items:
                    type: string
            additionalProperties: false
            required: [filter]
        """
        return yaml.safe_load(schema_yaml)

    async def configure(self, config):
        """Configure script.

        Parameters
        ----------
        config : `types.SimpleNamespace`
            Script configuration, as defined by `schema`.
        """
        self.config = config
        self.filter = config.filter

        if config.config_tcs and self.mtcs is None:
            self.log.debug("Creating MTCS.")
            self.mtcs = MTCS(
                domain=self.domain,
                intended_usage=MTCSUsages.Slew | MTCSUsages.StateTransition,
                log=self.log,
            )
            await self.mtcs.start_task
        elif config.config_tcs:
            self.log.debug("MTCS already defined, skipping.")

        if self.lsstcam is None:
            self.log.debug("Creating Camera.")
            self.lsstcam = LSSTCam(
                domain=self.domain,
                intended_usage=LSSTCamUsages.All,
                log=self.log,
                mtcs=self.mtcs,
            )
            await self.lsstcam.start_task
        else:
            self.log.debug("Camera already defined, skipping.")

        if hasattr(config, "ignore"):
            self.lsstcam.disable_checks_for_components(components=config.ignore)
            if config.config_tcs:
                self.mtcs.disable_checks_for_components(components=config.ignore)

    def set_metadata(self, metadata):
        pass

    async def run(self):
        if self.config.config_tcs:
            await self.mtcs.assert_all_enabled()

        await self.lsstcam.assert_all_enabled()

        self.lsstcam.setup_instrument(filter=self.filter)
