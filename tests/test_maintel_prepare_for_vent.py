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

import contextlib
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

from lsst.ts import standardscripts, utils
from lsst.ts.maintel.standardscripts.prepare_for import PrepareForVent
from lsst.ts.maintel.standardscripts.prepare_for.vent import (
    DOME_MAX_AZ,
    DOME_MIN_AZ,
    LOUVER_SUN_EXPOSED_PERCENT,
    SUN_ELEVATION_STOP,
    TEL_VENT_ELEVATION,
    WIND_DIRECTION_MEDIAN_WINDOW,
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
            self.script.mtcs.close_dome_louvers = AsyncMock()
            self.script.mtcs.get_enabled_dome_louvers = AsyncMock(
                return_value=list(MTDome.Louver)
            )
            self.script.mtcs.assert_dome_louvers_enabled = AsyncMock()
            self.script.mtcs.close_dome = AsyncMock()
            self.script.mtcs.point_azel = AsyncMock()
            self.script.mtcs.stop_tracking = AsyncMock()
            self.script.mtcs.get_sun_azel = Mock(return_value=(180.0, 45.0))

            self.script.loop_wait_time = 0.0

            self.script.get_dome_azimuth = AsyncMock(return_value=0.0)

            # get_outside_temperature/get_indoor_temperature read from these
            # histories directly (tel_temperature has a callback registered
            # on it in real use, so it can't also be pulled with .aget()).
            self.script.ess_outside = Mock()
            self.script._outside_temperature_history = [(utils.current_tai(), 10.0)]

            self.script.ess_indoor = Mock()
            self.script._indoor_temperature_history = [(utils.current_tai(), 15.0)]

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
        cases = [
            (
                "sun_at_aperture",
                dict(dome_az=0.0, sun_az=0.0),
                LOUVER_SUN_EXPOSED_PERCENT,
                100.0,
            ),
            (
                "sun_opposite_aperture",
                dict(dome_az=0.0, sun_az=180.0),
                100.0,
                LOUVER_SUN_EXPOSED_PERCENT,
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

    async def test_air_flow_callback_prunes_stale_samples(self):
        # Bounds memory over a long-running script; get_wind_direction
        # still computes its own precise trailing window separately.
        async with self.make_dry_script():
            stale_stamp = 1000.0 - WIND_DIRECTION_MEDIAN_WINDOW - 10.0
            self.script._wind_history.append((stale_stamp, 0.0))

            fresh = types.SimpleNamespace(direction=200.0, private_sndStamp=1000.0)
            await self.script._air_flow_callback(fresh)

            assert len(self.script._wind_history) == 1
            assert self.script._wind_history[0] == (1000.0, 200.0)

    async def test_wait_for_temperature_condition_handles_no_samples_yet(self):
        # Regression test: tel_temperature has a callback registered on it
        # (see configure), so get_outside_temperature/get_indoor_temperature
        # must return None -- not fall back to .aget(), which salobj
        # disallows on a topic with a callback -- and
        # wait_for_temperature_condition must treat None as "not yet met"
        # rather than crashing on None-arithmetic.
        async with self.make_dry_script():
            self.script._outside_temperature_history = []
            self.script._indoor_temperature_history = []
            self.script.mtcs.get_sun_azel = Mock(
                return_value=(180.0, SUN_ELEVATION_STOP)
            )

            condition_met = await self.script.wait_for_temperature_condition()

            assert condition_met is False
            self.script.ess_outside.tel_temperature.aget.assert_not_called()
            self.script.ess_indoor.tel_temperature.aget.assert_not_called()

    async def test_circular_median_handles_wraparound(self):
        # Samples clustered near the 0/360 boundary should not average
        # toward 180 the way a naive numeric median would.
        median = PrepareForVent._circular_median([350.0, 355.0, 5.0, 10.0])
        assert median == 355.0

    async def test_point_dome_away_from_sun_clamps_within_dome_limits(self):
        async with self.make_dry_script():
            # Sun in the south (180 deg): directly away is 0.0, out of
            # range, clamped to DOME_MIN_AZ.
            await self.script.point_dome_away_from_sun(sun_az=180.0)
            self.script.mtcs.slew_dome_to.assert_awaited_once_with(DOME_MIN_AZ)

        async with self.make_dry_script():
            # Sun azimuth chosen so "directly away" lands exactly at the
            # midpoint of [DOME_MIN_AZ, DOME_MAX_AZ] -- already in range,
            # regardless of the exact values of those two constants.
            midpoint = (DOME_MIN_AZ + DOME_MAX_AZ) / 2.0
            sun_az = (midpoint - 180.0) % 360.0
            await self.script.point_dome_away_from_sun(sun_az=sun_az)
            self.script.mtcs.slew_dome_to.assert_awaited_once_with(midpoint)

    async def test_compute_sun_safe_azimuth(self):
        cases = [
            ("already_safe_unchanged", (120.0, 0.0), 120.0),
            ("nudges_to_nearer_edge_ahead_of_sun", (10.0, 0.0), 60.0),
            ("nudges_to_nearer_edge_behind_sun", (350.0, 0.0), 300.0),
        ]
        for name, args, expected in cases:
            with self.subTest(name):
                assert PrepareForVent.compute_sun_safe_azimuth(*args) == expected

    async def test_reposition_dome_for_wind(self):
        async with self.make_dry_script():
            self.script.get_wind_direction = AsyncMock(return_value=200.0)

            dome_az = await self.script.reposition_dome_for_wind(
                sun_az=0.0, clamp_to_sun_avoidance_range=True
            )

            # 200 deg is outside [DOME_MIN_AZ, DOME_MAX_AZ], so it's
            # clamped to DOME_MAX_AZ.
            assert dome_az == DOME_MAX_AZ
            self.script.mtcs.slew_dome_to.assert_awaited_once_with(DOME_MAX_AZ)

        async with self.make_dry_script():
            self.script.get_wind_direction = AsyncMock(return_value=200.0)

            dome_az = await self.script.reposition_dome_for_wind(
                sun_az=0.0, clamp_to_sun_avoidance_range=False
            )

            # Not clamped: the sun-avoidance constraint no longer applies.
            assert dome_az == 200.0
            self.script.mtcs.slew_dome_to.assert_awaited_once_with(200.0)

        async with self.make_dry_script():
            # No wind data available: falls back to a direction safely
            # away from the sun (sun_az + 180) instead of blocking or
            # raising.
            self.script.get_wind_direction = AsyncMock(return_value=None)

            dome_az = await self.script.reposition_dome_for_wind(
                sun_az=30.0, clamp_to_sun_avoidance_range=False
            )

            assert dome_az == 210.0
            self.script.mtcs.slew_dome_to.assert_awaited_once_with(210.0)

        async with self.make_dry_script():
            # Same fallback, but clamped since the sun is still up:
            # away = (100 + 180) % 360 = 280, clamped down to DOME_MAX_AZ.
            self.script.get_wind_direction = AsyncMock(return_value=None)

            dome_az = await self.script.reposition_dome_for_wind(
                sun_az=100.0, clamp_to_sun_avoidance_range=True
            )

            assert dome_az == DOME_MAX_AZ
            self.script.mtcs.slew_dome_to.assert_awaited_once_with(DOME_MAX_AZ)

    @patch.multiple(
        PrepareForVent,
        wait_for_temperature_condition=AsyncMock(return_value=True),
    )
    async def test_vent_while_sun_sets_progresses_through_sun_elevation_bands(self):
        async with self.make_dry_script():
            self.script.get_wind_direction = AsyncMock(side_effect=[200.0, 250.0])
            # [run preflight, wait-phase nudge check, main-loop nudge check]
            self.script.get_dome_azimuth = AsyncMock(side_effect=[50.0, 260.0, 180.0])
            self.script.get_sun_azel = Mock(
                side_effect=[
                    (180.0, 45.0),  # run() preflight
                    (270.0, 45.0),  # vent_while_sun_sets preflight (wind az)
                    (270.0, 10.0),  # wait_for_sun_elevation_high: initial, > HIGH
                    (270.0, 3.0),  # end of wait iteration: <= HIGH, wait exits
                    (200.0, 3.0),  # main loop iter A: between HIGH and HORIZON
                    (45.0, -2.0),  # iter A end / iter B: at/below HORIZON (first)
                    (45.0, -3.0),  # iter B end / iter C: still at/below HORIZON
                    (45.0, SUN_ELEVATION_STOP),  # iter C end: loop exit
                ]
            )

            await self.configure_script()
            await self.run_script()

            # Computed rather than hand-derived, to avoid arithmetic
            # mistakes; compute_sun_safe_azimuth itself has its own
            # dedicated test for the underlying math.
            expected_wait_nudge = min(
                max(PrepareForVent.compute_sun_safe_azimuth(260.0, 270.0), DOME_MIN_AZ),
                DOME_MAX_AZ,
            )
            expected_main_nudge = min(
                max(PrepareForVent.compute_sun_safe_azimuth(180.0, 200.0), DOME_MIN_AZ),
                DOME_MAX_AZ,
            )
            slew_calls = [
                c.args[0] for c in self.script.mtcs.slew_dome_to.call_args_list
            ]
            assert slew_calls == [
                DOME_MIN_AZ,  # preflight: away from sun, clamped
                DOME_MAX_AZ,  # initial wind-facing positioning, clamped (200)
                expected_wait_nudge,  # nudge while waiting for SUN_ELEVATION_HIGH
                expected_main_nudge,  # nudge between HIGH and HORIZON
                250.0,  # repositioned for wind after sunset, unclamped
            ]

            # The shutter/louvers are never touched while waiting for the
            # sun to reach SUN_ELEVATION_HIGH: exactly 3 calls, one per
            # main-loop iteration, none during the wait phase.
            assert self.script.mtcs.open_dome_shutter.await_count == 3

            louver_calls = [
                call.kwargs["position"]
                for call in self.script.mtcs.open_dome_louvers.call_args_list
            ]
            assert len(louver_calls) == 3
            # Sun-avoidance-capped dict (all 34 louvers, all enabled per
            # the fixture default) between HIGH and HORIZON...
            assert len(louver_calls[0]) == 34
            # ...fully open once the sun is at/below the horizon.
            assert louver_calls[1] == {louver.name: 100.0 for louver in MTDome.Louver}
            assert louver_calls[2] == {louver.name: 100.0 for louver in MTDome.Louver}

            # The telescope is repositioned twice: once at the very start
            # (following the dome to its away-from-sun azimuth), and once
            # more to follow the dome after the sun drops below
            # SUN_ELEVATION_HORIZON.
            # Dome azimuths are wrapped to the mount's [-260, 260] deg
            # travel range before being sent to the telescope: 50.0 is
            # already in range, but 250.0 is not and comes out as -110.0.
            telescope_az_calls = [
                call.kwargs["az"] for call in self.script.mtcs.point_azel.call_args_list
            ]
            assert telescope_az_calls == [50.0, angle_wrap_center(250.0).deg]
            assert self.script.mtcs.stop_tracking.await_count == 2

    @patch.multiple(
        PrepareForVent,
        wait_for_temperature_condition=AsyncMock(return_value=True),
        vent_while_sun_sets=AsyncMock(),
    )
    async def test_run_temperature_met(self):
        async with self.make_dry_script():
            await self.configure_script()
            await self.run_script()

            self.script.mtcs.assert_all_enabled.assert_awaited_once()
            self.script.mtcs.disable_dome_following.assert_awaited_once()
            self.script.mtcs.slew_dome_to.assert_awaited_once_with(DOME_MIN_AZ)
            self.script.mtcs.point_azel.assert_awaited_once_with(
                target_name="Vent Position",
                az=0.0,
                el=TEL_VENT_ELEVATION,
                rot_tel=self.script.mtcs.tel_park_rot,
                wait_dome=False,
            )
            self.script.mtcs.stop_tracking.assert_awaited_once()
            self.script.mtcs.close_m1_cover.assert_awaited_once()
            self.script.wait_for_temperature_condition.assert_awaited_once()
            self.script.vent_while_sun_sets.assert_awaited_once()

    @patch.multiple(
        PrepareForVent,
        wait_for_temperature_condition=AsyncMock(return_value=False),
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
