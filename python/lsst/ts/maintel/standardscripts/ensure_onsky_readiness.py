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

__all__ = ["EnsureOnSkyReadiness"]

import yaml
from lsst.ts import salobj
from lsst.ts.observatory.control.maintel.lsstcam import LSSTCam, LSSTCamUsages
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages
from lsst.ts.xml.enums import MTAOS, MTM1M3, MTDome


class EnsureOnSkyReadiness(salobj.BaseScript):
    """
    Ensure On Sky Readiness.

    This script performs a sequence of checks and actions to ensure the
    telescope and associated systems are ready for on-sky operations.
    The main steps executed by this script are:

    1. Ensure that all MTCS and Camera components are enabled.
    2. Ensure that the OCPS:101 CSC is enabled.
    3. Assert that the dome shutters are open.
    4. Ensure the M2 force balance system is enabled.
    5. Ensure MTM1M3 is raised at a safe elevation (with retry logic).
    6. Assert M1M3 force balance system is enabled.
    7. Assert M1M3 slew controller flags are enabled (warning if not).
    8. Ensure the MTMount is homed.
    9. Ensure the M1M3 Mirror Covers are open.
    10. Ensure Camera Cable Wrap (CCW) following is enabled.
    11. Ensure Compensation Mode is enabled for both Hexapods.
    12. Ensure the Dome is unparked.
    13. Ensure Dome Following Mode is enabled.
    14. Assert that the AOS (Active Optics System) Closed Loop is enabled.
    15. Ensure M1M3 is not in engineering mode.
    16. Assert that the MTM1M3TS is not in engineering mode.

    At each step, the script logs progress, checks system states, and takes
    corrective actions or raises warnings/errors as appropriate. If dome and
    aos closed loop states are not as expected, it collects the errors and
    raises an `AssertionError` at the end of the script run, summarizing
    issues encountered.

    Note: This script is not a complete end-to-end preparation for on-sky
    operations. It is a readiness check script that ensures the necessary
    systems are in place and configured correctly before on-sky operations
    are performed.
    """

    def __init__(self, index):
        super().__init__(index=index, descr="Ensure On Sky Readiness.")

        self.mtcs = None
        self.lsstcam = None
        self.ocps = None
        self.mtm1m3ts = None
        self.assertion_errors = []

        self.tel_raise_m1m3_min_el = 20.0
        self.home_both_axes_timeout = 300.0
        self.homing_attempts = 10

    async def configure_tcs(self) -> None:
        """Initialize MTCS if not already initialized."""
        if self.mtcs is None:
            self.log.debug("Creating MTCS instance.")
            self.mtcs = MTCS(
                domain=self.domain, log=self.log, intended_usage=MTCSUsages.All
            )
            await self.mtcs.start_task
        else:
            self.log.debug("MTCS already initialized.")

    async def configure_camera(self) -> None:
        """Initialize LSST Camera if not already initialized."""
        if self.lsstcam is None:
            self.log.debug("Creating LSST Camera instance.")
            self.lsstcam = LSSTCam(
                domain=self.domain,
                intended_usage=LSSTCamUsages.StateTransition,
                log=self.log,
            )
            await self.lsstcam.start_task
        else:
            self.log.debug("LSST Camera already initialized.")

    async def configure_ocps(self):
        """Configure OCPS if not already configured."""
        if self.ocps is None:
            self.log.debug("Creating OCPS instance.")
            self.ocps = salobj.Remote(self.domain, "OCPS", index=101)
            await self.ocps.start_task
        else:
            self.log.debug("OCPS already initialized.")

    async def configure_mtm1m3ts(self):
        """Configure MTM1M3TS remote if not already configured."""
        if self.mtm1m3ts is None:
            self.log.debug("Creating MTM1M3TS remote instance.")
            self.mtm1m3ts = salobj.Remote(self.domain, "MTM1M3TS")
            await self.mtm1m3ts.start_task
        else:
            self.log.debug("MTM1M3TS already initialized.")

    @classmethod
    def get_schema(cls):
        schema_yaml = """
        $schema: http://json-schema.org/draft-07/schema#
        $id: https://github.com/lsst-ts/ts_maintel_standardscripts/ensure_onsky_readiness.yaml
        title: EnsureOnSkyReadiness v1
        description: Configuration for EnsureOnSkyReadiness script.
        type: object
        properties:
          slew_flags:
            description: >-
              (Deprecated - RSO-592) List of M1M3 slew controller flags to change
              or "default" for a predefined combination of flags. This property is
              deprecated and will be removed in a future release. The slew controller
              flags are now automatically enabled at the CSC level when the mirror
              is raised.
            oneOf:
              - type: string
                enum: ["default"]
              - type: array
                items:
                  type: string
                  enum: ["ACCELERATIONFORCES", "BALANCEFORCES", "VELOCITYFORCES", "BOOSTERVALVES"]
            default: "default"
          enable_flags:
            description: >-
              (Deprecated - RSO-592) Corresponding booleans to enable or disable
              each slew flag. This property is deprecated and will be removed in
              a future release. The slew controller flags are now automatically
              enabled at the CSC level when the mirror is raised.
            type: array
            items:
              type: boolean
          homing_attempts:
            description: Number of attempts to home both axes.
            type: integer
            default: 10
            minimum: 1
        additionalProperties: false
        """
        return yaml.safe_load(schema_yaml)

    async def configure(self, config):
        """Configure the script.

        Parameters
        ----------
        config : types.SimpleNamespace
            Configuration namespace.
        """
        self.config = config

        if hasattr(config, "slew_flags") or hasattr(config, "enable_flags"):
            self.log.warning(
                "The 'slew_flags' and 'enable_flags' configuration properties are "
                "deprecated (RSO-592) and will be removed in a future release. "
                "The slew controller flags are now automatically enabled at the CSC "
                "level when the mirror is raised.",
                stacklevel=2,
                exc_info=DeprecationWarning(),
            )

        await self.configure_tcs()
        await self.configure_camera()
        await self.configure_ocps()
        await self.configure_mtm1m3ts()

        if hasattr(config, "homing_attempts"):
            self.homing_attempts = config.homing_attempts

    def set_metadata(self, metadata):
        metadata.duration = 300

    async def _is_mtmount_homed(self) -> bool:
        """
        Check if both axes of the MTMount are homed.

        Returns
        -------
        bool
            True if both axes are homed, False otherwise.

        Raises
        ------
        Exception
            If any error occurs while checking the homed state.
        """
        try:
            az_homed = (
                await self.mtcs.rem.mtmount.evt_azimuthHomed.aget(
                    timeout=self.mtcs.fast_timeout
                )
            ).homed
            el_homed = (
                await self.mtcs.rem.mtmount.evt_elevationHomed.aget(
                    timeout=self.mtcs.fast_timeout
                )
            ).homed

            self.log.debug(f"Azimuth homed: {az_homed}, Elevation homed: {el_homed}")
            return az_homed and el_homed
        except Exception as e:
            self.log.error(f"Error while checking MTMount home status: {e}")
            raise

    async def ensure_group_all_enabled(self, group, group_name):
        """Ensure all components in the group are enabled."""
        try:
            self.log.info(f"Ensuring all {group_name} components are enabled.")
            await group.assert_all_enabled()
        except AssertionError as e:
            self.log.warning(
                f"Some {group_name} CSCs are not enabled. {e}"
                f"Enabling all {group_name} components."
            )
            await group.enable()
        except Exception as e:
            self.log.error(f"Unexpected error while checking {group_name}: {e}")
            raise

    async def ensure_ocps_enabled(self) -> None:
        """Ensure the OCPS:101 CSC is enabled.

        This method checks the current summary state of the OCPS:101
        remote. If it is already in ENABLED state, no action is taken.
        If it is not enabled, it attempts to transition it to ENABLED.
        """
        self.log.info("Ensuring OCPS:101 is enabled.")

        summary_state = (
            await self.ocps.evt_summaryState.aget(timeout=self.mtcs.fast_timeout)
        ).summaryState

        current_state = salobj.State(summary_state)

        if current_state == salobj.State.ENABLED:
            self.log.info("OCPS:101 is already enabled.")
        else:
            self.log.warning(
                f"OCPS:101 is not enabled (current state: {current_state!r}). "
                "Attempting to enable."
            )
            await salobj.set_summary_state(self.ocps, salobj.State.ENABLED)
            self.log.info("OCPS:101 has been enabled.")

    async def assert_dome_shutter_opened(self) -> None:
        """Assert that dome shutters are opened.

        This method checks the current state of the dome shutters. If they
        are not open, it logs a warning and stores the error to be raised
        at the end of the script.
        """
        self.log.info("Assert that dome shutters are opened.")

        try:
            self.mtcs.rem.mtdome.evt_shutterMotion.flush()
            shutter_state = await self.mtcs.rem.mtdome.evt_shutterMotion.aget(
                timeout=self.mtcs.fast_timeout
            )
            shutter_state.state = [
                MTDome.MotionState(value) for value in shutter_state.state
            ]
            self.log.info(f"Dome shutter state: {shutter_state.state}.")

            expected_states = [MTDome.MotionState.OPEN, MTDome.MotionState.OPEN]
            if shutter_state.state == expected_states:
                self.log.info("Dome shutters are already open.")
            else:
                raise RuntimeError(
                    "Dome shutters are not open.\n"
                    f"Reported state: {shutter_state.state}.\n"
                    f"Expected state: {expected_states}.\n"
                    "Please check and open the dome shutters."
                )
        except Exception as e:
            self.log.warning(f"Dome shutter assertion failed: {e}")
            self.assertion_errors.append(e)

    async def ensure_m2_balance_system_enabled(self):
        """Ensure the M2 force balance system is enabled.

        This method calls MTCS.enable_m2_balance_system(), which:
        - Checks the current status of the M2 force balance system.
        - If the system is not enabled, sends the command to enable it.
        - Waits for the system status to update to enabled.
        - Logs progress and status.
        - If the system is already enabled, no action is taken.

        This ensures that the M2 force balance system is ready for
        on-sky operations.
        """
        self.log.info("Ensuring M2 force balance system is enabled.")
        await self.mtcs.enable_m2_balance_system()

    async def ensure_m1m3_raised_at_safe_elevation(self) -> None:
        """
        Ensure M1M3 is safely raised if needed.

        This method checks that the telescope elevation is at or above
        `self.tel_raise_m1m3_min_el` before allowing MTM1M3 to be raised.
        It then checks the current M1M3 detailed state:

        - If in FAULT, raises an error.
        - If in ACTIVE or ACTIVEENGINEERING, does nothing (already raised).
        - If in PARKED or PARKEDENGINEERING, issues the raise command.
        - If in any other state, raises an error.

        Raises
        ------
        RuntimeError
            If the elevation is not safe, or if M1M3 is in a FAULT or
            unexpected state.
        """
        elevation = (
            await self.mtcs.rem.mtmount.tel_elevation.aget(
                timeout=self.mtcs.fast_timeout
            )
        ).actualPosition

        if elevation < self.tel_raise_m1m3_min_el:
            raise RuntimeError(
                f"Elevation {elevation:.2f}° is below minimum {self.tel_raise_m1m3_min_el:.2f} deg. "
                f"Cannot raise M1M3. Move telescope manually to a safe position and try again."
            )
        # Get M1M3 detailed state
        detailed_state = MTM1M3.DetailedStates(
            (
                await self.mtcs.rem.mtm1m3.evt_detailedState.aget(
                    timeout=self.mtcs.fast_timeout
                )
            ).detailedState
        )
        fault_state = {MTM1M3.DetailedStates.FAULT}
        active_state = {
            MTM1M3.DetailedStates.ACTIVE,
            MTM1M3.DetailedStates.ACTIVEENGINEERING,
        }
        parked_state = {
            MTM1M3.DetailedStates.PARKED,
            MTM1M3.DetailedStates.PARKEDENGINEERING,
        }

        # Check M1M3 detailed state
        self.log.info(f"M1M3 detailed state: {detailed_state.name}.")
        if detailed_state in fault_state:
            raise RuntimeError(
                f"M1M3 in FAULT state ({detailed_state.name}). Cannot raise. "
                f"Please clear faults and try again."
            )
        elif detailed_state in active_state:
            self.log.info(f"M1M3 already {detailed_state.name}. Nothing to do.")
        elif detailed_state in parked_state:
            self.log.info(
                f"TMA elevation: {elevation:.2f} deg. M1M3 not raised. "
                f"Detailed state: {detailed_state.name}. Raising mirror."
            )
            await self.checkpoint("Raising M1M3 to safe position.")
            await self.mtcs.raise_m1m3()
        else:
            raise RuntimeError(
                f"M1M3 in unexpected state ({detailed_state.name}). Aborting."
                f"Please check the system and try again."
            )

    async def ensure_mtmount_homed(self) -> None:
        """
        Ensure both axes of the MTMount are homed.

        This method checks if both the azimuth and elevation axes of the
        MTMount are homed. If either axis is not homed, it enables the
        M1M3 booster valve via a context manager and issues a
        ``cmd_homeBothAxes`` command to home both axes.

        The booster valve context manager
        (``self.mtcs.m1m3_booster_valve()``) activates the booster valves
        during the homing motion to protect the M1M3 mirror, following the
        same pattern used by the ``home_both_axes`` script.

        The M1M3 force balance system must be enabled before calling
        this method. The ``run`` method ensures this by enabling the
        force balance system in a prior step.

        Raises
        ------
        RuntimeError
            On failure to home axes or retrieve status.
        """
        try:
            is_homed = await self._is_mtmount_homed()
        except Exception as e:
            raise RuntimeError(f"Error while checking MTMount homed status: {e}")

        if not is_homed:
            self.log.info("Homing both axes of the telescope.")
            await self.checkpoint("Homing both axes.")
            await self.mtcs.home_both_axes(homing_attempts=self.homing_attempts)
        else:
            self.log.info("Telescope is already homed. Nothing to do.")

    async def assert_m1m3_force_balance_enabled(self) -> None:
        """Assert that the M1M3 force balance system is enabled.

        This method checks the current state of the M1M3 force balance system
        and raises an error if it is not enabled. The force balance system
        should be automatically enabled when the mirror is raised.

        Raises
        ------
        RuntimeError
            If the force balance system is not enabled.
        """
        self.log.info("Assert that M1M3 force balance system is enabled.")
        await self.mtcs.assert_m1m3_force_balance_system_enabled()

    async def assert_m1m3_slew_controller_flags(self) -> None:
        """Assert that all M1M3 slew controller flags are enabled.

        This method checks the current state of the M1M3 slew controller
        settings and collects warnings for any flags that are not enabled.
        The warnings are added to assertion_errors to be reported at the
        end of the script.
        """
        self.log.info("Assert that M1M3 slew controller flags are enabled.")

        try:
            disabled_flags = await self.mtcs.assert_m1m3_slew_controller_settings()
            if disabled_flags:
                raise RuntimeError(
                    "Some M1M3 slew controller flags are not enabled.\n"
                    f"Disabled flags: {', '.join(disabled_flags)}\n"
                    "This may affect slew performance."
                )
        except Exception as e:
            self.log.warning(f"M1M3 slew controller flags assertion failed: {e}")
            self.assertion_errors.append(e)

    async def ensure_m1m3_cover_opened(self):
        """Ensure the mirror covers are opened.

        This method checks the current state of the mirror covers and
        opens them if they are closed. It also checks the telescope
        elevation to ensure it is safe to open the covers.

        High-level overview of checks and actions performed:
        - Checks the current state of the mirror covers (deployed, retracted,
          or other).
        - If covers are already open (retracted), nothing is done.
        - If covers are deployed, ensures the telescope is at a safe elevation
          (>= 20 degrees). If not, slews the telescope to that elevation,
          maintaining the current azimuth.
        - Stops telescope tracking before opening the covers.
        - Issues the open command and waits for the operation to complete.
        - Handles command errors, verifies the final state of the covers and
          locks, and raises RuntimeError if the system is in a FAULT state or
          if the operation fails.
        """
        self.log.info("Ensuring mirror covers are opened.")
        await self.mtcs.open_m1_cover()

    async def ensure_hexapod_compensation_mode_enabled(self):
        """Ensure compensation mode is enabled for both hexapods.

        This method calls MTCS.enable_compensation_mode() for both
        CameraHexapod (mthexapod_1) and M2Hexapod (mthexapod_2), enabling
        compensation mode if not already enabled. If compensation mode is
        already enabled for a hexapod, no action is taken.
        """
        self.log.info("Ensuring compensation mode is enabled for both hexapods.")
        await self.mtcs.enable_compensation_mode("mthexapod_1")
        await self.mtcs.enable_compensation_mode("mthexapod_2")

    async def ensure_ccw_following_enabled(self):
        """Ensure Camera Cable Wrap (CCW) following is enabled.

        This method calls MTCS.enable_ccw_following(), which enables the
        camera cable wrap to follow the rotator. If already enabled, no
        action is taken.
        """
        self.log.info("Ensuring Camera Cable Wrap following is enabled.")
        await self.mtcs.enable_ccw_following()

    async def ensure_dome_unparked(self) -> None:
        """Ensure the dome is unparked.

        This methdod calls MTCS.unpark_dome(), which checks the current
        dome azimuth motion state. If the dome is parked, it sends the
        command to unpark it. If already unparked, no action is taken.
        """

        self.log.info("Ensuring dome is unparked.")
        await self.mtcs.unpark_dome()

    async def ensure_dome_following_enabled(self):
        """Ensure dome following mode is enabled.

        This method calls MTCS.enable_dome_following(), which enables dome
        trajectory following mode if the check passes. If already enabled,
        no action is taken.
        """
        self.log.info("Ensuring dome following mode is enabled.")
        await self.mtcs.enable_dome_following()

    async def assert_aos_closed_loop_enabled(self) -> None:
        """Assert that AOS Closed Loop is enabled.

        This method checks the current state of the AOS closed loop. The
        closed loop is considered enabled if the state is not IDLE or ERROR.
        Valid enabled states include: WAITING_IMAGE, PROCESSING,
        WAITING_APPLY, and APPLYING_CORRECTION.
        """
        self.log.info("Assert that AOS Closed Loop is enabled.")

        invalid_states = {
            MTAOS.ClosedLoopState.IDLE,
            MTAOS.ClosedLoopState.ERROR,
        }

        try:
            self.mtcs.rem.mtaos.evt_closedLoopState.flush()
            closed_loop_state_evt = await self.mtcs.rem.mtaos.evt_closedLoopState.aget(
                timeout=self.mtcs.fast_timeout
            )
            state = MTAOS.ClosedLoopState(closed_loop_state_evt.state)
            self.log.info(f"AOS Closed Loop state: {state.name}.")

            if state not in invalid_states:
                self.log.info(f"AOS Closed Loop is enabled (state: {state.name}).")
            else:
                raise RuntimeError(
                    f"AOS Closed Loop is not enabled.\n"
                    f"Current state: {state.name}.\n"
                    "Make sure AOS closed loop is enabled before on-sky operations."
                )
        except Exception as e:
            self.log.warning(f"AOS closed loop assertion failed: {e}")
            self.assertion_errors.append(e)

    async def assert_mtm1m3ts_not_in_engineering_mode(self) -> None:
        """Assert that MTM1M3TS is not in engineering mode.

        This method checks whether the MTM1M3TS CSC is enabled and not in
        engineering mode. If the CSC is not enabled or is in engineering mode,
        the script will raise an error.

        Raises
        ------
        RuntimeError
            If MTM1M3TS is not enabled or is in engineering mode.
        """
        self.log.info("Assert that MTM1M3TS is not in engineering mode.")

        summary_state = (
            await self.mtm1m3ts.evt_summaryState.aget(timeout=self.mtcs.fast_timeout)
        ).summaryState

        current_state = salobj.State(summary_state)

        if current_state != salobj.State.ENABLED:
            raise RuntimeError(
                f"MTM1M3TS is not enabled (current state: {current_state!r}).\n"
                "Please check the MTM1M3TS CSC and enable it before proceeding."
            )

        self.mtm1m3ts.evt_engineeringMode.flush()
        engineering_mode_evt = await self.mtm1m3ts.evt_engineeringMode.aget(
            timeout=self.mtcs.fast_timeout
        )

        if engineering_mode_evt.engineeringMode:
            raise RuntimeError(
                "MTM1M3TS is in engineering mode.\n"
                "This prevents EAS/PID from commanding the glycol valve position.\n"
                "Please disable engineering mode on MTM1M3TS before on-sky operations.\n"
                "Check the troubleshooting documentation for more information."
            )

    async def run(self):
        """Run the script to ensure on-sky readiness."""

        await self.checkpoint("Ensure all MTCS components are enabled.")
        await self.ensure_group_all_enabled(self.mtcs, "MTCS")

        await self.checkpoint("Ensure all LSSTCam components are enabled.")
        await self.ensure_group_all_enabled(self.lsstcam, "LSSTCam")

        await self.checkpoint("Ensure OCPS:101 is enabled.")
        await self.ensure_ocps_enabled()

        await self.checkpoint("Assert that MTDome Shutters are opened.")
        await self.assert_dome_shutter_opened()

        await self.checkpoint("Ensure M2 Force Balance System is enabled.")
        await self.ensure_m2_balance_system_enabled()

        await self.checkpoint("Ensure MTM1M3 is raised at safe elevation.")
        await self.ensure_m1m3_raised_at_safe_elevation()

        await self.checkpoint("Assert M1M3 Force Balance System is enabled.")
        await self.assert_m1m3_force_balance_enabled()

        await self.checkpoint("Assert M1M3 Slew Controller Flags are enabled.")
        await self.assert_m1m3_slew_controller_flags()

        await self.checkpoint("Ensure MTMount is homed.")
        await self.ensure_mtmount_homed()

        await self.checkpoint("Ensure M1M3 Mirror Covers are opened.")
        await self.ensure_m1m3_cover_opened()

        await self.checkpoint("Ensure Camera Cable Wrap Following is enabled.")
        await self.ensure_ccw_following_enabled()

        await self.checkpoint("Ensure Hexapods Compensation Mode are enabled.")
        await self.ensure_hexapod_compensation_mode_enabled()

        await self.checkpoint("Ensure Dome is unparked.")
        await self.ensure_dome_unparked()

        await self.checkpoint("Ensure Dome Following is enabled.")
        await self.ensure_dome_following_enabled()

        await self.checkpoint("Assert that AOS Closed Loop is enabled.")
        await self.assert_aos_closed_loop_enabled()

        await self.checkpoint("Ensure M1M3 is not in engineering mode.")
        await self.mtcs.ensure_m1m3_not_in_engineering_mode()

        await self.checkpoint("Assert that MTM1M3TS is not in engineering mode.")
        await self.assert_mtm1m3ts_not_in_engineering_mode()

        if self.assertion_errors:
            error_messages = "\n\n".join(str(e) for e in self.assertion_errors)
            raise AssertionError(
                "All configurable systems have been properly set up, but the "
                "following critical systems need manual intervention:\n\n"
                f"{error_messages}\n\n"
                "Please take the necessary actions before on-sky operations "
                "can continue."
            )
