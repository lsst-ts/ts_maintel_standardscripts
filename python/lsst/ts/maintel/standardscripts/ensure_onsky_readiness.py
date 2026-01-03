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
    2. Assert that the dome shutters are open.
    3. Ensure the M2 force balance system is enabled.
    4. Ensure MTM1M3 is raised at a safe elevation.
    5. Ensure the MTMount is homed.
    6. Ensure the M1M3 Force Balance System is enabled.
    7. Ensure M1M3 Slew Controller Flags are set as required.
    8. Ensure the M1M3 Mirror Covers are open.
    9. Ensure Camera Cable Wrap (CCW) following is enabled.
    10. Ensure Compensation Mode is enabled for both Hexapods.
    11. Ensure Dome Following Mode is enabled.
    12. Assert that the AOS (Active Optics System) Closed Loop is enabled.

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
        self.assertion_errors = []

        self.tel_raise_m1m3_min_el = 20.0

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

    @classmethod
    def get_schema(cls):
        schema_yaml = """
        $schema: http://json-schema.org/draft-07/schema#
        $id: https://github.com/lsst-ts/ts_maintel_standardscripts/EnsureTMAReadiness/v1
        title: EnsureTMAReadiness v1
        description: Configuration for EnsureTMAReadiness script.
        type: object
        properties:
          slew_flags:
            description: >-
              List of M1M3 slew controller flags to change or "default" for a
              predefined combination of flags. If not provided, it will be set to
              "default".
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
              Corresponding booleans to enable or disable each slew flag. It will be
              [True, True, True, False] if the slew_flag is set as "default".
            type: array
            items:
              type: boolean
        """
        schema_dict = yaml.safe_load(schema_yaml)

        return schema_dict

    async def configure(self, config):
        """Configure the script.

        Parameters
        ----------
        config : types.SimpleNamespace
            Configuration namespace.
        """
        self.config = config

        if self.config.slew_flags == "default":
            self.config.slew_flags, self.config.enable_flags = (
                self._get_default_m1m3_slew_flags()
            )
        else:
            if len(self.config.slew_flags) != len(self.config.enable_flags):
                raise ValueError(
                    "slew_flags and enable_flags arrays must have the same length."
                )
            # Convert flag names to enumeration values and
            # store them back in config
            self.config.slew_flags = self._convert_m1m3_slew_flag_names_to_enum(
                self.config.slew_flags
            )

        await self.configure_tcs()
        await self.configure_camera()

    def set_metadata(self, metadata):
        metadata.duration = 300

    def _get_default_m1m3_slew_flags(self):
        """Return the default M1M3 slew flags and enables.

        Returns
        -------
        tuple of (list of MTM1M3.SetSlewControllerSettings, list of bool)
            Default M1M3 slew flags and enables.
        """
        default_flags = [
            MTM1M3.SetSlewControllerSettings.ACCELERATIONFORCES,
            MTM1M3.SetSlewControllerSettings.BALANCEFORCES,
            MTM1M3.SetSlewControllerSettings.VELOCITYFORCES,
            MTM1M3.SetSlewControllerSettings.BOOSTERVALVES,
        ]
        default_enables = [True, True, True, False]

        return default_flags, default_enables

    @staticmethod
    def _convert_m1m3_slew_flag_names_to_enum(flag_names):
        """Convert flag names (strings) to MTM1M3.SetSlewControllerSettings
        enum values.

        Parameters
        ----------
        flag_names : list of str
            List of flag names as strings.

        Returns
        -------
        list of MTM1M3.SetSlewControllerSettings
            List of enumeration values corresponding to the flag names.
        """
        return [MTM1M3.SetSlewControllerSettings[name] for name in flag_names]

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
        MTMount are homed. If either axes are not homed, it issues a
        `cmd_homeBothAxes` command to home both axes.

        Raises
        ------
        RuntimeError: On failure to home axes or retrieve status.
        """
        try:
            is_homed = await self._is_mtmount_homed()
        except Exception as e:
            raise RuntimeError(f"Error while checking MTMount homed status: {e}")

        if not is_homed:
            self.log.info("Homing both axes of the telescope.")
            await self.checkpoint("Homing both axes.")
            await self.mtcs.rem.mtmount.cmd_homeBothAxes.start(
                timeout=self.mtcs.long_timeout
            )
        else:
            self.log.info("Telescope is already homed. Nothing to do.")

    async def ensure_m1m3_balance_system_enabled(self):
        """Ensure the M1M3 force balance system is enabled.

        This method calls MTCS.enable_m1m3_balance_system(), which:
        - Checks the current state of the M1M3 force balance system
          (hardpoint corrections).
        - If the system is not enabled, sends the command to enable
          hardpoint corrections.
        - Waits for the force balance system to reach the enabled state,
          monitoring status.
        - Handles command timeouts and logs progress.
        - Raises RuntimeError if the system fails to reach the enabled state.

        If the force balance system is already enabled, no action is taken.
        """
        self.log.info("Ensuring M1M3 force balance system is enabled.")

        # Ensure M1M3 in engineering mode
        await self.mtcs.enter_m1m3_engineering_mode()
        await self.mtcs.enable_m1m3_balance_system()

    async def ensure_m1m3_slew_controller_flags_enabled(self):
        """Ensure M1M3 slew controller flags are enabled."""
        self.log.info("Ensuring M1M3 slew controller flags are correctly enabled.")
        for flag, enable in zip(self.config.slew_flags, self.config.enable_flags):
            await self.mtcs.set_m1m3_slew_controller_settings(flag, enable)

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

        This method checks the current state of the AOS closed loop. If it
        is not in WAITING_IMAGE state, it logs a warning and stores the
        error to be raised at the end of the script.
        """
        self.log.info("Assert that AOS Closed Loop is enabled.")

        try:
            self.mtcs.rem.mtaos.evt_closedLoopState.flush()
            closed_loop_state_evt = await self.mtcs.rem.mtaos.evt_closedLoopState.aget(
                timeout=self.mtcs.fast_timeout
            )
            state = MTAOS.ClosedLoopState(closed_loop_state_evt.state)
            self.log.info(f"AOS Closed Loop state: {state.name}.")

            if state == MTAOS.ClosedLoopState.WAITING_IMAGE:
                self.log.info("AOS Closed Loop is enabled and waiting for image.")
            else:
                raise RuntimeError(
                    f"AOS Closed Loop is not in WAITING_IMAGE state.\n"
                    f"Current state: {state.name}.\n"
                    "Make sure aos closed loop is enabled. "
                )
        except Exception as e:
            self.log.warning(f"AOS closed loop assertion failed: {e}")
            self.assertion_errors.append(e)

    async def run(self):
        """Run the script to ensure on-sky readiness."""

        await self.checkpoint("Ensure all MTCS components are enabled.")
        await self.ensure_group_all_enabled(self.mtcs, "MTCS")

        await self.checkpoint("Ensure all LSSTCam components are enabled.")
        await self.ensure_group_all_enabled(self.lsstcam, "LSSTCam")

        await self.checkpoint("Assert that MTDome Shutters are opened.")
        await self.assert_dome_shutter_opened()

        await self.checkpoint("Ensure M2 Force Balance System is enabled.")
        await self.ensure_m2_balance_system_enabled()

        await self.checkpoint("Ensure MTM1M3 is raised at safe elevation.")
        await self.ensure_m1m3_raised_at_safe_elevation()

        await self.checkpoint("Ensure MTMount is homed.")
        await self.ensure_mtmount_homed()

        await self.checkpoint("Ensure M1M3 Force Balance System is enabled.")
        await self.ensure_m1m3_balance_system_enabled()

        await self.checkpoint("Ensure M1M3 Slew Controller Flags are enabled.")
        await self.ensure_m1m3_slew_controller_flags_enabled()

        await self.checkpoint("Ensure M1M3 Mirror Covers are opened.")
        await self.ensure_m1m3_cover_opened()

        await self.checkpoint("Ensure Camera Cable Wrap Following is enabled.")
        await self.ensure_ccw_following_enabled()

        await self.checkpoint("Ensure Hexapods Compensation Mode are enabled.")
        await self.ensure_hexapod_compensation_mode_enabled()

        await self.checkpoint("Ensure Dome Following is enabled.")
        await self.ensure_dome_following_enabled()

        await self.checkpoint("Assert that AOS Closed Loop is enabled.")
        await self.assert_aos_closed_loop_enabled()

        if self.assertion_errors:
            error_messages = "\n\n".join(str(e) for e in self.assertion_errors)
            raise AssertionError(
                "All configurable systems have been properly set up, but the "
                "following critical systems need manual intervention:\n\n"
                f"{error_messages}\n\n"
                "Please take the necessary actions before on-sky operations "
                "can continue."
            )
