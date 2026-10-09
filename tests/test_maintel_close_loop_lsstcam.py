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

import asyncio
import random
import types
import unittest

import numpy as np
import pandas as pd
import yaml
from lsst.ts import standardscripts
from lsst.ts.maintel.standardscripts import CloseLoopLSSTCam
from lsst.ts.maintel.standardscripts.thermal_trim import (
    GRADIENT_FIELDS,
    TRUSS_TOPIC,
    TrimCalculator,
)
from lsst.ts.observatory.control import ROI, ROICommon, ROISpec
from lsst.ts.observatory.control.maintel.lsstcam import LSSTCam, LSSTCamUsages
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages
from lsst.ts.observatory.control.utils.enums import ClosedLoopMode

random.seed(47)  # for set_random_lsst_dds_partition_prefix


class TestCloseLoopLSSTCam(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        self.script = CloseLoopLSSTCam(index=index)

        self.script.mtcs = MTCS(
            domain=self.script.domain,
            intended_usage=MTCSUsages.DryTest,
            log=self.script.log,
        )

        self.script._camera = LSSTCam(
            domain=self.script.domain,
            intended_usage=LSSTCamUsages.DryTest,
            log=self.script.log,
        )

        # MTCS mocks
        self.script.mtcs.assert_all_enabled = unittest.mock.AsyncMock()
        self.script.mtcs.offset_camera_hexapod = unittest.mock.AsyncMock()
        self.script.mtcs.disable_checks_for_components = unittest.mock.Mock()
        self.script.mtcs.rem.mtrotator = unittest.mock.AsyncMock()
        self.script.mtcs.rem.mtrotator.configure_mock(
            **{
                "tel_rotation.next.return_value": types.SimpleNamespace(
                    actualPosition=0.0
                ),
            }
        )

        self.script.mtcs.rem.mtptg = unittest.mock.AsyncMock()
        self.script.mtcs.rem.mtptg.configure_mock(
            **{
                "evt_currentTarget.aget.return_value": types.SimpleNamespace(
                    ra=0.17,
                    declination=-0.52,
                    rotAngle=0.0,
                )
            }
        )

        self.script._camera.rem.mtcamera = unittest.mock.AsyncMock()
        self.script._camera.rem.mtcamera.configure_mock(
            **{
                "evt_endSetFilter.aget.return_value": types.SimpleNamespace(
                    filterName="r",
                )
            }
        )

        # MTAOS mocks
        self.script.mtcs.rem.mtaos = unittest.mock.AsyncMock()
        self.script.mtcs.rem.mtaos.configure_mock(
            **{
                "cmd_runWEP.set_start": unittest.mock.AsyncMock(),
                "cmd_runOFC.set_start": self.get_offsets,
                "evt_wavefrontError.next": self.return_zernikes,
                "evt_degreeOfFreedom.next": self.return_offsets,
                "cmd_issueCorrection.start": self.apply_offsets,
                "evt_wavefrontError.flush": unittest.mock.AsyncMock(),
                "evt_degreeOfFreedom.aget": self.return_current_dof,
                "cmd_offsetDOF.set_start": unittest.mock.AsyncMock(
                    side_effect=self.apply_dof_offset
                ),
            }
        )

        # Thermal telemetry returned by the mocked EFD client; the gradients
        # frame may be replaced by an empty one to test the fallback.
        self.truss_frame = self.make_efd_frame(
            ["temperatureItem6", "temperatureItem7"], [[10.0, 12.0], [11.0, 13.0]]
        )
        self.gradients_frame = self.make_efd_frame(
            list(GRADIENT_FIELDS.values()), [[0.01, -0.02, 0.1, -0.05]]
        )
        self.efd_client = unittest.mock.AsyncMock()
        self.efd_client.select_time_series.side_effect = self.select_time_series
        self.script.get_efd_client = unittest.mock.AsyncMock(
            return_value=self.efd_client
        )

        # Camera mocks
        self.script.camera.assert_all_enabled = unittest.mock.AsyncMock()
        self.script.camera.take_acq = unittest.mock.AsyncMock()
        self.script.camera.take_cwfs = unittest.mock.AsyncMock()

        self.script.assert_mode_compatibility = unittest.mock.AsyncMock()

        self.state_0 = np.zeros(50)
        self.state_0[:5] += 1

        self.corrections = types.SimpleNamespace(visitDoF=np.zeros(50))

        return (self.script,)

    @staticmethod
    def make_efd_frame(columns, rows):
        index = pd.date_range(
            end=pd.Timestamp.now(tz="UTC"), periods=len(rows), freq="10s"
        )
        return pd.DataFrame(rows, columns=columns, index=index)

    async def select_time_series(self, topic, fields, start, end, index=None):
        return self.truss_frame if topic == TRUSS_TOPIC else self.gradients_frame

    async def return_current_dof(self, *args, **kwargs):
        return types.SimpleNamespace(aggregatedDoF=self.state_0.copy())

    async def apply_dof_offset(self, value, **kwargs):
        self.state_0 += np.asarray(value)

    async def return_zernikes(self, *args, **kwargs):
        return np.random.rand(19)

    async def return_offsets(self, *args, **kwargs):
        return self.corrections

    async def apply_offsets(self, *args, **kwags):
        await asyncio.sleep(0.5)
        self.state_0 += self.corrections.visitDoF

    async def get_offsets(self, *args, **kwags):
        # return corrections to be non zero the first time this is called
        await asyncio.sleep(0.5)
        self.corrections = types.SimpleNamespace(visitDoF=np.zeros(50))

        if any(self.state_0):
            self.corrections.visitDoF[:5] -= 0.5

    async def test_configure(self):
        # Try configure with minimum set of parameters declared
        async with self.make_script():
            mode = "CWFS"
            max_iter = 10
            exposure_time = 30
            filter = "r"
            used_dofs = ["M2_dz", "M2_dx", "M2_dy", "M2_rx", "M2_ry"]
            threshold = [0.005] * 50
            truncation_index = 22
            apply_corrections = True

            await self.configure_script(
                mode=mode,
                max_iter=max_iter,
                exposure_time=exposure_time,
                filter=filter,
                used_dofs=used_dofs,
                threshold=threshold,
                truncation_index=truncation_index,
                apply_corrections=apply_corrections,
            )

            assert self.script.mode == ClosedLoopMode.CWFS
            assert self.script.max_iter == max_iter
            assert self.script.exposure_time == exposure_time
            assert self.script.filter == filter

            configured_dofs = np.zeros(50)
            configured_dofs[:5] += 1
            assert all(self.script.used_dofs == configured_dofs)
            assert self.script.threshold == threshold
            assert self.script.truncation_index == truncation_index
            assert self.script.apply_corrections == apply_corrections

    async def test_configure_wep_config(self):
        async with self.make_script():
            wep_config_dic = {"field1": "val1", "field2": "val2"}
            await self.configure_script(wep_config=wep_config_dic, filter="r")
            assert self.script.wep_config == yaml.dump(wep_config_dic)

    async def test_configure_ignore(self):
        async with self.make_script():
            ignore = ["mtdometrajectory", "no_comp"]

            await self.configure_script(filter="r", ignore=ignore)

            self.script.mtcs.disable_checks_for_components.assert_called_once_with(
                components=ignore
            )

    async def test_configure_thermal_prealignment_default(self):
        async with self.make_script():
            await self.configure_script(filter="r")

            assert not self.script.thermal_prealignment["enabled"]
            assert self.script.thermal_prealignment["truss_sal_index"] == 122
            assert self.script.thermal_prealignment["truss_temperature_items"] == [6, 7]
            assert self.script.thermal_prealignment["gradients_sal_index"] == 114

    async def test_configure_thermal_prealignment(self):
        async with self.make_script():
            await self.configure_script(
                filter="r",
                thermal_prealignment=dict(enabled=True, lookback=120),
            )

            assert self.script.thermal_prealignment["enabled"]
            assert self.script.thermal_prealignment["lookback"] == 120
            # Entries not given take their defaults.
            assert not self.script.thermal_prealignment["required"]
            assert self.script.thermal_prealignment["max_data_age"] == 900
            assert isinstance(self.script.trim_calculator, TrimCalculator)

    async def test_configure_thermal_prealignment_bad_coefficients(self):
        async with self.make_script():
            with self.assertRaises(Exception):
                await self.configure_script(
                    filter="r",
                    thermal_prealignment=dict(
                        enabled=True, coefficients_path="/no/such/file.yaml"
                    ),
                )

    def expected_thermal_v1(self, with_gradients=True):
        """Return the v1 the pre-alignment should predict."""
        calc = self.script.trim_calculator
        if not with_gradients:
            v1, _, _ = calc.predict_trim(truss_temp_c=11.5)
            return v1
        gradients = self.gradients_frame.iloc[0]
        v1, _, _ = calc.predict_trim(
            truss_temp_c=11.5,
            z_gradient_c_per_m=gradients["zGradient"],
            y_gradient_c_per_m=gradients["yGradient"],
            radial_gradient_c_per_m=gradients["radialGradient"],
            x_gradient_c_per_m=gradients["xGradient"],
        )
        return v1

    def expected_thermal_offset(self, with_gradients=True):
        """Return the DOF offset the pre-alignment should apply."""
        return self.script.trim_calculator.dof_offset(
            self.expected_thermal_v1(with_gradients), self.state_0
        )

    async def test_run_thermal_prealignment(self):
        async with self.make_script():
            await self.configure_script(
                filter="r",
                set_roi=False,
                thermal_prealignment=dict(enabled=True),
            )
            expected_v1 = self.expected_thermal_v1()
            expected = self.expected_thermal_offset()
            assert np.any(expected != 0)

            await self.script.run_thermal_prealignment()

            np.testing.assert_allclose(self.script.thermal_dof_offset, expected)
            self.script.mtcs.rem.mtaos.cmd_offsetDOF.set_start.assert_awaited_once()
            # The state is now at the predicted v1, and only the v1
            # components changed.
            calc = self.script.trim_calculator
            assert np.isclose(calc.v1_from_dof(self.state_0), expected_v1)
            untouched = calc.v1_dof_vector == 0
            np.testing.assert_allclose(
                self.state_0[untouched], 1.0 * (np.arange(50) < 5)[untouched]
            )

    async def test_run_thermal_prealignment_gradients_fallback(self):
        async with self.make_script():
            await self.configure_script(
                filter="r",
                set_roi=False,
                thermal_prealignment=dict(enabled=True),
            )
            self.gradients_frame = pd.DataFrame()
            expected = self.expected_thermal_offset(with_gradients=False)

            await self.script.run_thermal_prealignment()

            np.testing.assert_allclose(self.script.thermal_dof_offset, expected)
            self.script.mtcs.rem.mtaos.cmd_offsetDOF.set_start.assert_awaited_once()

    async def test_run_thermal_prealignment_gradients_required(self):
        async with self.make_script():
            await self.configure_script(
                filter="r",
                set_roi=False,
                thermal_prealignment=dict(
                    enabled=True, required=True, require_gradients=True
                ),
            )
            self.gradients_frame = pd.DataFrame()

            with self.assertRaises(RuntimeError):
                await self.script.run_thermal_prealignment()

            self.script.mtcs.rem.mtaos.cmd_offsetDOF.set_start.assert_not_awaited()

    async def test_run_thermal_prealignment_not_required(self):
        async with self.make_script():
            await self.configure_script(
                filter="r",
                set_roi=False,
                thermal_prealignment=dict(enabled=True),
            )
            self.script.get_efd_client = unittest.mock.AsyncMock(
                side_effect=RuntimeError("No EFD")
            )

            # Must not raise: the closed loop continues without it.
            await self.script.run_thermal_prealignment()

            assert self.script.thermal_dof_offset is None
            self.script.mtcs.rem.mtaos.cmd_offsetDOF.set_start.assert_not_awaited()

    async def test_run_thermal_prealignment_no_apply_corrections(self):
        async with self.make_script():
            await self.configure_script(
                filter="r",
                set_roi=False,
                apply_corrections=False,
                thermal_prealignment=dict(enabled=True),
            )
            expected = self.expected_thermal_offset()

            await self.script.run_thermal_prealignment()

            np.testing.assert_allclose(self.script.thermal_dof_offset, expected)
            self.script.mtcs.rem.mtaos.cmd_offsetDOF.set_start.assert_not_awaited()

    async def test_run_thermal_prealignment_config_telemetry(self):
        async with self.make_script():
            gradients = self.gradients_frame.iloc[0]
            await self.configure_script(
                filter="r",
                set_roi=False,
                thermal_prealignment=dict(
                    enabled=True,
                    telemetry=dict(
                        truss_temp_c=11.5,
                        x_gradient_c_per_m=float(gradients["xGradient"]),
                        y_gradient_c_per_m=float(gradients["yGradient"]),
                        z_gradient_c_per_m=float(gradients["zGradient"]),
                        radial_gradient_c_per_m=float(gradients["radialGradient"]),
                    ),
                ),
            )
            expected = self.expected_thermal_offset()

            await self.script.run_thermal_prealignment()

            # The EFD is not consulted and the offset matches the one the
            # same values would give from the EFD.
            self.script.get_efd_client.assert_not_awaited()
            np.testing.assert_allclose(self.script.thermal_dof_offset, expected)
            self.script.mtcs.rem.mtaos.cmd_offsetDOF.set_start.assert_awaited_once()

    async def test_run_thermal_prealignment_config_telemetry_truss_only(self):
        async with self.make_script():
            await self.configure_script(
                filter="r",
                set_roi=False,
                thermal_prealignment=dict(
                    enabled=True, telemetry=dict(truss_temp_c=11.5)
                ),
            )
            expected = self.expected_thermal_offset(with_gradients=False)

            await self.script.run_thermal_prealignment()

            self.script.get_efd_client.assert_not_awaited()
            np.testing.assert_allclose(self.script.thermal_dof_offset, expected)

    async def test_configure_thermal_prealignment_bad_telemetry(self):
        async with self.make_script():
            for telemetry in [
                dict(z_gradient_c_per_m=0.1),  # truss_temp_c missing
                dict(truss_temp_c=11.5, bogus=1.0),
            ]:
                with self.assertRaises(Exception):
                    await self.configure_script(
                        filter="r",
                        thermal_prealignment=dict(enabled=True, telemetry=telemetry),
                    )

    async def test_run_with_thermal_prealignment(self):
        async with self.make_script():
            await self.configure_script(
                max_iter=2,
                filter="r",
                used_dofs=[0, 1, 2, 3, 4],
                set_roi=False,
                thermal_prealignment=dict(enabled=True),
            )

            await self.run_script()

            self.script.mtcs.rem.mtaos.cmd_offsetDOF.set_start.assert_awaited_once()
            assert self.script.thermal_dof_offset is not None

    async def test_run(self):
        # Start the test itself

        class DummyGuiderROIs:
            def __init__(self, log=None):
                pass

            def get_guider_rois(
                self,
                ra,
                dec,
                sky_angle,
                roi_size,
                roi_time,
                band,
                npix_edge=50,
                use_guider=True,
                use_wavefront=False,
                use_science=False,
            ):
                roi_spec = ROISpec(
                    common=ROICommon(
                        rows=roi_size, cols=roi_size, integration_time_millis=roi_time
                    ),
                    roi=dict(R00SG0=ROI(segment=7, start_row=10, start_col=20)),
                )
                return roi_spec, None

        with unittest.mock.patch(
            "lsst.ts.maintel.standardscripts.base_close_loop.GuiderROIs",
            DummyGuiderROIs,
        ):
            async with self.make_script():
                await self.configure_script(
                    max_iter=10,
                    filter="r",
                    used_dofs=[0, 1, 2, 3, 4],
                )

                # Run the script
                await self.run_script()

                assert all(self.state_0 == np.zeros(50))
                assert not self.script.set_roi_failed


if __name__ == "__main__":
    unittest.main()
