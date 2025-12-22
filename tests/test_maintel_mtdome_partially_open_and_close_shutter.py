import contextlib
import types
import unittest

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
                    "evt_operationalMode.aget.return_value": MTDome.OperationalMode.NORMAL,
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

    async def test_configure_normal(self):
        async with self.make_dry_script():
            self.script.calculate_sleep_time = unittest.mock.Mock(return_value=10.0)
            await self.configure_script()

            self.script.mtcs.rem.mtdome.evt_operationalMode.aget.assert_awaited_once()
            self.script.calculate_sleep_time.assert_called_once_with(
                aperture_level=self.script.partially_open_target_level,
                shutter_speed=self.script.shutter_speed["NORMAL"],
                queue_latency=self.script.script_queue_latency,
            )

    async def test_configure_degraded(self):
        async with self.make_dry_script():
            self.script.calculate_sleep_time = unittest.mock.Mock(return_value=55.0)
            self.script.mtcs.rem.mtdome.configure_mock(
                **{
                    "evt_operationalMode.aget.return_value": MTDome.OperationalMode.DEGRADED,
                }
            )
            await self.configure_script()

            self.script.mtcs.rem.mtdome.evt_operationalMode.aget.assert_awaited_once()
            self.script.calculate_sleep_time.assert_called_once_with(
                aperture_level=self.script.partially_open_target_level,
                shutter_speed=self.script.shutter_speed["DEGRADED"],
                queue_latency=self.script.script_queue_latency,
            )

    async def test_configure_override(self):
        async with self.make_dry_script():
            await self.configure_script(override_sleep_time=15.0)

            self.script.mtcs.rem.mtdome.evt_operationalMode.aget.assert_not_awaited()
            assert self.script.sleep_time == 15.0

    async def test_run_fail_tma_is_not_parked_at_horizon(self):
        async with self.make_dry_script():
            self.script.mtcs.rem.mtmount.configure_mock(
                **{
                    "tel_elevation.aget.return_value": types.SimpleNamespace(
                        actualPosition=self.tel_elevation_above_horizon
                    ),
                }
            )

            await self.configure_script()

            with pytest.raises(AssertionError):
                await self.run_script()

    async def test_run_fail_mirror_covers_not_retracted(self):
        async with self.make_dry_script():
            self.script.mtcs.rem.mtmount.configure_mock(
                **{
                    "evt_mirrorCoversMotionState.aget.return_value": types.SimpleNamespace(
                        state=MTMount.DeployableMotionState.DEPLOYED
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
            await self.configure_script()
            with unittest.mock.patch(
                "asyncio.sleep",
                new_callable=unittest.mock.AsyncMock,
            ) as mock_sleep:
                await self.run_script()

                self.script.mtcs.rem.mtdome.cmd_openShutter.start.assert_awaited()

                self.script.mtcs.rem.mtdome.assert_has_calls(
                    [
                        unittest.mock.call.cmd_openShutter.start(
                            timeout=self.script.mtcs.long_timeout
                        ),
                        unittest.mock.call.cmd_stop.set_start(
                            engageBrakes=False,
                            subSystemIds=MTDome.SubSystemId.APSCS,
                            timeout=self.script.mtcs.fast_timeout,
                        ),
                        unittest.mock.call.cmd_closeShutter.start(
                            timeout=self.script.mtcs.long_timeout
                        ),
                    ]
                )
                mock_sleep.assert_has_awaits(
                    [
                        unittest.mock.call(self.script.sleep_time),
                        unittest.mock.call(self.script.sleep_time_before_close),
                    ]
                )
