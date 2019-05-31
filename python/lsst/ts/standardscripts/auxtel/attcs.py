import asyncio
import logging
import math

from astropy.time import Time

from lsst.ts import salobj
import SALPY_ATPtg


class ATTCS:
    """
    High level library for the Auxiliary Telescope Control System

    This is the high level interface for interacting with the CSCs that control the Auxiliary Telescope.
    Essentially this will allow the user to slew and track the telescope.

    Parameters
    ----------
    atmcs: salobj.Remote
    ataos: salobj.Remote
    atpneumatics: salobj.Remote
    athexapod: salobj.Remote
    atdome: salobj.Remote
    atdometrajectory: salobj.Remote

    Attributes
    ----------
    atmcs: salobj.Remote
    ataos: salobj.Remote
    atpneumatics: salobj.Remote
    athexapod: salobj.Remote
    atdome: salobj.Remote
    atdometrajectory: salobj.Remote
    """
    def __init__(
            self,
            atmcs,
            ataos,
            atpneumatics,
            athexapod,
            atdome,
            atdometrajectory):
        self.atmcs = atmcs
        self.ataos = ataos
        self.atpneumatics = atpneumatics
        self.athexapod = athexapod
        self.atdome = atdome
        self.atdometrajectory = atdometrajectory
        self.log = logging.getLogger("ATTCS")

    async def slew(
            self,
            ra,
            declination,
            rotPA=0,
            targetName="slew_icrs",
            targetInstance=SALPY_ATPtg.ATPtg_shared_TargetInstances_current,
            frame=SALPY_ATPtg.ATPtg_shared_CoordFrame_icrs,
            epoch=2000,
            equinox=2000,
            parallax=0,
            pmRA=0,
            pmDec=0,
            rv=0,
            dRA=0,
            dDec=0,
            rotFrame=SALPY_ATPtg.ATPtg_shared_RotFrame_target,
            rotMode=SALPY_ATPtg.AtPtg_shared_RotMode_field):
        """
        Slew the telescope

        Parameters
        ----------

        ra: float
            desired right ascension to slew to
        dec: float
            desired declination to slew to
        rotPA: float
            desired rotator position angle for slew
        targetName: str
            Name of the target
        targetInstance
        frame
        epoch
        equinox
        parallax
        pmRA
        pmDec
        rv
        dRA
        rotFrame
        rotMode

        """
        self.atptg.cmd_raDecTarget.set(
            ra=ra,
            declination=declination,
            rotPA=rotPA,
            targetName=targetName,
            targetInstance=targetInstance,
            frame=frame,
            epoch=epoch,
            equinox=equinox,
            parallax=parallax,
            pmRA=pmRA,
            pmDec=pmDec,
            rv=rv,
            dRA=dRA,
            dDec=dDec,
            rotFrame=rotFrame,
            rotMode=rotMode)
        self.atmcs.evt_summaryState.flush()
        self.atptg.evt_summaryState.flush()
        self.atmcs.evt_allAxesInPosition.flush()
        self.atptg.cmd_raDecTarget.start(timeout=300)
        coro_list = [
            asyncio.ensure_future(self.wait_for_position),
            asyncio.ensure_future(self.check_atptg_state),
            asyncio.ensure_future(self.check_atmcs_state)]
        for res in asyncio.as_completed((coro_list)):
            try:
                await res
            except RuntimeError as rte:

                for coro in coro_list:
                    if not coro.done():
                        coro.cancel()
                        try:
                            await coro
                        except asyncio.CancelledError:
                            pass
                raise rte
            else:
                break

    async def check_atmcs_state(self):
        """
        check atmcs state and raise exception if in other state than enabled.
        """
        while True:
            summary_state = await self.atmcs.evt_summaryState.next(flush=False)
            if summary_state.summaryState != salobj.State.ENABLED:
                raise RuntimeError(f"ATMCS state is {salobj.State(summary_state.summaryState)}")

    async def check_atptg_state(self):
        """
        check atptg state and raise exception if in other state than enabled.
        """
        while True:
            summary_state = await self.atptg.evt_summaryState.next(flush=False)
            if summary_state.summaryState != salobj.State.ENABLED:
                raise RuntimeError(f"ATPtg state is {salobj.State(summary_state.summaryState)}")

    async def check_athexapod_state(self):
        while True:
            summary_state = await self.athexapod.evt_summaryState.next(flush=False)
            if summary_state.summaryState != salobj.State.ENABLED:
                raise RuntimeError(f"ATHexapod state is {salobj.State(summary_state.summaryState)}")

    async def check_atpneumatics_state(self):
        while True:
            summary_state = await self.atpneumatics.evt_summaryState.next(flush=False)
            if summary_state.summaryState != salobj.State.ENABLED:
                raise RuntimeError(f"ATPneumatics state is {salobj.State(summary_state.summaryState)}")

    async def check_ataos_state(self):
        while True:
            summary_state = await self.ataos.evt_summaryState.next(flush=False)
            if summary_state.summaryState != salobj.State.ENABLED:
                raise RuntimeError(f"ATAOS state is {salobj.State(summary_state.summaryState)}")

    async def check_atdome_state(self):
        while True:
            summary_state = await self.atdome.evt_summaryState.next(flush=False)
            if summary_state.summaryState != salobj.State.ENABLED:
                raise RuntimeError(f"ATDome state is {salobj.State(summary_state.summaryState)}")

    async def check_atdometrajectory_state(self):
        while True:
            summary_state = await self.atdome.evt_summaryState.next(flush=False)
            if summary_state.summaryState != salobj.State.ENABLED:
                raise RuntimeError(f"ATDometrajectory state is {salobj.State(summary_state.summaryState)}")

    async def wait_for_position(self):
        """
        Wait for position of atmcs to be ready.
        """
        while True:
            in_position = await self.atmcs.evt_allAxesInPosition.next(flush=False)
            self.log.debug(f"Got {in_position.inPosition}")
            if in_position.inPosition:
                self.logo.info(f"Telescope slew finished")
                break

    async def check_track(
            self,
            track_duration=None,
            check_atpneumatics=False,
            check_athexapod=False,
            check_target=False):
        start_time = Time.now()
        while Time.now() - start_time < track_duration:
            coro_list = [
                asyncio.ensure_future(self.check_atmcs_state),
                asyncio.ensure_future(self.check_atptg_state),
                asyncio.ensure_future(self.check_target_status)]
            if check_atpneumatics:
                coro_list.append(asyncio.ensure_future(self.check_atpneumatics_state))
            if check_athexapod:
                coro_list.append(asyncio.ensure_future(self.check_athexapod_state))
            for res in asyncio.as_completed((coro_list)):
                try:
                    await res
                except RuntimeError as rte:
                    for coro in coro_list:
                        if not coro.done():
                            coro.cancel()
                            try:
                                await coro
                            except asyncio.CancelledError:
                                pass
                    raise rte
                else:
                    break

    async def check_target_status(self):
        while True:
            in_position = await self.atmcs.evt_allAxesInPosition.next(flush=False)
            self.log.debug(f"Got {in_position.inPosition}")
            if in_position.inPosition is False:
                raise RuntimeError(f"ATMCS is no longer tracking.")

    async def verify_hexapod(self):
        athexapod_inposition = self.athexapod.evt_inPosition.next(flush=True, timeout=60)
        athexapod_positionupdate = self.athexapod.evt_positionUpdate.next(flush=True, timeout=60)
        ataos_hexapod_correction_completed = self.ataos.evt_hexapodCorrectionCompleted.next(
            flush=True,
            timeout=30)
        results = await asyncio.gather(
            athexapod_inposition,
            athexapod_positionupdate,
            ataos_hexapod_correction_completed)
        hexapod_position = results[1]
        hexapod_correction = results[2]
        self.hexapod_check_values(hexapod_position, hexapod_correction, self.within)

    async def verify_pneumatics(self):
        atpneumatic_m1_set_pressure = self.atpneumatics.evt_m1SetPressure.next(flush=True, timeout=120)
        atpneumatics_m2_set_pressure = self.atpneumatics.evt_m2SetPressure.next(flush=True, timeout=120)
        ataos_m1_correction_started = self.ataos.evt_m1CorrectionStarted.next(flush=True, timeout=120)
        ataos_m2_correction_started = self.ataos.evt_m2CorrectionStarted.next(flush=True, timeout=120)
        results2 = await asyncio.gather(
            ataos_m1_correction_started,
            atpneumatic_m1_set_pressure,
            ataos_m2_correction_started,
            atpneumatics_m2_set_pressure)
        self.pneumatics_check_values(results2[0], results2[1], self.within)
        self.pneumatics_check_values(results2[2], results2[3], self.within)

    def hexapod_check_values(self, athex_position, athex_correction, within=0.03):
        self.log.info(f"Checking hexapod correction within {within*100} percent tolerance")
        c1 = math.isclose(athex_position.positionX, athex_correction.hexapod_x, rel_tol=within)
        self.log.info(
            f"Hexapod x check is {c1}, "
            f"difference is {athex_position.positionX - athex_correction.hexapod_x}")
        c2 = math.isclose(athex_position.positionY, athex_correction.hexapod_y, rel_tol=within)
        self.log.info(
            f"Hexapod y check is {c2}, "
            f"difference is {athex_position.positionY - athex_correction.hexapod_y}")
        c3 = math.isclose(athex_position.positionZ, athex_correction.hexapod_z, rel_tol=within)
        self.log.info(
            f"Hexapod z check is {c3}, "
            f"difference is {athex_position.positionZ - athex_correction.hexapod_z}")
        if (c1 or c2 or c3) is False:
            raise RuntimeError(f"Hexapod not corrected within {within*100} percent tolerance")

    def pneumatics_check_values(self, atpne_pre, atpneu_post, within=0.03):
        self.log.info(f"checking pneumatics correction within {within*100} percent tolerance")
        c1 = math.isclose(atpne_pre.pressure, atpneu_post.pressure, rel_tol=within)
        self.log.info(f"pneumatics is {c1}")
        if c1 is False:
            raise RuntimeError(f"Pneumatics not corrected within {within*100} percent tolerance")
