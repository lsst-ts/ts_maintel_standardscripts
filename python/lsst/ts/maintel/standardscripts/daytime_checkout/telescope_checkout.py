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

__all__ = ["TelescopeCheckout"]

from .base_telescope_checkout import BaseTelescopeCheckout


class TelescopeCheckout(BaseTelescopeCheckout):
    """Exercise only the Simonyi Telescope during daytime checkout."""

    def __init__(self, index: int) -> None:
        super().__init__(
            index=index,
            descr="Execute daytime checkout of the Simonyi Telescope.",
        )
        self.include_dome = False

    @classmethod
    def get_schema(cls) -> dict:
        schema = super().get_schema()
        schema.update(
            {
                "$id": (
                    "https://github.com/lsst-ts/ts_maintel_standardscripts/"
                    "telescope_checkout.yaml"
                ),
                "title": "TelescopeCheckout v1",
                "description": (
                    "Configuration for the Simonyi Telescope daytime checkout. "
                    "The M1 mirror covers remain closed. MTDome is not checked "
                    "or commanded."
                ),
            }
        )
        dome_components = cls.format_component_list(cls.get_dome_components())
        dome_policy = "The telescope-only checkout automatically skips {}.".format(
            dome_components
        )
        schema["properties"]["ignore"]["description"] += f" {dome_policy}"
        return schema
