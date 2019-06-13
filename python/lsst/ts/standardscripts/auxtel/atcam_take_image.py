# This file is part of ts_standardscripts
#
# Developed for the LSST Data Management System.
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

__all__ = ["ATCamTakeImage"]

import collections

import numpy as np
import yaml

from lsst.ts import salobj
from lsst.ts.scriptqueue.base_script import BaseScript
from .latiss import LATISS


class ATCamTakeImage(BaseScript):
    """ Take a series of images with the ATCamera with set exposure times.

    Parameters
    ----------
    index : `int`
        SAL index of this Script

    Notes
    -----
    **Checkpoints**

    * exposure {n} of {m}: before sending the ATCamera ``takeImages`` command
    """
    def __init__(self, index):
        super().__init__(index=index, descr="Test ATCamTakeImage")
        self.atcam = salobj.Remote(domain=self.domain, name="ATCamera")
        self.atspec = salobj.Remote(domain=self.domain, name="ATSpectrograph")

        self.latiss = LATISS(atcam=self.atcam,
                             atspec=self.atspec)
        self.cmd_timeout = 60.  # command timeout (sec)
        # large because of an issue with one of the components

    @property
    def schema(self):
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_standardscripts/auxtel/ATCamTakeImage.yaml
            title: ATCamTakeImage v1
            description: Configuration for ATCamTakeImage.
            type: object
            properties:
              nimages:
                description: The number of images to take; if omitted then use the length of exp_times
                    or take a single exposure if exp_times is a scalar.
                anyOf:
                  - type: integer
                    minimum: 1
                  - type: "null"
                default: null
              exp_times:
                description: The exposure time of each image (sec). If a single value,
                  then the same exposure time is used for each exposure.
                anyOf:
                  - type: array
                    minItems: 1
                    items:
                      type: number
                      minimum: 0
                  - type: number
                    minimum: 0
                default: 0
              shutter:
                description: Open the shutter?
                type: boolean
                default: false
              groupid:
                description: Value for the GROUPID entry in the image header.
                type: string
                default: ""
              filter:
                description: Filter name or ID; if omitted the filter is not changed.
                anyOf:
                  - type: string
                  - type: integer
                    minimum: 1
                  - type: "null"
                default: null
              grating:
                description: Grating name; if omitted the grating is not changed.
                anyOf:
                  - type: string
                  - type: integer
                    minimum: 1
                  - type: "null"
                default: null
              linear_stage:
                description: Linear stage position; if omitted the linear stage is not moved.
                anyOf:
                  - type: number
                  - type: "null"
                default: null
            required: [nimages, exp_times, shutter, groupid, filter, grating, linear_stage]
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
        self.log.info("Configure started")

        self.config = config

        nimages = config.nimages
        if isinstance(config.exp_times, collections.Iterable):
            if nimages is not None:
                if len(config.exp_times) != nimages:
                    raise ValueError(f"nimages={nimages} specified and exp_times={config.exp_times} "
                                     "is an array, but the length does not match nimages")
        else:
            # exp_time is a scalar; if nimages is specified then
            # take that many images, else take 1 image
            if nimages is None:
                nimages = 1
            config.exp_times = [config.exp_times]*nimages

        self.log.info(f"exposure times={self.config.exp_times}, "
                      f"shutter={self.config.shutter}, "
                      f"image_name={self.config.groupid}"
                      f"filter={self.config.filter}"
                      f"grating={self.config.grating}"
                      f"linear_stage={self.config.linear_stage}")

    def set_metadata(self, metadata):
        nimages = len(self.config.exp_times)
        mean_exptime = np.mean(self.config.exp_times)
        metadata.duration = (mean_exptime + self.readout_time +
                             self.config.shutter_time*2 if self.config.shutter else 0) * nimages

    async def run(self):
        nimages = len(self.config.exp_times)
        for i, exposure in enumerate(self.config.exp_times):
            await self.checkpoint(f"exposure {i+1} of {nimages}")
            end_readout = await self.latiss.take_image(exptime=exposure,
                                                       shutter=self.config.shutter,
                                                       image_seq_name=self.config.groupid,
                                                       filter=self.config.filter,
                                                       grating=self.config.grating,
                                                       linear_stage=self.config.linear_stage)
            self.log.debug(f"Took {end_readout.imageName}")
