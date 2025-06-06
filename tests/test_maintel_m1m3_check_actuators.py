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

import asyncio
import logging
import types
import unittest

from lsst.ts import salobj
from lsst.ts.maintel.standardscripts.m1m3 import CheckActuators
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages
from lsst.ts.standardscripts import BaseScriptTestCase
from lsst.ts.xml.enums.MTM1M3 import BumpTest, DetailedStates
from lsst.ts.xml.tables.m1m3 import force_actuator_from_id


class FakeBumpTestValue:
    def __init__(self, name):
        self.name = name

    def __eq__(self, other):
        # Allow comparison with other FakeBumpTestValue objects or strings.
        if isinstance(other, FakeBumpTestValue):
            return self.name == other.name
        elif isinstance(other, str):
            return self.name == other
        return False

    def __hash__(self):
        return hash(self.name)

    def __repr__(self):
        return f"<FakeBumpTestValue {self.name}>"


class TestCheckActuators(BaseScriptTestCase, unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.log = logging.getLogger(cls.__name__)

    async def basic_make_script(self, index):
        """Create a mocked script instance."""
        self.script = CheckActuators(index=index)

        self.script.mtcs = MTCS(
            self.script.domain, intended_usage=MTCSUsages.DryTest, log=self.script.log
        )
        await self.script.configure_tcs()
        self.script.mtcs.run_m1m3_actuator_bump_test = unittest.mock.AsyncMock(
            side_effect=self.mock_test_bump
        )
        self.script.mtcs.stop_m1m3_bump_test = unittest.mock.AsyncMock()
        self.script.mtcs.enter_m1m3_engineering_mode = unittest.mock.AsyncMock()
        self.script.mtcs.exit_m1m3_engineering_mode = unittest.mock.AsyncMock()
        self.script.mtcs.assert_liveliness = unittest.mock.AsyncMock()
        self.script.mtcs.assert_all_enabled = unittest.mock.AsyncMock()
        self.script.mtcs.assert_m1m3_detailed_state = unittest.mock.AsyncMock()
        self.script.mtcs.wait_m1m3_actuator_in_testing_state = unittest.mock.AsyncMock()

        self.script.mtcs.get_m1m3_bump_test_status = unittest.mock.AsyncMock(
            side_effect=self.mock_get_m1m3_bump_test_status
        )

        self.script.mtcs.rem.mtm1m3 = unittest.mock.AsyncMock()
        self.script.mtcs.rem.mtm1m3.configure_mock(
            **{
                "evt_detailedState.aget": self.get_m1m3_detailed_state,
            }
        )
        self.script.mtcs.get_m1m3_actuator_to_test = self.get_m1m3_actuator_to_test

        self.bump_test_status = types.SimpleNamespace(
            testState=[BumpTest.NOTTESTED] * len(self.script.m1m3_actuator_ids)
        )

        self.failed_primary_test = set()
        self.failed_secondary_test = set()

        return (self.script,)

    async def get_m1m3_detailed_state(self, *args, **kwags):
        return types.SimpleNamespace(detailedState=DetailedStates.PARKED)

    async def get_m1m3_actuator_to_test(self, actuators_to_test):
        for actuator in actuators_to_test:
            yield force_actuator_from_id(actuator)
            await asyncio.sleep(0.5)

    # Side effects
    async def mock_test_bump(self, actuator_id, primary, secondary):
        """Mock the bump test with simulated failure states.

        Simulates failures dynamically based on the failed sets.
        """
        await asyncio.sleep(0.5)
        actuator_index = self.script.mtcs.get_m1m3_actuator_index(actuator_id)

        # Determine failure states dynamically
        failed_states = self.script._get_failed_states()

        # Check if the actuator is in the failed sets
        if (
            actuator_id in self.failed_primary_test
            or actuator_id in self.failed_secondary_test
        ):
            # Use the first failure state for simplicity
            self.bump_test_status.testState[actuator_index] = next(iter(failed_states))
            raise RuntimeError(f"Actuator {actuator_id} bump test failed.")
        else:
            self.bump_test_status.testState[actuator_index] = BumpTest.PASSED

    async def mock_get_m1m3_bump_test_status(self, actuator_id):
        """Mock the bump test status with simulated failure states.

        Returns primary and secondary statuses dynamically.
        """
        # Determine failure states dynamically
        failed_states = self.script._get_failed_states()

        # Determine primary and secondary test statuses
        primary_test_status = (
            next(iter(failed_states))
            if actuator_id in self.failed_primary_test
            else BumpTest.PASSED
        )
        secondary_test_status = (
            next(iter(failed_states))
            if actuator_id in self.failed_secondary_test
            else BumpTest.PASSED
        )

        return primary_test_status, secondary_test_status

    async def mock_test_bump_new_xml(self, actuator_id, primary, secondary):
        """New mock bump test for new XML (granular failures).

        Simulates a bump test that uses granular failure codes.
        """
        await asyncio.sleep(0.5)
        actuator_index = self.script.mtcs.get_m1m3_actuator_index(actuator_id)
        # If either failure is expected for this actuator, simulate failure.
        if (
            actuator_id in self.failed_primary_test_new
            or actuator_id in self.failed_secondary_test_new
        ):
            if actuator_id in self.failed_primary_test_new:
                self.bump_test_status.testState[actuator_index] = (
                    BumpTest.FAILED_TESTEDPOSITIVE_OVERSHOOT
                )
            else:
                self.bump_test_status.testState[actuator_index] = BumpTest.PASSED
            raise RuntimeError(f"Actuator {actuator_id} bump test failed.")
        else:
            self.bump_test_status.testState[actuator_index] = BumpTest.PASSED

    async def mock_get_m1m3_bump_test_status_new_xml(self, actuator_id):
        """New mock get_bump_test_status for new XML (granular failures).

        Returns granular failure statuses for primary and secondary.
        """
        primary_status = (
            BumpTest.FAILED_TESTEDPOSITIVE_OVERSHOOT
            if actuator_id in self.failed_primary_test_new
            else BumpTest.PASSED
        )
        secondary_status = (
            BumpTest.FAILED_TESTEDNEGATIVE_OVERSHOOT
            if actuator_id in self.failed_secondary_test_new
            else BumpTest.PASSED
        )
        return (primary_status, secondary_status)

    @classmethod
    def patch_bump_test_for_new_xml(cls):
        """Patch the BumpTest enum to add granular failure values.

        Adds granular failure values if they don't exist.
        """
        if not hasattr(BumpTest, "FAILED_TESTEDPOSITIVE_OVERSHOOT"):
            BumpTest.FAILED_TESTEDPOSITIVE_OVERSHOOT = FakeBumpTestValue(
                "FAILED_TESTEDPOSITIVE_OVERSHOOT"
            )
        if not hasattr(BumpTest, "FAILED_TESTEDNEGATIVE_OVERSHOOT"):
            BumpTest.FAILED_TESTEDNEGATIVE_OVERSHOOT = FakeBumpTestValue(
                "FAILED_TESTEDNEGATIVE_OVERSHOOT"
            )

    @classmethod
    def patch_bump_test_for_old_xml(cls):
        """Patch the BumpTest enum to add the old XML failure value.

        Adds the old XML failure value if it doesn't exist.
        """
        if not hasattr(BumpTest, "FAILED"):
            BumpTest.FAILED = FakeBumpTestValue("FAILED")

    async def test_configure_all(self):
        """Testing a valid configuration: all actuators"""

        # Configure with "all" actuators
        async with self.make_script():
            actuators = "all"

            await self.configure_script(actuators=actuators)

            assert self.script.actuators_to_test == self.script.m1m3_actuator_ids
            assert self.script.program is None
            assert self.script.reason is None
            assert self.script.checkpoint_message is None

    async def test_configure_last_failed(self):
        """Testing a valid configuration: last failed actuators"""

        # Configure with "last_failed" actuators
        async with self.make_script():
            actuators = "last_failed"

            await self.configure_script(actuators=actuators)

            # At configuration stage all actuators are selected
            # for later filtering
            assert self.script.actuators_to_test == self.script.m1m3_actuator_ids
            assert self.script.program is None
            assert self.script.reason is None
            assert self.script.checkpoint_message is None

    async def test_configure_valid_ids(self):
        """Testing a valid configuration: valid actuators ids"""

        # Try configure with a list of valid actuators ids
        async with self.make_script():
            actuators = [101, 210, 301, 410]

            await self.configure_script(
                actuators=actuators,
            )

            assert self.script.actuators_to_test == actuators
            assert self.script.program is None
            assert self.script.reason is None
            assert self.script.checkpoint_message is None

    async def test_configure_bad(self):
        """Testing an invalid configuration: bad actuators ids"""

        async with self.make_script():
            # Invalid actuators: 501 and 505
            actuators = [501, 505]

            # If actuators_bad_ids is not empty, it should raise a ValueError
            actuators_bad_ids = [
                actuator
                for actuator in actuators
                if actuator not in self.script.m1m3_actuator_ids
            ]
            if actuators_bad_ids:
                with self.assertRaises(salobj.ExpectedError):
                    await self.configure_script(
                        actuators=actuators_bad_ids,
                    )

    @unittest.mock.patch(
        "lsst.ts.standardscripts.BaseBlockScript.obs_id", "202306060001"
    )
    async def test_configure_with_program_reason(self):
        """Testing a valid configuration: with program and reason"""

        # Try configure with a list of valid actuators ids
        async with self.make_script():
            self.script.get_obs_id = unittest.mock.AsyncMock(
                side_effect=["202306060001"]
            )
            await self.configure_script(
                program="BLOCK-123",
                reason="SITCOM-321",
            )

            assert self.script.program == "BLOCK-123"
            assert self.script.reason == "SITCOM-321"
            assert (
                self.script.checkpoint_message
                == "CheckActuators BLOCK-123 202306060001 SITCOM-321"
            )

    async def test_run_all_pass(self):
        """Test the script with all actuators and a specific list.
        All actuators pass.
        """
        # Subtest for all actuators
        async with self.make_script():
            with self.subTest("all actuators"):
                actuators = "all"
                await self.configure_script(actuators=actuators)

                # Run the script
                await self.run_script()

                # Assert all passed on mocked bump test. Had to get indexes.
                actuators_to_test_index = [
                    self.script.mtcs.get_m1m3_actuator_index(actuator_id)
                    for actuator_id in self.script.actuators_to_test
                ]
                assert all(
                    self.bump_test_status.testState[actuator_index] == BumpTest.PASSED
                    for actuator_index in actuators_to_test_index
                )
                # Expected await count for assert_all_enabled method
                expected_awaits = len(self.script.actuators_to_test) + 1

                # Assert we await once for all mock methods defined above
                self.script.mtcs.enter_m1m3_engineering_mode.assert_awaited_once()
                self.script.mtcs.exit_m1m3_engineering_mode.assert_awaited_once()
                self.script.mtcs.assert_liveliness.assert_awaited_once()
                self.script.mtcs.assert_m1m3_detailed_state.assert_awaited_once()
                assert (
                    self.script.mtcs.assert_all_enabled.await_count == expected_awaits
                )

                # Assert expected calls to run_m1m3_actuator_bump_test
                expected_calls = [
                    unittest.mock.call(
                        actuator_id=actuator_id,
                        primary=True,
                        secondary=self.script.has_secondary_actuator(actuator_id),
                    )
                    for actuator_id in self.script.actuators_to_test
                ]
                self.script.mtcs.run_m1m3_actuator_bump_test.assert_has_calls(
                    expected_calls
                )

        # Subtest for a specific list of actuators
        async with self.make_script():
            with self.subTest("list of actuators"):
                actuators = [101, 210, 301, 410]
                await self.configure_script(actuators=actuators)

                # Run the script
                await self.run_script()

                # Assert all passed on mocked bump test. Had to get indexes.
                actuators_to_test_index = [
                    self.script.mtcs.get_m1m3_actuator_index(actuator_id)
                    for actuator_id in self.script.actuators_to_test
                ]
                assert all(
                    self.bump_test_status.testState[actuator_index] == BumpTest.PASSED
                    for actuator_index in actuators_to_test_index
                )
                # Expected await count for assert_all_enabled method
                expected_awaits = len(self.script.actuators_to_test) + 1

                # Assert we await once for all mock methods defined above
                self.script.mtcs.enter_m1m3_engineering_mode.assert_awaited_once()
                self.script.mtcs.exit_m1m3_engineering_mode.assert_awaited_once()
                self.script.mtcs.assert_liveliness.assert_awaited_once()
                self.script.mtcs.assert_m1m3_detailed_state.assert_awaited_once()
                assert (
                    self.script.mtcs.assert_all_enabled.await_count == expected_awaits
                )

                # Assert expected calls to run_m1m3_actuator_bump_test
                expected_calls = [
                    unittest.mock.call(
                        actuator_id=actuator_id,
                        primary=True,
                        secondary=self.script.has_secondary_actuator(actuator_id),
                    )
                    for actuator_id in self.script.actuators_to_test
                ]
                self.script.mtcs.run_m1m3_actuator_bump_test.assert_has_calls(
                    expected_calls
                )

    async def test_run_with_failed_actuators_old_xml(self):
        """Test the script with actuators that fail the bump test.

        Uses old XML enums for failure states.
        """
        # Patch the old XML failure value
        self.patch_bump_test_for_old_xml()

        async with self.make_script():
            actuators = "all"
            await self.configure_script(actuators=actuators)
            self.failed_primary_test = {101, 218, 220}
            self.failed_secondary_test = {220, 330}

            # Mock _get_failed_states to simulate the old XML version
            self.script._get_failed_states = unittest.mock.Mock(
                return_value={BumpTest.FAILED}
            )

            # Run the script
            with self.assertRaises(AssertionError, msg="FAILED the bump test"):
                await self.run_script()

            # Verify the failures dictionary
            expected_failures = {
                101: {
                    "type": "SAA",
                    "primary_index": self.script.m1m3_actuator_ids.index(101),
                    "secondary_index": None,
                    "primary_failure": "FAILED",  # Old XML failure
                    "secondary_failure": None,
                },
                218: {
                    "type": "DAA",
                    "primary_index": self.script.m1m3_actuator_ids.index(218),
                    "secondary_index": self.script.m1m3_secondary_actuator_ids.index(
                        218
                    ),
                    "primary_failure": "FAILED",  # Old XML failure
                    "secondary_failure": None,
                },
                220: {
                    "type": "DAA",
                    "primary_index": self.script.m1m3_actuator_ids.index(220),
                    "secondary_index": self.script.m1m3_secondary_actuator_ids.index(
                        220
                    ),
                    "primary_failure": "FAILED",  # Old XML failure
                    "secondary_failure": "FAILED",  # Old XML failure
                },
                330: {
                    "type": "DAA",
                    "primary_index": self.script.m1m3_actuator_ids.index(330),
                    "secondary_index": self.script.m1m3_secondary_actuator_ids.index(
                        330
                    ),
                    "primary_failure": None,
                    "secondary_failure": "FAILED",  # Old XML failure
                },
            }
            assert self.script.failures == expected_failures

            # Additional asserts (same as for new_xml)
            self.script.mtcs.enter_m1m3_engineering_mode.assert_awaited_once()
            self.script.mtcs.exit_m1m3_engineering_mode.assert_awaited_once()
            self.script.mtcs.assert_liveliness.assert_awaited_once()
            self.script.mtcs.assert_m1m3_detailed_state.assert_awaited_once()
            assert (
                self.script.mtcs.assert_all_enabled.await_count
                == len(self.script.actuators_to_test) + 1
            )

            # Assert expected calls to run_m1m3_actuator_bump_test
            expected_calls = [
                unittest.mock.call(
                    actuator_id=actuator_id,
                    primary=True,
                    secondary=self.script.has_secondary_actuator(actuator_id),
                )
                for actuator_id in self.script.actuators_to_test
            ]
            self.script.mtcs.run_m1m3_actuator_bump_test.assert_has_calls(
                expected_calls
            )

    async def test_run_with_failed_actuators_new_xml(self):
        """Test the script with actuators that fail the bump test.

        Uses new XML enums for granular failure states.
        """
        # Patch granular values if needed.
        self.patch_bump_test_for_new_xml()

        async with self.make_script():
            actuators = "all"
            await self.configure_script(actuators=actuators)

            # Define new failure sets for granular failures
            self.failed_primary_test_new = {101, 218, 220}
            self.failed_secondary_test_new = {220, 330}

            # Override the bump test mocks with the new XML versions.
            self.script.mtcs.run_m1m3_actuator_bump_test = unittest.mock.AsyncMock(
                side_effect=self.mock_test_bump_new_xml
            )
            self.script.mtcs.get_m1m3_bump_test_status = unittest.mock.AsyncMock(
                side_effect=self.mock_get_m1m3_bump_test_status_new_xml
            )

            # Override _get_failed_states
            self.script._get_failed_states = lambda: {
                BumpTest.FAILED_TESTEDPOSITIVE_OVERSHOOT,
                BumpTest.FAILED_TESTEDNEGATIVE_OVERSHOOT,
            }

            # Record failures and eventually raise a RuntimeError.
            with self.assertRaises(AssertionError, msg="FAILED the bump test"):
                await self.run_script()

            expected_failures = {
                101: {
                    "type": "SAA",
                    "primary_index": self.script.m1m3_actuator_ids.index(101),
                    "secondary_index": None,
                    "primary_failure": "FAILED_TESTEDPOSITIVE_OVERSHOOT",
                    "secondary_failure": None,
                },
                218: {
                    "type": "DAA",
                    "primary_index": self.script.m1m3_actuator_ids.index(218),
                    "secondary_index": self.script.m1m3_secondary_actuator_ids.index(
                        218
                    ),
                    "primary_failure": "FAILED_TESTEDPOSITIVE_OVERSHOOT",
                    "secondary_failure": None,
                },
                220: {
                    "type": "DAA",
                    "primary_index": self.script.m1m3_actuator_ids.index(220),
                    "secondary_index": self.script.m1m3_secondary_actuator_ids.index(
                        220
                    ),
                    "primary_failure": "FAILED_TESTEDPOSITIVE_OVERSHOOT",
                    "secondary_failure": "FAILED_TESTEDNEGATIVE_OVERSHOOT",
                },
                330: {
                    "type": "DAA",
                    "primary_index": self.script.m1m3_actuator_ids.index(330),
                    "secondary_index": self.script.m1m3_secondary_actuator_ids.index(
                        330
                    ),
                    "primary_failure": None,
                    "secondary_failure": "FAILED_TESTEDNEGATIVE_OVERSHOOT",
                },
            }

            # Convert recorded failures to a comparable dictionary
            actual_failures = {}
            for actuator_id, details in self.script.failures.items():
                actual_failures[actuator_id] = {
                    "type": details["type"],
                    "primary_index": details["primary_index"],
                    "secondary_index": details["secondary_index"],
                    "primary_failure": (
                        details["primary_failure"]
                        if details["primary_failure"] is not None
                        else None
                    ),
                    "secondary_failure": (
                        details["secondary_failure"]
                        if details["secondary_failure"] is not None
                        else None
                    ),
                }

            assert actual_failures == expected_failures

            # Additional assertions about awaited calls, etc.
            self.script.mtcs.enter_m1m3_engineering_mode.assert_awaited_once()
            self.script.mtcs.exit_m1m3_engineering_mode.assert_awaited_once()
            self.script.mtcs.assert_liveliness.assert_awaited_once()
            self.script.mtcs.assert_m1m3_detailed_state.assert_awaited_once()
            expected_awaits = len(self.script.actuators_to_test) + 1
            assert self.script.mtcs.assert_all_enabled.await_count == expected_awaits

            expected_calls = [
                unittest.mock.call(
                    actuator_id=actuator_id,
                    primary=True,
                    secondary=self.script.has_secondary_actuator(actuator_id),
                )
                for actuator_id in self.script.actuators_to_test
            ]
            self.script.mtcs.run_m1m3_actuator_bump_test.assert_has_calls(
                expected_calls
            )

    async def test_run_last_failed_actuators(self):
        """Test the script with the 'last_failed' configuration.

        Verifies that only the last failed actuators are tested.
        """
        # Patch granular values if needed
        self.patch_bump_test_for_new_xml()

        async with self.make_script():
            await self.configure_script(actuators="last_failed")

            # Define new failure sets for granular failures
            self.failed_primary_test_new = {101, 218, 220}
            self.failed_secondary_test_new = {220, 330}

            # Override the bump test mocks with the new XML versions
            self.script.mtcs.run_m1m3_actuator_bump_test = unittest.mock.AsyncMock(
                side_effect=self.mock_test_bump_new_xml
            )
            self.script.mtcs.get_m1m3_bump_test_status = unittest.mock.AsyncMock(
                side_effect=self.mock_get_m1m3_bump_test_status_new_xml
            )

            # Override _get_failed_states
            self.script._get_failed_states = lambda: {
                BumpTest.FAILED_TESTEDPOSITIVE_OVERSHOOT,
                BumpTest.FAILED_TESTEDNEGATIVE_OVERSHOOT,
            }

            # Expected actuators to test
            expected_to_test = (
                self.failed_primary_test_new | self.failed_secondary_test_new
            )

            # Run the script and expect failure
            with self.assertRaises(AssertionError, msg="FAILED the bump test"):
                await self.run_script()

            # Verify that only the last failed actuators were tested
            tested_actuators = set(self.script.failures.keys())
            assert tested_actuators == expected_to_test

            # Verify the failures dictionary
            expected_failures = {
                101: {
                    "type": "SAA",
                    "primary_index": self.script.m1m3_actuator_ids.index(101),
                    "secondary_index": None,
                    "primary_failure": "FAILED_TESTEDPOSITIVE_OVERSHOOT",
                    "secondary_failure": None,
                },
                218: {
                    "type": "DAA",
                    "primary_index": self.script.m1m3_actuator_ids.index(218),
                    "secondary_index": self.script.m1m3_secondary_actuator_ids.index(
                        218
                    ),
                    "primary_failure": "FAILED_TESTEDPOSITIVE_OVERSHOOT",
                    "secondary_failure": None,
                },
                220: {
                    "type": "DAA",
                    "primary_index": self.script.m1m3_actuator_ids.index(220),
                    "secondary_index": self.script.m1m3_secondary_actuator_ids.index(
                        220
                    ),
                    "primary_failure": "FAILED_TESTEDPOSITIVE_OVERSHOOT",
                    "secondary_failure": "FAILED_TESTEDNEGATIVE_OVERSHOOT",
                },
                330: {
                    "type": "DAA",
                    "primary_index": self.script.m1m3_actuator_ids.index(330),
                    "secondary_index": self.script.m1m3_secondary_actuator_ids.index(
                        330
                    ),
                    "primary_failure": None,
                    "secondary_failure": "FAILED_TESTEDNEGATIVE_OVERSHOOT",
                },
            }
            assert self.script.failures == expected_failures

            # Verify engineering mode and liveliness checks
            self.script.mtcs.enter_m1m3_engineering_mode.assert_awaited_once()
            self.script.mtcs.exit_m1m3_engineering_mode.assert_awaited_once()
            self.script.mtcs.assert_liveliness.assert_awaited_once()
            self.script.mtcs.assert_m1m3_detailed_state.assert_awaited_once()
            expected_awaits = len(self.script.actuators_to_test) + 1
            assert self.script.mtcs.assert_all_enabled.await_count == expected_awaits

            # Check that the last failed actuators were tested
            expected_calls = [
                unittest.mock.call(
                    actuator_id=actuator_id,
                    primary=True,
                    secondary=self.script.has_secondary_actuator(actuator_id),
                )
                for actuator_id in expected_to_test
            ]
            self.script.mtcs.run_m1m3_actuator_bump_test.assert_has_calls(
                expected_calls
            )

            # Check that no other actuators were tested
            not_expected_to_test_indexes = [
                self.script.mtcs.get_m1m3_actuator_index(actuator_id)
                for actuator_id in self.script.m1m3_actuator_ids
                if actuator_id not in expected_to_test
            ]
            assert all(
                self.bump_test_status.testState[actuator_index] == BumpTest.NOTTESTED
                for actuator_index in not_expected_to_test_indexes
            )
