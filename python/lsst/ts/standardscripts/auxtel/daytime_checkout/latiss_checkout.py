# This file is part of ts_standardscripts
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

__all__ = ["LatissCheckout"]

import asyncio

from lsst.ts import salobj
from lsst.ts.observatory.control.auxtel.latiss import LATISS, LATISSUsages
from ...utils import get_topic_time_utc

STD_TIMEOUT = 10  # seconds


class LatissCheckout(salobj.BaseScript):
    """DayTime LATISS Checkout SAL Script.

    This script performs the daytime checkout of
    LATISS to ensure it is ready to be released
    for nighttime operations

    Parameters
    ----------
    index : `int`
        Index of Script SAL component.

    Notes
    -----
    **Checkpoints**

    - "Bias Frame Verification": Before taking bias frame.
    - "Engineering Frame Verification": Before taking engineering frame. Final
    checkpoint in script.

    **Details**

    This script is used to perform the daytime checkout of LATISS to ensure it
    is ready for nighttime operations. It does not include telescope or dome
    motion. It will enable LATISS, take a bias and an engineering frame, and
    check that both frames were successfully ingested by OODS.
    """

    def __init__(self, index=1, add_remotes: bool = True):

        super().__init__(
            index=index,
            descr="Execute daytime checkout of LATISS.",
        )

        latiss_usage = None if add_remotes else LATISSUsages.DryTest

        # Instantiate latiss. We need to do this after the call to
        # super().__init__() above. We can also pass in the script domain and
        # logger to both classes so log messages generated internally are
        # published to the efd.
        self.latiss = LATISS(
            domain=self.domain, intended_usage=latiss_usage, log=self.log
        )

    @classmethod
    def get_schema(cls):
        return None

    async def configure(self, config):
        # This script does not require any configuration
        pass

    def set_metadata(self, metadata):
        """Set estimated duration of the script."""

        metadata.duration = 5.0 * 60  # Approximate 5min to completion.

    async def run(self):

        await self.assert_feasibility()

        # Bias Verification, start with checkpoint for observer
        await self.checkpoint("Bias Frame Verification")

        self.latiss.rem.atoods.evt_imageInOODS.flush()
        await self.latiss.take_bias(nbias=1)
        try:
            ingest_event = await self.latiss.rem.atoods.evt_imageInOODS.next(
                flush=False, timeout=STD_TIMEOUT
            )
        except asyncio.TimeoutError:
            raise RuntimeError(
                "Timeout waiting for imageInOODS event for bias frame. This "
                "usually means there is a problem with the image ingestion."
            )

        assert ingest_event.statusCode == 0, "Bias image ingestion was not successful!"

        ingest_event_time = get_topic_time_utc(ingest_event)
        self.log.info(
            f"The last ingested image was {ingest_event.obsid} at {ingest_event_time} UT"
        )

        # Engineering test frame verification
        await self.checkpoint("Engineering Frame Verification")

        available_setup = await self.latiss.get_available_instrument_setup()
        self.log.info(
            f"The available filters are {available_setup[0]} and gratings are {available_setup[1]} "
        )

        self.latiss.rem.atoods.evt_imageInOODS.flush()
        await self.latiss.take_engtest(2, filter=0, grating=0)
        try:
            ingest_event = await self.latiss.rem.atoods.evt_imageInOODS.next(
                flush=False, timeout=STD_TIMEOUT
            )
        except asyncio.TimeoutError:
            raise RuntimeError(
                "Timeout waiting for imageInOODS event for eng frame. This "
                "usually means there is a problem with the image ingestion."
            )

        assert ingest_event.statusCode == 0, "Eng image ingestion was not successful!"

        ingest_event_time = get_topic_time_utc(ingest_event)
        inst_setup = await self.latiss.get_setup()
        self.log.info(
            f"The last ingested image was {ingest_event.obsid} at {ingest_event_time.utc}"
            f"UT with {inst_setup[0]} filter and {inst_setup[1]} grating "
        )

    async def assert_feasibility(self):
        """Verify that the system is in a feasible state to execute the
        script.
        """
        await self.latiss.assert_all_enabled()
