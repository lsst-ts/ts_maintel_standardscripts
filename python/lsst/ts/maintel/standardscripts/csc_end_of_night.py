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

__all__ = ["CscEndOfNight", "EndOfNightConfig"]

import asyncio
from copy import deepcopy

import yaml
from lsst.ts import salobj
from lsst.ts.observatory.control.maintel.lsstcam import LSSTCam, LSSTCamUsages
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages


class EndOfNightConfig:
    """
    The End-of-Night configurations for desired states
    """

    MTCS = {
        "mtmount": "DISABLED",
        "mtptg": "ENABLED",
        "mtaos": "STANDBY",
        "mtm1m3": "ENABLED",
        "mtm2": "ENABLED",
        "mthexapod_1": "DISABLED",
        "mthexapod_2": "DISABLED",
        "mtrotator": "DISABLED",
        "mtdome": "DISABLED",
        "mtdometrajectory": "DISABLED",
    }
    LSSTCam = {
        "mtcamera": "ENABLED",
        "mtheaderservice": "ENABLED",
        "mtoods": "ENABLED",
    }


class CscEndOfNight(salobj.BaseScript):
    """Send MTCS and LSSTCam CSCs to End Of Night State.

    Parameters
    ----------
    index : `int`
        Index of Script SAL component.
    """

    def __init__(self, index):
        super().__init__(
            index=index, descr="Put MTCS and LSSTCam CSCs into the end-of-night state."
        )

        self.mtcs = None
        self.mtcs_end_of_night_csc_states = deepcopy(EndOfNightConfig.MTCS)
        self.lsstcam = None
        self.lsstcam_end_of_night_csc_states = deepcopy(EndOfNightConfig.LSSTCam)

    @classmethod
    def get_schema(cls):
        schema_yaml = f"""
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_maintel_standardscripts/csc_end_of_night.yaml
            title: CscEndOfNight v1
            description: Configuration for CscEndOfNight
            type: object
            properties:
              csc:
                description: List of CSCs to configure.
                type: array
                items:
                  type: string
                  enum: {list(EndOfNightConfig.MTCS) + list(EndOfNightConfig.LSSTCam)}
                default: {list(EndOfNightConfig.MTCS) + list(EndOfNightConfig.LSSTCam)}
              state:
                description: List of states corresponding to the CSCs.
                type: array
                items:
                  type: string
                  enum: ["ENABLED", "STANDBY", "DISABLED"]
                default: {list(EndOfNightConfig.MTCS.values()) + list(EndOfNightConfig.LSSTCam.values())}
              ignore:
                description: >-
                  CSCs from the group to exclude from the end-of-night target
                  state transition. These CSCs will also be ignored during the
                  status check. Names must match those in
                  self.mtcs.components_attr or self.lsstcam.components_attr
                  (e.g., hexapod_1).
                type: array
                items:
                  type: string
              additionalProperties: false
        """
        return yaml.safe_load(schema_yaml)

    async def configure(self, config):
        """Configure script.

        Parameters
        ----------
        config : `types.SimpleNamespace`
            Script configuration, as defined by `schema`.

        Raises
        ------
        ValueError
            If the number of elements in the 'csc' and 'state' properties do
            not match.

        """
        self.log.info("Configure started")

        self.config = config
        # Check cardinalities
        if len(config.csc) != len(config.state):
            raise ValueError(
                "Properties 'csc' and 'state' must have the same number of elements."
            )
        # Configure remote groups
        if self.mtcs is None:
            self.log.debug("Creating MTCS.")
            self.mtcs = MTCS(
                domain=self.domain,
                intended_usage=MTCSUsages.StateTransition,
                log=self.log,
            )
            await self.mtcs.start_task
        else:
            self.log.debug("MTCS already defined, skipping.")

        if self.lsstcam is None:
            self.log.debug("Creating LSSTCam.")
            self.lsstcam = LSSTCam(
                domain=self.domain,
                intended_usage=LSSTCamUsages.StateTransition,
                log=self.log,
            )
            await self.lsstcam.start_task
        else:
            self.log.debug("LSSTCam already defined, skipping.")

        # Configure states with overrides
        end_of_night_csc_states = dict(
            list(EndOfNightConfig.MTCS.items()) + list(EndOfNightConfig.LSSTCam.items())
        )
        # Take into account only overrides with new transitions
        override = dict(
            (csc, new_state)
            for csc, new_state in zip(self.config.csc, self.config.state)
            if new_state != end_of_night_csc_states[csc]
        )
        # Apply overrides
        for csc in end_of_night_csc_states:
            if csc in override:
                self.log.debug(
                    f"Overriding transition of CSC {csc!r} from "
                    f"{end_of_night_csc_states[csc]!r} to {override[csc]!r}."
                )
                end_of_night_csc_states[csc] = override[csc]
        # Configure ignores
        if hasattr(config, "ignore"):
            self.mtcs.disable_checks_for_components(components=config.ignore)
            self.lsstcam.disable_checks_for_components(components=config.ignore)
        # Build the send_to_state dictionaries considering the checks
        mtcs_send_to_state = {
            "ENABLED": [],
            "STANDBY": [],
            "DISABLED": [],
        }
        for csc, state in end_of_night_csc_states.items():
            if getattr(self.mtcs.check, csc, False):
                mtcs_send_to_state[state].append(csc)

        lsstcam_send_to_state = {
            "ENABLED": [],
            "STANDBY": [],
            "DISABLED": [],
        }
        for csc, state in end_of_night_csc_states.items():
            if getattr(self.lsstcam.check, csc, False):
                lsstcam_send_to_state[state].append(csc)

        self.end_of_night_csc_states = end_of_night_csc_states
        self.mtcs_send_to_state = mtcs_send_to_state
        self.lsstcam_send_to_state = lsstcam_send_to_state

    def set_metadata(self, metadata):
        # a crude estimate; state transitions are typically quick
        # but we don't know how many of them there will be
        metadata.duration = 2 * (
            sum(len(csc_list) for csc_list in self.mtcs_send_to_state.values())
            + sum(len(csc_list) for csc_list in self.lsstcam_send_to_state.values())
        )

    async def run(self):
        """Run script."""
        # Tasks for MTCS
        set_state_tasks = [
            self.mtcs.set_state(
                state=getattr(salobj.State, state_name),
                components=csc_list,
            )
            for state_name, csc_list in self.mtcs_send_to_state.items()
        ]
        # Tasks for LSSTCam
        set_state_tasks.extend(
            [
                self.lsstcam.set_state(
                    state=getattr(salobj.State, state_name),
                    components=csc_list,
                )
                for state_name, csc_list in self.lsstcam_send_to_state.items()
            ]
        )

        # Launch set_state tasks
        set_state_retvals = await asyncio.gather(
            *set_state_tasks, return_exceptions=True
        )

        # Check return values for exceptions
        set_state_exceptions = [
            value for value in set_state_retvals if isinstance(value, Exception)
        ]

        # Task to get_state
        mtcs_state_cscs = sum(
            [list(csc_values) for csc_values in self.mtcs_send_to_state.values()],
            start=[],
        )
        lsstcam_state_cscs = sum(
            [list(csc_values) for csc_values in self.lsstcam_send_to_state.values()],
            start=[],
        )

        get_state_tasks = [
            self.mtcs.get_state(component=mtcs_csc) for mtcs_csc in mtcs_state_cscs
        ]
        get_state_tasks.extend(
            [
                self.lsstcam.get_state(component=lsstcam_csc)
                for lsstcam_csc in lsstcam_state_cscs
            ]
        )

        # Launch get_state tasks
        get_state_retvals = await asyncio.gather(
            *get_state_tasks, return_exceptions=True
        )

        summary = f"State transitions summary {'(with errorrs)' if set_state_exceptions else ''}:\n"
        summary += "\n".join(
            f"{csc}: {state.name if not isinstance(state, Exception) else repr(state)}"
            for csc, state in zip(
                mtcs_state_cscs + lsstcam_state_cscs, get_state_retvals
            )
        )

        self.log.info(summary)

        if set_state_exceptions:
            err_message = "\n".join(
                repr(exception) for exception in set_state_exceptions
            )
            raise RuntimeError(err_message)
