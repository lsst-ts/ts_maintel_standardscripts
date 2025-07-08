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
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

__all__ = ["PointAzEl"]

import yaml
from lsst.ts.observatory.control.maintel.mtcs import MTCS
from lsst.ts.standardscripts.base_point_azel import BasePointAzEl


class PointAzEl(BasePointAzEl):
    """Main Telescope point_azel script.

    Parameters
    ----------
    index : `int`
        Index of Script SAL component.

    """

    def __init__(self, index):
        super().__init__(
            index=index,
            descr="Slew the main telescope to a pair of (az, el) coordinates.",
        )

        self.mtcs = None
        self.slew_time_guess = 15

    @property
    def tcs(self):
        return self.mtcs

    @classmethod
    def get_schema(cls):
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_standardscripts/maintel/point_azel.py
            title: PointAzEl v1
            description: Configuration for PointAzEl.
            properties:
                az:
                    description: >-
                        Target Azimuth in degrees. If no value is specified,
                        the current azimuth will be used with the provided
                        target elevation.
                    type: number
                el:
                    description: >-
                        Target Elevation in degrees. If no value is specified,
                        the current elevation will be used with the provided
                        target azimuth.
                    type: number
                    minimum: 0.0
                    maximum: 90.0
            anyOf:
                - required: [az]
                - required: [el]
            additionalProperties: false
        """
        schema_dict = yaml.safe_load(schema_yaml)

        base_schema_dict = super().get_schema()

        for prop in base_schema_dict["properties"]:
            if prop not in schema_dict["properties"]:
                schema_dict["properties"][prop] = base_schema_dict["properties"][prop]

        return schema_dict

    async def configure(self, config):
        """Configure script.

        Parameters
        ----------
        config : `types.SimpleNamespace`
            Script configuration, as defined by `schema`.
        """
        self.config = config

        await super().configure(config=config)

        if not hasattr(config, "az"):
            config.az = await self.get_current_azimuth()
            self.log.info(f"No azimuth specified. Using current azimuth: {config.az}")

        if not hasattr(config, "el"):
            config.el = await self.get_current_elevation()
            self.log.info(
                f"No elevation specified. Using current elevation: {config.el}"
            )

    async def get_current_azimuth(self):
        mount_az = await self.mtcs.rem.mtmount.tel_azimuth.next(
            flush=True,
            timeout=self.mtcs.fast_timeout,
        )
        return mount_az.actualPosition

    async def get_current_elevation(self):
        mount_el = await self.mtcs.rem.mtmount.tel_elevation.next(
            flush=True,
            timeout=self.mtcs.fast_timeout,
        )
        return mount_el.actualPosition

    async def configure_tcs(self):
        """Handle creating MTCS object and waiting for remote to start."""

        if self.mtcs is None:
            self.log.debug("Creating MTCS")
            self.mtcs = MTCS(self.domain, log=self.log)
            await self.mtcs.start_task

    def set_metadata(self, metadata):
        metadata.duration = self.slew_time_guess
