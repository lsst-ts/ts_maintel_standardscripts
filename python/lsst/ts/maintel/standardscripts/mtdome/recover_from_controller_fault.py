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

__all__ = ["RecoverFromControllerFault"]

import asyncio

import numpy as np
import yaml
from lsst.ts import salobj
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages
from lsst.ts.utils import angle_diff
from lsst.ts.xml.enums.MTDome import SubSystemId


class RecoverFromControllerFault(salobj.BaseScript):
    """Attempts to recover the MTDome from a low-level controller fault that
    prevents movement.

    Recovery steps:
    1. Check the dome following state and disable dome following if necessary.
    2. Send the exitFault command for the MTDome Azimuth Motion Control System.
    3. Check the current dome azimuth and move the dome a small amount.
    4. Confirm the dome reached the commanded position after a delay.
    5. If the target position is reached, enable the dome following and finish.
    6. If MTDome is not at target position and the maximum number of attempts
       has not been reached return to step 2. Otherwise finish, with an
       exception.

    Parameters
    ----------
    index : `int`
        Index of Script SAL component.
    """

    MAX_ATTEMPTS = 2

    def __init__(self, index):
        super().__init__(
            index=index,
            descr="Attempts to recover the MTDome from a low-level controller fault that prevent movement.",
        )
        self.mtcs = None
        self.exitFault_subSystemIds = SubSystemId.AMCS  # Azimuth Motion Control System

    @classmethod
    def get_schema(cls):
        url = "https://github.com/lsst-ts/"
        path = "ts_maintel_standardscripts/maintel/mtdome/recover_from_controller_fault.yaml"
        schema_yaml = f"""
            $schema: http://json-schema.org/draft-07/schema#
            $id: {url}{path}
            title: RecoverFromControllerFault v1
            description: >-
              Attempts to recover the MTDome from a low-level controller fault
              that prevents movement.
            type: object
            properties:
              delta_move:
                description: >-
                  Small amount in degrees to move the dome. The absolute value
                  must be greater than the dome slew tolerance.
                type: number
                default: 3.0
            additionalProperties: false
        """
        return yaml.safe_load(schema_yaml)

    async def configure(self, config):
        """Configure script.

        Parameters
        ----------
        config : `types.SimpleNamespace`
            Script configuration, as defined by `schema`.
        """
        self.config = config

        if self.mtcs is None:
            self.log.debug("Creating MTCS.")
            self.mtcs = MTCS(
                domain=self.domain,
                intended_usage=MTCSUsages.Slew,
                log=self.log,
            )
            await self.mtcs.start_task

        if np.abs(self.config.delta_move) <= self.mtcs.dome_slew_tolerance.degree:
            raise ValueError(
                f"The absolute value of delta_move ({np.abs(self.config.delta_move)})"
                f"is below the slew azimuth error tolerance {self.mtcs.dome_slew_tolerance}"
            )

    def set_metadata(self, metadata):
        # An estimate based on slew_to() operation.
        metadata.duration = self.mtcs.long_long_timeout + self.mtcs.move_dome_timeout

    async def run(self):
        # Check MTDome following state and disable dome following if necessary
        if await self.mtcs.check_dome_following():
            await self.mtcs.disable_dome_following()

        recovery_success = False

        # Check the current dome azimuth
        dome_az = await self.mtcs.rem.mtdome.tel_azimuth.next(
            flush=True,
            timeout=self.mtcs.fast_timeout,
        )
        self.log.info(f"Current dome azimuth: {dome_az.positionActual}")

        # Move the dome a small amount from the current position
        target_az = (dome_az.positionActual + self.config.delta_move) % 360

        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            self.log.info(f"Attempt {attempt}: Sending exitFault command...")
            try:
                await self.mtcs.rem.mtdome.cmd_exitFault.set(
                    subSystemIds=self.exitFault_subSystemIds,
                    timeout=self.mtcs.fast_timeout,
                )
            except Exception as err:
                self.log.warning(f"exitFault failed on attempt {attempt}: {err}")
                continue

            await asyncio.sleep(1)

            moved, final_az = await self.move_dome_and_check_success(target_az)
            if moved:
                recovery_success = True
                break
            else:
                self.log.warning(
                    f"Dome did not reach target position on attempt {attempt}. Retrying..."
                )
                target_az = (final_az + self.config.delta_move) % 360

        # Enable the dome following.
        await self.mtcs.enable_dome_following()

        if not recovery_success:
            az_enabled = await self.mtcs.rem.mtdome.logevent_azEnabled.next(
                flush=True, timeout=self.mtcs.fast_timeout
            )

            self.log.error(
                f"Failed to move dome after {self.MAX_ATTEMPTS} attempts.\n"
                f"Controller state: {az_enabled.state}. "
                f"Fault code: {az_enabled.faultCode}"
            )
            raise RuntimeError("Dome not moving; see logs for controller status.")

    async def move_dome_and_check_success(self, target_az):
        self.log.info(f"Attempting to slew dome to {target_az} deg...")
        await self.mtcs.slew_dome_to(az=target_az)
        after_slew_az = await self.mtcs.rem.mtdome.tel_azimuth.next(
            flush=True, timeout=self.mtcs.fast_timeout
        )
        dome_az_diff = angle_diff(after_slew_az.positionActual, target_az)
        moved = np.abs(dome_az_diff) < self.mtcs.dome_slew_tolerance
        if moved:
            self.log.info(
                f"Dome successfully moved to {after_slew_az.positionActual} deg."
            )
        else:
            self.log.warning(
                f"Dome did not reach target position (actual: {after_slew_az.positionActual} deg)."
            )
        return moved, after_slew_az.positionActual
