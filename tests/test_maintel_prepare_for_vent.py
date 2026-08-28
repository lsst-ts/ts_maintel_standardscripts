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

import collections
import contextlib
import unittest
from unittest.mock import AsyncMock, Mock, patch

import astropy.units as u
import numpy as np
from astropy.stats import circmean
from lsst.ts import standardscripts
from lsst.ts.maintel.standardscripts.prepare_for.vent import (
    VENT_PARAMS,
    PrepareForVent,
    VentCondition,
)
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages
from lsst.ts.utils import angle_wrap_center
from lsst.ts.xml.enums import MTDome


class TestPrepareForVent(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        self.script = PrepareForVent(index=index)

        return (self.script,)

    @contextlib.asynccontextmanager
    async def make_dry_script(self):
        async with self.make_script():
            self.script.mtcs = MTCS(
                domain=self.script.domain,
                intended_usage=MTCSUsages.DryTest,
                log=self.script.log,
            )
            self.script.mtcs.assert_all_enabled = AsyncMock()
            self.script.mtcs.disable_dome_following = AsyncMock()
            self.script.mtcs.slew_dome_to = AsyncMock()
            self.script.mtcs.close_m1_cover = AsyncMock()
            self.script.mtcs.open_dome_shutter = AsyncMock()
            self.script.mtcs.open_dome_louvers = AsyncMock()
            self.script.mtcs.get_enabled_dome_louvers = AsyncMock(
                return_value=list(MTDome.Louver)
            )
            self.script.mtcs.assert_dome_louvers_enabled = AsyncMock()
            self.script.mtcs.point_azel = AsyncMock()
            self.script.mtcs.stop_tracking = AsyncMock()
            self.script.mtcs.get_sun_azel = Mock(return_value=(180.0, 45.0))

            self.script.loop_wait_time = 0.0

            self.script.get_dome_azimuth = AsyncMock(return_value=0.0)

            # Pre-set so configure() skips creating real salobj.Remote
            # objects (its callbacks are exercised directly, by calling the
            # *_callback methods, not through live remotes).
            self.script.ess_outside = Mock()
            self.script._outside_temperature_history = collections.deque(
                [10.0], maxlen=30
            )

            self.script.ess_indoor = Mock()
            self.script._indoor_temperature_history = collections.deque(
                [15.0], maxlen=30
            )

            yield

    async def test_config_defaults_to_all_louvers(self):
        async with self.make_dry_script():
            await self.configure_script()

            assert self.script.louvers == "all"

    async def test_config_accepts_explicit_louver_list(self):
        async with self.make_dry_script():
            await self.configure_script(louvers=["A1", "E2"])

            assert self.script.louvers == ["A1", "E2"]

    async def test_compute_louver_positions(self):
        # Wrapped in make_dry_script(), even though this test never touches
        # self.script, because BaseScriptTestCase.asyncTearDown always tries
        # to clean up SAL topics and needs the per-test state make_script()
        # sets up to do that.
        async with self.make_dry_script():
            cases = [
                (
                    "sun_at_aperture",
                    dict(dome_az=0.0, sun_az=0.0),
                    VENT_PARAMS.louver_sun_exposed_percent,
                    100.0,
                ),
                (
                    "sun_opposite_aperture",
                    dict(dome_az=0.0, sun_az=180.0),
                    100.0,
                    VENT_PARAMS.louver_sun_exposed_percent,
                ),
            ]
            for name, kwargs, expected_a1, expected_f1 in cases:
                with self.subTest(name):
                    positions = PrepareForVent.compute_louver_positions(**kwargs)
                    assert len(positions) == 34
                    assert positions["A1"] == expected_a1
                    assert positions["F1"] == expected_f1

    async def test_get_enabled_louver_positions_drops_disabled_louvers(self):
        async with self.make_dry_script():
            self.script._active_louvers = {"A1", "F1"}
            full_positions = {louver.name: 42.0 for louver in MTDome.Louver}

            positions = self.script.get_enabled_louver_positions(full_positions)

            assert positions == {"A1": 42.0, "F1": 42.0}

    async def test_wait_for_vent_condition_handles_no_samples_yet(self):
        # Regression test: np.median silently returns nan (not None) for an
        # empty array, rather than raising -- so wait_for_vent_condition
        # must explicitly treat "no samples yet" as "condition not met"
        # instead of crashing or misreading nan as a real temperature.
        async with self.make_dry_script():
            self.script._outside_temperature_history = collections.deque(maxlen=30)
            self.script._indoor_temperature_history = collections.deque(maxlen=30)
            self.script.mtcs.get_sun_azel = Mock(
                return_value=(180.0, VENT_PARAMS.sun_elevation_stop)
            )

            vent_condition = await self.script.wait_for_vent_condition()

            assert vent_condition == VentCondition.SUN_ELEVATION

    async def test_compute_sun_safe_azimuth(self):
        # See test_compute_louver_positions for why this is wrapped in
        # make_dry_script() despite never touching self.script.
        async with self.make_dry_script():
            cases = [
                ("already_safe_unchanged", (120.0, 0.0), 120.0),
                ("nudges_to_nearer_edge_ahead_of_sun", (10.0, 0.0), 60.0),
                ("nudges_to_nearer_edge_behind_sun", (350.0, 0.0), 300.0),
            ]
            for name, args, expected in cases:
                with self.subTest(name):
                    assert PrepareForVent.compute_sun_safe_azimuth(*args) == expected

    async def test_reposition_dome_for_wind(self):
        # circmean's sin/cos round-trip isn't bit-exact even for a single
        # sample (e.g. circmean([200.0 deg]) comes back ~199.99999999999997,
        # not exactly 200.0), so the expected wind direction is computed the
        # same way the implementation does rather than asserted as a
        # literal.
        single_sample_wind = (
            circmean(np.asarray([200.0]) * u.deg).to_value(u.deg) % 360.0
        )

        async with self.make_dry_script():
            self.script._wind_history = collections.deque([200.0], maxlen=600)

            dome_az = await self.script.reposition_dome_for_wind(
                sun_az=0.0, clamp_to_sun_avoidance_range=True
            )

            # single_sample_wind is outside [dome_min_az, dome_max_az], so
            # it's clamped to dome_max_az.
            assert dome_az == VENT_PARAMS.dome_max_az
            self.script.mtcs.slew_dome_to.assert_awaited_once_with(
                VENT_PARAMS.dome_max_az
            )

        async with self.make_dry_script():
            self.script._wind_history = collections.deque([200.0], maxlen=600)

            dome_az = await self.script.reposition_dome_for_wind(
                sun_az=0.0, clamp_to_sun_avoidance_range=False
            )

            # Not clamped: the sun-avoidance constraint no longer applies.
            assert dome_az == single_sample_wind
            self.script.mtcs.slew_dome_to.assert_awaited_once_with(single_sample_wind)

        async with self.make_dry_script():
            # No wind data available: falls back to a direction safely
            # away from the sun (sun_az + 180) instead of blocking or
            # raising.
            self.script._wind_history = collections.deque(maxlen=600)

            dome_az = await self.script.reposition_dome_for_wind(
                sun_az=30.0, clamp_to_sun_avoidance_range=False
            )

            assert dome_az == 210.0
            self.script.mtcs.slew_dome_to.assert_awaited_once_with(210.0)

        async with self.make_dry_script():
            # Same fallback, but clamped since the sun is still up:
            # away = (100 + 180) % 360 = 280, clamped down to dome_max_az.
            self.script._wind_history = collections.deque(maxlen=600)

            dome_az = await self.script.reposition_dome_for_wind(
                sun_az=100.0, clamp_to_sun_avoidance_range=True
            )

            assert dome_az == VENT_PARAMS.dome_max_az
            self.script.mtcs.slew_dome_to.assert_awaited_once_with(
                VENT_PARAMS.dome_max_az
            )

        async with self.make_dry_script():
            # Samples clustered near the 0/360 boundary should circular-mean
            # near 0, not naively average toward 180 the way a plain
            # numeric mean would. Computed rather than hand-derived (same
            # call the implementation itself makes), to avoid arithmetic
            # mistakes.
            samples = [350.0, 355.0, 5.0, 10.0]
            self.script._wind_history = collections.deque(samples, maxlen=600)

            dome_az = await self.script.reposition_dome_for_wind(
                sun_az=180.0, clamp_to_sun_avoidance_range=False
            )

            expected = circmean(np.asarray(samples) * u.deg).to_value(u.deg) % 360.0
            assert dome_az == expected
            self.script.mtcs.slew_dome_to.assert_awaited_once_with(expected)

    @patch.multiple(
        PrepareForVent,
        wait_for_vent_condition=AsyncMock(
            return_value=VentCondition.TEMPERATURE_CONDITION_MET
        ),
    )
    async def test_vent_while_sun_sets_progresses_through_sun_elevation_bands(self):
        async with self.make_dry_script():
            # Any non-empty history is enough here: circmean itself is
            # mocked below (its correctness is covered separately by
            # test_reposition_dome_for_wind) -- this just needs to satisfy
            # reposition_dome_for_wind's "do we have wind data at all" guard.
            self.script._wind_history = collections.deque([0.0], maxlen=600)
            # get_dome_azimuth is called exactly twice now: once in
            # wait_for_sun_elevation_high's nudge check, once in the main
            # loop's first (sun > horizon) iteration's nudge check. run()'s
            # initial telescope pointing no longer reads it back -- it
            # reuses the dome azimuth it just computed and commanded.
            self.script.get_dome_azimuth = AsyncMock(side_effect=[260.0, 180.0])
            # wait_for_sun_elevation_high now runs before the wind-facing
            # reposition (see vent_while_sun_sets), so its two reads come
            # first; the wind-reposition's own fresh read (only sun_az is
            # used, elevation is discarded) comes right after the wait ends.
            self.script.mtcs.get_sun_azel = Mock(
                side_effect=[
                    (180.0, 45.0),  # run() preflight
                    (270.0, 10.0),  # wait_for_sun_elevation_high: initial, > high
                    (270.0, 3.0),  # end of wait iteration: <= high, wait exits
                    (270.0, 3.0),  # fresh read for wind reposition (wind az)
                    (200.0, 3.0),  # main loop iter A: between high and horizon
                    (45.0, -2.0),  # iter A end / iter B: at/below horizon (first)
                    (45.0, -3.0),  # iter B end / iter C: still at/below horizon
                    (45.0, VENT_PARAMS.sun_elevation_stop),  # iter C end: loop exit
                ]
            )

            with patch(
                "lsst.ts.maintel.standardscripts.prepare_for.vent.circmean",
                side_effect=[200.0 * u.deg, 250.0 * u.deg],
            ):
                await self.configure_script()
                await self.run_script()

            # Computed rather than hand-derived, to avoid arithmetic
            # mistakes; compute_sun_safe_azimuth itself has its own
            # dedicated test for the underlying math.
            expected_wait_nudge = min(
                max(
                    PrepareForVent.compute_sun_safe_azimuth(260.0, 270.0),
                    VENT_PARAMS.dome_min_az,
                ),
                VENT_PARAMS.dome_max_az,
            )
            expected_main_nudge = min(
                max(
                    PrepareForVent.compute_sun_safe_azimuth(180.0, 200.0),
                    VENT_PARAMS.dome_min_az,
                ),
                VENT_PARAMS.dome_max_az,
            )
            # run()'s initial dome target: sun_az=180 -> away=(180+180)%360=0,
            # clamped up to dome_min_az.
            initial_dome_az = VENT_PARAMS.dome_min_az
            slew_calls = [
                c.args[0] for c in self.script.mtcs.slew_dome_to.call_args_list
            ]
            assert slew_calls == [
                initial_dome_az,  # preflight: away from sun, clamped
                expected_wait_nudge,  # nudge while waiting for sun_elevation_high
                VENT_PARAMS.dome_max_az,  # wind-facing positioning after the wait
                expected_main_nudge,  # nudge between high and horizon
                250.0,  # repositioned for wind after sunset, unclamped
            ]

            # open_dome_shutter_if_needed/open_dome_louvers_if_needed only
            # send a command when the desired state actually changed, so
            # the shutter is only sent once (iter A) and the louvers only
            # twice (iter A's sun-avoidance-capped set, then iter B's
            # fully-open set -- iter C's is identical to iter B's and gets
            # skipped).
            self.script.mtcs.open_dome_shutter.assert_awaited_once()

            louver_calls = [
                call.kwargs["position"]
                for call in self.script.mtcs.open_dome_louvers.call_args_list
            ]
            assert len(louver_calls) == 2
            # Sun-avoidance-capped dict (all 34 louvers, all enabled per
            # the fixture default) between high and horizon...
            assert len(louver_calls[0]) == 34
            # ...fully open once the sun is at/below the horizon.
            assert louver_calls[1] == {louver.name: 100.0 for louver in MTDome.Louver}

            # The telescope is repositioned twice: once at the very start
            # (reusing the just-commanded away-from-sun dome target), and
            # once more to follow the dome after the sun drops below the
            # sun horizon limit. Dome azimuths are wrapped to the mount's
            # [-260, 260] deg travel range before being sent to the
            # telescope: initial_dome_az is already in range, but 250.0 is
            # not and comes out as -110.0.
            telescope_az_calls = [
                call.kwargs["az"] for call in self.script.mtcs.point_azel.call_args_list
            ]
            assert telescope_az_calls == [
                angle_wrap_center(initial_dome_az).deg,
                angle_wrap_center(250.0).deg,
            ]
            assert self.script.mtcs.stop_tracking.await_count == 2

    @patch.multiple(
        PrepareForVent,
        wait_for_vent_condition=AsyncMock(
            return_value=VentCondition.TEMPERATURE_CONDITION_MET
        ),
        vent_while_sun_sets=AsyncMock(),
    )
    async def test_run_temperature_met(self):
        async with self.make_dry_script():
            await self.configure_script()
            await self.run_script()

            self.script.mtcs.assert_all_enabled.assert_awaited_once()
            self.script.mtcs.disable_dome_following.assert_awaited_once()
            self.script.mtcs.slew_dome_to.assert_awaited_once_with(
                VENT_PARAMS.dome_min_az
            )
            self.script.mtcs.point_azel.assert_awaited_once_with(
                target_name="Vent Position",
                az=VENT_PARAMS.dome_min_az,
                el=VENT_PARAMS.tel_vent_elevation,
                rot_tel=self.script.mtcs.tel_park_rot,
                wait_dome=False,
            )
            self.script.mtcs.stop_tracking.assert_awaited_once()
            self.script.mtcs.close_m1_cover.assert_awaited_once()
            self.script.wait_for_vent_condition.assert_awaited_once()
            self.script.vent_while_sun_sets.assert_awaited_once()

    @patch.multiple(
        PrepareForVent,
        wait_for_vent_condition=AsyncMock(return_value=VentCondition.SUN_ELEVATION),
        vent_while_sun_sets=AsyncMock(),
    )
    async def test_run_temperature_not_met(self):
        async with self.make_dry_script():
            await self.configure_script()
            await self.run_script()

            self.script.vent_while_sun_sets.assert_not_awaited()
            self.script.mtcs.slew_dome_to.assert_awaited_with(0.0)
            self.script.mtcs.open_dome_shutter.assert_awaited_once()
            self.script.mtcs.open_dome_louvers.assert_awaited_once_with(
                position={louver.name: 100.0 for louver in MTDome.Louver}
            )


if __name__ == "__main__":
    unittest.main()
