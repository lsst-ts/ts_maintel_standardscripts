import contextlib
import types
import unittest

import numpy as np
import pytest
from lsst.ts import standardscripts
from lsst.ts.maintel.standardscripts.mtdome import PartiallyOpenAndCloseShutter
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages
from lsst.ts.xml.enums import MTDome, MTMount


class TestPartiallyOpenAndCloseShutter(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        self.script = PartiallyOpenAndCloseShutter(index=index)
        self.tel_elevation_at_horizon = 14.9  # deg
        self.tel_elevation_above_horizon = 20.0  # deg
        return (self.script,)

    @contextlib.asynccontextmanager
    async def make_dry_script(self):
        async with self.make_script(self):
            self.script.mtcs = MTCS(
                domain=self.script.domain,
                intended_usage=MTCSUsages.DryTest,
                log=self.script.log,
            )
            self.script.mtcs.rem.mtdome = unittest.mock.AsyncMock()
            self.script.mtcs.rem.mtmount = unittest.mock.AsyncMock()
            fully_close_state = types.SimpleNamespace(
                state=[MTDome.MotionState.CLOSED.value, MTDome.MotionState.CLOSED.value]
            )
            self.script.mtcs.rem.mtdome.configure_mock(
                **{
                    "evt_shutterMotion.aget.return_value": fully_close_state,
                }
            )
            self.script.mtcs.rem.mtmount.configure_mock(
                **{
                    "evt_mirrorCoversMotionState.aget.return_value": types.SimpleNamespace(
                        state=MTMount.DeployableMotionState.RETRACTED
                    ),
                    "tel_elevation.aget.return_value": types.SimpleNamespace(
                        actualPosition=self.tel_elevation_at_horizon
                    ),
                }
            )
            yield

    async def test_configure(self):
        async with self.make_dry_script():
            await self.configure_script(target_aperture_level=1.0)

            assert self.script.target_position == pytest.approx(
                100.0 / self.script.SHUTTER_FULL_APERTURE
            )

    async def test_run_fail_mirror_covers_retracted_tma_not_at_horizon(self):
        async with self.make_dry_script():
            self.script.mtcs.rem.mtmount.configure_mock(
                **{
                    "evt_mirrorCoversMotionState.aget.return_value": types.SimpleNamespace(
                        state=MTMount.DeployableMotionState.RETRACTED
                    ),
                    "tel_elevation.aget.return_value": types.SimpleNamespace(
                        actualPosition=self.tel_elevation_above_horizon
                    ),
                }
            )

            await self.configure_script()

            with pytest.raises(AssertionError):
                await self.run_script()

    async def test_run_fail_mirror_covers_not_retracted_not_deployed(self):
        async with self.make_dry_script():
            self.script.mtcs.rem.mtmount.configure_mock(
                **{
                    "evt_mirrorCoversMotionState.aget.return_value": types.SimpleNamespace(
                        state=MTMount.DeployableMotionState.DEPLOYING
                    ),
                }
            )

            await self.configure_script()

            with pytest.raises(AssertionError):
                await self.run_script()

    async def test_run_fail_shutter_not_fully_closed(self):
        async with self.make_dry_script():
            not_fully_close_state = types.SimpleNamespace(
                state=[MTDome.MotionState.CLOSED.value, MTDome.MotionState.OPEN.value]
            )
            self.script.mtcs.rem.mtdome.configure_mock(
                **{
                    "evt_shutterMotion.aget.return_value": not_fully_close_state,
                }
            )

            await self.configure_script()

            with pytest.raises(AssertionError):
                await self.run_script()

    async def test_run_success(self):
        async with self.make_dry_script():
            await self.configure_script(target_aperture_level=0.6)
            aperture_list = [
                types.SimpleNamespace(positionActual=(aperture, aperture))
                for aperture in np.linspace(
                    start=0.0, stop=self.script.target_position, num=10
                )
            ]
            self.script.mtcs.rem.mtdome.configure_mock(
                **{
                    "tel_apertureShutter.next.side_effect": aperture_list,
                }
            )
            await self.run_script()

            self.script.mtcs.rem.mtdome.cmd_openShutter.start.assert_awaited_once_with(
                timeout=self.script.mtcs.long_timeout
            )
            assert (
                self.script.mtcs.rem.mtdome.tel_apertureShutter.next.await_count
                == len(aperture_list)
            )
            self.script.mtcs.rem.mtdome.cmd_stop.set_start.assert_awaited_once_with(
                engageBrakes=False,
                subSystemIds=MTDome.SubSystemId.APSCS,
                timeout=self.script.mtcs.fast_timeout,
            )
            self.script.mtcs.rem.mtdome.cmd_closeShutter.start.assert_awaited_once_with(
                timeout=self.script.mtcs.long_timeout
            )

    async def test_cleanup(self):
        async with self.make_dry_script():
            await self.configure_script(target_aperture_level=0.6)

            # Simulate an error during the waiting stage to trigger cleanup
            with unittest.mock.patch.object(
                self.script,
                "wait_for_shutter_to_reach_aperture_level",
                side_effect=Exception("Test exception"),
            ):
                with pytest.raises(Exception):
                    await self.script.run()

            await self.script.cleanup()

            # Ensure that the mtdome is stopped and closed
            self.script.mtcs.rem.mtdome.cmd_stop.set_start.assert_awaited_once_with(
                engageBrakes=False,
                subSystemIds=MTDome.SubSystemId.APSCS,
                timeout=self.script.mtcs.fast_timeout,
            )
            self.script.mtcs.rem.mtdome.cmd_closeShutter.start.assert_awaited_once_with(
                timeout=self.script.mtcs.long_timeout
            )
