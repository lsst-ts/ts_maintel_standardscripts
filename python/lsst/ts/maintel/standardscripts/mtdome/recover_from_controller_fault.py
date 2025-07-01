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
    - Check the MTDome following state and disable dome following if necessary.
    - Send the exitFault command for the MTDome Azimuth Motion Control System.
    - Check the current dome azimuth and move the dome a small amount.
    - Confirm the dome reached the commanded position after a delay.
    - Enable the dome following.

    If the MTDome does not recover, the script ends with an exception.

    Parameters
    ----------
    index : `int`
        Index of Script SAL component.
    """

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

        # Send the exitFault command
        await self.mtcs.rem.mtdome.cmd_exitFault.set(
            subSystemIds=self.exitFault_subSystemIds,
            timeout=self.mtcs.fast_timeout,
        )

        # Check the current dome azimuth
        dome_az = await self.mtcs.rem.mtdome.tel_azimuth.next(
            flush=True,
            timeout=self.mtcs.fast_timeout,
        )

        # Move the dome a small amount from the current position
        target_az = (dome_az.positionActual + self.config.delta_move) % 360

        self.log.info(
            f"Slewing the dome from current azimuth <{dome_az.positionActual} deg> to <{target_az} deg>."
        )
        await self.mtcs.slew_dome_to(az=target_az)

        # Confirm the dome arrived in commanded position.
        after_slew_az = await self.mtcs.rem.mtdome.tel_azimuth.next(
            flush=True,
            timeout=self.mtcs.fast_timeout,
        )

        dome_az_diff = angle_diff(after_slew_az.positionActual, target_az)
        recover_success = np.abs(dome_az_diff) < self.mtcs.dome_slew_tolerance

        if recover_success:
            self.log.info(
                f"The dome is in the range of commanded position: {after_slew_az.positionActual} deg\n"
            )
        elif dome_az.positionActual == after_slew_az.positionActual:
            self.log.error("The dome is not moving.\n")
        else:
            self.log.error(
                f"The dome is not in the range of commanded position ({after_slew_az.positionActual} deg)\n"
            )

        # Enable the dome following.
        await self.mtcs.enable_dome_following()

        if not recover_success:
            raise RuntimeError("The dome is not in the commanded position (see logs).")
