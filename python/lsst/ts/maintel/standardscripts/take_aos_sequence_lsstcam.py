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

__all__ = ["TakeAOSSequenceLSSTCam"]

from lsst.ts.observatory.control.maintel.lsstcam import LSSTCam, LSSTCamUsages
from lsst.ts.standardscripts.base_take_aos_sequence import BaseTakeAOSSequence


class TakeAOSSequenceLSSTCam(BaseTakeAOSSequence):
    """Take aos sequence with LSSTCam.

    Parameters
    ----------
    index : `int`
        Index of Script SAL component.

    Notes
    -----
    **Checkpoints**

    * sequence {n} of {m}: before taking a sequence.

    """

    def __init__(self, index, descr="Take AOS sequence with LsstCam.") -> None:
        super().__init__(index=index, descr=descr)

        self._camera = None

    @property
    def camera(self):
        return self._camera

    @property
    def oods(self):
        return self._camera.rem.mtoods

    async def configure_camera(self) -> None:
        """Handle creating the camera object and waiting remote to start."""
        if self._camera is None:
            self.log.debug("Creating Camera.")
            self._camera = LSSTCam(
                self.domain,
                intended_usage=LSSTCamUsages.TakeImage | LSSTCamUsages.StateTransition,
                log=self.log,
            )
            await self._camera.start_task
        else:
            self.log.debug("Camera already defined, skipping.")

    def get_instrument_name(self) -> str:
        """Get instrument name.

        Returns
        -------
        instrument_name: `string`
        """
        return "LSSTCam"
