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

__all__ = ["EnableLSSTCam"]

import yaml
from lsst.ts.observatory.control.maintel.lsstcam import LSSTCam, LSSTCamUsages
from lsst.ts.standardscripts.enable_group import EnableGroup


class EnableLSSTCam(EnableGroup):
    """Enable all LSSTCam components.

    The Script configuration only accepts settings values for the CSCs that
    are configurable.

    The following CSCs will be enabled:

        - MTCamera
        - MTHeaderService: not configurable
        - MTOODS

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
        super().__init__(index=index, descr="Enable LSSTCam.")
        self.config = None
        self._lsstcam = None  # Postpone LSSTCam creation to the configure phase

    async def configure(self, config):
        if self._lsstcam is None:
            self._lsstcam = LSSTCam(
                self.domain,
                intended_usage=LSSTCamUsages.StateTransition,
                log=self.log,
            )
            await self._lsstcam.start_task
        await super().configure(config=config)

    @property
    def group(self):
        return self._lsstcam

    @staticmethod
    def components():
        """Return list of components name as appeared in
        `self.group.components`.

        Returns
        -------
        components : `list` of `str`.

        """
        return set(["mtcamera", "mtheaderservice", "mtoods"])

    @classmethod
    def get_schema(cls):
        schema_yaml = f"""
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_standardscripts/maintel/enable_lsstcam.yaml
            title: EnableLSSTCam v1
            description: Configuration for EnableLSSTCam
            type: object
            properties:
                mtcamera:
                    description: Configuration for the MTCamera component.
                    anyOf:
                      - type: string
                      - type: "null"
                    default: null
                mtoods:
                    description: Configuration for the MTOODS component.
                    anyOf:
                      - type: string
                      - type: "null"
                    default: null
                ignore:
                    description: >-
                        CSCs from the group to ignore. Name must match those in
                        self.group.components, e.g.; mtoods.
                        Valid options are: {cls.components()}.
                    type: array
                    items:
                        type: string
            additionalProperties: false
        """
        return yaml.safe_load(schema_yaml)
