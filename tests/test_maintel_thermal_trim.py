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

import unittest

import numpy as np
import pandas as pd
from lsst.ts.maintel.standardscripts.thermal_trim import (
    GRADIENT_FIELDS,
    GRADIENTS_TOPIC,
    TRUSS_TOPIC,
    ThermalTelemetry,
    TrimCalculator,
    get_thermal_telemetry,
)
from lsst.ts.observatory.control.utils.enums import DOFName

GRADIENT_COLUMNS = list(GRADIENT_FIELDS.values())
TRUSS_COLUMNS = ["temperatureItem6", "temperatureItem7"]


def make_frame(columns, rows, age):
    """Make a time-indexed DataFrame whose last row is ``age`` s old."""
    index = pd.date_range(
        end=pd.Timestamp.now(tz="UTC") - pd.Timedelta(seconds=age),
        periods=len(rows),
        freq="10s",
    )
    return pd.DataFrame(rows, columns=columns, index=index)


class FakeEfdClient:
    """EFD client stub returning canned truss and gradient frames."""

    def __init__(self, truss, gradients):
        self.truss = truss
        self.gradients = gradients
        self.calls = []

    async def select_time_series(self, topic, fields, start, end, index=None):
        self.calls.append((topic, fields, index))
        return self.truss if topic == TRUSS_TOPIC else self.gradients


class TestTrimCalculator(unittest.TestCase):
    def setUp(self):
        self.calc = TrimCalculator()

    def test_predict_trim(self):
        v1, v1_dz, dof = self.calc.predict_trim(11.3, -0.0656, -0.0196, -0.0168, 0.0017)

        expected_dz = (
            self.calc.intercept_um
            + self.calc.truss_um_per_c * 11.3
            + self.calc.gradient_um_per_c_per_m["z"] * -0.0656
            + self.calc.gradient_um_per_c_per_m["y"] * -0.0196
            + self.calc.gradient_um_per_c_per_m["radial"] * -0.0168
            + self.calc.gradient_um_per_c_per_m["x"] * 0.0017
        )
        self.assertAlmostEqual(v1_dz, expected_dz)
        self.assertAlmostEqual(v1, expected_dz * self.calc.v1_per_um_dz)
        self.assertEqual(set(dof), {"M2_dz", "Cam_dz", "M1M3_B3", "M2_B5"})
        for name, value in dof.items():
            self.assertAlmostEqual(value, self.calc.v1_dof_um_per_unit[name] * v1)
            self.assertAlmostEqual(self.calc.v1_dof_vector[DOFName[name]] * v1, value)

    def test_predict_from_telemetry_without_gradients(self):
        telemetry = ThermalTelemetry(
            truss_temp_c=10.0, truss_n_samples=1, truss_age=0.0
        )
        features = self.calc.features_from_telemetry(telemetry)
        self.assertEqual(features["truss_temp_c"], 10.0)
        for name, value in features.items():
            if name != "truss_temp_c":
                self.assertEqual(value, 0.0)
        self.assertEqual(
            self.calc.predict_from_telemetry(telemetry), self.calc.predict_trim(10.0)
        )

    def test_telemetry_from_config(self):
        telemetry = ThermalTelemetry.from_config(dict(truss_temp_c=11.3))
        self.assertEqual(telemetry.truss_temp_c, 11.3)
        self.assertIsNone(telemetry.gradients)

        # Partial gradients count as unavailable.
        telemetry = ThermalTelemetry.from_config(
            dict(truss_temp_c=11.3, z_gradient_c_per_m=-0.07)
        )
        self.assertIsNone(telemetry.gradients)

        telemetry = ThermalTelemetry.from_config(
            dict(
                truss_temp_c=11.3,
                x_gradient_c_per_m=0.0017,
                y_gradient_c_per_m=-0.0196,
                z_gradient_c_per_m=-0.0656,
                radial_gradient_c_per_m=-0.0168,
            )
        )
        self.assertEqual(
            telemetry.gradients,
            dict(x=0.0017, y=-0.0196, z=-0.0656, radial=-0.0168),
        )
        v1, _, _ = self.calc.predict_from_telemetry(telemetry)
        expected_v1, _, _ = self.calc.predict_trim(
            11.3, -0.0656, -0.0196, -0.0168, 0.0017
        )
        self.assertAlmostEqual(v1, expected_v1)

    def test_extrapolated_features(self):
        self.assertEqual(self.calc.extrapolated_features(truss_temp_c=10.0), [])
        outside = self.calc.extrapolated_features(
            truss_temp_c=30.0, z_gradient_c_per_m=0.0
        )
        self.assertEqual(len(outside), 1)
        self.assertIn("truss_temp_c", outside[0])

    def test_dof_offset(self):
        state = 0.3 * self.calc.v1_dof_vector
        # A component orthogonal to v1 must be left alone.
        state[DOFName.M2_dx] = 17.0
        self.assertAlmostEqual(self.calc.v1_from_dof(state), 0.3)

        offset = self.calc.dof_offset(0.5, state)
        np.testing.assert_allclose(offset, 0.2 * self.calc.v1_dof_vector)
        self.assertEqual(offset[DOFName.M2_dx], 0.0)
        self.assertAlmostEqual(self.calc.v1_from_dof(state + offset), 0.5)

        with self.assertRaises(ValueError):
            self.calc.v1_from_dof(np.zeros(10))


class TestGetThermalTelemetry(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.truss = make_frame(TRUSS_COLUMNS, [[10.0, 12.0], [11.0, 13.0]], age=5)
        self.gradients = make_frame(
            GRADIENT_COLUMNS, [[0.1, 0.2, 0.3, 0.4], [0.3, 0.2, 0.1, 0.0]], age=20
        )

    async def test_nominal(self):
        client = FakeEfdClient(self.truss, self.gradients)
        telemetry = await get_thermal_telemetry(client)

        self.assertAlmostEqual(telemetry.truss_temp_c, 11.5)
        self.assertEqual(telemetry.truss_n_samples, 2)
        self.assertEqual(telemetry.gradients_n_samples, 2)
        for axis in GRADIENT_FIELDS:
            self.assertAlmostEqual(telemetry.gradients[axis], 0.2)

        self.assertEqual(
            client.calls,
            [
                (TRUSS_TOPIC, TRUSS_COLUMNS, 122),
                (GRADIENTS_TOPIC, GRADIENT_COLUMNS, 114),
            ],
        )

    async def test_query_parameters(self):
        truss = make_frame(
            ["temperatureItem1", "temperatureItem2"], [[10.0, 12.0]], age=5
        )
        client = FakeEfdClient(truss, self.gradients)
        await get_thermal_telemetry(
            client,
            truss_sal_index=9,
            truss_temperature_items=[1, 2],
            gradients_sal_index=8,
        )
        self.assertEqual(
            client.calls[0], (TRUSS_TOPIC, ["temperatureItem1", "temperatureItem2"], 9)
        )
        self.assertEqual(client.calls[1], (GRADIENTS_TOPIC, GRADIENT_COLUMNS, 8))

    async def test_gradients_unavailable(self):
        for gradients in [
            pd.DataFrame(),
            make_frame(GRADIENT_COLUMNS, [[np.nan] * 4], age=5),
            make_frame(GRADIENT_COLUMNS, [[0.1] * 4], age=2000),
        ]:
            telemetry = await get_thermal_telemetry(
                FakeEfdClient(self.truss, gradients)
            )
            self.assertIsNone(telemetry.gradients)
            self.assertAlmostEqual(telemetry.truss_temp_c, 11.5)

    async def test_truss_channel_nan(self):
        truss = make_frame(TRUSS_COLUMNS, [[10.0, np.nan]], age=5)
        telemetry = await get_thermal_telemetry(FakeEfdClient(truss, self.gradients))
        self.assertAlmostEqual(telemetry.truss_temp_c, 10.0)

    async def test_truss_unavailable(self):
        for truss in [
            pd.DataFrame(),
            make_frame(TRUSS_COLUMNS, [[np.nan, np.nan]], age=5),
            make_frame(TRUSS_COLUMNS, [[10.0, 12.0]], age=2000),
        ]:
            with self.assertRaises(RuntimeError):
                await get_thermal_telemetry(FakeEfdClient(truss, self.gradients))


if __name__ == "__main__":
    unittest.main()
