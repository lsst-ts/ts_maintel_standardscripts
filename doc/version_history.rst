.. py:currentmodule:: lsst.ts.maintel.standardscripts

.. _lsst.ts.maintel.standardscripts.version_history:

===============
Version History
===============

.. towncrier release notes start

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
