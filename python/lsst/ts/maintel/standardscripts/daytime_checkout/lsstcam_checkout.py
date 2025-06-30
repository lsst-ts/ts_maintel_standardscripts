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

__all__ = ["LsstCamCheckout"]

import asyncio

import yaml
from lsst.ts import salobj, utils
from lsst.ts.observatory.control.maintel.lsstcam import LSSTCam, LSSTCamUsages
from lsst.ts.standardscripts.utils import get_topic_time_utc

STD_TIMEOUT = 10  # seconds
INGESTION_TIMEOUT = 30  # seconds to wait for all image ingestion events
MAX_TELEMETRY_AGE = 60  # Maximum age for imageInOODS telemetry to be considered valid


class LsstCamCheckout(salobj.BaseScript):
    """Daytime LSSTCam Checkout SAL Script.

    This script performs a daytime checkout of LSSTCam to ensure it is ready
    to be released for nighttime operations. It verifies that LSSTCam is
    enabled, logs the current instrument configuration, takes a bias frame
    and an engineering frame, and checks that both frames were successfully
    ingested by OODS with all raft/sensor combinations having successful
    status.

    This script does not perform any telescope or dome motion, and does not
    change any instrument configuration. It is purely a verification script
    for camera functionality.

    Parameters
    ----------
    index : `int`
        Index of Script SAL component.

    Notes
    -----
    **Checkpoints**

    - "Checking LSSTCam Setup": Logs filter installed and available filters.
    - "Bias Frame Verification": Before taking bias frame.
    - "Engineering Frame Verification": Before taking engineering frames.
      Final checkpoint in script.

    **Details**

    This script is used to perform the daytime checkout of LSSTCam to ensure it
    is ready for nighttime operations. It does not include telescope or dome
    motion. It will enable LSSTCam, take a bias and an engineering frame, and
    check that both frames were successfully ingested by OODS with all
    raft/sensor combinations having successful status.
    """

    def __init__(self, index):
        super().__init__(
            index=index,
            descr="Execute daytime checkout of LSSTCam.",
        )
        self.lsstcam = None
        self.timeout = STD_TIMEOUT
        self.ingestion_timeout = INGESTION_TIMEOUT
        self.current_filter = None  # Store current filter discovered during checkout

    @classmethod
    def get_schema(cls):
        """Return the JSON schema for configuring this script."""
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_maintel_standardscripts/lsstcam_checkout.yaml
            title: LsstCamCheckout v1
            description: Configuration for LsstCamCheckout daytime script.
            type: object
            properties:
              program:
                description: Program name for image headers.
                type: string
                default: LSSTCAM-CHECKOUT
              reason:
                description: Short tag-like string used for disambiguation (image header).
                type: string
                default: daytime_checkout
              note:
                description: Observer note to be added to the image header.
                type: string
                default: ''
            additionalProperties: false
        """
        return yaml.safe_load(schema_yaml)

    async def configure(self, config):
        """Configure the script and LSSTCam object.

        Parameters
        ----------
        config : dict
            Script configuration dictionary, as defined by the schema.
        """
        if self.lsstcam is None:
            self.lsstcam = LSSTCam(
                domain=self.domain,
                intended_usage=LSSTCamUsages.TakeImageFull,
                log=self.log,
            )
            await self.lsstcam.start_task

        self.program = config.get("program", "LSSTCAM-CHECKOUT")
        self.reason = config.get("reason", "daytime_checkout")
        self.note = config.get("note", "")

    def set_metadata(self, metadata):
        """Set estimated duration and metadata for this script.

        Parameters
        ----------
        metadata : lsst.ts.standardscripts.Metadata
            Metadata object to update.
        """
        metadata.duration = 20
        metadata.instrument = "LSSTCam"
        metadata.filter = self.current_filter
        metadata.survey = self.program

    async def run(self):
        """Orchestrate the daytime checkout procedure.

        Runs each logical step as a dedicated method.
        """
        await self.assert_feasibility()
        await self.log_setup_info()
        await self.verify_bias_frame()
        await self.verify_engtest_frame()

    async def assert_feasibility(self):
        """Check that all required LSSTCam components are enabled and ready.

        Raises
        ------
        AssertionError
            If any LSSTCam component is not enabled.
        """
        await self.lsstcam.assert_all_enabled()

    async def log_setup_info(self):
        """Log current instrument configuration.

        Logs the current filter in the beam and the available filters.

        Raises
        ------
        Exception
            If any information cannot be retrieved.
        """
        await self.checkpoint("Checking LSSTCam Setup")

        try:
            self.current_filter = await self.lsstcam.get_current_filter()
            self.log.info(f"Current filter in beam: {self.current_filter}")
        except Exception as e:
            self.log.warning(f"Could not retrieve current filter: {e}")
            self.current_filter = None

        try:
            available_filters = await self.lsstcam.get_available_filters()
            self.log.info(f"Available filters: {available_filters}")
        except Exception as e:
            self.log.warning(f"Could not retrieve available filters: {e}")

    async def verify_bias_frame(self):
        """Take a bias frame and verify successful OODS ingestion.

        This step flushes the OODS event queue, takes a bias frame with
        metadata, waits for OODS ingestion events, and checks that all
        ingestion events for the obsid have statusCode == 0.

        Raises
        ------
        RuntimeError
            If image ingestion fails or times out.
        """
        await self.checkpoint("Bias Frame Verification")

        self.lsstcam.rem.mtoods.evt_imageInOODS.flush()
        exposure_ids = await self.lsstcam.take_bias(
            nbias=1,
            program=self.program,
            reason=self.reason,
            note=self.note,
        )

        # Verify ingestion of the bias image taken
        exposure_id = exposure_ids[0]
        # Extract date and sequence from exposure_id (format: YYYYMMDDNNNNNN)
        exposure_id_str = str(exposure_id)
        date_part = exposure_id_str[:8]  # YYYYMMDD
        seq_part = exposure_id_str[8:]  # NNNNNN
        expected_obsid = f"MC_O_{date_part}_{seq_part:0>6}"

        await self._verify_image_ingestion(expected_obsid=expected_obsid)

    async def verify_engtest_frame(self):
        """Take an engineering frame and verify successful OODS ingestion.

        This step flushes the OODS event queue, takes an engineering test
        frame with metadata, waits for OODS ingestion events, and checks
        that all ingestion events for the obsid have statusCode == 0.

        Raises
        ------
        RuntimeError
            If image ingestion fails or times out.
        """
        await self.checkpoint("Engineering Frame Verification")

        self.lsstcam.rem.mtoods.evt_imageInOODS.flush()

        # Take the engineering test images and get the exposure IDs
        exposure_ids = await self.lsstcam.take_engtest(
            n=1,
            exptime=2,
            program=self.program,
            reason=self.reason,
            note=self.note,
        )

        # Verify ingestion of the image taken
        exposure_id = exposure_ids[0]
        # Extract date and sequence from exposure_id (format: YYYYMMDDNNNNNN)
        exposure_id_str = str(exposure_id)
        date_part = exposure_id_str[:8]  # YYYYMMDD
        seq_part = exposure_id_str[8:]  # NNNNNN
        expected_obsid = f"MC_O_{date_part}_{seq_part:0>6}"

        await self._verify_image_ingestion(expected_obsid=expected_obsid)

        # Get the current filter for logging after the image
        try:
            inst_filter = await self.lsstcam.get_current_filter()
            # Update current filter if we get a good reading
            if inst_filter and inst_filter != "UNKNOWN":
                self.current_filter = inst_filter
        except Exception:
            inst_filter = "UNKNOWN"
        self.log.info(f"Engineering test completed with filter {inst_filter}")

    async def _verify_image_ingestion(self, expected_obsid):
        """Verify successful OODS ingestion for a single image.

        This method collects all ingestion events for the specified obsid
        and verifies that all raft/sensor combinations have statusCode == 0.
        For LSSTCam, this means checking all 189 raft/sensor combinations.

        Parameters
        ----------
        expected_obsid : str
            Expected observation ID in format "MC_O_YYYYMMDD_NNNNNN"
            constructed from the exposure_id returned by the camera. The
            exposure_id is an integer in format YYYYMMDDNNNNNN where
            YYYYMMDD is the date and NNNNNN is the sequence number.

        Raises
        ------
        RuntimeError
            If image ingestion fails, times out, or has wrong status codes.
        """
        ingestion_events = []
        start_time = utils.current_tai()

        self.log.info(f"Waiting for OODS ingestion events for obsid {expected_obsid}")

        while utils.current_tai() - start_time < self.ingestion_timeout:
            try:
                ingest_event = await self.lsstcam.rem.mtoods.evt_imageInOODS.next(
                    flush=False, timeout=15  # Short timeout for individual events
                )

                # Check telemetry age
                event_timestamp = ingest_event.private_sndStamp
                telemetry_age = utils.current_tai() - event_timestamp
                if telemetry_age > MAX_TELEMETRY_AGE:
                    self.log.warning(
                        f"Ignoring stale ingestion event (age: {telemetry_age:.1f}s)"
                    )
                    continue

                # Collect events for our expected obsid
                if ingest_event.obsid == expected_obsid:
                    ingestion_events.append(ingest_event)
                    self.log.debug(
                        f"Collected ingestion event for {ingest_event.obsid}, "
                        f"raft={ingest_event.raft}, sensor={ingest_event.sensor}, "
                        f"statusCode={ingest_event.statusCode}"
                    )

            except asyncio.TimeoutError:
                # No more events in short timeout, check if we have enough
                if ingestion_events:
                    break
                continue

        if not ingestion_events:
            raise RuntimeError(
                f"No ingestion events received for expected obsid {expected_obsid}. "
                "This usually means there is a problem with the image ingestion."
            )

        # Check that all ingestion events have statusCode == 0
        failed_ingestions = [
            event for event in ingestion_events if event.statusCode != 0
        ]

        if failed_ingestions:
            error_details = [
                f"raft={event.raft}, sensor={event.sensor}, "
                f"statusCode={event.statusCode}, description='{event.description}'"
                for event in failed_ingestions
            ]
            raise RuntimeError(
                f"Image ingestion failed for {len(failed_ingestions)} "
                f"raft/sensor combinations: {'; '.join(error_details)}"
            )

        # Log successful ingestion
        ingest_event_time = get_topic_time_utc(ingestion_events[0])
        self.log.info(
            f"Successfully verified ingestion of {len(ingestion_events)} raft/sensor "
            f"combinations for obsid {expected_obsid} at {ingest_event_time} UT"
        )
