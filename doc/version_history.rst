.. py:currentmodule:: lsst.ts.maintel.standardscripts

.. _lsst.ts.maintel.standardscripts.version_history:

===============
Version History
===============

.. towncrier release notes start

v0.9.0 (2026-06-08)
===================

New Features
------------

- Updated ``m1m3/enable_m1m3_slew_controller_flags.py`` so the ``default`` slew flag configuration now enables all M1M3 slew controller flags. (`RSO-548 <https://rubinobs.atlassian.net//browse/RSO-548>`_)
- Updated ``maintel/ensure_onsky_readiness.py`` to ensure M1M3 is not in engineering mode at the end of the script execution. (`RSO-548 <https://rubinobs.atlassian.net//browse/RSO-548>`_)
- Updated ``maintel/ensure_onsky_readiness.py`` to assert that all M1M3 slew controller flags are enabled after raising the mirror, since slew controller flags are now automatically enabled at the CSC level when the mirror is raised.
  If any flag is not enabled, a warning is collected and reported at the end of the script.
  The ``slew_flags`` and ``enable_flags`` configuration properties are now deprecated (RSO-592) and will be removed in a future release. (`RSO-548 <https://rubinobs.atlassian.net//browse/RSO-548>`_)
- Added a ``homing_attempts`` configuration parameter to ``maintel/ensure_onsky_readiness.py``, ``maintel/prepare_for/onsky.py``, and ``maintel/prepare_for/flat.py`` scripts.
  It controls how many times the scripts will attempt to home the mount before failing (``default: 10``). (`RSO-548 <https://rubinobs.atlassian.net//browse/RSO-548>`_)
- Updated ``maintel/ensure_onsky_readiness.py``, ``maintel/prepare_for/onsky.py``, and ``maintel/prepare_for/flat.py`` to check that ``MTM1M3TS`` is not in engineering mode, preventing EAS/PID from being blocked from commanding the glycol valve position. (`RSO-548 <https://rubinobs.atlassian.net//browse/RSO-548>`_)
- Replaced explicit force balance system enable step with an assertion check in ``maintel/ensure_onsky_readiness.py``.
  The force balance system is now automatically enabled at the CSC level when the mirror is raised, and the script verifies this is the case.
  The same change was applied to ``MTCS.prepare_for_onsky()`` and ``MTCS.prepare_for_flatfield()`` in ``ts_observatory_control``. (`RSO-548 <https://rubinobs.atlassian.net//browse/RSO-548>`_)
- Updated ``maintel/ensure_onsky_readiness.py`` to assert that the M1M3 force balance system is enabled after raising the mirror, since force balance is now automatically enabled at the CSC level when the mirror is raised.
  The script raises an error if force balance is not enabled. (`RSO-548 <https://rubinobs.atlassian.net//browse/RSO-548>`_)


v0.8.0 (2026-06-03)
===================

New Features
------------

- Added the 'synchronous_closed_loop' configuration parameter to the 'enable_aos_closed_loop.py' script. (`OSW-2269 <https://rubinobs.atlassian.net//browse/OSW-2269>`_)
- Updated HomeBothAxes script to perform a configurable amount of attempts to home the mount. (`OSW-2333 <https://rubinobs.atlassian.net//browse/OSW-2333>`_)
- Updated ``wait_mtaos_idle`` in the ``TrackTargetAndTakeImageLSSTCam`` script to handle aos correction if the state is WAITING_APPLY. (`OSW-2280 <https://rubinobs.atlassian.net//browse/OSW-2280>`_)


v0.7.0 (2026-05-22)
===================

New Features
------------

- Add a ``maintel/prepare_for/flat.py`` script to prepare Simonyi for in-dome flat-field calibrations. (`DM-51803 <https://rubinobs.atlassian.net//browse/DM-51803>`_)
- Added a set_roi parameter to the take_image_lsstcam.py script, providing the option to skip the guider ROI setting phase when it is not required for a specific observation. (`LSSTCAM-155 <https://rubinobs.atlassian.net//browse/LSSTCAM-155>`_)
- Updated the ``track_target_and_take_image_lsstcam.py`` script to enable TCS synchronization when there is a filter change. (`OSW-1705 <https://rubinobs.atlassian.net//browse/OSW-1705>`_)
- Update ``take_image_lsstcam`` script to reset guider roi when ``set_roi`` is False. (`OSW-1709 <https://rubinobs.atlassian.net//browse/OSW-1709>`_)
- The ``prepare_for_onsky`` script now configures the camera filter during preparation to support the on-sky initial alignment optimization effort described in `RSO-76 <https://rubinobs.atlassian.net/browse/RSO-76>`_. (`OSW-1719 <https://rubinobs.atlassian.net//browse/OSW-1719>`_)
- Update script ``point_azel.py`` to raise an exception if the MTM1M3 component is ignored. (`OSW-1901 <https://rubinobs.atlassian.net//browse/OSW-1901>`_)
- In mtdome/recover_from_controller_fault.py, add feature to verify azEnabled log_event after sending exitFault cmd. (`OSW-1968 <https://rubinobs.atlassian.net//browse/OSW-1968>`_)
- Updated the ``ensure_onsky_readiness.py`` script to ensure the ``OCPS:101`` CSC is enabled as part of the on-sky readiness checks. (`OSW-1970 <https://rubinobs.atlassian.net//browse/OSW-1970>`_)
- Updated the 'enable_aos_closed_loop.py' script with a new parameter to toggle the discarding of intermediate MTAOS corrections. (`OSW-2094 <https://rubinobs.atlassian.net//browse/OSW-2094>`_)


Bug Fixes
---------

- Add base schema required field inheritance to derived scripts (`DM-53280 <https://rubinobs.atlassian.net//browse/DM-53280>`_)
- Update documentation build configuration for documenteer 1.0+. (`DM-53280.2 <https://rubinobs.atlassian.net//browse/DM-53280.2>`_)
- Updated laser_tracker/align.py to add intended usage and limit the ammount of resources allocated by the script. (`OSW-1941 <https://rubinobs.atlassian.net//browse/OSW-1941>`_)
- Updated ``take_image_lsstcam.py`` to move the guider ROI selection process to the run stage of the script execution, instead of the configuration stage. (`RSO-40 <https://rubinobs.atlassian.net//browse/RSO-40>`_)


Other Changes and Additions
---------------------------

- Fixed the test_configure_ignore unit test for the take_image_lsstcam script to maintain test suite reliability. (`LSSTCAM-155 <https://rubinobs.atlassian.net//browse/LSSTCAM-155>`_)
- Improved ``ensure_onsky_readiness`` script to align MTMount homing logic with the ``home_both_axes.py`` pattern: increased homing timeout from ~30s to 300s, wrapped homing command with the M1M3 booster valve context manager, and reordered steps so the M1M3 force balance system is enabled before homing. (`OSW-1878 <https://rubinobs.atlassian.net//browse/OSW-1878>`_)
- In mtdome/recover_from_controller_fault.py, reduce default delta_move from 3 deg to 2 deg. (`OSW-1968 <https://rubinobs.atlassian.net//browse/OSW-1968>`_)
- In mtdome/recover_from_controller_fault.py, update timeout used to wait for in_position event and capture slew_dome faults to prevent script from failing before additional recovery attempts. (`OSW-1968 <https://rubinobs.atlassian.net//browse/OSW-1968>`_)
- In mtdome/recover_from_controller_fault.py, refactor method to check that the fault is cleared and check EnabledState. (`OSW-1968 <https://rubinobs.atlassian.net//browse/OSW-1968>`_)
- Updated the 'home_both_axes.py' script to ignore mtaos during execution. (`OSW-2094 <https://rubinobs.atlassian.net//browse/OSW-2094>`_)


v0.6.1 (2026-01-13)
===================

New Features
------------

- Updated _run_close_loop to verify that the MTAOS is ready for closed-loop operations at every iteration, ensuring more stable and synchronized execution during image sequences. (`OSW-1677 <https://rubinobs.atlassian.net//browse/OSW-1677>`_)
- Implemented a retry mechanism in _run_close_loop that automatically retries the first iteration of the closed loop if a correction timeout occurs.
  This provides a robust workaround for scenarios where the MTAOS discards initial corrections following significant elevation, rotation, or filter changes. (`OSW-1677 <https://rubinobs.atlassian.net//browse/OSW-1677>`_)
- Introduced a custom exception specifically for correction timeouts in wait_correction_for_visit_id, allowing for more granular error catching and handling in the imaging script. (`OSW-1677 <https://rubinobs.atlassian.net//browse/OSW-1677>`_)


Bug Fixes
---------

- Fixed a logic error in wait_correction_for_visit_id where a reversed comparison index caused the loop to terminate immediately instead of waiting for corrections to complete. (`OSW-1677 <https://rubinobs.atlassian.net//browse/OSW-1677>`_)


v0.6.0 (2026-01-09)
===================

New Features
------------

- Integrated the new ``LSSTCam.set_init_guider`` method into the ``track_target_and_take_image_lsstcam.py`` script to set guider ROI during the slew process, reducing total execution time by approximately 0.5 seconds. (`OSW-1632 <https://rubinobs.atlassian.net//browse/OSW-1632>`_)


v0.5.1 (2026-01-07)
===================

New Features
------------

- In `maintel/ensure_onsky_readiness.py`, ensure the dome is unparked before enabling dome following. (`RSO-56 <https://rubinobs.atlassian.net//browse/RSO-56>`_)


Bug Fixes
---------

- In ``track_target_and_take_image_lsstcam.py``, update termination condition in ``wait_correction_for_visit_id`` to interrupt if the degree of freedom is equal to or larger than the first exposure taken.
  This allows working around a situation where we do a large slew followed by a filter change, which caused the first correction to be discarded by the MTAOS. (`OSW-1618 <https://rubinobs.atlassian.net//browse/OSW-1618>`_)
- In ``track_target_and_take_image_lsstcam.py``, updated how additional AOS exposures after filter change are taken to use supplemental group ID. (`OSW-1618 <https://rubinobs.atlassian.net//browse/OSW-1618>`_)


v0.5.0 (2026-01-02)
===================

New Features
------------

- Add ignore feature to `move_rotator` script. (`DM-52566 <https://rubinobs.atlassian.net//browse/DM-52566>`_)
- configure roi size and roi time integration in track_target_and_take_image_lsstcam.py script (`OSW-1180 <https://rubinobs.atlassian.net//browse/OSW-1180>`_)
- In ``take_image_lsstcam.py``, add guider roi selection procedure.
  The script will retrieve information about the current target from the pointing component and use that to calculate roi regions. (`OSW-1485 <https://rubinobs.atlassian.net//browse/OSW-1485>`_)
- Updated ``TrackTargetAndTakeImageLSSTCam`` script to add a feature to allow running a few additional exposures for closed loop when there is a filter change.
  At each iteration it takes 2 exposures and wait until the correction for the first exposure is applied before continuing. (`OSW-1593 <https://rubinobs.atlassian.net//browse/OSW-1593>`_)


Bug Fixes
---------

- Applied intended usages to MTCS in ``enable_dome_following``. (`DM-53159 <https://rubinobs.atlassian.net//browse/DM-53159>`_)
- Applied intended usages to MTCS in ``enable_m1m3_balance_system``. (`DM-53159 <https://rubinobs.atlassian.net//browse/DM-53159>`_)
- Applied intended usages to MTCS in ``ensure_onsky_readiness``. (`DM-53159 <https://rubinobs.atlassian.net//browse/DM-53159>`_)
- Applied intended usages to MTCS in ``disable_dome_following``. (`DM-53159 <https://rubinobs.atlassian.net//browse/DM-53159>`_)
- Update the ``home_both_axes.py`` script to keep force balance system enabled and to use booster valve context manager while homing. (`DM-53537 <https://rubinobs.atlassian.net//browse/DM-53537>`_)
- Updated ``TakeAOSSequenceLSSTCam`` to configure TCS synchronization for the camera. (`OSW-1309 <https://rubinobs.atlassian.net//browse/OSW-1309>`_)
- In ``track_target_and_take_image_lsstcam.py``, fix how roi spec is passed to the init guider method.
  Originally the roi data was a yaml string but we updated the method to return an ROISpec object. (`OSW-1485 <https://rubinobs.atlassian.net//browse/OSW-1485>`_)
- In ``disable_hexapod_compensation_mode.py``, add intended usage to ``MTCS`` class to limit resources allocated. (`OSW-1485 <https://rubinobs.atlassian.net//browse/OSW-1485>`_)


v0.4.0 (2025-10-20)
===================

New Features
------------

- Add script to recover the ``MTDome`` from a low-level controller fault that prevents movement. (`DM-50444 <https://rubinobs.atlassian.net//browse/DM-50444>`_)
- Add a `prepare_for/onsky.py` script that prepares the telescope and dome for on-sky operations. (`DM-51325 <https://rubinobs.atlassian.net//browse/DM-51325>`_)
- Add ``get_available_imgtypes`` implementation to ``TakeImageComCam`` and ``TakeImageLSSTCam`` (`DM-51409 <https://rubinobs.atlassian.net//browse/DM-51409>`_)
- Update ``TakeImageAnyCam`` to read available image types from ``LSSTCam`` and ``ComCam`` classes. (`DM-51409 <https://rubinobs.atlassian.net//browse/DM-51409>`_)
- - In `base_close_loop.py`, add an option to run closed loop at a fixed `az`, `el`` and `rot`. (`DM-52297 <https://rubinobs.atlassian.net//browse/DM-52297>`_)
- Implement guider selection in track_target_and_take_image script. (`OSW-964 <https://rubinobs.atlassian.net//browse/OSW-964>`_)


Bug Fixes
---------

- In mtdome/recover_from_controller_fault.py, fix usage for both 'cmd_exitFault' call and 'evt_azEnabled' status query. (`DM-52592 <https://rubinobs.atlassian.net//browse/DM-52592>`_)


v0.3.0 (2025-08-25)
===================

New Features
------------

- Move MTAOS start/stop close loop logic to MTCS. (`DM-50762 <https://rubinobs.atlassian.net//browse/DM-50762>`_)
- Added a new script called `maintel/ensure_onsky_readiness.py` to perform a sequence of checks and actions ensuring the telescope and associated systems are ready for on-sky operations. (`DM-50862 <https://rubinobs.atlassian.net//browse/DM-50862>`_)
- Allow ``move_p2p.py`` and ``point_azel.py`` scripts to receive only one axis. (`DM-51170 <https://rubinobs.atlassian.net//browse/DM-51170>`_)
- Add `offset_dome` script that performs a relative movement of the MTDome. (`DM-51171 <https://rubinobs.atlassian.net//browse/DM-51171>`_)
- In ``base_close_loop.py``:
  - Update compute_ofc_offset to retrieve the filter from the camera if it is not set.
  - Ensure threshold check only runs if the visit dof and threshold array are the same length.
  - Stop waiting for the wep results after run wep executes. (`DM-51217 <https://rubinobs.atlassian.net//browse/DM-51217>`_)
- Add calibration screen alignment function to `lasertracker/align.py` script (`DM-51304 <https://rubinobs.atlassian.net//browse/DM-51304>`_)
- Update laser_tracker/align.py make sure ``MTCS`` ignore the ``MTDome`` when repositioning the telescope. (`DM-51639 <https://rubinobs.atlassian.net//browse/DM-51639>`_)
- Updated ``home_both_axes.py``, to set wait_dome=True while slewing the telescope to final position. (`DM-51828 <https://rubinobs.atlassian.net//browse/DM-51828>`_)
- Updated ``csc_end_of_night.py`` to set default end of night state to DISABLED. The MTDomeTrajectory CSC should remain DISABLED at the end of the night. This ensures that vignetting calculations for image metadata are correctly handled, as the CSC cannot perform these calculations when in STANDBY. (`DM-51828 <https://rubinobs.atlassian.net//browse/DM-51828>`_)
- Updated ``home_both_axes.py`` to add cleanup method that will stop tracking if script fails. (`DM-51828 <https://rubinobs.atlassian.net//browse/DM-51828>`_)
- In ``home_both_axes.py``, add new configurable option to re-home the axis at a provided az/el position. (`DM-51900 <https://rubinobs.atlassian.net//browse/DM-51900>`_)
- Limited the resources allocated by ``MTCS`` in ``enable_hexapod_compensation_mode.py``. (`DM-52162 <https://rubinobs.atlassian.net//browse/DM-52162>`_)
- Limited the resources allocated by ``MTCS`` in ``mtrotator/move_rotator.py``. (`DM-52162 <https://rubinobs.atlassian.net//browse/DM-52162>`_)
- Limited the resources allocated by ``MTCS`` in ``point_azel.py``. (`DM-52162 <https://rubinobs.atlassian.net//browse/DM-52162>`_)
- Ensure scripts used to take calibrations for SimonyiTel are enforcing the required MTCS state. (`OSW-897 <https://rubinobs.atlassian.net//browse/OSW-897>`_)
- Updated the m1m3 check actuators script to run the bump test concurrently for multiple actuators. It relies on the new ``get_m1m3_actuator_to_test`` method from ``MTCS`` to retrieve feasible actuators to test concurrently. (`OSW-949 <https://rubinobs.atlassian.net//browse/OSW-949>`_)


Bug Fixes
---------

- Modified the ``ensure_onsky_readiness`` script behavior to keep going if Dome Shutter and/or AOS Closed Loop are not open/enabled. (`DM-51428 <https://rubinobs.atlassian.net//browse/DM-51428>`_)
- Added protection against cancellations in ``m1m3/check_actuators.py``. (`DM-51428 <https://rubinobs.atlassian.net//browse/DM-51428>`_)
- Fixed targets for laser tracker align script. (`DM-51428 <https://rubinobs.atlassian.net//browse/DM-51428>`_)
- Fixed a bug in ``base_close_loop`` retrieving current camera filter. (`DM-51428 <https://rubinobs.atlassian.net//browse/DM-51428>`_)


Other Changes and Additions
---------------------------

- In maintel/m2:
  - Rename enable_closed_loop.py to enable_m2_closed_loop.py
  - Rename disable_closed_loop.py to disable_m2_closed_loop.py (`DM-51230 <https://rubinobs.atlassian.net//browse/DM-51230>`_)
- In ``set_dof.py``, handle condition when the retrieved state contains invalid nan values. (`DM-51639 <https://rubinobs.atlassian.net//browse/DM-51639>`_)


v0.2.0 (2025-06-06)
===================

New Features
------------

- In set_dof.py script add ability to synchronize dof with state of a specific day obs and sequence number. (`DM-47601 <https://rubinobs.atlassian.net//browse/DM-47601>`_)
- Add script to send ``MTCS`` and ``LSSTCam`` CSCs to End-of-Night State (`DM-48225 <https://rubinobs.atlassian.net//browse/DM-48225>`_)
- Add script to track target and take image with LSSTCam. (`DM-49337 <https://rubinobs.atlassian.net//browse/DM-49337>`_)
- Add ignore property to park_dome.py and unpark_dome.py scripts. (`DM-49414 <https://rubinobs.atlassian.net//browse/DM-49414>`_)
- Add unit tests for park_dome.py and unpark_dome.py scripts. (`DM-49414 <https://rubinobs.atlassian.net//browse/DM-49414>`_)
- Update scripts that subclass ``BaseTakeImage`` to define ``tcs`` property. (`DM-49502 <https://rubinobs.atlassian.net//browse/DM-49502>`_)
- Add scripts to open and close the MTDome shutter. (`DM-49506 <https://rubinobs.atlassian.net//browse/DM-49506>`_)
- Add SAL script to perform a filter-change operation for LSSTCam. (`DM-49527 <https://rubinobs.atlassian.net//browse/DM-49527>`_)
- Extend the mtdome/crawl_az script to accept position and velocity. (`DM-49529 <https://rubinobs.atlassian.net//browse/DM-49529>`_)
- In ``track_target_and_take_image`` scripts, pass ``note`` option through to ``take_object`` call and update unit tests. (`DM-49700 <https://rubinobs.atlassian.net//browse/DM-49700>`_)
- Add `enable_aos_closed_loop.py` and `disable_aos_closed_loop.py` scripts. (`DM-49857 <https://rubinobs.atlassian.net//browse/DM-49857>`_)
- Add script to enable LSSTCam components. (`DM-49921 <https://rubinobs.atlassian.net//browse/DM-49921>`_)
- In apply_dof.py, limit resources in MTCS class. (`DM-49954 <https://rubinobs.atlassian.net//browse/DM-49954>`_)
- In m1m3/enable_m1m3_slew_controller_flags.py, update script to stop activating/deactivating engineering mode. (`DM-49954 <https://rubinobs.atlassian.net//browse/DM-49954>`_)
- In ``set_dof.py``:
  - ignore errors importing lsst_efd_client
  - Remove required properties (`DM-49954 <https://rubinobs.atlassian.net//browse/DM-49954>`_)
- In take_aos_sequence:
  - Add LSSTCamUsages.StateTransition to the intended usages when creating the LSSTCam object.
  - Abstract oods property (`DM-49954 <https://rubinobs.atlassian.net//browse/DM-49954>`_)
- In base_close_loop.py:
  - limit resources of MTCS
  - Fix group_id in second exposure while waiting for RA in close_loop
  - Make filter not required
  - Add default filter if no filter provided (`DM-49954 <https://rubinobs.atlassian.net//browse/DM-49954>`_)
- In focus_sweep_lsstcam.py:
  - Fix bug in LSSTCam
  - Add StateTransition usage to LSSTCam (`DM-49954 <https://rubinobs.atlassian.net//browse/DM-49954>`_)
- In ``track_target_and_take_image_lsstcam.py``:
  - add MTCS instancte to LSSTCam so it can handle filter changes correctly.
  - add mechanism to wait for MTAOS to be ready to take image. (`DM-49954 <https://rubinobs.atlassian.net//browse/DM-49954>`_)
- Update `laser_tracker/align.py` script to add calibration screen to the list of targets. (`DM-50398 <https://rubinobs.atlassian.net//browse/DM-50398>`_)
- In `offset_mtcs.py`, add intended usage (`MTCSUsages.Slew`) to the function call to limit the amount of resources allocated by the script. (`DM-50398 <https://rubinobs.atlassian.net//browse/DM-50398>`_)
- In `enable_aos_closed.py`, increased the CLOSED_LOOP_STATE_TIMEOUT from 10s to 120s to wait longer for the closed loop ready state to be reached. (`DM-50700 <https://rubinobs.atlassian.net//browse/DM-50700>`_)
- In `laser_tracker/align.py`, introduced a new `zn_selected` property in the schema and related methods. (`DM-50700 <https://rubinobs.atlassian.net//browse/DM-50700>`_)
- In enable_aos_closed_loop.py script, add option to configure the zernike selected. (`DM-50986 <https://rubinobs.atlassian.net//browse/DM-50986>`_)
- In laser_tracker/align.py zero out z alignment. Z alignment is temperature dependent and not corrected for by laser alignment. (`DM-50986 <https://rubinobs.atlassian.net//browse/DM-50986>`_)


Bug Fixes
---------

- Needed to add await to self.laser.start_task for power_on and power_off_tunablelaser.py (`DM-49463 <https://rubinobs.atlassian.net//browse/DM-49463>`_)
- In take_image_lsstcam.py, fix issue setting value of instrument_setup_time and add missing await to start_task. (`DM-49683 <https://rubinobs.atlassian.net//browse/DM-49683>`_)
- In ``set_dof.py``:
  - add missing awaits in ApplyDOF and get_image calls
  - fix call to super in the configure method (`DM-49954 <https://rubinobs.atlassian.net//browse/DM-49954>`_)
- In offset_m2_hexapod.py, add missing mtcs attribute. (`DM-49954 <https://rubinobs.atlassian.net//browse/DM-49954>`_)
- In change_filter_lsstcam.py, add missing await to ``setup_instrument``. (`DM-49954 <https://rubinobs.atlassian.net//browse/DM-49954>`_)
- Await for start_task in enable/disable dome following scripts. (`DM-49954 <https://rubinobs.atlassian.net//browse/DM-49954>`_)
- Update stop_rotator.py to add missing await to start_task. (`DM-49954 <https://rubinobs.atlassian.net//browse/DM-49954>`_)


Performance Enhancement
-----------------------

- Add `take_aos_sequence_lsstcam.py` and abstract aos sequence into `base_take_aos_sequence.py` (`DM-49514 <https://rubinobs.atlassian.net//browse/DM-49514>`_)
- Fix `base_close_loop` to take an image while waiting for the LSSTCam WEP RA results. (`DM-49757 <https://rubinobs.atlassian.net//browse/DM-49757>`_)
- Add truncation_index as a configurable parameter to `close_loop_lsstcam.py`. (`DM-49992 <https://rubinobs.atlassian.net//browse/DM-49992>`_)
- * Add configuration to be passed to `enable_aos_closed_loop.py` script. (`DM-50623 <https://rubinobs.atlassian.net//browse/DM-50623>`_)


API Removal or Deprecation
--------------------------

- Remove dependencies on ``lsst.ts.idl`` from all scripts and tests, and use ``lsst.ts.xml`` instead. (`DM-50775 <https://rubinobs.atlassian.net//browse/DM-50775>`_)


Other Changes and Additions
---------------------------

- - The check actuators script has been refactored to support detailed failure statuses
    (e.g., FAILED_TIMEOUT, FAILED_TESTEDPOSITIVE_OVERSHOOT) from the updated XML enumeration 
    while maintaining backward compatibility with the previous single FAILED logic. (`DM-49547 <https://rubinobs.atlassian.net//browse/DM-49547>`_)


v0.1.0 (2025-03-11)
===================

Initial Release
---------------

- New script to turn the Tunable Laser off, i.e. stop propagating (`DM-45743 <https://rubinobs.atlassian.net//browse/DM-45743>`_)
- Split `ts_maintel_standardscripts` repo from `ts_standardscripts`
  to focus exclusively on main telescope logic. (`DM-47293 <https://rubinobs.atlassian.net//browse/DM-47293>`_, `DM-48005 <https://rubinobs.atlassian.net//browse/DM-48005>`_)
- Update the implementation of the ignore feature in all scripts to use the ``RemoteGroup.disable_checks_for_components`` method.

  Updated scripts:
  - ``enable_group.py``
  - ``offline_group.py``
  - ``auxtel/disable_ataos_corrections.py``
  - ``auxtel/prepare_for/onsky.py``
  - ``auxtel/prepare_for/co2_cleanup.py``
  - ``auxtel/enable_ataos_corrections.py``
  - ``standby_group.py``
  - ``base_point_azel.py``
  - ``base_track_target.py``
  - ``base_focus_sweep.py``
  - ``maintel/apply_dof.py``
  - ``maintel/offset_camera_hexapod.py``
  - ``maintel/offset_m2_hexapod.py``
  - ``maintel/close_mirror_covers.py``
  - ``maintel/mtmount/unpark_mount.py``
  - ``maintel/mtmount/park_mount.py``
  - ``maintel/base_close_loop.py``
  - ``maintel/open_mirror_covers.py``
  - ``maintel/move_p2p.py``
  - ``maintel/mtdome/slew_dome.py``
  - ``maintel/mtdome/home_dome.py``
  - ``maintel/take_image_anycam.py``
  - ``maintel/take_aos_sequence_comcam.py`` (`DM-47619 <https://rubinobs.atlassian.net//browse/DM-47619>`_)
- In `maintel/m1m3/enable_m1m3_slew_controller_flags.py`, update `run_block`` method to use new `m1m3_in_engineering_mode`` context manager to enter/exit engineering mode when setting slew controller settings. (`DM-47890 <https://rubinobs.atlassian.net//browse/DM-47890>`_)
- Added new property `disable_m1m3_force_balance` with default `false`.
  Maintains the ability to disable the M1M3 balance system, in case
  the coupling effect between the elevation axis and m1m3
  support system, repeats again, driving the system to a huge
  oscillation (`DM-48022 <https://rubinobs.atlassian.net//browse/DM-48022>`_)


Bug Fixes
---------

- In `auxtel/daytime_checkout/slew_and_take_image_checkout.py`, fix how TCS readiness is configured. (`DM-47890 <https://rubinobs.atlassian.net//browse/DM-47890>`_)
- fix unittest test_maintel_track_target_and_take_image_comcam.py
  to point to comcam script rather than auxtel one. (`DM-48005 <https://rubinobs.atlassian.net//browse/DM-48005>`_)


API Removal or Deprecation
--------------------------

- Deprecate `ignore_m1m3` property. (`DM-48022 <https://rubinobs.atlassian.net//browse/DM-48022>`_)


Other Changes and Additions
---------------------------

- Fix unit tests for TakeImageLatiss and ATGetStdFlatDataset to work with new take_image command procedure. (`DM-47667 <https://rubinobs.atlassian.net//browse/DM-47667>`_)
- General improvements to kafka compatibility.

  When trying to create the remotes on the init method we usually have some issues with the test cluster.
  By moving these to the configure state, as we have been doing recently with all scripts, it makes the script quicker to start and also reduces load on the testing kafka cluster. (`DM-49122 <https://rubinobs.atlassian.net//browse/DM-49122>`_)
