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
from contextlib import asynccontextmanager

import yaml
from lsst.ts import salobj, utils
from lsst.ts.observatory.control.maintel.lsstcam import LSSTCam, LSSTCamUsages
from lsst.ts.standardscripts.utils import get_topic_time_utc

INGESTION_TIMEOUT = 30  # seconds to wait for all image ingestion events


class LsstCamCheckout(salobj.BaseScript):
    """Daytime LSSTCam Checkout SAL Script.

    This script performs a daytime checkout of LSSTCam to ensure it is ready
    to be released for nighttime operations. It verifies that LSSTCam is
    enabled, logs the current instrument configuration, takes a bias frame
    and an engineering frame, and checks that both frames were successfully
    ingested by MTOODS with all raft/sensor combinations having successful
    status.

    Parameters
    ----------
    index : `int`
        Index of Script SAL component.

    Notes
    -----
    **Checkpoints**

    - "Checking Component Status": Before verifying CSCs are enabled.
    - "Checking LSSTCam Setup": Logs installed and available filters.
    - "Bias Frame Verification": Before taking bias frame.
    - "Engineering Frame Verification": Before taking engineering frames.

    **Details**

    This script is used to perform the daytime checkout of LSSTCam to ensure it
    is ready for nighttime operations. It does not include telescope or dome
    motion. It will enable LSSTCam, take a bias and an engineering frame, and
    check that both frames were successfully ingested by MTOODS with all
    raft/sensor combinations having successful status.

    Individual LSSTCam components can be ignored in status checks using
    the 'ignore' parameter.
    """

    def __init__(self, index):
        super().__init__(
            index=index,
            descr="Execute daytime checkout of LSSTCam.",
        )
        self.lsstcam = None
        self.ingestion_timeout = INGESTION_TIMEOUT
        self.current_filter = None
        self.available_filters = None

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
                anyOf:
                  - type: string
                  - type: "null"
                default: "camera_checkout"
              reason:
                description: Optional reason for taking the data.
                anyOf:
                  - type: string
                  - type: "null"
              note:
                description: A descriptive note about the image being taken.
                anyOf:
                  - type: string
                  - type: "null"
              ignore:
                description: >-
                  CSCs from the LSSTCam group to ignore in status check.
                  Name must match those in self.lsstcam.components, e.g.
                  mtheaderservice, etc.
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

        """
        self.program = getattr(config, "program", "daytime_checkout")
        self.reason = getattr(config, "reason", None)
        self.note = getattr(config, "note", None)

        if self.lsstcam is None:
            self.lsstcam = LSSTCam(
                domain=self.domain,
                intended_usage=LSSTCamUsages.All,
                log=self.log,
            )
            await self.lsstcam.start_task

        if hasattr(config, "ignore"):
            self.lsstcam.disable_checks_for_components(components=config.ignore)

    def set_metadata(self, metadata):
        """Set estimated duration and metadata."""
        read_out_time = getattr(self.lsstcam, "read_out_time", 2.0)
        shutter_time = getattr(self.lsstcam, "shutter_time", 1.0)
        per_exposure_time = self.ingestion_timeout + read_out_time + shutter_time

        metadata.duration = 2 * per_exposure_time
        metadata.instrument = "LSSTCam"
        metadata.filter = self.current_filter
        metadata.survey = self.program

    async def run(self):

        await self.assert_feasibility()
        await self.log_setup_info()

        await self.verify_bias_frame()
        await self.verify_engtest_frame()

    async def assert_feasibility(self):
        """Check that all required components are enabled and ready.

        Raises
        ------
        AssertionError
            If any LSSTCam component is not enabled.
        """
        await self.checkpoint("Checking components status.")

        await self.lsstcam.assert_all_enabled()

    async def log_setup_info(self):
        """Log current LSSTCam configuration.

        Logs the current filter in the beam and the available filter names.
        Failures are logged as warnings and do not abort the checkout.

        Notes
        -----
        ``self.current_filter`` may be set to `None` if the current filter
        cannot be retrieved.
        """
        await self.checkpoint("Checking LSSTCam Setup.")

        try:
            self.current_filter = await self.lsstcam.get_current_filter()
            self.log.info(f"Current filter in beam: {self.current_filter}.")
        except Exception as e:
            self.log.warning(f"Could not retrieve current filter: {e}.")
            self.current_filter = None

        try:
            self.available_filters = await self.lsstcam.get_available_filters()
            self.log.info(f"Available filters: {self.available_filters}.")
        except Exception as e:
            self.log.warning(f"Could not retrieve available filters: {e}.")

    async def verify_bias_frame(self):
        """Take a bias frame and verify MTOODS ingestion.

        The image is taken inside ``ingested_image()``, which flushes the
        MTOODS queue, waits up to ``self.ingestion_timeout``, and validates
        ingestion for the latest exposure.

        Raises
        ------
        RuntimeError
            If ingestion validation fails.
        """
        await self.checkpoint("Bias Frame Verification.")

        async with self.ingested_image():
            await self.lsstcam.take_bias(nbias=1)

        self.log.info("Bias exposure ingestion verified successfully.")

    async def verify_engtest_frame(self):
        """Take an engineering frame and verify MTOODS ingestion.

        The image is taken inside ``ingested_image()``, which flushes the
        MTOODS queue, waits up to ``self.ingestion_timeout``, and validates
        ingestion for the latest exposure.

        Raises
        ------
        RuntimeError
            If ingestion validation fails.
        """
        await self.checkpoint("Engineering Frame Verification.")

        async with self.ingested_image():
            await self.lsstcam.take_engtest(
                n=1,
                exptime=1,
                program=self.program,
                reason=self.reason,
                note=self.note,
            )

        self.log.info("Engineering exposure ingestion verified successfully.")

        try:
            inst_filter = await self.lsstcam.get_current_filter()
        except Exception as e:
            self.log.warning(
                f"Engineering test completed but could not read current filter: {e}."
            )
        else:
            if inst_filter:
                self.current_filter = inst_filter
            self.log.info(f"Engineering test completed with filter {inst_filter}.")

    @asynccontextmanager
    async def ingested_image(self):
        """Flush MTOODS events, run image acquisition, then validate ingestion.

        Runs the camera command inside the context and verifies ingestion
        for the latest exposure. It flushes MTOODS events before running the
        command to ensure that only events related to the current exposure
        are considered. After the command completes, it waits for ingestion
        events to arrive and validates that at least one event is received
        for the latest exposure and that all events report successful
        ingestion.

        Raises
        ------
        RuntimeError
            If no post-flush events arrive in time or any event reports
            failure.
        """

        self.lsstcam.rem.mtoods.evt_imageInOODS.flush()
        flush_time = utils.current_tai()

        try:
            yield
        except Exception:
            raise
        else:

            (
                ingestion_events,
                failed_ingestions,
                unique_pairs,
                observed_obsid,
            ) = await self._collect_ingestion_events(flush_time)

            self._validate_ingestion(
                ingestion_events,
                failed_ingestions,
                unique_pairs,
                observed_obsid,
            )

    async def _collect_ingestion_events(self, flush_time):
        """Collect ingestion events emitted after the provided flush time."""
        ingestion_events = []
        failed_ingestions = []
        unique_pairs = set()
        observed_obsid = None

        self.log.info("Waiting for MTOODS ingestion events for the latest exposure.")

        async def collect_events():
            nonlocal observed_obsid
            while True:

                # Wait for the next ingestion event
                try:
                    ingest_event = await self.lsstcam.rem.mtoods.evt_imageInOODS.next(
                        flush=False, timeout=self.ingestion_timeout
                    )
                except asyncio.TimeoutError:
                    return

                # Ignore events that were emitted before the flush
                if ingest_event.private_sndStamp < flush_time:
                    self.log.warning(
                        f"Ignoring pre-flush ingestion event with obsid "
                        f"{getattr(ingest_event, 'obsid', '<unknown>')} ."
                    )
                    continue

                # Track events for the first observed obsid and ignore others
                if observed_obsid is None:
                    observed_obsid = ingest_event.obsid
                    self.log.debug(f"Tracking ingestion for obsid {observed_obsid}.")
                elif ingest_event.obsid != observed_obsid:
                    self.log.warning(
                        f"Ignoring ingestion event for unexpected obsid "
                        f"{ingest_event.obsid} (expected {observed_obsid})."
                    )
                    continue

                # Process the valid ingestion events
                ingestion_events.append(ingest_event)
                unique_pairs.add((ingest_event.raft, ingest_event.sensor))
                if ingest_event.statusCode != 0:
                    failed_ingestions.append(ingest_event)
                self.log.debug(
                    f"Collected ingestion event for {ingest_event.obsid}, "
                    f"raft={ingest_event.raft}, sensor={ingest_event.sensor}, "
                    f"statusCode={ingest_event.statusCode}."
                )

        # Wait for events to be collected until timeout
        try:
            await asyncio.wait_for(collect_events(), timeout=self.ingestion_timeout)
        except asyncio.TimeoutError:
            pass

        return ingestion_events, failed_ingestions, unique_pairs, observed_obsid

    def _validate_ingestion(
        self, ingestion_events, failed_ingestions, unique_pairs, observed_obsid
    ):
        """Validate collected ingestion events and log success details."""
        if not ingestion_events:
            raise RuntimeError(
                "No ingestion events received for the latest exposure. This usually "
                "means there is a problem with the image ingestion."
            )

        if failed_ingestions:
            error_details = [
                f"raft={event.raft}, sensor={event.sensor}, statusCode={event.statusCode}, "
                f"description='{event.description}'"
                for event in failed_ingestions
            ]
            raise RuntimeError(
                f"Image ingestion failed for {len(failed_ingestions)} raft/sensor "
                f"combinations: {'; '.join(error_details)}."
            )

        ingest_event_time = get_topic_time_utc(ingestion_events[0])
        self.log.info(
            f"Successfully verified ingestion of {len(unique_pairs)} "
            f"raft/sensor combinations for obsid {observed_obsid} "
            f"at {ingest_event_time} UT."
        )
