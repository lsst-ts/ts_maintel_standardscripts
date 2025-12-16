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

__all__ = ["TrackTargetAndTakeImageLSSTCam"]

import asyncio

import astropy.units as u
from astropy.coordinates import Angle
from lsst.ts.observatory.control.maintel.lsstcam import LSSTCam, LSSTCamUsages
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages
from lsst.ts.observatory.control.utils import RotType
from lsst.ts.observatory.control.utils.extras.guider_roi import GuiderROIs
from lsst.ts.standardscripts.base_track_target_and_take_image import (
    BaseTrackTargetAndTakeImage,
)
from lsst.ts.xml.enums.MTAOS import ClosedLoopState


class TrackTargetAndTakeImageLSSTCam(BaseTrackTargetAndTakeImage):
    """Track target and take image script.

    This script implements a simple visit consisting of slew to a target,
    start tracking and take image.

    Parameters
    ----------
    index : `int`
        Index of Script SAL component.
    add_remotes : `bool` (optional)
        Create remotes to control components (default: `True`)? If False, the
        script will not work for normal operations. Useful for unit testing.
    """

    def __init__(self, index, add_remotes: bool = True):
        super().__init__(
            index=index, descr="Track target and take image with MainTel and LSSTCam."
        )

        mtcs_usage, lsstcam_usage = (
            (
                MTCSUsages.Slew | MTCSUsages.StateTransition,
                LSSTCamUsages.TakeImageFull | LSSTCamUsages.StateTransition,
            )
            if add_remotes
            else (MTCSUsages.DryTest, LSSTCamUsages.DryTest)
        )

        self.angle_filter_change = 0.0
        self.tolerance_angle_filter_change = 1e-2

        self.mtcs = MTCS(self.domain, intended_usage=mtcs_usage, log=self.log)

        self.lsstcam = LSSTCam(
            self.domain,
            intended_usage=lsstcam_usage,
            log=self.log,
            mtcs=self.mtcs,
        )

        self.instrument_name = "LSSTCam"

    @property
    def tcs(self):
        return self.mtcs

    @classmethod
    def get_schema(cls):
        url = "https://github.com/"
        path = "lsst-ts/ts_maintel_standardscripts/maintel/track_target_and_take_image_lsstcam.yaml"
        schema_dict = cls.get_base_schema()
        schema_dict["$id"] = f"{url}{path}"
        schema_dict["title"] = "TrackTargetAndTakeImageLSSTCam v1"
        schema_dict["description"] = "Configuration for TrackTargetAndTakeImageLSSTCam."

        schema_dict["properties"]["roi_size"] = {
            "type": "integer",
            "description": "Size of the guider ROI in pixels (rows and cols).",
            "default": 400,
            "minimum": 1,
        }
        schema_dict["properties"]["roi_time_ms"] = {
            "type": "integer",
            "description": "Integration time for the guider ROI in milliseconds.",
            "default": 200,
            "minimum": 1,
        }

        return schema_dict

    def get_instrument_name(self):
        return self.instrument_name

    async def configure(self, config):
        await super().configure(config)
        try:
            await self.set_guider_roi()
        except Exception:
            self.log.exception("Failed to set guider ROI: continuing...")

    async def set_guider_roi(self):
        """Run guider ROI selection and initialize guiders.

        Uses DM-based selection via GuiderROIs and initializes the guider
        configuration in the camera before running.
        """

        ra_deg = Angle(self.config.ra, unit=u.hourangle).deg
        dec_deg = Angle(self.config.dec, unit=u.deg).deg
        sky_angle = float(self.config.rot_sky)

        # Determine band first letter (e.g., r, i, etc.)
        band_value = (
            self.config.band_filter[0]
            if isinstance(self.config.band_filter, list)
            else self.config.band_filter
        )
        band = str(band_value)[0].lower()

        roi_size = getattr(
            self.config, "roi_size", self.lsstcam.DEFAULT_GUIDER_ROI_ROWS
        )
        roi_time_ms = getattr(
            self.config, "roi_time_ms", self.lsstcam.DEFAULT_GUIDER_ROI_TIME_MS
        )

        guider_rois = GuiderROIs(log=self.log)
        roi_spec, _ = guider_rois.get_guider_rois(
            ra=ra_deg,
            dec=dec_deg,
            sky_angle=sky_angle,
            roi_size=roi_size,
            roi_time=roi_time_ms,
            band=band,
            npix_edge=50,
            use_guider=True,
            use_wavefront=False,
            use_science=False,
        )

        await self.lsstcam.init_guider(roi_spec=roi_spec)

    async def load_playlist(self):
        """Load playlist."""
        await self.lsstcam.rem.mtcamera.cmd_play.set_start(
            playlist=self.config.camera_playlist,
            repeat=True,
            timeout=self.lsstcam.fast_timeout,
        )

    async def assert_feasibility(self):
        """Verify that the system is in a feasible state to execute the
        script.
        """
        await asyncio.gather(
            self.mtcs.assert_all_enabled(),
            self.lsstcam.assert_all_enabled(),
        )

    async def track_target_and_setup_instrument(self):
        """Track target and setup instrument in parallel."""

        current_filter = await self.lsstcam.get_current_filter()

        self.tracking_started = True

        if current_filter != self.config.band_filter:
            self.log.debug(
                f"Filter change required: {current_filter} -> {self.config.band_filter}"
            )
            await self._handle_slew_and_change_filter()
        else:
            self.log.debug(
                f"Already in the desired filter ({current_filter}), slewing and tracking."
            )

        await self.mtcs.slew_icrs(
            ra=self.config.ra,
            dec=self.config.dec,
            rot=self.config.rot_sky,
            rot_type=RotType.Sky,
            target_name=self.config.name,
            az_wrap_strategy=self.config.az_wrap_strategy,
            time_on_target=self.get_estimated_time_on_target(),
        )

    async def _handle_slew_and_change_filter(self):
        """Handle slewing and changing filter at the same time.

        For LSSTCam we need to send the rotator to zero and keep it there while
        the filter is changing.
        """

        await self.mtcs.slew_icrs(
            ra=self.config.ra,
            dec=self.config.dec,
            rot=self.angle_filter_change,
            rot_type=RotType.Physical,
            target_name=f"{self.config.name} - filter change",
            az_wrap_strategy=self.config.az_wrap_strategy,
            time_on_target=self.get_estimated_time_on_target(),
        )

        await self.lsstcam.setup_filter(filter=self.config.band_filter)

    async def _wait_rotator_reach_filter_change_angle(self):
        """Wait until the rotator reach the filter change angle."""

        while True:
            rotator_position = await self.mtcs.rem.mtrotator.tel_rotation.next(
                flush=True, timeout=self.mtcs.fast_timeout
            )

            if (
                abs(rotator_position.actualPosition - self.angle_filter_change)
                < self.tolerance_angle_filter_change
            ):
                self.log.debug("Rotator inside tolerance range.")
                break
            else:
                self.log.debug(
                    "Rotator not in position: "
                    f"{rotator_position.actualPosition} -> {self.angle_filter_change}"
                )
                await asyncio.sleep(self.mtcs.tel_settle_time)

    async def take_data(self):
        """Take data while making sure MTCS is tracking."""

        tasks = [
            asyncio.create_task(self._take_data()),
            asyncio.create_task(self.mtcs.check_tracking()),
        ]

        await self.mtcs.process_as_completed(tasks)

    async def _take_data(self):
        """Take data."""

        for exptime in self.config.exp_times:
            await self.wait_mtaos_idle()
            await asyncio.sleep(exptime)

    async def wait_mtaos_idle(self):
        self.mtcs.rem.mtaos.evt_closedLoopState.flush()
        mtaos_closed_loop_state = await self.mtcs.rem.mtaos.evt_closedLoopState.aget()
        self.log.info(
            f"MTAOS closed loop state: {ClosedLoopState(mtaos_closed_loop_state.state).name}."
        )
        while mtaos_closed_loop_state.state not in {
            ClosedLoopState.IDLE,
            ClosedLoopState.WAITING_IMAGE,
            ClosedLoopState.PROCESSING,
            ClosedLoopState.ERROR,
        }:
            try:
                mtaos_closed_loop_state = (
                    await self.mtcs.rem.mtaos.evt_closedLoopState.next(
                        flush=False, timeout=self.mtcs.long_timeout
                    )
                )
                self.log.info(
                    f"MTAOS closed loop state: {ClosedLoopState(mtaos_closed_loop_state.state).name}."
                )
            except asyncio.TimeoutError:
                self.log.warning(
                    "No new closed loop state event. Continuing. "
                    "Last known state: {ClosedLoopState(mtaos_closed_loop_state.state).name}."
                )
                return

    async def stop_tracking(self):
        """Execute stop tracking on MTCS."""
        await self.mtcs.stop_tracking()
