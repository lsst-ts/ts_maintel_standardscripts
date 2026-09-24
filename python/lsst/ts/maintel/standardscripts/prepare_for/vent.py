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

__all__ = ["PrepareForVent"]

import asyncio
import collections
import enum

import astropy.units as u
import numpy as np
import yaml
from astroplan import Observer
from astropy.stats import circmean
from lsst.ts import salobj, utils
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages
from lsst.ts.utils import angle_diff, angle_wrap_center
from lsst.ts.xml.enums import MTDome

# ESS SAL index for the outside weather station (temperature + wind).
ESS_OUTSIDE_INDEX = 301

# ESS SAL index for the in-dome temperature sensor.
ESS_INDOOR_INDEX = 112

# Sun elevation thresholds (deg) that control dome/louver/shutter behavior
# while venting.
SUN_ELEVATION_HIGH = 43.5
SUN_ELEVATION_HORIZON = 42.0
SUN_ELEVATION_STOP = 41.0

TEL_VENT_ELEVATION = 30.0
LOUVER_SUN_AVOIDANCE_ANGLE = 60.0
LOUVER_SUN_EXPOSED_PERCENT = 50.0

TEMPERATURE_DIFFERENTIAL_THRESHOLD = -1.0

LOOP_WAIT_TIME = 30.0

DOME_MIN_AZ = 30.0
DOME_MAX_AZ = 150.0

# TODO: remove when OSW-2359 is finished and import table from xml.
LOUVER_AZIMUTH_OFFSETS = [
    53.10,
    53.10,
    67.50,
    67.50,
    67.50,
    95.50,
    95.50,
    95.50,
    120.75,
    120.75,
    120.75,
    120.75,
    120.75,
    120.75,
    180.00,
    180.00,
    180.00,
    180.00,
    180.00,
    180.00,
    239.25,
    239.25,
    239.25,
    239.25,
    239.25,
    239.25,
    264.50,
    264.50,
    264.50,
    292.50,
    292.50,
    292.50,
    306.90,
    306.90,
]


class VentCondition(enum.IntEnum):
    TEMPERATURE_CONDITION_MET = enum.auto()
    SUN_ELEVATION = enum.auto()


class PrepareForVent(salobj.BaseScript):
    """Run the Simonyi evening venting protocol.

    Disables dome following, points the dome shutter away from the sun and
    closes the mirror covers, then waits until the outside temperature drops
    close enough to the in-dome temperature before venting. The telescope is
    pointed to the dome's azimuth at ``TEL_VENT_ELEVATION`` at the start of
    the script, and again once the sun drops to or below
    ``SUN_ELEVATION_HORIZON`` (see below) -- it is not moved at any other
    point.

    Once venting starts, the dome is repositioned for the wind exactly
    twice (see `reposition_dome_for_wind`): once at the start, and once more
    when the sun drops to or below ``SUN_ELEVATION_HORIZON``, since the
    sun-avoidance constraint no longer applies at that point (the telescope
    is repositioned to match at that same moment). Until the sun reaches
    ``SUN_ELEVATION_HIGH``, the shutter and louvers are left untouched
    entirely, and the dome is only ever nudged the minimum amount needed to
    stay clear of the sun (see `compute_sun_safe_azimuth`); this also
    continues to be the only dome movement between ``SUN_ELEVATION_HIGH``
    and ``SUN_ELEVATION_HORIZON`` once the shutter/louvers do start opening.
    The louvers/shutter are opened progressively as the sun sets, staying
    compliant with the EAS dome sun-avoidance model. By the time the sun
    reaches ``SUN_ELEVATION_STOP`` the dome shutter and all louvers are fully
    opened and the script ends. If the temperature condition is never met,
    the dome is repositioned for the wind one last time and the
    shutter/louvers are opened directly once the sun reaches
    ``SUN_ELEVATION_STOP``, without the progressive adjustments.

    Parameters
    ----------
    index : `int`
        Index of Script SAL component.

    Raises
    ------
    RuntimeError
        If ``louvers`` names a louver that is disabled at the start of the
        script (see `assert_configured_louvers_enabled`).

    Notes
    -----
    **Configuration**

    - ``louvers``: either ``"all"`` (default; use all enabled louvers) or
      an explicit list of louver names (e.g. ``["A1", "E2"]``) to restrict
      to. Louvers outside this set are left uncommanded.

    **Checkpoints**

    - "Disabling dome following": before disabling dome following.
    - "Pointing dome shutter away from the sun": before the initial dome
      slew.
    - "Pointing telescope to initial dome azimuth": before the one-time
      telescope move.
    - "Closing mirror covers": before closing the mirror covers.
    - "Waiting for outside temperature to drop below in-dome temperature":
      before the temperature gate.
    - "Positioning dome for the current wind direction": before the one-time
      wind-facing dome slew at the start of venting.
    - "Sun at ... deg elevation, waiting ...s for sun to reach
      SUN_ELEVATION_HIGH ...": once per loop iteration while waiting for the
      sun to reach ``SUN_ELEVATION_HIGH`` (see `wait_for_sun_elevation_high`);
      the shutter and louvers are not touched during this wait.
    - "Venting: sun at ... deg elevation, ... deg azimuth; dome at ... deg
      azimuth": once per loop iteration between ``SUN_ELEVATION_HIGH`` and
      ``SUN_ELEVATION_HORIZON`` (see `vent_while_sun_sets`).
    - "Sun elevation below SUN_ELEVATION_HORIZON, positioning dome and
      telescope to point into wind ...": once per loop iteration at or below
      ``SUN_ELEVATION_HORIZON`` (see `vent_while_sun_sets`).
    - "Sun reached the stop elevation before the temperature condition was
      met; opening dome shutters and louvers to 100 percent": if venting
      never started because the temperature condition was never met.
    """

    def __init__(self, index):
        super().__init__(index=index, descr="Prepare Simonyi for evening venting.")

        self.mtcs = None
        self.ess_outside = None
        self.ess_indoor = None

        self.loop_wait_time = LOOP_WAIT_TIME

        # airflow sample frequency is 1/s so this collection samples 600s of
        # history
        self._wind_history: collections.deque = collections.deque(maxlen=600)
        # temperature sample frequency is 0.25/s so this collection samples
        # 120s of history
        self._outside_temperature_history: collections.deque = collections.deque(
            maxlen=30
        )
        self._indoor_temperature_history: collections.deque = collections.deque(
            maxlen=30
        )
        self.louvers = "all"
        self._active_louvers = None

        # Last position actually commanded, so open_dome_shutter_if_needed
        # / open_dome_louvers_if_needed can skip re-sending a command that
        # wouldn't change anything.
        self._shutter_opened = False
        self._commanded_louver_position = None

    @classmethod
    def get_schema(cls):
        louver_names = ", ".join(louver.name for louver in MTDome.Louver)
        schema_yaml = f"""
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_maintel_standardscripts/prepare_for/vent.yaml
            title: PrepareForVent v1
            description: Configuration for PrepareForVent.
            type: object
            properties:
              louvers:
                description: >-
                  Which MTDome louvers to operate during venting. Either the
                  string "all" (use all enabled louvers) or an explicit list
                  of louver names (e.g. ["A1", "E2"]) to restrict to.
                oneOf:
                  - type: string
                    enum: [all]
                  - type: array
                    items:
                      type: string
                      enum: [{louver_names}]
                    minItems: 1
                    uniqueItems: true
                default: all
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
        self.louvers = config.louvers

        if self.mtcs is None:
            self.mtcs = MTCS(
                domain=self.domain,
                intended_usage=MTCSUsages.PrepareForVent,
                log=self.log,
            )
            await self.mtcs.start_task

        if self.ess_outside is None:
            self.ess_outside = salobj.Remote(
                domain=self.domain,
                name="ESS",
                index=ESS_OUTSIDE_INDEX,
                include=["temperature", "airFlow"],
            )
            self.ess_outside.tel_airFlow.callback = self._air_flow_callback
            self.ess_outside.tel_temperature.callback = (
                self._outside_temperature_callback
            )
            await self.ess_outside.start_task

        if self.ess_indoor is None:
            self.ess_indoor = salobj.Remote(
                domain=self.domain,
                name="ESS",
                index=ESS_INDOOR_INDEX,
                include=["temperature"],
            )
            self.ess_indoor.tel_temperature.callback = self._indoor_temperature_callback
            await self.ess_indoor.start_task

    async def assert_configured_louvers_enabled(self):
        """Raise if any explicitly-configured louver (see the ``louvers``
        config option) is not currently enabled.

        A no-op when ``louvers`` is ``"all"``: there's nothing to assert
        in that case, since any enabled louver is a valid choice.

        Raises
        ------
        RuntimeError
            If any explicitly-configured louver is not currently enabled.
            The error names both the disabled louver(s) and the currently
            enabled ones, so a misconfigured ``louvers`` list is easy to
            spot and fix.
        """
        if self.louvers == "all":
            return
        await self.mtcs.assert_dome_louvers_enabled(self.louvers)

    def set_metadata(self, metadata):
        metadata.duration = self.estimate_time_until_sun_elevation(SUN_ELEVATION_STOP)

    def estimate_time_until_sun_elevation(self, elevation):
        """Estimate the time until the setting sun reaches ``elevation``.

        Parameters
        ----------
        elevation : `float`
            Target sun elevation, in degrees.

        Returns
        -------
        `float`
            Estimated seconds until the sun reaches ``elevation``.
        """
        observer = Observer(
            location=self.mtcs.location, name="Rubin", timezone="Chile/Continental"
        )

        target_time = observer.sun_set_time(
            utils.astropy_time_from_tai_unix(utils.current_tai()),
            which="next",
            horizon=elevation * u.deg,
        )

        return target_time.unix_tai - utils.current_tai()

    @staticmethod
    def _format_temperature(value):
        """Format a temperature for a log/checkpoint message.

        Parameters
        ----------
        value : `float` or `None`
            Temperature, in deg C, or `None` if not yet available.

        Returns
        -------
        `str`
            ``"{value:.2f} C"``, or ``"N/A"`` if ``value`` is `None`.
        """
        return "N/A" if value is None else f"{value:.2f} C"

    async def _outside_temperature_callback(self, data):
        """Append an ESS outside temperature sample to the rolling
        history, using deque to manage length.

        Parameters
        ----------
        data : `salobj.BaseMsgType`
            ESS temperature telemetry sample.
        """
        self._outside_temperature_history.append(data.temperatureItem[0])

    async def _indoor_temperature_callback(self, data):
        """Append an ESS in-dome temperature sample to the rolling
        history, using deque to manage length.

        Parameters
        ----------
        data : `salobj.BaseMsgType`
            ESS temperature telemetry sample.
        """
        self._indoor_temperature_history.append(data.temperatureItem[0])

    async def _air_flow_callback(self, data):
        """Append an ESS airFlow direction sample to the wind history,
        using deque to manage length.

        Parameters
        ----------
        data : `salobj.BaseMsgType`
            ESS airFlow telemetry sample.
        """
        self._wind_history.append(data.direction)

    async def get_dome_azimuth(self):
        """Get the current dome azimuth.

        Returns
        -------
        `float`
            Current dome azimuth, in degrees.
        """
        data = await self.mtcs.rem.mtdome.tel_azimuth.aget(
            timeout=self.mtcs.fast_timeout
        )
        return data.positionActual

    async def wait_for_vent_condition(self):
        """Wait until either the outside temperature is close enough to the
        in-dome temperature to begin venting or the sun reaches a low enough
        elevation that venting must start regardless of the temperature
        condition.

        Returns
        -------
        `VentCondition`
            ``VentCondition.TEMPERATURE_CONDITION_MET`` once the outside
            temperature is close enough to the in-dome temperature.
            ``VentCondition.SUN_ELEVATION`` if the sun reaches
            ``SUN_ELEVATION_STOP`` before that happens.
        """
        outside_temp = (
            float(np.median(self._outside_temperature_history))
            if self._outside_temperature_history
            else None
        )
        indoor_temp = (
            float(np.median(self._indoor_temperature_history))
            if self._indoor_temperature_history
            else None
        )

        _, sun_el = self.mtcs.get_sun_azel()

        while sun_el > SUN_ELEVATION_STOP and (
            outside_temp is None
            or indoor_temp is None
            or outside_temp - indoor_temp >= TEMPERATURE_DIFFERENTIAL_THRESHOLD
        ):
            self.log.info(
                "Waiting for outside temperature to drop below in-dome "
                f"temperature: outside={self._format_temperature(outside_temp)}, "
                f"indoor={self._format_temperature(indoor_temp)}."
            )
            await asyncio.sleep(self.loop_wait_time)

            outside_temp = (
                float(np.median(self._outside_temperature_history))
                if self._outside_temperature_history
                else None
            )
            indoor_temp = (
                float(np.median(self._indoor_temperature_history))
                if self._indoor_temperature_history
                else None
            )

            _, sun_el = self.mtcs.get_sun_azel()

        condition_met = (
            outside_temp is not None
            and indoor_temp is not None
            and outside_temp - indoor_temp < TEMPERATURE_DIFFERENTIAL_THRESHOLD
        )
        if condition_met:
            self.log.info(
                "Temperature condition met: "
                f"outside={self._format_temperature(outside_temp)}, "
                f"indoor={self._format_temperature(indoor_temp)}."
            )
            return VentCondition.TEMPERATURE_CONDITION_MET
        else:
            self.log.warning(
                "Sun reached the stop elevation before the temperature "
                "condition was met."
            )
        return VentCondition.SUN_ELEVATION

    async def reposition_dome_for_wind(self, sun_az, clamp_to_sun_avoidance_range):
        """Slew the dome to face the current wind direction, or -- if no
        wind data is available -- to a direction safely away from the sun.

        Called once, at the start of venting (with
        ``clamp_to_sun_avoidance_range=True``, since the sun is still up),
        and once more the first time the sun is found at or below
        ``SUN_ELEVATION_HORIZON`` (with
        ``clamp_to_sun_avoidance_range=False``, since the solar-avoidance
        constraint no longer applies at that point). Wind speed is not
        considered: operators are responsible for judging whether wind
        speed is safe to vent in.

        Parameters
        ----------
        sun_az : `float`
            Current sun azimuth, in degrees; used only if no wind
            direction is available.
        clamp_to_sun_avoidance_range : `bool`
            If `True`, the commanded azimuth is clamped to
            ``[DOME_MIN_AZ, DOME_MAX_AZ]``.

        Returns
        -------
        `float`
            The dome azimuth that was commanded.
        """

        if self._wind_history:
            # circmean requires a real ndarray/Quantity (it reads .shape
            # directly) and, given one, treats it as radians -- so the
            # degrees-valued history must be explicitly tagged with u.deg
            # and converted back.
            wind_direction = (
                circmean(np.asarray(self._wind_history) * u.deg).to_value(u.deg) % 360.0
            )
        else:
            wind_direction = None

        if wind_direction is None:
            self.log.warning(
                "No wind data available; positioning the dome safely away "
                "from the sun instead."
            )
            dome_az = (sun_az + 180.0) % 360.0
        else:
            dome_az = wind_direction

        if clamp_to_sun_avoidance_range:
            dome_az = min(max(dome_az, DOME_MIN_AZ), DOME_MAX_AZ)

        self.log.info(f"Positioning dome to {dome_az:.1f} deg.")
        await self.mtcs.slew_dome_to(dome_az)
        return dome_az

    @staticmethod
    def compute_sun_safe_azimuth(dome_az, sun_az):
        """Nudge ``dome_az`` the minimum amount needed to stay at least
        ``LOUVER_SUN_AVOIDANCE_ANGLE`` away from the sun.

        Used to keep the dome azimuth safe as the sun's azimuth drifts over
        time. Returns ``dome_az`` unchanged if it is already outside the
        avoidance zone.

        Parameters
        ----------
        dome_az : `float`
            Dome azimuth to check/adjust, in degrees.
        sun_az : `float`
            Current sun azimuth, in degrees.

        Returns
        -------
        `float`
            A dome azimuth at least ``LOUVER_SUN_AVOIDANCE_ANGLE`` from the
            sun, on the same side of the sun as ``dome_az``.
        """
        offset = angle_diff(dome_az, sun_az).deg
        if abs(offset) >= LOUVER_SUN_AVOIDANCE_ANGLE:
            return dome_az
        edge = (
            LOUVER_SUN_AVOIDANCE_ANGLE if offset >= 0.0 else -LOUVER_SUN_AVOIDANCE_ANGLE
        )
        return (sun_az + edge) % 360.0

    @staticmethod
    def compute_louver_positions(dome_az, sun_az):
        """Compute the desired open percentage for each louver, given the
        current dome and sun azimuths.

        Louvers more than ``LOUVER_SUN_AVOIDANCE_ANGLE`` from the sun are
        opened to 100%; louvers within that angle are capped at
        ``LOUVER_SUN_EXPOSED_PERCENT``, matching the ts_eas DomeModel
        defaults so the EAS sun-avoidance logic never needs to override this
        command.

        Parameters
        ----------
        dome_az : `float`
            Current dome azimuth, in degrees.
        sun_az : `float`
            Current sun azimuth, in degrees.

        Returns
        -------
        `dict` [`str`, `float`]
            Desired percent-open for each of the 34 louvers, keyed by
            `lsst.ts.xml.enums.MTDome.Louver` name.
        """
        return {
            MTDome.Louver(i + 1).name: (
                100.0
                if abs(angle_diff((dome_az + offset) % 360.0, sun_az).deg)
                > LOUVER_SUN_AVOIDANCE_ANGLE
                else LOUVER_SUN_EXPOSED_PERCENT
            )
            for i, offset in enumerate(LOUVER_AZIMUTH_OFFSETS)
        }

    def get_enabled_louver_positions(self, positions):
        """Filter a full louver-name-to-position mapping down to
        ``self._active_louvers``, determined once at the start of `run`.

        Parameters
        ----------
        positions : `dict` [`str`, `float`]
            Desired percent-open for each louver, keyed by
            `lsst.ts.xml.enums.MTDome.Louver` name. May include louvers
            outside the active set; those are dropped.

        Returns
        -------
        `dict` [`str`, `float`]
            The subset of ``positions`` for active louvers.
        """
        return {
            name: value
            for name, value in positions.items()
            if name in self._active_louvers
        }

    async def open_dome_shutter_if_needed(self):
        """Open the dome shutter, unless this script has already commanded
        it open.

        Called every loop iteration in `vent_while_sun_sets`, where the
        shutter is open for most of the run; without this check every
        iteration would re-send ``cmd_openShutter`` for no reason.
        """
        if self._shutter_opened:
            return

        self.log.info("Opening dome shutter.")
        await self.mtcs.open_dome_shutter()
        self._shutter_opened = True

    async def open_dome_louvers_if_needed(self, position):
        """Open (or otherwise position) the dome louvers, unless
        ``position`` matches what this script last commanded.

        Called every loop iteration in `vent_while_sun_sets`, where the
        desired louver positions often don't change between one iteration
        and the next; without this check every iteration would re-send
        ``cmd_setLouvers`` for no reason.

        Parameters
        ----------
        position : `dict` [`str`, `float`]
            Desired percent-open for each active louver, keyed by
            `lsst.ts.xml.enums.MTDome.Louver` name.
        """
        if position == self._commanded_louver_position:
            return

        self.log.info("Opening dome louvers.")
        await self.mtcs.open_dome_louvers(position=position)
        self._commanded_louver_position = position

    async def wait_for_sun_elevation_high(self):
        """Wait until the sun descends to ``SUN_ELEVATION_HIGH``.

        The shutter and louvers are not touched at all during this wait;
        the dome is only ever nudged the minimum amount needed to stay
        clear of the sun (see `compute_sun_safe_azimuth`).
        """
        sun_az, sun_el = self.mtcs.get_sun_azel()

        while sun_el > SUN_ELEVATION_HIGH:
            wait_time = self.estimate_time_until_sun_elevation(SUN_ELEVATION_HIGH)
            await self.checkpoint(
                f"Sun at {sun_el:.2f} deg elevation, waiting {wait_time:.0f}s "
                f"for sun to reach SUN_ELEVATION_HIGH ({SUN_ELEVATION_HIGH} deg)."
            )

            dome_az = await self.get_dome_azimuth()
            safe_az = min(
                max(self.compute_sun_safe_azimuth(dome_az, sun_az), DOME_MIN_AZ),
                DOME_MAX_AZ,
            )
            if safe_az != dome_az:
                self.log.info(
                    f"Nudging dome to {safe_az:.1f} deg to stay clear of the sun."
                )
                await self.mtcs.slew_dome_to(safe_az)

            await asyncio.sleep(self.loop_wait_time)
            sun_az, sun_el = self.mtcs.get_sun_azel()

    async def vent_while_sun_sets(self):
        """Track the sun's descent, keeping the dome/louvers safely
        positioned relative to the sun and opening the shutter/louvers as
        the sun gets lower, until the sun reaches ``SUN_ELEVATION_STOP``. By
        the time this loop exits, the shutter and louvers are already fully
        open (they reach that state progressively, once the sun is at or
        below ``SUN_ELEVATION_HORIZON``; see below).

        The dome is repositioned for the wind (see `reposition_dome_for_wind`)
        once, right before waiting for the sun to reach
        ``SUN_ELEVATION_HIGH`` (see `wait_for_sun_elevation_high`, which
        leaves the shutter/louvers untouched), and once more the first time
        the sun is found at or below ``SUN_ELEVATION_HORIZON`` -- at which
        point the telescope is also repositioned to match, since the
        sun-avoidance constraint no longer applies. In between, and on
        every other loop iteration while the sun is still above
        ``SUN_ELEVATION_HORIZON``, the dome is only nudged the minimum
        amount needed to stay clear of the sun -- it is never otherwise
        moved for the wind. The aperture shutter and louvers are commanded
        open every iteration from here on -- the louvers either capped for
        sun avoidance (see `compute_louver_positions`) while the sun is
        above ``SUN_ELEVATION_HORIZON`` or fully open once it is not -- but
        `open_dome_shutter_if_needed`/`open_dome_louvers_if_needed` only
        actually send a command when the desired state has changed since
        the last one sent.
        """
        sun_az, _ = self.mtcs.get_sun_azel()
        await self.checkpoint("Positioning dome for the current wind direction.")
        await self.reposition_dome_for_wind(sun_az, clamp_to_sun_avoidance_range=True)

        await self.wait_for_sun_elevation_high()

        repositioned_for_wind_after_sunset = False
        sun_az, sun_el = self.mtcs.get_sun_azel()

        while sun_el > SUN_ELEVATION_STOP:
            if sun_el > SUN_ELEVATION_HORIZON:
                dome_az = await self.get_dome_azimuth()
                safe_az = min(
                    max(self.compute_sun_safe_azimuth(dome_az, sun_az), DOME_MIN_AZ),
                    DOME_MAX_AZ,
                )
                if safe_az != dome_az:
                    dome_az = safe_az
                    self.log.info(
                        f"Nudging dome to {dome_az:.1f} deg to stay clear of "
                        "the sun."
                    )
                    await self.mtcs.slew_dome_to(dome_az)

                await self.checkpoint(
                    f"Venting: sun at {sun_el:.2f} deg elevation, "
                    f"{sun_az:.1f} deg azimuth; dome at {dome_az:.1f} deg "
                    "azimuth."
                )
                full_positions = self.compute_louver_positions(dome_az, sun_az)
            else:
                if not repositioned_for_wind_after_sunset:
                    dome_az = await self.reposition_dome_for_wind(
                        sun_az, clamp_to_sun_avoidance_range=False
                    )

                    tel_az = angle_wrap_center(dome_az).deg

                    self.log.info(
                        f"Pointing telescope to {tel_az:.1f} deg az (with the dome) at "
                        f"{TEL_VENT_ELEVATION} deg elevation."
                    )
                    await self.mtcs.point_azel(
                        target_name="Vent Position",
                        az=tel_az,
                        el=TEL_VENT_ELEVATION,
                        rot_tel=self.mtcs.tel_park_rot,
                        wait_dome=False,
                    )
                    await self.mtcs.stop_tracking()

                    repositioned_for_wind_after_sunset = True

                await self.checkpoint(
                    "Sun elevation below SUN_ELEVATION_HORIZON, positioning "
                    f"dome and telescope to point into wind ({dome_az:.1f} "
                    "deg)."
                )
                full_positions = {louver.name: 100.0 for louver in MTDome.Louver}

            await self.open_dome_shutter_if_needed()

            louver_position = self.get_enabled_louver_positions(full_positions)
            await self.open_dome_louvers_if_needed(louver_position)

            await asyncio.sleep(self.loop_wait_time)
            sun_az, sun_el = self.mtcs.get_sun_azel()

    async def run(self):
        await self.mtcs.assert_all_enabled()
        await self.assert_configured_louvers_enabled()

        configured_louvers = (
            {louver.name for louver in MTDome.Louver}
            if self.louvers == "all"
            else set(self.louvers)
        )
        enabled_louvers = await self.mtcs.get_enabled_dome_louvers()
        self._active_louvers = {
            louver.name
            for louver in enabled_louvers
            if louver.name in configured_louvers
        }

        await self.checkpoint("Disabling dome following.")
        await self.mtcs.disable_dome_following()

        sun_az, _ = self.mtcs.get_sun_azel()
        await self.checkpoint("Pointing dome shutter away from the sun.")

        dome_target_az = min(max((sun_az + 180.0) % 360.0, DOME_MIN_AZ), DOME_MAX_AZ)
        await self.mtcs.slew_dome_to(dome_target_az)

        await self.checkpoint("Pointing telescope to initial dome azimuth.")

        tel_az = angle_wrap_center(dome_target_az).deg

        self.log.info(
            f"Pointing telescope to {tel_az:.1f} deg az (with the dome) at "
            f"{TEL_VENT_ELEVATION} deg elevation."
        )
        await self.mtcs.point_azel(
            target_name="Vent Position",
            az=tel_az,
            el=TEL_VENT_ELEVATION,
            rot_tel=self.mtcs.tel_park_rot,
            wait_dome=False,
        )
        await self.mtcs.stop_tracking()

        await self.checkpoint("Closing mirror covers.")
        await self.mtcs.close_m1_cover()

        outside_temp = (
            float(np.median(self._outside_temperature_history))
            if self._outside_temperature_history
            else None
        )
        indoor_temp = (
            float(np.median(self._indoor_temperature_history))
            if self._indoor_temperature_history
            else None
        )

        await self.checkpoint(
            "Waiting for outside temperature to drop below in-dome temperature: "
            f"outside={self._format_temperature(outside_temp)}, "
            f"indoor={self._format_temperature(indoor_temp)}, "
            f"limit={TEMPERATURE_DIFFERENTIAL_THRESHOLD} C."
        )
        vent_condition = await self.wait_for_vent_condition()

        if vent_condition == VentCondition.TEMPERATURE_CONDITION_MET:
            await self.vent_while_sun_sets()
        elif vent_condition == VentCondition.SUN_ELEVATION:
            await self.checkpoint(
                "Sun reached the stop elevation before the temperature condition "
                "was met; opening dome shutters and louvers to 100 percent."
            )
            sun_az, _ = self.mtcs.get_sun_azel()
            await self.reposition_dome_for_wind(
                sun_az, clamp_to_sun_avoidance_range=False
            )
            await self.open_dome_shutter_if_needed()
            full_positions = {louver.name: 100.0 for louver in MTDome.Louver}
            await self.open_dome_louvers_if_needed(
                self.get_enabled_louver_positions(full_positions)
            )
