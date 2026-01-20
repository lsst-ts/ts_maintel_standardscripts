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

__all__ = ["TakeImageLSSTCam"]

import asyncio

import astropy.units as u
import yaml
from astropy.coordinates import Angle
from lsst.ts import salobj
from lsst.ts.observatory.control.maintel.lsstcam import LSSTCam, LSSTCamUsages
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages
from lsst.ts.observatory.control.utils.extras.guider_roi import GuiderROIs
from lsst.ts.observatory.control.utils.roi_spec import ROISpec
from lsst.ts.standardscripts.base_take_image import BaseTakeImage


class TakeImageLSSTCam(BaseTakeImage):
    """Take images with LSSTCam.

    Parameters
    ----------
    index : `int`
        Index of Script SAL component.

    Notes
    -----
    **Checkpoints**

    * exposure {n} of {m}: before sending the CCCamera ``takeImages`` command

    """

    def __init__(self, index):
        super().__init__(index=index, descr="Take images with LSSTCam.")

        self.config = None
        self.mtcs = None
        self._lsstcam = None

        self.instrument_setup_time = 0.0

        self.instrument_name = "LSSTCam"
        self.roi_spec = None

    @property
    def tcs(self):
        return self.mtcs

    @property
    def camera(self):
        return self._lsstcam

    @staticmethod
    def get_available_imgtypes():
        return LSSTCam.get_image_types()

    @classmethod
    def get_schema(cls):
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_standardscripts/maintel/LSSTCamTakeImage.yaml
            title: LSSTCamTakeImage v1
            description: Configuration for LSSTCamTakeImage.
            type: object
            properties:
              filter:
                description: Filter name or ID; if omitted the filter is not changed.
                anyOf:
                  - type: string
                  - type: integer
                    minimum: 1
                  - type: "null"
                default: null
              set_roi:
                description: Whether to set the ROI specification. If false, roi_spec is ignored.
                type: boolean
                default: true
              roi_spec:
                description: Definition of the ROI Specification.
                type: object
                additionalProperties: false
                required:
                  - common
                  - roi
                properties:
                  common:
                    description: Common properties to all ROIs.
                    type: object
                    additionalProperties: false
                    required:
                      - rows
                      - cols
                      - integration_time_millis
                    properties:
                      rows:
                        description: Number of rows for each ROI.
                        type: number
                        minimum: 10
                        maximum: 400
                      cols:
                        description: Number of columns for each ROI.
                        type: number
                        minimum: 10
                        maximum: 400
                      integration_time_millis:
                        description: Guider exposure integration time in milliseconds.
                        type: number
                        minimum: 5
                        maximum: 200
                  roi:
                    description: Definition of the ROIs regions.
                    minProperties: 1
                    additionalProperties: false
                    patternProperties:
                      "^[a-zA-Z0-9]+$":
                        type: object
                        additionalProperties: false
                        required:
                          - segment
                          - start_row
                          - start_col
                        properties:
                          segment:
                            type: number
                            description: Segment of the CCD where the center of the ROI is located.
                          start_row:
                            type: number
                            description: The bottom-left row origin of the ROI.
                          start_col:
                            type: number
                            description: The bottom-left column origin of the ROI.
              ignore:
                description: >-
                  CSCs from the MTCS group to ignore in status check. Name must
                  match those in self.mtcs.components_attr, e.g.; mtmount, mtptg.
                type: array
                items:
                  type: string
            additionalProperties: false
        """
        schema_dict = yaml.safe_load(schema_yaml)

        base_schema_dict = super(TakeImageLSSTCam, cls).get_schema()

        for prop in base_schema_dict["properties"]:
            schema_dict["properties"][prop] = base_schema_dict["properties"][prop]

        return schema_dict

    async def configure(self, config):

        if self.mtcs is None:
            self.mtcs = MTCS(self.domain, log=self.log, intended_usage=MTCSUsages.Slew)
            await self.mtcs.start_task

        if self._lsstcam is None:
            self._lsstcam = LSSTCam(
                self.domain,
                intended_usage=LSSTCamUsages.TakeImage,
                log=self.log,
                tcs_ready_to_take_data=self.mtcs.ready_to_take_data,
            )
            await self._lsstcam.start_task

            self.instrument_setup_time = self._lsstcam.filter_change_timeout

        if hasattr(config, "ignore") and config.ignore:
            self.mtcs.disable_checks_for_components(components=config.ignore)

        await super().configure(config=config)

    async def get_guider_roi(self):
        """Retrieve the guider roi from the current telescope position."""
        try:
            current_target = await self.mtcs.rem.mtptg.evt_currentTarget.aget(
                timeout=self.mtcs.fast_timeout
            )
            target_ra_angle = Angle(current_target.ra, unit=u.rad).to(u.deg)
            target_dec_angle = Angle(current_target.declination, unit=u.rad).to(u.deg)
            sky_angle = Angle(current_target.rotAngle, unit=u.deg)
            self.log.info(
                f"Current target: ra={target_ra_angle}, dec={target_dec_angle}, sky_angle={sky_angle}."
            )
        except asyncio.TimeoutError:
            self.log.info(
                "Failed to retrieve current target coordinates.Continuing without guider roi."
            )
            return None

        current_filter = await self._lsstcam.get_current_filter()

        band = current_filter[0]

        roi_size = self._lsstcam.DEFAULT_GUIDER_ROI_ROWS
        roi_time_ms = self._lsstcam.DEFAULT_GUIDER_ROI_TIME_MS

        guider_rois = GuiderROIs(log=self.log)
        roi_spec, _ = guider_rois.get_guider_rois(
            ra=target_ra_angle.to(u.deg).value,
            dec=target_dec_angle.to(u.deg).value,
            sky_angle=sky_angle.to(u.deg).value,
            roi_size=roi_size,
            roi_time=roi_time_ms,
            band=band,
            npix_edge=50,
            use_guider=True,
            use_wavefront=False,
            use_science=False,
        )

        return roi_spec

    def get_instrument_name(self):
        return self.instrument_name

    def get_instrument_configuration(self):
        return dict(filter=self.config.filter)

    async def assert_feasibility(self):
        if getattr(self.config, "image_type", None) != "FLAT":
            return None

        mtdometrajectory_ignored = not self.mtcs.check.mtdometrajectory
        mtdome_ignored = not self.mtcs.check.mtdome

        if not mtdometrajectory_ignored:
            dome_trajectory_evt = (
                await self.mtcs.rem.mtdometrajectory.evt_summaryState.aget(
                    timeout=self.mtcs.long_timeout
                )
            )
            dome_trajectory_summary_state = salobj.State(
                dome_trajectory_evt.summaryState
            )

            if dome_trajectory_summary_state != salobj.State.ENABLED:
                raise RuntimeError(
                    "MTDomeTrajectory must be ENABLED before taking flats to ensure "
                    "vignetting state is published. "
                    f"Current state {dome_trajectory_summary_state.name}."
                )

        if not mtdome_ignored:
            dome_evt = await self.mtcs.rem.mtdome.evt_summaryState.aget(
                timeout=self.mtcs.long_timeout
            )
            dome_summary_state = salobj.State(dome_evt.summaryState)

            acceptable_mtdome_state = {salobj.State.DISABLED, salobj.State.ENABLED}

            if dome_summary_state not in acceptable_mtdome_state:
                raise RuntimeError(
                    f"MTDome must be in {acceptable_mtdome_state} before taking flats, "
                    f"current state {dome_summary_state.name}."
                )

    async def run(self):

        set_roi = self.config.set_roi
        self.log.info(f"{set_roi=}.")

        if set_roi:
            if (roi_spec := getattr(self.config, "roi_spec", None)) is not None:
                self.roi_spec = ROISpec.parse_obj(roi_spec)
            else:
                try:
                    self.roi_spec = await self.get_guider_roi()
                except Exception as e:
                    self.log.info(
                        f"Failed to get guider ROI, ignoring. Feature still under development. {e}",
                        exc_info=True,
                    )
        else:
            self.roi_spec = None

        if self.roi_spec is not None:
            await self.camera.init_guider(roi_spec=self.roi_spec)

        await super(TakeImageLSSTCam, self).run()
