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
import re
from contextlib import asynccontextmanager

import yaml
from lsst.ts import salobj, utils
from lsst.ts.observatory.control.maintel.lsstcam import LSSTCam, LSSTCamUsages
from lsst.ts.standardscripts.utils import get_topic_time_utc

INGESTION_TIMEOUT = 15  # max time to wait for all raft/sensors ingestion events

# Expected ingestion counts by image type
EXPECTED_BIAS_INGEST_SCIENCE = 189
EXPECTED_BIAS_INGEST_GUIDER = 0
EXPECTED_BIAS_INGEST_WFS = 0
EXPECTED_ENGTEST_INGEST_SCIENCE = 189
EXPECTED_ENGTEST_INGEST_GUIDER = 8
EXPECTED_ENGTEST_INGEST_WFS = 8


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
        self.expected_bias_ingest_science = EXPECTED_BIAS_INGEST_SCIENCE
        self.expected_bias_ingest_guider = EXPECTED_BIAS_INGEST_GUIDER
        self.expected_bias_ingest_wfs = EXPECTED_BIAS_INGEST_WFS
        self.expected_engtest_ingest_science = EXPECTED_ENGTEST_INGEST_SCIENCE
        self.expected_engtest_ingest_guider = EXPECTED_ENGTEST_INGEST_GUIDER
        self.expected_engtest_ingest_wfs = EXPECTED_ENGTEST_INGEST_WFS
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

        async with self.ingested_image(
            expected_science=self.expected_bias_ingest_science,
            expected_guider=self.expected_bias_ingest_guider,
            expected_wfs=self.expected_bias_ingest_wfs,
            image_label="bias",
        ):
            await self.lsstcam.take_bias(nbias=1)

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

        async with self.ingested_image(
            expected_science=self.expected_engtest_ingest_science,
            expected_guider=self.expected_engtest_ingest_guider,
            expected_wfs=self.expected_engtest_ingest_wfs,
            image_label="engtest",
        ):
            await self.lsstcam.take_engtest(
                n=1,
                exptime=1,
                program=self.program,
                reason=self.reason,
                note=self.note,
            )

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
    async def ingested_image(
        self,
        expected_science,
        expected_guider,
        expected_wfs,
        image_label,
    ):
        """Flush MTOODS events, run image acquisition, then validate.

        Logs the total expected ingestion count, flushes MTOODS events,
        runs the camera command inside the context, and verifies
        ingestion for the latest exposure. Only events related to the
        current exposure are considered. After the command completes,
        it waits for ingestion events and validates that the expected
        number of science, guider and WFS ingestions are received.

        Parameters
        ----------
        expected_science : `int`
            Expected number of science sensor ingestions.
        expected_guider : `int`
            Expected number of guider sensor ingestions.
        expected_wfs : `int`
            Expected number of wavefront sensor ingestions.
        image_label : `str`
            Label for the image type (e.g. ``"bias"``,
            ``"engtest"``), used in log and error messages.

        Raises
        ------
        RuntimeError
            If no post-flush events arrive in time or the expected
            number of science, guider or WFS ingestions is not
            reached within the timeout.
        """

        expected_total = expected_science + expected_guider + expected_wfs
        breakdown_parts = [f"{expected_science} science"]
        if expected_guider > 0:
            breakdown_parts.append(f"{expected_guider} guider")
        if expected_wfs > 0:
            breakdown_parts.append(f"{expected_wfs} wfs")
        self.log.info(
            f"Expecting {expected_total} ingestions "
            f"({', '.join(breakdown_parts)}) "
            f"for '{image_label}' image."
        )

        self.lsstcam.rem.mtoods.evt_imageInOODS.flush()
        flush_time = utils.current_tai()

        try:
            yield
        except Exception:
            raise
        else:

            (
                ingestion_events,
                unique_pairs,
                observed_obsid,
            ) = await self._collect_ingestion_events(flush_time, image_label)

            self._validate_ingestion(
                ingestion_events,
                unique_pairs,
                observed_obsid,
                expected_science=expected_science,
                expected_guider=expected_guider,
                expected_wfs=expected_wfs,
                image_label=image_label,
            )

    async def _collect_ingestion_events(self, flush_time, image_label):
        """Collect ingestion events emitted after flush time.

        Parameters
        ----------
        flush_time : `float`
            TAI timestamp; events before this are ignored.
        image_label : `str`
            Label for the image type, used in log messages.

        Returns
        -------
        ingestion_events : `list`
            All valid ingestion events for the tracked obsid.
        unique_pairs : `set`
            Unique ``(raft, sensor)`` pairs collected.
        observed_obsid : `str` or `None`
            The obsid being tracked, or `None` if no events
            arrived.
        """
        ingestion_events = []
        unique_pairs = set()
        observed_obsid = None

        self.log.info(
            f"Waiting for MTOODS '{image_label}' ingestion events "
            f"for the latest exposure."
        )

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
                self.log.debug(
                    f"Collected ingestion event for {ingest_event.obsid}, "
                    f"raft={ingest_event.raft}, sensor={ingest_event.sensor}."
                )

        # Wait for events to be collected until timeout
        try:
            await asyncio.wait_for(collect_events(), timeout=self.ingestion_timeout)
        except asyncio.TimeoutError:
            pass

        return ingestion_events, unique_pairs, observed_obsid

    def _validate_ingestion(
        self,
        ingestion_events,
        unique_pairs,
        observed_obsid,
        expected_science,
        expected_guider,
        expected_wfs,
        image_label,
    ):
        """Validate collected ingestion events.

        Checks that at least one ingestion event was received and
        that the expected number of science, guider and WFS sensor
        ingestions were received. On failure, logs the list of
        received raft/sensor pairs for each expected category before
        raising. On success, logs a summary with total and per-type
        counts. Only sensor types with a non-zero expected
        count are included in log and error messages.

        Parameters
        ----------
        ingestion_events : `list`
            All collected ingestion events for the observed obsid.
        unique_pairs : `set`
            Unique ``(raft, sensor)`` pairs collected.
        observed_obsid : `str` or `None`
            The obsid being tracked.
        expected_science : `int`
            Expected number of science sensor ingestions.
        expected_guider : `int`
            Expected number of guider sensor ingestions.
        expected_wfs : `int`
            Expected number of wavefront sensor ingestions.
        image_label : `str`
            Label for the image type, used in log and error
            messages.

        Raises
        ------
        RuntimeError
            If no events were received or the expected science,
            guider or WFS counts are not met within the defined
            time window.
        """
        if not ingestion_events:
            raise RuntimeError(
                f"No '{image_label}' ingestion events received "
                f"for the latest exposure within "
                f"{self.ingestion_timeout} seconds. This usually "
                f"means there is a problem with the image "
                f"ingestion."
            )

        science_pairs, guider_pairs, wfs_pairs = self._count_sensor_types(
            ingestion_events
        )
        science_count = len(science_pairs)
        guider_count = len(guider_pairs)
        wfs_count = len(wfs_pairs)

        expected_total = expected_science + expected_guider + expected_wfs
        received_total = science_count + guider_count + wfs_count

        is_incomplete = (
            science_count < expected_science
            or guider_count < expected_guider
            or wfs_count < expected_wfs
        )

        if is_incomplete:
            self.log.warning(
                f"Incomplete {image_label} ingestion for obsid "
                f"{observed_obsid}.\n"
                f"Science sensors ingested: "
                f"{self._group_by_raft(science_pairs)}.\n"
            )
            if expected_guider > 0:
                self.log.warning(
                    f"Incomplete {image_label} ingestion for obsid "
                    f"{observed_obsid}.\n"
                    f"Guider sensors ingested: "
                    f"{self._group_by_raft(guider_pairs)}.\n"
                )
            if expected_wfs > 0:
                self.log.warning(
                    f"Incomplete {image_label} ingestion for obsid "
                    f"{observed_obsid}.\n"
                    f"WFS sensors ingested: "
                    f"{self._group_by_raft(wfs_pairs)}.\n"
                )

            # Build context-aware ingestion breakdown
            received_parts = [f"{science_count}/{expected_science} science"]
            if expected_guider > 0:
                received_parts.append(f"{guider_count}/{expected_guider} guider")
            if expected_wfs > 0:
                received_parts.append(f"{wfs_count}/{expected_wfs} wfs")

            raise RuntimeError(
                f"{image_label.capitalize()} ingestion "
                f"incomplete for obsid {observed_obsid}. "
                f"Received {received_total}/{expected_total} "
                f"total ingestions "
                f"({', '.join(received_parts)}) "
                f"within {self.ingestion_timeout} seconds."
            )

        # Build context-aware success breakdown
        success_parts = [f"{science_count} science"]
        if expected_guider > 0:
            success_parts.append(f"{guider_count} guider")
        if expected_wfs > 0:
            success_parts.append(f"{wfs_count} wfs")

        ingest_event_time = get_topic_time_utc(ingestion_events[0])
        self.log.info(
            f"{image_label.capitalize()} exposure ingestion "
            f"verified successfully: "
            f"{', '.join(success_parts)} sensors "
            f"for obsid {observed_obsid} "
            f"at {ingest_event_time} UT."
        )

    @staticmethod
    def _group_by_raft(pairs):
        """Group sensor names by raft for readable log output.

        Parameters
        ----------
        pairs : `set`
            Set of ``(raft, sensor)`` tuples.

        Returns
        -------
        grouped : `dict`
            Sorted mapping of raft name to sorted list of
            sensor names, e.g.
            ``{R00: [S00, S01], R01: [S00]}``.
        """
        grouped = {}
        for raft, sensor in sorted(pairs):
            grouped.setdefault(raft, []).append(sensor)
        return grouped

    def _count_sensor_types(self, ingestion_events):
        """Count unique science, guider and WFS sensor pairs.

        Parameters
        ----------
        ingestion_events : `list`
            Ingestion events to classify by sensor type.

        Returns
        -------
        science_pairs : `set`
            Unique ``(raft, sensor)`` pairs for science sensors.
        guider_pairs : `set`
            Unique ``(raft, sensor)`` pairs for guider sensors.
        wfs_pairs : `set`
            Unique ``(raft, sensor)`` pairs for wavefront
            sensors.
        """
        science_pairs = set()
        guider_pairs = set()
        wfs_pairs = set()
        science_pattern = re.compile(r"^S\d{2}$")
        guider_pattern = re.compile(r"^SG\d$")
        wfs_pattern = re.compile(r"^SW\d$")

        for event in ingestion_events:
            pair = (event.raft, event.sensor)
            if science_pattern.match(event.sensor):
                science_pairs.add(pair)
            elif guider_pattern.match(event.sensor):
                guider_pairs.add(pair)
            elif wfs_pattern.match(event.sensor):
                wfs_pairs.add(pair)

        return science_pairs, guider_pairs, wfs_pairs
