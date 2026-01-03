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
                MTCSUsages.Slew | MTCSUsages.StateTransition | MTCSUsages.AOS,
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
        schema_dict["properties"]["run_aos_closed_loop_on_filter_change"] = {
            "type": "boolean",
            "description": "Run AOS closed loop when there is a filter change?",
            "default": False,
        }
        schema_dict["properties"]["aos_closed_loop_settings"] = {
            "type": "object",
            "additionalProperties": False,
            "description": "Configuration for the aos closed loop.",
            "default": {
                "n_iter": 1,
            },
            "properties": {
                "n_iter": {
                    "type": "integer",
                    "description": "Number of iterations to run.",
                },
            },
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

        filter_change_required = current_filter != self.config.band_filter
        if filter_change_required:
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

        if filter_change_required and self.config.run_aos_closed_loop_on_filter_change:
            self.log.info("Filter changed, running a close loop sequence.")
            await self._run_close_loop()
        elif filter_change_required:
            self.log.info("Filter changed but not running close loop sequence.")

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
            await self.lsstcam.take_object(
                exptime=exptime,
                group_id=self.group_id,
                reason=self.config.reason,
                program=self.config.program,
                note=self.note,
            )

    async def wait_mtaos_idle(self):
        self.mtcs.rem.mtaos.evt_closedLoopState.flush()
        mtaos_closed_loop_state = await self.mtcs.rem.mtaos.evt_closedLoopState.aget(
            timeout=self.mtcs.long_timeout
        )
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

    async def _wait_mtaos_ready_for_closed_loop(self):
        self.mtcs.rem.mtaos.evt_closedLoopState.flush()
        mtaos_closed_loop_state = await self.mtcs.rem.mtaos.evt_closedLoopState.aget(
            timeout=self.mtcs.long_timeout
        )
        while mtaos_closed_loop_state.state not in {
            ClosedLoopState.WAITING_IMAGE,
        }:
            try:
                mtaos_closed_loop_state = (
                    await self.mtcs.rem.mtaos.evt_closedLoopState.next(
                        flush=False, timeout=self.mtcs.long_long_timeout
                    )
                )
                self.log.info(
                    f"MTAOS closed loop state: {ClosedLoopState(mtaos_closed_loop_state.state).name}."
                )
            except asyncio.TimeoutError as e:
                raise RuntimeError(
                    "Waiting for the MTAOS closed loop state to go to WAITING_IMAGE took too long.\n\n"
                    "We need to wait for the closed loop to be in this state so we can run close "
                    "loop sequence. This might indicate there is an issue with the Rapid Analisys "
                    "backend or something alike delaying the image processing.\n"
                    "You might want to reach out for support."
                ) from e

    async def _run_close_loop(self):
        """Run a close loop sequence."""

        self.mtcs.rem.mtaos.evt_closedLoopState.flush()
        mtaos_closed_loop_state = await self.mtcs.rem.mtaos.evt_closedLoopState.aget(
            timeout=self.mtcs.long_timeout
        )
        if mtaos_closed_loop_state.state == ClosedLoopState.IDLE:
            raise RuntimeError(
                "Current MTAOS closed loop state is IDLE. \n\n"
                "In order to support changing filters with this script the MTAOS "
                "close loop must be running. If you forgot to enable close loop "
                "prior to resuming survey operations you might need to stop, "
                "align the optics, enable close loop and resume again. "
                "If this is intentional, request your support to disable the "
                "filter close loop sequence feature in this script."
            )
        self.log.info(
            f"MTAOS closed loop state: {ClosedLoopState(mtaos_closed_loop_state.state).name}."
        )
        await self._wait_mtaos_ready_for_closed_loop()
        exptime = self.config.exp_times[0]
        for exp in range(self.config.aos_closed_loop_settings["n_iter"]):
            visit_ids = await self.lsstcam.take_object(
                exptime=exptime,
                group_id=self.group_id,
                reason=f"{self.config.reason}_filter_change_close_loop",
                program=self.config.program,
                note=f"close_loop#{exp+1}",
            )
            wait_correction_for_visit_id_task = asyncio.create_task(
                self.wait_correction_for_visit_id(visit_id=visit_ids[0])
            )
            await self.lsstcam.take_object(
                exptime=exptime,
                group_id=self.group_id,
                reason=f"{self.config.reason}_filter_change_close_loop",
                program=self.config.program,
                note=f"extra_visit_while_waiting_for_correction#{exp+1}",
            )
            await wait_correction_for_visit_id_task

    async def wait_correction_for_visit_id(self, visit_id: int) -> None:
        """Wait for the AOS correction for the provided visit id.

        Parameters
        ----------
        visit_id : `int`
            Visit id to wait the correction for.
        """
        self.mtcs.rem.mtaos.evt_degreeOfFreedom.flush()
        degree_of_freedom = await self.mtcs.rem.mtaos.evt_degreeOfFreedom.aget(
            timeout=self.mtcs.long_timeout
        )
        degree_of_freedom_visit_id_index = degree_of_freedom.visitId % 100000
        visit_id_index = visit_id % 100000
        self.log.info(
            f"Waiting for degree of freedom for {visit_id=} ({visit_id_index=}); "
            f"got initial {degree_of_freedom_visit_id_index}."
        )
        while visit_id_index <= degree_of_freedom_visit_id_index:
            try:
                degree_of_freedom = await self.mtcs.rem.mtaos.evt_degreeOfFreedom.next(
                    flush=False,
                    timeout=(
                        self.mtcs.long_long_timeout + self.config.exp_times[0] * 2.0
                    ),
                )
            except TimeoutError as e:
                raise RuntimeError(
                    f"Timeout waiting for AOS corrections to complete for visit {visit_id}; "
                    f"last correction received was for {degree_of_freedom_visit_id_index}. "
                    "This might be a sign that RA is taking too long to calculate the corrections "
                    "or some other issue calculating the corrections themselves (e.g. too cloudy). "
                    "Check the dataset on RubinTV and/or reach out to support for help identifying the issue."
                ) from e
            degree_of_freedom_visit_id_index = degree_of_freedom.visitId % 100000
            self.log.info(
                f"Waiting for degree of freedom for {visit_id_index=}; "
                f"got {degree_of_freedom_visit_id_index}."
            )

    async def stop_tracking(self):
        """Execute stop tracking on MTCS."""
        await self.mtcs.stop_tracking()
