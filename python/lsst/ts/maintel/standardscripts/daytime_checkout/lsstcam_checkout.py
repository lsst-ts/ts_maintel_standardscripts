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


class LsstCamCheckout(salobj.BaseScript):
    """Daytime LSSTCam Checkout SAL Script.

    This script performs a daytime checkout of LSSTCam to ensure it is ready
    to be released for nighttime operations. It verifies that LSSTCam is
    enabled, logs the current instrument configuration, takes dark frames,
    and checks that all frames were successfully ingested by MTOODS and
    WFOODS with all required raft/sensor combinations having successful
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
    - "Taking and verifying ingestion for dark frame N of M.": Before taking
      and verifying each dark frame.

    **Details**

    This script is used to perform the daytime checkout of LSSTCam to ensure it
    is ready for nighttime operations. It does not include telescope or dome
    motion. It will enable LSSTCam, take dark frames, and check that all frames
    were successfully ingested by MTOODS and WFOODS.
    Each exposure requires 189 science-sensor ingestions from MTOODS and eight
    wavefront-sensor ingestions from WFOODS. Guider ingestion is not required
    by this checkout. Dark frames provide a finite integration while avoiding
    the daytime dome-light risk of open-shutter engineering frames, and still
    exercise image acquisition and OODS ingestion, including WFS coverage.

    Individual LSSTCam components can be ignored in status checks using
    the 'ignore' parameter.
    """

    _SCIENCE_SENSOR_PATTERN = re.compile(r"^S\d{2}$")
    _GUIDER_SENSOR_PATTERN = re.compile(r"^SG\d$")
    _WFS_SENSOR_PATTERN = re.compile(r"^SW\d$")

    def __init__(self, index):
        super().__init__(
            index=index,
            descr="Execute daytime checkout of LSSTCam.",
        )
        self.lsstcam = None
        self.wfoods = None
        self.ingestion_timeout = 120  # max time to wait for ingestion events
        self.expected_dark_ingest_science = 21 * 9
        self.expected_dark_ingest_wfs = 4 * 2
        self.program = None
        self.reason = None
        self.note = None
        self.dark_exptime = 30.0
        self.ndarks = 2
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
                default: "BLOCK-T594"
              reason:
                description: Optional reason for taking the data.
                anyOf:
                  - type: string
                  - type: "null"
                default: "LSSTCamCheckout"
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
        self.program = getattr(config, "program", None)
        self.reason = getattr(config, "reason", None)
        self.note = getattr(config, "note", None)

        if self.lsstcam is None:
            self.lsstcam = LSSTCam(
                domain=self.domain,
                intended_usage=LSSTCamUsages.All,
                log=self.log,
                tcs_ready_to_take_data=None,
            )
            await self.lsstcam.start_task

        if self.wfoods is None:
            self.wfoods = salobj.Remote(
                self.domain,
                "WFOODS",
                readonly=True,
                include=["imageInOODS"],
            )
            await self.wfoods.start_task

        if hasattr(config, "ignore"):
            self.lsstcam.disable_checks_for_components(components=config.ignore)

    def set_metadata(self, metadata):
        """Set estimated duration and metadata."""
        dark_duration = (
            self.dark_exptime + self.ingestion_timeout + self.lsstcam.read_out_time
        )

        metadata.duration = self.ndarks * dark_duration
        metadata.instrument = "LSSTCam"
        if self.program is not None:
            metadata.survey = self.program

    async def run(self):
        await self.assert_feasibility()
        await self.log_setup_info()

        await self.verify_dark_frames()

    async def assert_feasibility(self):
        """Check that all required components are enabled and ready."""
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
        except Exception:
            self.log.warning("Could not retrieve current filter.", exc_info=True)
            self.current_filter = None

        try:
            self.available_filters = await self.lsstcam.get_available_filters()
            self.log.info(f"Available filters: {self.available_filters}.")
        except Exception:
            self.log.warning("Could not retrieve available filters.", exc_info=True)

    async def verify_dark_frames(self):
        """Take dark frames and verify MTOODS and WFOODS ingestion.

        Each image is taken inside ``ingested_image()``, which flushes the
        MTOODS and WFOODS queues, waits up to ``self.ingestion_timeout``, and
        validates ingestion for the latest exposure.

        Raises
        ------
        RuntimeError
            If ingestion validation fails.
        """
        for index in range(1, self.ndarks + 1):
            await self.checkpoint(
                f"Taking and verifying ingestion for dark frame "
                f"{index} of {self.ndarks}."
            )
            self.log.info(f"Taking dark frame {index} of {self.ndarks}.")
            async with self.ingested_image(
                expected_science=self.expected_dark_ingest_science,
                expected_wfs=self.expected_dark_ingest_wfs,
                image_label="dark",
            ):
                exposure_ids = await self.lsstcam.take_darks(
                    exptime=self.dark_exptime,
                    ndarks=1,
                    program=self.program,
                    reason=self.reason,
                    note=self.note,
                )
                self.log.info(
                    f"Dark exposure id {index} of {self.ndarks}: {exposure_ids[0]}."
                )

    @asynccontextmanager
    async def ingested_image(
        self,
        expected_science,
        expected_wfs,
        image_label,
    ):
        """Flush OODS events, run image acquisition, then validate.

        Logs the total expected ingestion count, flushes MTOODS and WFOODS
        events, runs the camera command inside the context, and verifies
        ingestion for the latest exposure. Only events related to the current
        exposure are considered. After the command completes, it waits for
        ingestion events and validates that the expected number of science
        and WFS ingestions are received.

        Parameters
        ----------
        expected_science : `int`
            Expected number of MTOODS science-sensor ingestions.
        expected_wfs : `int`
            Expected number of WFOODS wavefront-sensor ingestions.
        image_label : `str`
            Label for the image type, used in log and error messages.

        Raises
        ------
        RuntimeError
            If no post-flush events arrive in time or the expected
            number of science or WFS ingestions is not reached within
            the timeout.
        """

        expected_total = expected_science + expected_wfs
        self.log.info(
            f"Expecting {expected_total} required ingestions "
            f"({expected_science} science sensors, "
            f"{expected_wfs} WFS sensors) "
            f"for '{image_label}' image."
        )

        flush_time = utils.current_tai()
        self.lsstcam.rem.mtoods.evt_imageInOODS.flush()
        self.wfoods.evt_imageInOODS.flush()

        try:
            yield
        except Exception:
            raise
        else:
            self.log.info(
                f"Waiting for MTOODS '{image_label}' science ingestion events "
                f"for the latest exposure."
            )
            self.log.info(
                f"Waiting for WFOODS '{image_label}' WFS ingestion events "
                f"for the latest exposure."
            )

            (
                (mtoods_events, mtoods_obsid),
                (wfoods_events, wfoods_obsid),
            ) = await asyncio.gather(
                self._collect_ingestion_events(
                    topic=self.lsstcam.rem.mtoods.evt_imageInOODS,
                    oods_name="MTOODS",
                    sensor_pattern=self._SCIENCE_SENSOR_PATTERN,
                    expected_count=expected_science,
                    flush_time=flush_time,
                ),
                self._collect_ingestion_events(
                    topic=self.wfoods.evt_imageInOODS,
                    oods_name="WFOODS",
                    sensor_pattern=self._WFS_SENSOR_PATTERN,
                    expected_count=expected_wfs,
                    flush_time=flush_time,
                ),
            )

            self._validate_ingestion(
                mtoods_events=mtoods_events,
                mtoods_obsid=mtoods_obsid,
                wfoods_events=wfoods_events,
                wfoods_obsid=wfoods_obsid,
                expected_science=expected_science,
                expected_wfs=expected_wfs,
                image_label=image_label,
            )

    async def _collect_ingestion_events(
        self,
        topic,
        oods_name,
        sensor_pattern,
        expected_count,
        flush_time,
    ):
        """Collect one OODS service's events emitted after flush time.

        Parameters
        ----------
        topic : `salobj.topics.RemoteEvent`
            OODS ``imageInOODS`` event topic.
        oods_name : `str`
            Name of the OODS service, used in log messages.
        sensor_pattern : `re.Pattern`
            Pattern identifying the required sensor category.
        expected_count : `int`
            Number of successful unique sensor ingestions required.
        flush_time : `float`
            TAI timestamp; events before this are ignored.

        Returns
        -------
        ingestion_events : `list`
            All valid ingestion events for the tracked obsid.
        observed_obsid : `str` or `None`
            The obsid being tracked, or `None` if no events
            arrived.
        """
        ingestion_events = []
        successful_pairs = set()
        observed_obsid = None

        if expected_count == 0:
            return ingestion_events, observed_obsid

        async def collect_events():
            nonlocal observed_obsid
            while len(successful_pairs) < expected_count:
                # Wait for the next ingestion event
                try:
                    ingest_event = await topic.next(
                        flush=False, timeout=self.ingestion_timeout
                    )
                except asyncio.TimeoutError:
                    return

                # Ignore events that were emitted before the flush
                if ingest_event.private_sndStamp < flush_time:
                    self.log.warning(
                        f"Ignoring pre-flush ingestion event with obsid "
                        f"{getattr(ingest_event, 'obsid', '<unknown>')}."
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
                if (
                    sensor_pattern.fullmatch(ingest_event.sensor)
                    and ingest_event.statusCode == 0
                ):
                    successful_pairs.add((ingest_event.raft, ingest_event.sensor))
                self.log.debug(
                    f"Collected {oods_name} ingestion event for "
                    f"{ingest_event.obsid}, "
                    f"raft={ingest_event.raft}, sensor={ingest_event.sensor}."
                )

        # Wait for events to be collected until timeout
        try:
            await asyncio.wait_for(collect_events(), timeout=self.ingestion_timeout)
        except asyncio.TimeoutError:
            pass

        return ingestion_events, observed_obsid

    def _validate_ingestion(
        self,
        mtoods_events,
        mtoods_obsid,
        wfoods_events,
        wfoods_obsid,
        expected_science,
        expected_wfs,
        image_label,
    ):
        """Validate collected ingestion events.

        Check that MTOODS received the expected science sensors and WFOODS
        received the expected wavefront sensors for the same exposure.
        Guider events observed in MTOODS are reported but do not contribute
        to the required total.

        Parameters
        ----------
        mtoods_events : `list`
            MTOODS events for the observed exposure.
        mtoods_obsid : `str` or `None`
            The obsid tracked from MTOODS.
        wfoods_events : `list`
            WFOODS events for the observed exposure.
        wfoods_obsid : `str` or `None`
            The obsid tracked from WFOODS.
        expected_science : `int`
            Expected number of MTOODS science-sensor ingestions.
        expected_wfs : `int`
            Expected number of WFOODS wavefront-sensor ingestions.
        image_label : `str`
            Label for the image type, used in log and error
            messages.

        Raises
        ------
        RuntimeError
            If required events were not received, the OODS services report
            different obsids, or the expected counts are not met.
        """
        if expected_science > 0 and not mtoods_events:
            raise RuntimeError(
                f"No MTOODS '{image_label}' science ingestion events received "
                f"for the latest exposure within "
                f"{self.ingestion_timeout} seconds. This usually "
                f"means there is a problem with MTOODS image ingestion."
            )

        if expected_wfs > 0 and not wfoods_events:
            raise RuntimeError(
                f"No WFOODS '{image_label}' WFS ingestion events received "
                f"for the latest exposure within "
                f"{self.ingestion_timeout} seconds. This usually "
                f"means there is a problem with WFOODS image ingestion."
            )

        if (
            mtoods_obsid is not None
            and wfoods_obsid is not None
            and mtoods_obsid != wfoods_obsid
        ):
            raise RuntimeError(
                f"MTOODS and WFOODS reported different obsids for the "
                f"'{image_label}' exposure: {mtoods_obsid} and {wfoods_obsid}."
            )

        science_pairs, guider_pairs, _ = self._count_sensor_types(mtoods_events)
        _, _, wfs_pairs = self._count_sensor_types(wfoods_events)
        science_count = len(science_pairs)
        guider_count = len(guider_pairs)
        wfs_count = len(wfs_pairs)

        observed_obsid = mtoods_obsid or wfoods_obsid
        expected_total = expected_science + expected_wfs
        received_total = science_count + wfs_count

        is_incomplete = science_count < expected_science or wfs_count < expected_wfs

        if is_incomplete:
            if science_count < expected_science:
                self.log.warning(
                    f"Incomplete {image_label} science-sensor ingestion for obsid "
                    f"{observed_obsid}.\n"
                    f"Science sensors ingested: "
                    f"{self._group_by_raft(science_pairs)}."
                )
            if wfs_count < expected_wfs:
                self.log.warning(
                    f"Incomplete {image_label} WFS ingestion for obsid "
                    f"{observed_obsid}.\n"
                    f"WFS sensors ingested: "
                    f"{self._group_by_raft(wfs_pairs)}."
                )

            raise RuntimeError(
                f"{image_label.capitalize()} ingestion "
                f"incomplete for obsid {observed_obsid}. "
                f"Received {received_total}/{expected_total} "
                f"required ingestions "
                f"({science_count}/{expected_science} science sensors, "
                f"{wfs_count}/{expected_wfs} WFS sensors) "
                f"within {self.ingestion_timeout} seconds."
            )

        if guider_count > 0:
            self.log.info(
                f"Observed {guider_count} MTOODS guider ingestions for obsid "
                f"{observed_obsid}; guider ingestion is informational and is "
                f"not included in checkout validation."
            )

        ingest_event_time = get_topic_time_utc((mtoods_events or wfoods_events)[0])
        self.log.info(
            f"{image_label.capitalize()} exposure ingestion "
            f"verified successfully: {received_total} required sensors "
            f"({science_count} science sensors, {wfs_count} WFS sensors) "
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
        """Count successful unique science, guider and WFS sensor pairs.

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

        for event in ingestion_events:
            pair = (event.raft, event.sensor)
            if event.statusCode != 0:
                continue
            if self._SCIENCE_SENSOR_PATTERN.fullmatch(event.sensor):
                science_pairs.add(pair)
            elif self._GUIDER_SENSOR_PATTERN.fullmatch(event.sensor):
                guider_pairs.add(pair)
            elif self._WFS_SENSOR_PATTERN.fullmatch(event.sensor):
                wfs_pairs.add(pair)

        return science_pairs, guider_pairs, wfs_pairs
