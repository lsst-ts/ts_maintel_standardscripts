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

__all__ = ["CheckActuators"]


import asyncio
import io
import os
import time

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import yaml
from astropy.time import Time, TimeDelta

try:
    from lsst_efd_client import EfdClient
except ImportError:
    import warnings

    warnings.warn("Could not import lsst_efd_client library.")

try:
    from lsst.ts.xml.tables.m1m3 import FATable
except ImportError:
    from lsst.ts.criopy.M1M3FATable import FATABLE as FATable

from lsst.ts import utils
from lsst.ts.observatory.control.maintel.mtcs import MTCS
from lsst.ts.standardscripts.base_block_script import BaseBlockScript
from lsst.ts.standardscripts.utils import get_s3_bucket
from lsst.ts.xml.enums.MTM1M3 import BumpTest, DetailedStates
from lsst.ts.xml.enums.Script import ScriptState
from lsst.ts.xml.tables.m1m3 import force_actuator_from_id

EFD_NAMES = dict(
    tucson="tucson_teststand_efd",
    base="base_efd",
    summit="summit_efd",
)


class CheckActuators(BaseBlockScript):
    """Perform a M1M3 bump test on either a selection of individual
    actuators or on all actuators.

    Parameters
    ----------
    index : `int`
        Index of Script SAL component.

    Notes
    -----

    In case of dual actuators both cylinders will be tested consecutively.
    The Script will fail if M1M3 mirror is raised.

    **Checkpoints**

    - "Running bump test on FA ID: {id}.": Check individual actuator.
    - "M1M3 bump test completed.": Check complete.

    """

    def __init__(self, index):
        super().__init__(index=index, descr="Bump Test on M1M3 Actuators")

        self.mtcs = None

        # Average duration (seconds) of a bump test on a single actuator
        self.time_one_bump = 25

        # Getting list of actuator ids from mtcs
        self.m1m3_actuator_ids = None
        self.m1m3_secondary_actuator_ids = None

        # Actuators that will be effectively tested
        self.actuators_to_test = None

        # Dictionary to capture failures with full details
        self.failures = {}  # Initialize the failures attribute

    async def assert_feasibility(self):
        """Verify that the system is in a feasible state before
        running bump test. Note that M1M3 mirror should be in lowered
        position.
        """

        for comp in self.mtcs.components_attr:
            if comp != "mtm1m3":
                self.log.debug(f"Ignoring component {comp}.")
                setattr(self.mtcs.check, comp, False)

        # Check all enabled and liveliness
        await asyncio.gather(
            self.mtcs.assert_all_enabled(),
            self.mtcs.assert_liveliness(),
        )
        # Check if m1m3 detailed state is either PARKED or PARKEDENGINEERING
        expected_states = {DetailedStates.PARKED, DetailedStates.PARKEDENGINEERING}
        try:
            await self.mtcs.assert_m1m3_detailed_state(expected_states)
        except AssertionError:
            raise RuntimeError(
                "Please park M1M3 before proceeding with the bump test. This can be done "
                "by lowering the mirror or enabling the M1M3 CSC."
            )

    @classmethod
    def get_schema(cls):
        m1m3_actuator_ids_str = ",".join([str(fa.actuator_id) for fa in FATable])

        url = "https://github.com/lsst-ts/"
        path = (
            "ts_externalscripts/blob/main/python/lsst/ts/standardscripts/"
            "maintel/m1m3/check_actuators.py"
        )
        schema_yaml = f"""
        $schema: http://json-schema.org/draft-07/schema#
        $id: {url}{path}
        title: CheckAcutators v1
        description: Configuration for Maintel bump test SAL Script.
        type: object
        properties:
            actuators:
                description: Actuators to run the bump test.
                oneOf:
                  - type: array
                    items:
                      type: number
                      enum: [{m1m3_actuator_ids_str}]
                    minItems: 1
                    uniqueItems: true
                    additionalItems: false
                  - type: string
                    enum: ["all", "last_failed"]
                default: "all"
            ignore_actuators:
                description: Actuators to ignore during the bump test.
                type: array
                items:
                    type: number
                    enum: [{m1m3_actuator_ids_str}]
                default: []
        additionalProperties: false
        """
        schema_dict = yaml.safe_load(schema_yaml)

        base_schema_dict = super().get_schema()

        for properties in base_schema_dict["properties"]:
            schema_dict["properties"][properties] = base_schema_dict["properties"][
                properties
            ]

        return schema_dict

    async def configure(self, config):
        """Configure the script.

        Parameters
        ----------
        config : `types.SimpleNamespace`
            Configuration
        """

        self.config = config

        await self.configure_tcs()

        # Get actuators to be tested.
        # (if "last_failed" is used, select all actuators for later filtering)
        self.actuators_to_test = (
            self.m1m3_actuator_ids
            if config.actuators in ["all", "last_failed"]
            else config.actuators
        )
        if config.ignore_actuators:
            self.actuators_to_test = [
                actuator_id
                for actuator_id in self.actuators_to_test
                if actuator_id not in config.ignore_actuators
            ]

        await super().configure(config=config)

    async def configure_tcs(self):
        if self.mtcs is None:
            self.mtcs = MTCS(self.domain, log=self.log)
            await self.mtcs.start_task

        # Getting list of actuator ids from mtcs
        self.m1m3_actuator_ids = self.mtcs.get_m1m3_actuator_ids()
        self.m1m3_secondary_actuator_ids = self.mtcs.get_m1m3_actuator_secondary_ids()

        self.actuators_to_test = self.m1m3_actuator_ids.copy()

    def set_metadata(self, metadata):
        """Set metadata."""

        # Getting total number of secondary actuators to be tested
        total_tested_secondary = sum(
            [
                1
                for actuator in self.actuators_to_test
                if self.has_secondary_actuator(actuator)
            ]
        )

        # Setting metadata
        metadata.duration = self.time_one_bump * (
            len(self.actuators_to_test) + total_tested_secondary
        )

    def has_secondary_actuator(self, actuator_id: int) -> bool:
        """Determines whether a given actuator has a
        secondary axis or not.
        """

        return actuator_id in self.m1m3_secondary_actuator_ids

    @staticmethod
    def _get_failed_states():
        """Determine the set of failure states based on the XML version.

        Returns
        -------
        `set`
            A set of failure states.
        """
        if hasattr(BumpTest, "FAILED"):
            # Old XML version
            return {BumpTest.FAILED}
        else:
            # New XML version with granular failure states
            return {
                BumpTest.FAILED_TIMEOUT,
                BumpTest.FAILED_TESTEDPOSITIVE_OVERSHOOT,
                BumpTest.FAILED_TESTEDPOSITIVE_UNDERSHOOT,
                BumpTest.FAILED_TESTEDNEGATIVE_OVERSHOOT,
                BumpTest.FAILED_TESTEDNEGATIVE_UNDERSHOOT,
                BumpTest.FAILED_NONTESTEDPROBLEM,
            }

    async def actuator_last_test_failed(self, actuator_id: int) -> bool:
        """Determines whether the last bump test for a given actuator failed.

        Parameters
        ----------
        actuator_id : `int`
            Actuator ID.

        Returns
        -------
        `bool`
            True if the last bump test failed, False otherwise.
        """
        primary_status, secondary_status = await self.mtcs.get_m1m3_bump_test_status(
            actuator_id
        )

        # Get the failure states
        failed_states = self._get_failed_states()

        # Check if either primary or secondary status is in the failure states
        return primary_status in failed_states or secondary_status in failed_states

    async def run_block(self):
        await self.assert_feasibility()
        start_time = time.monotonic()

        # Get M1M3 detailed state
        detailed_state = DetailedStates(
            (
                await self.mtcs.rem.mtm1m3.evt_detailedState.aget(
                    timeout=self.mtcs.fast_timeout,
                )
            ).detailedState
        )
        self.log.info(f"Current M1M3 detailed state: {detailed_state!r}.")

        # Filter actuator_to_test when the last_failed option is used
        if self.config.actuators == "last_failed":
            actuators_mask = await asyncio.gather(
                *[
                    self.actuator_last_test_failed(actuator_id)
                    for actuator_id in self.actuators_to_test
                ]
            )
            self.actuators_to_test = [
                actuator_id
                for actuator_id, mask in zip(self.actuators_to_test, actuators_mask)
                if mask
            ]
            self.log.info(
                f"Selecting actuators that failed the last bump test: {self.actuators_to_test!r}."
            )

        # Put M1M3 in engineering mode
        await self.mtcs.enter_m1m3_engineering_mode()

        # Dictionary to capture failures with full details
        self.failures = {}

        # Get the failure states
        failed_states = self._get_failed_states()

        await self.checkpoint("Running bump test.")

        actuator_bump_test_tasks = dict()

        async for actuator_type in self.mtcs.get_m1m3_actuator_to_test(
            self.actuators_to_test
        ):
            await self.mtcs.assert_all_enabled()
            actuator_id = actuator_type.actuator_id

            secondary_exist = self.has_secondary_actuator(actuator_id)

            # Get primary and secondary indexes
            primary_index = self.m1m3_actuator_ids.index(actuator_id)
            secondary_index = None
            if secondary_exist:
                secondary_index = self.m1m3_secondary_actuator_ids.index(actuator_id)

            # Run the bump test
            task = asyncio.create_task(
                self.mtcs.run_m1m3_actuator_bump_test(
                    actuator_id=actuator_id,
                    primary=True,
                    secondary=secondary_exist,
                )
            )
            actuator_bump_test_tasks[actuator_type.actuator_id] = task

            await self.mtcs.wait_m1m3_actuator_in_testing_state(actuator_type)

            currently_running_actuators = ", ".join(
                [
                    f"{actuator_id}"
                    for actuator_id in actuator_bump_test_tasks
                    if not actuator_bump_test_tasks[actuator_id].done()
                ]
            )
            await self.checkpoint(
                f"Running bump test for {currently_running_actuators}."
            )

        self.log.info("Finished scheduling all tests, waiting for them to complete.")

        running_tasks = [
            task for task in actuator_bump_test_tasks.values() if not task.done()
        ]

        for task in asyncio.as_completed(running_tasks):
            currently_running_actuators = ", ".join(
                [
                    f"{actuator_id}"
                    for actuator_id in actuator_bump_test_tasks
                    if not actuator_bump_test_tasks[actuator_id].done()
                ]
            )
            await self.checkpoint(
                f"Running bump test for {currently_running_actuators}."
            )
            try:
                await task
            except asyncio.CancelledError:
                self.log.info("Bump test task cancelled; ignoring.")
            except Exception:
                self.log.exception("Bump test task failed. Ignoring.")

        await self.checkpoint("All tasks completed; collecting results.")

        # Get bump test status after running
        status = await self.mtcs.rem.mtm1m3.evt_forceActuatorBumpTestStatus.aget(
            timeout=self.mtcs.fast_timeout
        )
        for i, actuator_id in enumerate(self.actuators_to_test):
            actuator_type = force_actuator_from_id(actuator_id)
            primary_index = actuator_type.index
            secondary_index = actuator_type.s_index
            # Getting test status
            primary_status, secondary_status = (
                await self.mtcs.get_m1m3_bump_test_status(actuator_id=actuator_id)
            )

            has_secondary_actuator = self.has_secondary_actuator(actuator_id)

            # Record failures
            primary_failure_type = (
                primary_status.name if primary_status in failed_states else None
            )
            secondary_failure_type = (
                secondary_status.name
                if has_secondary_actuator and secondary_status in failed_states
                else None
            )

            # Log status update after bump test
            secondary_status_text = (
                f" Secondary FA (Index {secondary_index}): {secondary_failure_type}."
                if secondary_failure_type is not None
                else ""
            )
            self.log.info(
                f"Bump test done for {i + 1} of {len(self.actuators_to_test)}. "
                f"FA ID {actuator_id}. Primary FA (Index {primary_index}): "
                f"{primary_failure_type}.{secondary_status_text}"
            )

            if primary_failure_type is not None or secondary_failure_type is not None:
                primary_timestamp = (
                    status.primaryTestTimestamps[primary_index]
                    if primary_index is not None
                    else None
                )
                secondary_timestamp = (
                    status.secondaryTestTimestamps[secondary_index]
                    if secondary_index is not None
                    else None
                )
                self.failures[actuator_id] = {
                    "type": actuator_type.actuator_type.name,
                    "primary_index": primary_index,
                    "secondary_index": secondary_index,
                    "primary_failure": primary_failure_type,
                    "secondary_failure": secondary_failure_type,
                    "primary_timestamp": primary_timestamp,
                    "secondary_timestamp": secondary_timestamp,
                    "orientation": actuator_type.orientation.name,
                }

        end_time = time.monotonic()
        elapsed_time = end_time - start_time

        # Final checkpoint
        await self.checkpoint(
            f"M1M3 bump test completed. It took {elapsed_time:.2f} seconds."
        )

        # Generating final report from failures
        if not self.failures:
            self.log.info("All actuators PASSED the bump test.")
        else:
            # Collect the failed actuator IDs for the header
            failed_actuators_id = list(self.failures.keys())
            for actuator_id, failed_actuator in self.failures.items():
                url = await self.plot_actuator_force(failed_actuator)
                failed_actuator["primary_plot_url"] = url["primary"]
                failed_actuator["secondary_plot_url"] = url["secondary"]

            # Create formatted output for failures
            failure_details = "\n".join(
                f"  - Actuator ID {actuator_id}: Type {failure['type']}, "
                f"Primary Index {failure['primary_index']}, Secondary Index "
                f"{failure['secondary_index']}, Primary Failure "
                f"{failure['primary_failure']}, Secondary Failure "
                f"{failure['secondary_failure']},\n"
                f"Primary Plot URL {failure['primary_plot_url']},\n"
                f"Secondry Plot URL {failure['secondary_plot_url']}"
                for actuator_id, failure in self.failures.items()
            )

            # Combine the header and the detailed report
            error_message = (
                f"Actuators {sorted(failed_actuators_id)} FAILED the bump test.\n\n"
                f"Failure Details:\n{failure_details or '  None'}"
            )

            self.log.error(error_message)
            raise RuntimeError(error_message)

    async def plot_actuator_force(self, failed_actuator) -> dict:
        client = await self.get_efd_client()
        url = {"primary": None, "secondary": None}

        if failed_actuator["primary_failure"]:
            direction = "z"
            actuator_id = failed_actuator["primary_index"]
            end_time = failed_actuator["primary_timestamp"]
            applied_forces, measured_forces = await self.get_forces_data_from_efd(
                client, "primary", actuator_id, end_time
            )
            self.log.info(
                f"Plotting applied vs measured {direction} forces for actuator {actuator_id}"
            )
            url["primary"] = await self.plot_and_save(
                actuator_id, direction, applied_forces, measured_forces
            )

        if failed_actuator["secondary_failure"]:
            actuator_id = failed_actuator["secondary_index"]
            if "Y_" in failed_actuator["orientation"]:
                direction = "y"
            elif "X_" in failed_actuator["orientation"]:
                direction = "x"
            end_time = failed_actuator["secondary_timestamp"]
            applied_forces, measured_forces = await self.get_forces_data_from_efd(
                client, "secondary", actuator_id, end_time
            )
            self.log.info(
                f"Plotting applied vs measured {direction} forces for actuator {actuator_id}"
            )
            url["secondary"] = await self.plot_and_save(
                actuator_id, direction, applied_forces, measured_forces
            )

        return url

    async def get_efd_client(self) -> str:
        """Get the EFD name.
        Returns
        -------
        EfdClient
            Client instance to query the EFD.
        Raises
        ------
        RuntimeError
            Wrong EFD name
        """
        site = os.environ.get("LSST_SITE")
        if site is None or site not in EFD_NAMES:
            message = (
                "LSST_SITE environment variable not defined"
                if site is None
                else (f"No image server url for {site=}.")
            )
            raise RuntimeError("Wrong EFD name: " + message)
        return EfdClient(EFD_NAMES[site])

    async def get_forces_data_from_efd(self, client, test_type, actuator_id, end_time):
        """Get the timestamps and forces for a given event.
        Parameters
        ----------
        client : EfdClient
            Connected EFD client.
        test_type : `str`
            Primary or secondary test.
        actuator_id : `int`
            Actuator ID.
        end_time : `float`
            Finish time for bump test according to forceActuatorBumpTestStatus.

        Returns
        -------
        applied_forces : `list`
            List of applied forces in the specified direction.
        measured_forces : `list`
            List of measured forces in the specified direction.

        Raises
        ------
        RuntimeError
            Error querying data.
        """
        end_time = Time(end_time, format="unix")
        start_time = end_time - TimeDelta(2 * self.time_one_bump, format="sec")
        query_field = f"{test_type}CylinderForces{actuator_id}"
        try:
            applied_forces = await client.select_time_series(
                topic_name="lsst.sal.MTM1M3.appliedCylinderForces",
                fields=query_field,
                end=end_time,
                start=start_time,
            )
        except Exception:
            raise RuntimeError(
                f"Error querying for {query_field} from 'lsst.sal.MTM1M3.appliedCylinderForces'"
                f" between {start_time} and {end_time}."
            )

        try:
            measured_forces = await client.select_time_series(
                topic_name="lsst.sal.MTM1M3.forceActuatorData",
                fields=query_field,
                end=end_time,
                start=start_time,
            )
        except Exception:
            raise RuntimeError(
                f"Error querying for {query_field} from 'lsst.sal.MTM1M3.forceActuatorData'"
                f" between {start_time} and {end_time}."
            )

        return applied_forces, measured_forces

    async def plot_and_save(
        self, actuator_id, direction, applied_forces, measured_forces
    ) -> str:
        """Save plot to the LFA."""
        applied_col = applied_forces.columns[0]
        measured_col = measured_forces.columns[0]
        fig, ax = plt.subplots(1, 1)
        ax.plot(
            applied_forces.index,
            applied_forces[applied_col],
            label=f"FA {actuator_id} {direction} Applied",
        )
        ax.plot(
            measured_forces.index,
            measured_forces[measured_col],
            label=f"FA {actuator_id} {direction} Measured",
        )
        ax.set_xlabel("Time (TAI)")
        ax.set_ylabel("Force (N)")
        ax.legend()
        ax.grid(True, alpha=0.3)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
        ax.xaxis.set_major_locator(mdates.SecondLocator(interval=5))

        self.log.info("Saving actuator force plot to LFA.")

        plot_output = io.BytesIO()
        fig.savefig(plot_output)
        plot_output.seek(0)

        s3bucket = get_s3_bucket()

        key = s3bucket.make_key(
            salname=self.salinfo.name,
            salindexname=self.salinfo.index,
            generator=f"actuator_id_{actuator_id}_{direction}",
            date=utils.astropy_time_from_tai_unix(utils.current_tai()),
            other=self.obs_id,
            suffix=".png",
        )

        await s3bucket.upload(fileobj=plot_output, key=key)

        url = f"{s3bucket.service_resource.meta.client.meta.endpoint_url}/{s3bucket.name}/{key}"

        await self.evt_largeFileObjectAvailable.set_write(
            id=self.obs_id,
            url=url,
            generator=f"{self.salinfo.name}:{self.salinfo.index}",
            mimeType="PNG",
            version=1,
        )

        return url

    async def cleanup(self):
        if self.state.state != ScriptState.ENDING:
            try:
                self.log.warning("M1M3 bump test stopped. Killing actuator forces.")

                await self.mtcs.stop_m1m3_bump_test()

            except Exception:
                self.log.exception("Unexpected exception in stop_m1m3_bump_test.")

        # Exiting engineering mode
        await self.mtcs.exit_m1m3_engineering_mode()
