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
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages

BAND_TO_FILTER = {
    "u": "u_24",
    "g": "g_6",
    "r": "r_57",
    "i": "i_39",
    "z": "z_20",
    "y": "y_10",
}


class PrepareForOnSky(salobj.BaseScript):
    """Run MTCS prepare for on-sky operations.

    Parameters
    ----------
    index : `int`
        Index of Script SAL component.

    Notes
    -----
    **Checkpoints**

    Preparing MTCS components for on-sky operations: before running prepare for
    on-sky operations on MTCS and LSSTCam.
    Setting up LSSTCam with filter 'FILTER': before configuring LSSTCam with
    the specified filter.
    """

    def __init__(self, index):
        super().__init__(index=index, descr="Run prepare for on-sky operations.")

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
                filter:
                    description: >-
                        Filter to be set up. May be specified either as a full
                        filter name (e.g. i_39) or as a band (e.g. i). Default
                        is "i_39".
                    type: string
                    default: "i_39"
                    enum:
                        - "u"
                        - "g"
                        - "r"
                        - "i"
                        - "z"
                        - "y"
                        - "u_24"
                        - "g_6"
                        - "r_57"
                        - "i_39"
                        - "z_20"
                        - "y_10"
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

    @staticmethod
    def map_filter_value(filter_value: str) -> str:
        """Map a filter configuration value to a full filter name."""

        filter_text = str(filter_value).strip()
        filter_band_lower = filter_text.lower()

        if filter_band_lower in BAND_TO_FILTER:
            return BAND_TO_FILTER[filter_band_lower]

        return filter_text

    async def configure_tcs(self) -> None:
        """Initialize MTCS if not already initialized."""
        if self.mtcs is None:
            self.log.debug("Creating MTCS instance.")
            self.mtcs = MTCS(
                domain=self.domain, log=self.log, intended_usage=MTCSUsages.All
            )
            await self.mtcs.start_task
        else:
            self.log.debug("MTCS already initialized.")

    async def configure_camera(self) -> None:
        """Initialize LSST Camera if not already initialized."""
        if self.lsstcam is None:
            self.log.debug("Creating LSST Camera instance.")
            self.lsstcam = LSSTCam(
                domain=self.domain,
                intended_usage=LSSTCamUsages.All,
                log=self.log,
                mtcs=self.mtcs,
            )
            await self.lsstcam.start_task
        else:
            self.log.debug("LSST Camera already initialized.")

    async def configure(self, config):

        await self.configure_tcs()
        await self.configure_camera()

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

        filter_value = getattr(config, "filter", "i_39")
        self.filter = self.map_filter_value(filter_value)

    def set_metadata(self, metadata):
        metadata.duration = 600.0 + self.lsstcam.filter_change_timeout

    async def run(self):

        await self.checkpoint("Preparing MTCS components for on-sky operations.")

        await self.mtcs.assert_all_enabled(
            message="All MTCS components need to be enabled to prepare for on-sky observations."
        )

        await self.mtcs.prepare_for_onsky()

        await self.checkpoint(f"Setting up LSSTCam with filter '{self.filter}'.")

        await self.lsstcam.assert_all_enabled(
            message="All LSSTCam components need to be enabled to prepare for on-sky observations."
        )

        await self.lsstcam.setup_instrument(filter=self.filter)

        self.log.info("Prepare for on-sky operations completed successfully.")
