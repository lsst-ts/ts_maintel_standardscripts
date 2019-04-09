#!/usr/bin/env python

import asyncio
import collections

import numpy as np

from lsst.ts import salobj
from lsst.ts import scriptqueue

import SALPY_ATMonochromator
import SALPY_Electrometer
import SALPY_FiberSpectrograph
import SALPY_ATCamera
import SALPY_ATSpectrograph
import SALPY_ATArchiver
import csv
import datetime
import os
import pathlib
import requests

__all__ = ["CalSysTakeNarrowbandData"]


def is_sequence(value):
    """Return True if value is a sequence that is not a `str` or `bytes`.
    """
    if isinstance(value, str) or isinstance(value, bytes):
        return False
    return isinstance(value, collections.Sequence)


def as_array(value, dtype, nelt):
    """Return a scalar or sequence as a 1-d array of specified type and length.

    Parameters
    ----------
    value : ``any`` or `list` [``any``]
        Value to convert to a list
    dtype : `type`
        Type of data for output
    nelt : `int`
        Required number of elements

    Returns
    -------
    array : `numpy.ndarray`
        ``value`` as a 1-dimensional array with the specified type and length.

    Raises
    ------
    ValueError
        If ``value`` is a sequence of the wrong length
    TypeError
        If ``value`` (if a scalar) or any of its elements (if a sequence)
        cannot be cast to ``dtype``.
    """
    if is_sequence(value):
        if len(value) != nelt:
            raise ValueError(f"len={len(value)} != {nelt}")
        return np.array(value, dtype=dtype)
    return np.array([value] * nelt, dtype=dtype)


class CalSysTakeNarrowbandData(scriptqueue.BaseScript):
    """
    """

    def __init__(self, index):
        super().__init__(index=index,
                         descr="Configure and take LATISS data using the"
                               "auxiliary telescope CalSystem.",
                         remotes_dict={'electrometer': salobj.Remote(SALPY_Electrometer, 1),
                                       'monochromator': salobj.Remote(SALPY_ATMonochromator),
                                       'fiber_spectrograph': salobj.Remote(SALPY_FiberSpectrograph),
                                       'atcamera': salobj.Remote(SALPY_ATCamera),
                                       'atspectrograph': salobj.Remote(SALPY_ATSpectrograph),
                                       'atarchiver': salobj.Remote(SALPY_ATArchiver)
                                       })
        self.cmd_timeout = 60
        self.change_grating_time = 60

    async def configure(self, wavelengths, integration_times, fiber_spectrograph_integration_times,
                        mono_grating_types=1,
                        mono_entrance_slit_widths=2,
                        mono_exit_slit_widths=4,
                        image_types="test",
                        lamps="Kiloarc",
                        fiber_spectrometer_delays=1,
                        latiss_filter=0,
                        latiss_grating=0,
                        latiss_stage_pos=60,
                        nimages_per_wavelength=1,
                        shutter=1,
                        image_sequence_name="test",
                        take_image=True,
                        setup_spectrograph=True,
                        file_location="~/develop",
                        script_type="narrowband"
                        ):
        """Configure the script.

        Parameters
        ----------
        wavelengths : `float` or `list` [`float`]
            Wavelength for each image (nm).
        integration_times :  : `float` or `list` [`float`]
            Integration time for each image (sec).
        mono_grating_types : `int` or `list` [`int`]
            Grating type for each image. The choices are:

            * 1: red
            * 2: blue
            * 3: mirror
        mono_entrance_slit_widths : `float` or `list` [`float`]
            Width of the monochrometer entrance slit for each image (mm).
        mono_exit_slit_widths : `float` or `list` [`float`]
            Width of the monochrometer exit slit for each image (mm).
        image_types : `str` or `list` [`str`]
            Type of each image.
        lamps : `str` or `list` [`str`]
            Name of lamp for each image.
        fiber_spectrometer_delays : `float` or `list` [`float`]
            Delay before taking each image (sec).

        Raises
        ------
        salobj.ExpectedError :
            If the lengths of all arguments that are sequences do not match.

        Notes
        -----
        Arguments can be scalars or sequences. All sequences must have the
        same length, which is the number of images taken. If no argument
        is a sequence then one image is taken.
        """
        self.log.setLevel(10)
        self.log.info("Configure started")

        nelt = 1
        kwargs = locals()
        for argname in ("wavelengths", "integration_times", "mono_grating_types",
                        "mono_entrance_slit_widths", "mono_exit_slit_widths",
                        "image_types", "lamps", "fiber_spectrometer_delays",
                        "latiss_filter", "latiss_grating", "latiss_stage_pos",
                        "nimages_per_wavelength", "shutter", "image_sequence_name",
                        "fiber_spectrograph_integration_times"):
            value = kwargs[argname]
            if is_sequence(value):
                nelt = len(value)
                break
        self.file_location = os.path.expanduser(file_location)
        self.setup_spectrograph = setup_spectrograph
        self.take_image = take_image
        self.script_type = script_type
        # Monochromator Setup
        self.wavelengths = as_array(wavelengths, dtype=float, nelt=nelt)
        self.integration_times = as_array(integration_times, dtype=float, nelt=nelt)
        self.mono_grating_types = as_array(mono_grating_types, dtype=int, nelt=nelt)
        self.mono_entrance_slit_widths = as_array(mono_entrance_slit_widths, dtype=float, nelt=nelt)
        self.mono_exit_slit_widths = as_array(mono_exit_slit_widths, dtype=float, nelt=nelt)
        self.image_types = as_array(image_types, dtype=str, nelt=nelt)
        self.lamps = as_array(lamps, dtype=str, nelt=nelt)
        # Fiber spectrograph
        self.fiber_spectrometer_delays = as_array(fiber_spectrometer_delays, dtype=float, nelt=nelt)
        self.fiber_spectrograph_integration_times = as_array(fiber_spectrograph_integration_times, dtype=float,
                                                             nelt=nelt)
        # ATSpectrograph Setup
        self.latiss_filter = as_array(latiss_filter, dtype=int, nelt=nelt)
        self.latiss_grating = as_array(latiss_grating, dtype=int, nelt=nelt)
        self.latiss_stage_pos = as_array(latiss_stage_pos, dtype=int, nelt=nelt)
        # ATCamera
        self.image_sequence_name = as_array(image_sequence_name, dtype=str, nelt=nelt)
        self.shutter = as_array(shutter, dtype=int, nelt=nelt)
        self.nimages_per_wavelength = as_array(nimages_per_wavelength, dtype=int, nelt=nelt)
        self.log.info("Configure completed")
        # note that the ATCamera exposure time uses self.integration_times for this version

    def set_metadata(self, metadata):
        """Compute estimated duration.

        Parameters
        ----------
        metadata : SAPY_Script.Script_logevent_metadataC
        """
        nimages = len(self.lamps)
        metadata.duration = self.change_grating_time * nimages + \
                            np.sum((self.integration_times + 2) * self.nimages_per_wavelength)

    async def run(self):
        """Run script."""

        await self.checkpoint("start")
        electrometer_urls = []
        fiber_spectrograph_urls = []

        path = pathlib.Path(f"{self.file_location}")
        csv_filename = f"calsys_take_{self.script_type}_data_{datetime.date.today()}.csv"
        file_exists = pathlib.Path(f"{path}/{csv_filename}").is_file()
        fieldnames = []
        if self.take_image:
            fieldnames.append("ATArchiver Image Name")
            fieldnames.append("ATArchiver Image Sequence Name")
        if self.setup_spectrograph:
            fieldnames.append("ATSpectrograph Filter")
            fieldnames.append("ATSpectrograph Grating")
            fieldnames.append("ATSpectrograph Linear Stage Position")
        fieldnames.append("Exposure Time")
        fieldnames.append("Fiber Spectrograph Exposure Time")
        fieldnames.append("Monochromator Grating")
        fieldnames.append("Monochromator Wavelength")
        fieldnames.append("Monochromator Entrance Slit Size")
        fieldnames.append("Monochromator Exit Slit Size")
        fieldnames.append("Fiber Spectrograph Fits File")
        fieldnames.append("Electrometer Fits File")

        with open(f"{path}/{csv_filename}", "a", newline="") as csvfile:
            data_writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            if not file_exists:
                data_writer.writeheader()

            nelt = len(self.wavelengths)
            for i in range(nelt):
                self.log.info(f"take image {i} of {nelt}")

                await self.checkpoint("setup")

                self.monochromator.cmd_changeWavelength.set(wavelength=self.wavelengths[i])
                await self.monochromator.cmd_changeWavelength.start(timeout=self.cmd_timeout)
                self.log.debug(f"Changed monochromator wavelength to {self.wavelengths[i]}")

                self.monochromator.cmd_changeSlitWidth.set(
                    slit=SALPY_ATMonochromator.ATMonochromator_shared_Slit_FrontExit,
                    slitWidth=self.mono_exit_slit_widths[i])
                await self.monochromator.cmd_changeSlitWidth.start(timeout=self.cmd_timeout)
                self.log.debug(f"Changed monochromator exit slit width to {self.mono_exit_slit_widths[i]}")

                self.monochromator.cmd_changeSlitWidth.set(
                    slit=SALPY_ATMonochromator.ATMonochromator_shared_Slit_FrontEntrance,
                    slitWidth=self.mono_entrance_slit_widths[i])
                await self.monochromator.cmd_changeSlitWidth.start(timeout=self.cmd_timeout)
                self.log.debug(f"Changed monochromator entrance slit width to {self.mono_entrance_slit_widths[i]}")

                self.monochromator.cmd_selectGrating.set(gratingType=self.mono_grating_types[i])
                await self.monochromator.cmd_selectGrating.start(
                    timeout=self.cmd_timeout + self.change_grating_time)
                self.log.debug(f"Changed monochromator grating to {self.mono_grating_types[i]}")

                # Setup ATSpectrograph
                if self.setup_spectrograph:
                    self.atspectrograph.cmd_changeDisperser.set(disperser=self.latiss_grating[i])
                    try:
                        await self.atspectrograph.cmd_changeDisperser.start(timeout=self.cmd_timeout)
                    except salobj.AckError as e:
                        self.log.error(f"{e.ack.result}")

                    self.atspectrograph.cmd_changeFilter.set(filter=self.latiss_filter[i])
                    await self.atspectrograph.cmd_changeFilter.start(timeout=self.cmd_timeout)

                    self.atspectrograph.cmd_moveLinearStage.set(distanceFromHome=self.latiss_stage_pos[i])
                    await self.atspectrograph.cmd_moveLinearStage.start(timeout=self.cmd_timeout)

                # setup ATCamera
                # Because we take ancillary data at the same time as the image, we can only take
                # 1 image at a time, therefore numImages is hardcoded to be 1.

                await self.checkpoint("expose")

                # The electrometer startScanDt command is not reported as done
                # until the scan is done, so start the scan and then start
                # taking the image data
                coros = []
                coro1 = self.start_electrometer_scan(i)
                coro2 = self.start_take_spectrum(i)
                if self.take_image:
                    coro3 = self.start_camera_take_image(i)
                if self.take_image:
                    results = await asyncio.gather(coro1, coro2, coro3)
                else:
                    results = await asyncio.gather(coro1, coro2)
                await self.checkpoint("Write data to csv file")
                electrometer_lfo_url = results[0].url
                fiber_spectrograph_lfo_url = results[1].url
                if self.take_image:
                    atcamera_ps_description = results[2].description
                    atcamera_image_name_list = atcamera_ps_description.split(' ')
                    atcamera_image_name = atcamera_image_name_list[1]
                self.log.debug(f"Writing csv file")
                row_dict = {}
                for fieldname in fieldnames:
                    row_dict[fieldname] = None
                row_dict["Exposure Time"] = self.integration_times[i]
                row_dict["Fiber Spectrograph Exposure Time"] = self.fiber_spectrograph_integration_times[i]
                row_dict["Monochromator Grating"] = self.mono_grating_types[i]
                row_dict["Monochromator Wavelength"] = self.wavelengths[i]
                row_dict["Monochromator Entrance Slit Size"] = self.mono_entrance_slit_widths[i]
                row_dict["Monochromator Exit Slit Size"] = self.mono_exit_slit_widths[i]
                row_dict["Fiber Spectrograph Fits File"] = fiber_spectrograph_lfo_url
                row_dict["Electrometer Fits File"] = electrometer_lfo_url
                if self.take_image:
                    row_dict["ATArchiver Image Name"] = atcamera_image_name
                    row_dict["ATArchiver Image Sequence Name"] = self.image_sequence_name[i]
                if self.setup_spectrograph:
                    row_dict["ATSpectrograph Filter"] = self.latiss_filter[i]
                    row_dict["ATSpectrograph Grating"] = self.latiss_grating[i]
                    row_dict["ATSpectrograph Linear Stage Position"] = self.latiss_stage_pos[i]
                data_writer.writerow(row_dict)
        with open(f"{path}/{csv_filename}", newline='') as csvfile:
            data_reader = csv.DictReader(csvfile)
            self.log.debug(f"Reading CSV file")
            for row in data_reader:
                fiber_spectrograph_url = row["Fiber Spectrograph Fits File"]
                electrometer_url = row["Electrometer Fits File"]
                electrometer_url += ".fits"
                electrometer_url = electrometer_url.replace("https://127.0.0.1", "http://10.0.100.133:8000")
                self.log.debug(f"Fixed electrometer url")
                electrometer_url_name = electrometer_url.split("/")[-1]
                fiber_spectrograph_url_name = fiber_spectrograph_url.split("/")[-1]
                fiber_spectrograph_fits_request = requests.get(fiber_spectrograph_url)
                electrometer_fits_request = requests.get(electrometer_url)
                with open(f"{self.file_location}/fiber_spectrograph_fits_files/{fiber_spectrograph_url_name}",
                          "wb") as file:
                    file.write(fiber_spectrograph_fits_request.content)
                    self.log.debug(f"Download Fiber Spectrograph fits file")
                with open(f"{self.file_location}/electrometer_fits_files/{electrometer_url_name}", "wb") as file:
                    file.write(electrometer_fits_request.content)
                    self.log.debug(f"Downloaded Electrometer fits file")
            self.log.info(f"Fits Files downloaded")
        await self.checkpoint("Done")

    async def start_electrometer_scan(self, index):
        self.electrometer.cmd_startScanDt.set(
            scanDuration=self.integration_times[index] + self.fiber_spectrometer_delays[index] * 2)
        electrometer_lfo_coro = self.electrometer.evt_largeFileObjectAvailable.next(timeout=self.cmd_timeout,
                                                                                    flush=True)
        await self.electrometer.cmd_startScanDt.start(timeout=self.cmd_timeout)
        self.log.debug(f"Electrometer finished scan")
        return await electrometer_lfo_coro

    async def start_take_spectrum(self, index):
        """Wait for `self.fiber_spectrometer_delays` then take a spectral image.

        Parameters
        ----------
        index : int
            Index of image to take.

        Returns
        -------
        cmd_captureSpectImage.start : coro
        """
        await self.electrometer.evt_detailedState.next(flush=True, timeout=self.cmd_timeout)
        await asyncio.sleep(self.fiber_spectrometer_delays[index])

        timeout = self.integration_times[index] + self.cmd_timeout
        fiber_spectrograph_lfo_coro = self.fiber_spectrograph.evt_largeFileObjectAvailable.next(
            timeout=self.cmd_timeout, flush=True)
        self.fiber_spectrograph.cmd_captureSpectImage.set(
            imageType=self.image_types[index],
            integrationTime=self.fiber_spectrograph_integration_times[index],
            lamp=self.lamps[index],
        )
        self.log.info(f"take a {self.integration_times[index]} second exposure")
        await self.fiber_spectrograph.cmd_captureSpectImage.start(timeout=timeout)
        self.log.debug(f"Fiber Spectrograph captured spectrum image")
        return await fiber_spectrograph_lfo_coro

    async def start_camera_take_image(self, index):
        self.atcamera.cmd_takeImages.set(shutter=self.shutter[index],
                                         numImages=1,
                                         expTime=self.integration_times[index],
                                         imageSequenceName=self.image_sequence_name[index])
        atarchiver_lfo_coro = self.atarchiver.evt_processingStatus.next(flush=True, timeout=(self.cmd_timeout * 2) +
                                                                                            self.integration_times[
                                                                                                index])
        await self.atcamera.cmd_takeImages.start(timeout=self.cmd_timeout + self.integration_times[index])
        self.log.debug(f"Camera took image")
        return await atarchiver_lfo_coro


if __name__ == '__main__':
    CalSysTakeNarrowbandData.main()

