# This file is part of ts_maintel_standardscripts.
#
# Developed for the Vera C. Rubin Observatory Telescope and Site Systems.
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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

__all__ = ["LsstCamCheckout"]

from ..base_lsstcam_checkout import BaseLsstCamCheckout


class LsstCamCheckout(BaseLsstCamCheckout):
    """Perform the daytime LSSTCam checkout with two 30-second DARKs.

    Each DARK is validated independently and must produce 189 successful
    science-sensor ingestions in MTOODS and eight successful wavefront-sensor
    ingestions in WFOODS for the same obsid. Guider ingestion is reported but
    does not determine whether the checkout succeeds.

    The DARK exposures avoid the daytime dome-light risk of open-shutter
    engineering frames. The camera is intentionally operated without TCS
    synchronization.
    """

    def __init__(self, index: int) -> None:
        super().__init__(
            index=index,
            descr="Execute daytime checkout of LSSTCam.",
        )
        self.dark_exptime = 30.0  # seconds
        self.ndarks = 2

    @classmethod
    def get_schema(cls) -> dict:
        schema = super().get_schema()
        schema.update(
            {
                "$id": (
                    "https://github.com/lsst-ts/ts_maintel_standardscripts/"
                    "daytime/lsstcam_checkout.yaml"
                ),
                "title": "LsstCamCheckout v1",
                "description": "Configuration for LsstCamCheckout daytime script.",
            }
        )
        return schema
