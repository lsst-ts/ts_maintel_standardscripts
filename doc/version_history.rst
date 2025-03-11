.. py:currentmodule:: lsst.ts.maintel.standardscripts

.. _lsst.ts.maintel.standardscripts.version_history:

===============
Version History
===============

.. towncrier release notes start

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
