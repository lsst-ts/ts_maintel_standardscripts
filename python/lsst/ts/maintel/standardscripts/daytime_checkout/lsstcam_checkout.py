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
import random

import yaml
from lsst.ts import salobj, utils
from lsst.ts.observatory.control.maintel.lsstcam import LSSTCam, LSSTCamUsages
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages
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

    - "Checking Component Status": Before verifying component enablement.
    - "Checking LSSTCam Setup": Logs filter installed and available filters.
    - "Bias Frame Verification": Before taking bias frame.
    - "Engineering Frame Verification": Before taking engineering frames.
    - "Exercising Filter Changes": Before exercising filter wheel (if enabled).
      Final checkpoint in script.

    **Details**

    This script is used to perform the daytime checkout of LSSTCam to ensure it
    is ready for nighttime operations. It does not include telescope or dome
    motion. It will enable LSSTCam, take a bias and an engineering frame, and
    check that both frames were successfully ingested by OODS with all
    raft/sensor combinations having successful status.

    Optionally, the script can exercise the filter wheel by cycling from the
    current filter to a randomly selected different filter and back to the
    original filter. This requires MTCS to be available and enabled. The script
    can also be configured to only perform the filter exercise and skip the
    image checks.

    Individual LSSTCam or MTCS components can be ignored in status checks using
    the 'ignore' parameter. However, when exercising filters, the mtrotator
    component cannot be ignored as it is required for filter changes.
    """

    def __init__(self, index):
        super().__init__(
            index=index,
            descr="Execute daytime checkout of LSSTCam.",
        )
        self.lsstcam = None
        self.mtcs = None
        self.ingestion_timeout = INGESTION_TIMEOUT
        self.current_filter = None  # Store current filter discovered during checkout

    @classmethod
    def get_schema(cls):
        """Return the JSON schema for configuring this script."""
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_maintel_standardscripts/daytime/lsstcam_checkout.yaml
            title: LsstCamCheckout v1
            description: Configuration for LsstCamCheckout daytime script.
            type: object
            properties:
              program:
                description: Optional name of the program this data belongs to.
                type: string
                default: ""
              reason:
                description: Optional reason for taking the data.
                type: string
                default: daytime_checkout
              note:
                description: A descriptive note about the image being taken.
                type: string
                default: ""
              exercise_filters:
                description: >
                  Whether to exercise filter changes by cycling from current filter
                  to a randomly selected different filter and back to original.
                  Requires MTCS to be available.
                type: boolean
                default: false
              filter_only:
                description: >
                  Whether to only exercise filters and skip image checks. When true,
                  exercise_filters must also be true.
                type: boolean
                default: false
              ignore:
                description: >-
                  CSCs from the LSSTCam or MTCS group to ignore in status check.
                  Name must match those in self.lsstcam.components or
                  self.mtcs.components, e.g.; mtrotator, mtmount,
                  mtheaderservice, etc. Note: when exercising filters, do not
                  ignore mtrotator as it is required for filter changes.
                type: array
                items:
                  type: string
            additionalProperties: false
        """
        return yaml.safe_load(schema_yaml)

    async def configure(self, config):
        """Configure the script and LSSTCam object.

        Parameters
        ----------
        config : types.SimpleNamespace
            Script configuration object, as defined by the schema.

        Raises
        ------
        RuntimeError
            If filter_only is True but exercise_filters is False.
        """
        # Validate parameter combinations
        if getattr(config, "filter_only", False) and not getattr(
            config, "exercise_filters", False
        ):
            raise RuntimeError("filter_only=True requires exercise_filters=True")

        # Initialize MTCS if filter exercise is requested
        if getattr(config, "exercise_filters", False):
            if self.mtcs is None:
                self.mtcs = MTCS(
                    domain=self.domain,
                    intended_usage=MTCSUsages.Slew | MTCSUsages.StateTransition,
                    log=self.log,
                )
                await self.mtcs.start_task

        # Initialize LSSTCam if not already done
        if self.lsstcam is None:
            self.lsstcam = LSSTCam(
                domain=self.domain,
                intended_usage=LSSTCamUsages.All,
                log=self.log,
                mtcs=self.mtcs,
            )
            await self.lsstcam.start_task

        self.program = getattr(config, "program", "")
        self.reason = getattr(config, "reason", "daytime_checkout")
        self.note = getattr(config, "note", "")
        self.exercise_filters = getattr(config, "exercise_filters", False)
        self.filter_only = getattr(config, "filter_only", False)

        # Handle ignore parameter for component status checks
        if hasattr(config, "ignore"):
            ignore_components = config.ignore

            # Validate that mtrotator is not ignored when exercising filters
            if self.exercise_filters and "mtrotator" in ignore_components:
                raise RuntimeError(
                    "Cannot ignore 'mtrotator' when exercise_filters=True. "
                    "The rotator is required for filter changes."
                )

            # Apply ignore settings to components
            self.lsstcam.disable_checks_for_components(components=ignore_components)
            if self.exercise_filters and self.mtcs is not None:
                self.mtcs.disable_checks_for_components(components=ignore_components)

    def set_metadata(self, metadata):
        """Set estimated duration and metadata for this script.

        Parameters
        ----------
        metadata : lsst.ts.standardscripts.Metadata
            Metadata object to update.
        """
        # Base duration for image checks; add time for filter exercise
        base_duration = 120
        if getattr(self, "exercise_filters", False):
            base_duration += 120  # Add 60 seconds for filter changes

        metadata.duration = base_duration
        metadata.instrument = "LSSTCam"
        metadata.filter = self.current_filter
        metadata.survey = self.program

    async def run(self):
        """Orchestrate the daytime checkout procedure.

        Runs each logical step as a dedicated method.
        """
        await self.assert_feasibility()
        await self.log_setup_info()

        # Always perform image checks unless filter_only is True
        if not self.filter_only:
            await self.verify_bias_frame()
            await self.verify_engtest_frame()

        # Perform filter exercise if requested
        if self.exercise_filters:
            await self.exercise_filter_changes()

    async def assert_feasibility(self):
        """Check that all required components are enabled and ready.

        Raises
        ------
        AssertionError
            If any LSSTCam component is not enabled, or if MTCS is not
            enabled when filter exercise is requested.
        """
        await self.checkpoint("Checking Component Status")

        await self.lsstcam.assert_all_enabled()

        # Also check MTCS if filter exercise is requested
        if self.exercise_filters:
            await self.mtcs.assert_all_enabled()

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
            exptime=1,
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
                    flush=False, timeout=STD_TIMEOUT
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

    async def exercise_filter_changes(self):
        """Exercise the filter exchanger system by cycling through filters.

        Cycles from the current filter to a randomly selected different filter
        and back to the original one to verify filter change mechanisms.

        Raises
        ------
        RuntimeError
            If any filter change fails or if the filter wheel state is invalid.
        """
        await self.checkpoint("Exercising Filter Changes")

        if self.current_filter is None:
            raise RuntimeError(
                "Current filter is unknown - cannot exercise filter changes"
            )

        # Get available filters
        try:
            available_filters = await self.lsstcam.get_available_filters()
            self.log.info(f"Available filters: {available_filters}")
        except Exception as e:
            raise RuntimeError(f"Failed to get available filters: {e}")

        # Determine target filter (randomly select different from current)
        other_filters = [f for f in available_filters if f != self.current_filter]

        # Randomly select from the available alternatives
        target_filter = random.choice(other_filters)
        self.log.info(
            f"Will cycle: {self.current_filter} -> {target_filter} -> {self.current_filter}"
        )

        # First filter change: current -> random selected
        try:
            self.log.info(
                f"Changing filter from {self.current_filter} to {target_filter}"
            )
            await self.mtcs.change_filter(target_filter)
            self.log.info(f"Successfully changed filter to {target_filter}")
        except Exception as e:
            raise RuntimeError(f"Failed to change filter to {target_filter}: {e}")

        # Second filter change: random selected -> original
        try:
            self.log.info(
                f"Changing filter from {target_filter} back to {self.current_filter}"
            )
            await self.mtcs.change_filter(self.current_filter)
            self.log.info(f"Successfully changed filter back to {self.current_filter}")
        except Exception as e:
            raise RuntimeError(
                f"Failed to change filter back to {self.current_filter}: {e}"
            )

        # Verify final filter state
        try:
            final_filter = await self.lsstcam.get_current_filter()
            if final_filter != self.current_filter:
                raise RuntimeError(
                    f"Filter exercise failed - expected {self.current_filter}, "
                    f"got {final_filter}"
                )
            self.log.info(
                f"Filter exercise completed successfully - filter is {final_filter}"
            )
        except Exception as e:
            raise RuntimeError(f"Failed to verify final filter state: {e}")
