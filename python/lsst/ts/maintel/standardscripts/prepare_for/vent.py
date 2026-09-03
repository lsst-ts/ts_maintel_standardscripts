# This file is part of ts_maintel_standardscripts
#
# Developed for the Vera Rubin Observatory.
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

__all__ = ["PrepareForVent"]

import asyncio
import statistics

import astropy.units as u
import yaml
from astroplan import Observer
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
SUN_ELEVATION_HIGH = 6.0
SUN_ELEVATION_HORIZON = -1.0
SUN_ELEVATION_STOP = -6.0

TEL_VENT_ELEVATION = 30.0
LOUVER_SUN_AVOIDANCE_ANGLE = 60.0
LOUVER_SUN_EXPOSED_PERCENT = 50.0

TEMPERATURE_DIFFERENTIAL_THRESHOLD = -1.0
TEMPERATURE_MEDIAN_WINDOW = 120.0
WIND_DIRECTION_MEDIAN_WINDOW = 600.0

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

        self._wind_history = []
        self._outside_temperature_history = []
        self._indoor_temperature_history = []
        self.louvers = "all"
        self._active_louvers = None

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
        metadata.duration = self.estimate_duration()

    def estimate_duration(self):
        """Estimate the script duration.

        Returns
        -------
        `float`
            Estimated duration (in seconds) until the sun reaches
            ``SUN_ELEVATION_STOP``.
        """
        return self.estimate_time_until_sun_elevation(SUN_ELEVATION_STOP)

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

    def get_sun_azel(self):
        """Get sun azel from MTCS.

        Returns
        -------
        `tuple`[`float`, `float`]
            Current azimuth and elevation of the sun.
        """
        return self.mtcs.get_sun_azel()

    async def point_dome_away_from_sun(self, sun_az):
        """Slew the dome so the shutter points as close as possible to
        directly away from the sun, without exceeding the dome's
        ``[DOME_MIN_AZ, DOME_MAX_AZ]`` azimuth limits.

        Parameters
        ----------
        sun_az : `float`
            Current sun azimuth, in degrees.
        """
        target_az = min(max((sun_az + 180.0) % 360.0, DOME_MIN_AZ), DOME_MAX_AZ)
        await self.mtcs.slew_dome_to(target_az)

    async def point_telescope_to_vent_position(self, dome_az):
        """Point the telescope to the dome's azimuth at
        ``TEL_VENT_ELEVATION``.

        Called once, at the start of the script, and once more when the sun
        drops to or below ``SUN_ELEVATION_HORIZON`` (see
        `vent_while_sun_sets`); not moved at any other point.

        Parameters
        ----------
        dome_az : `float`
            Dome azimuth to point the telescope to, in degrees.
        """
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

    def get_outside_temperature(self):
        """Get the median outside temperature from the ESS weather station
        over the ``TEMPERATURE_MEDIAN_WINDOW`` seconds prior to this call.

        Median-filtering avoids reacting to a single noisy sample; the ESS
        temperature sensors can be noisy. There is no live-reading
        fallback: ``tel_temperature`` has a callback registered on it (see
        `configure`), and salobj does not allow also pulling samples from a
        topic that has a callback.

        Returns
        -------
        `float` or `None`
            Median outside temperature (deg C) over the trailing
            ``TEMPERATURE_MEDIAN_WINDOW`` seconds, or `None` if no samples
            were collected in that window (e.g. this is called before the
            first telemetry sample has arrived).
        """
        return self._median_within_window(
            self._outside_temperature_history, TEMPERATURE_MEDIAN_WINDOW
        )

    def get_indoor_temperature(self):
        """Get the median in-dome temperature from the ESS sensor over the
        ``TEMPERATURE_MEDIAN_WINDOW`` seconds prior to this call.

        Median-filtering avoids reacting to a single noisy sample; the ESS
        temperature sensors can be noisy. There is no live-reading
        fallback: ``tel_temperature`` has a callback registered on it (see
        `configure`), and salobj does not allow also pulling samples from a
        topic that has a callback.

        Returns
        -------
        `float` or `None`
            Median in-dome temperature (deg C) over the trailing
            ``TEMPERATURE_MEDIAN_WINDOW`` seconds, or `None` if no samples
            were collected in that window (e.g. this is called before the
            first telemetry sample has arrived).
        """
        return self._median_within_window(
            self._indoor_temperature_history, TEMPERATURE_MEDIAN_WINDOW
        )

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
        history, trimming entries older than ``TEMPERATURE_MEDIAN_WINDOW``
        so it doesn't grow unbounded over a long-running script.

        Parameters
        ----------
        data : `salobj.BaseMsgType`
            ESS temperature telemetry sample.
        """
        now = data.private_sndStamp
        self._outside_temperature_history.append((now, data.temperatureItem[0]))

        cutoff = now - TEMPERATURE_MEDIAN_WINDOW
        self._outside_temperature_history = [
            sample
            for sample in self._outside_temperature_history
            if sample[0] >= cutoff
        ]

    async def _indoor_temperature_callback(self, data):
        """Append an ESS in-dome temperature sample to the rolling
        history, trimming entries older than ``TEMPERATURE_MEDIAN_WINDOW``
        so it doesn't grow unbounded over a long-running script.

        Parameters
        ----------
        data : `salobj.BaseMsgType`
            ESS temperature telemetry sample.
        """
        now = data.private_sndStamp
        self._indoor_temperature_history.append((now, data.temperatureItem[0]))

        cutoff = now - TEMPERATURE_MEDIAN_WINDOW
        self._indoor_temperature_history = [
            sample for sample in self._indoor_temperature_history if sample[0] >= cutoff
        ]

    @staticmethod
    def _median_within_window(history, window):
        """Return the median of ``history`` values within the trailing
        ``window`` seconds of now.

        Parameters
        ----------
        history : `list` of (`float`, `float`)
            ``(timestamp, value)`` samples.
        window : `float`
            Trailing window, in seconds.

        Returns
        -------
        `float` or `None`
            The median value, or `None` if no samples fall within the
            window.
        """
        cutoff = utils.current_tai() - window
        values = [value for t, value in history if t >= cutoff]
        return statistics.median(values) if values else None

    async def _air_flow_callback(self, data):
        """Append an ESS airFlow direction sample to the wind history,
        trimming entries older than ``WIND_DIRECTION_MEDIAN_WINDOW`` so it
        doesn't grow unbounded over a long-running script (e.g. a lengthy
        wait in `wait_for_temperature_condition`). Wind speed is not
        tracked.

        This trim is only to bound memory: `get_wind_direction` still
        computes its own precise trailing window, relative to the moment
        it's called, from whatever remains here.

        Parameters
        ----------
        data : `salobj.BaseMsgType`
            ESS airFlow telemetry sample.
        """
        now = data.private_sndStamp
        self._wind_history.append((now, data.direction))

        cutoff = now - WIND_DIRECTION_MEDIAN_WINDOW
        self._wind_history = [
            sample for sample in self._wind_history if sample[0] >= cutoff
        ]

    async def get_wind_direction(self):
        """Get the median wind direction from the ESS weather station over
        the ``WIND_DIRECTION_MEDIAN_WINDOW`` seconds prior to this call.

        Median-filtering avoids reacting to a single noisy sample in favor
        of the sustained wind direction. This is only ever called at the
        two points where the dome is repositioned for the wind (see
        `reposition_dome_for_wind`), not continuously.

        Returns
        -------
        `float` or `None`
            Median wind direction (degrees, 0 = north, 90 = east) over the
            ``WIND_DIRECTION_MEDIAN_WINDOW`` seconds prior to this call, or
            `None` if no samples were collected in that window.
        """
        cutoff = utils.current_tai() - WIND_DIRECTION_MEDIAN_WINDOW
        directions = [direction for t, direction in self._wind_history if t >= cutoff]
        if not directions:
            return None

        return self._circular_median(directions)

    @staticmethod
    def _circular_median(angles_deg):
        """Return the circular median of a list of angles.

        Returns whichever observed angle minimizes the sum of absolute
        circular distances to all other samples. This handles wraparound
        (e.g. samples clustered near 0/360 deg) correctly and, like a
        standard median, is resistant to outliers.

        Parameters
        ----------
        angles_deg : `list` of `float`
            Angles, in degrees.

        Returns
        -------
        `float`
            The circular median, in degrees.
        """
        return min(
            angles_deg,
            key=lambda candidate: sum(
                abs(angle_diff(candidate, other).deg) for other in angles_deg
            ),
        )

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

    async def wait_for_temperature_condition(self):
        """Wait until the outside temperature is close enough to the in-dome
        temperature to begin venting.

        Returns
        -------
        `bool`
            `True` once the temperature condition is met. `False` if the sun
            reaches ``SUN_ELEVATION_STOP`` before the condition is met.
        """
        outside_temp = self.get_outside_temperature()
        indoor_temp = self.get_indoor_temperature()
        _, sun_el = self.get_sun_azel()

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

            outside_temp = self.get_outside_temperature()
            indoor_temp = self.get_indoor_temperature()
            _, sun_el = self.get_sun_azel()

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
        else:
            self.log.warning(
                "Sun reached the stop elevation before the temperature "
                "condition was met."
            )
        return condition_met

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
        wind_direction = await self.get_wind_direction()
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

    async def wait_for_sun_elevation_high(self):
        """Wait until the sun descends to ``SUN_ELEVATION_HIGH``.

        The shutter and louvers are not touched at all during this wait;
        the dome is only ever nudged the minimum amount needed to stay
        clear of the sun (see `compute_sun_safe_azimuth`).
        """
        sun_az, sun_el = self.get_sun_azel()

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
            sun_az, sun_el = self.get_sun_azel()

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
        moved for the wind. The aperture shutter is opened every iteration
        from here on, and the louvers are opened, either capped for sun
        avoidance (see `compute_louver_positions`) while the sun is above
        ``SUN_ELEVATION_HORIZON`` or fully open once it is not.
        """
        sun_az, _ = self.get_sun_azel()
        await self.checkpoint("Positioning dome for the current wind direction.")
        await self.reposition_dome_for_wind(sun_az, clamp_to_sun_avoidance_range=True)

        await self.wait_for_sun_elevation_high()

        repositioned_for_wind_after_sunset = False
        sun_az, sun_el = self.get_sun_azel()

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
                    await self.point_telescope_to_vent_position(dome_az)
                    repositioned_for_wind_after_sunset = True

                await self.checkpoint(
                    "Sun elevation below SUN_ELEVATION_HORIZON, positioning "
                    f"dome and telescope to point into wind ({dome_az:.1f} "
                    "deg)."
                )
                full_positions = {louver.name: 100.0 for louver in MTDome.Louver}

            self.log.info("Opening dome shutter.")
            await self.mtcs.open_dome_shutter()

            louver_position = self.get_enabled_louver_positions(full_positions)
            self.log.info("Opening dome louvers.")
            await self.mtcs.open_dome_louvers(position=louver_position)

            await asyncio.sleep(self.loop_wait_time)
            sun_az, sun_el = self.get_sun_azel()

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

        sun_az, _ = self.get_sun_azel()
        await self.checkpoint("Pointing dome shutter away from the sun.")
        await self.point_dome_away_from_sun(sun_az)

        dome_az = await self.get_dome_azimuth()
        await self.checkpoint("Pointing telescope to initial dome azimuth.")
        await self.point_telescope_to_vent_position(dome_az)

        await self.checkpoint("Closing mirror covers.")
        await self.mtcs.close_m1_cover()

        outside_temp = self.get_outside_temperature()
        indoor_temp = self.get_indoor_temperature()
        await self.checkpoint(
            "Waiting for outside temperature to drop below in-dome temperature: "
            f"outside={self._format_temperature(outside_temp)}, "
            f"indoor={self._format_temperature(indoor_temp)}, "
            f"limit={TEMPERATURE_DIFFERENTIAL_THRESHOLD} C."
        )
        temperature_condition_met = await self.wait_for_temperature_condition()

        if temperature_condition_met:
            await self.vent_while_sun_sets()
        else:
            await self.checkpoint(
                "Sun reached the stop elevation before the temperature condition "
                "was met; opening dome shutters and louvers to 100 percent."
            )
            sun_az, _ = self.get_sun_azel()
            await self.reposition_dome_for_wind(
                sun_az, clamp_to_sun_avoidance_range=False
            )
            await self.mtcs.open_dome_shutter()
            full_positions = {louver.name: 100.0 for louver in MTDome.Louver}
            await self.mtcs.open_dome_louvers(
                position=self.get_enabled_louver_positions(full_positions)
            )
