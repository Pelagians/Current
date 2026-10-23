# COSMIC native repair candidates

These source patches address the three failures reproduced during PR #29's
disposable x86_64 UEFI qualification. They are candidates until boot evidence
establishes their effect. The normal BlueBuild recipes do not consume them yet.

- The portal patch replaces an unrecoverable Wayland-dispatch panic with a logged
  unsuccessful process exit. It preserves native service recovery and error
  visibility; it does not turn disconnects into successes or disable coredumps.
- Alma 9 welcome specifies an initial size within its existing maximum limits.
  The vendor default initial size is 1024×768, larger than the application's
  900×650 maximum. Its content scrolls within the available height while native
  Back/Next/Finish remain outside the scroll area. No completion marker,
  fullscreen shortcut, resolution change or user preference reset is involved.
- Alma 10's floating panel repaints its complete transparent surface instead of
  relying on preserved EGL buffer contents. Expanded panels retain damage
  tracking. This is a conservative candidate for the observed margin streaks,
  with a possible repaint cost, not a confirmed upstream root-cause fix.

`sources.json` binds native source RPM checksums, upstream package versions and
signed immutable parent images. The rebuild retains the vendor's dependencies,
installation, licenses and test sections, applies one patch with native
`%autosetup`, and adds `.current1` to the native release. Cargo uses the SRPM's
vendored dependencies with network access disabled. Source and repaired binary
RPMs accompany build receipts. Build dependencies exist only in disposable
containers; candidate payloads install only the repaired runtime RPMs.

Dispatch **current-builder** (`build.yml`) on the feature branch with
`cosmic_repairs_only=true`. This calls `test-cosmic-repairs.yml` without requiring
the new workflow to exist on `stable`. Five native x86_64 package builds produce three signed isolated
bootc candidates under `br-repair-run-RUN-ATTEMPT`. The candidates retain the
standard image repository identity and setup API. Their test indexes contain
only x86_64; they do not qualify ARM or replace the normal multi-architecture
publication gate. Run the existing workstation UEFI harness against those
channels and bind `image_revision` to the repair workflow's exact source SHA.

Acceptance requires fresh native Alma 9 onboarding, repeated Alma 10 dock
captures after reboots, actual portal capture, normal shutdown diagnostics,
graphical login, cross-distribution staging and exact rollback. Original
1280×800 software virtio rendering, enforcing SELinux and XFS stay unchanged.
An absent panic alone does not establish clean session teardown. A clean frame
alone does not establish absence of an intermittent rendering defect.

For a retry after a builder-only change, `cosmic_repairs_seed_run` may identify a
completed repair run on the same repository/branch. Only present, unexpired RPM
artifacts are reused. The assembler rechecks every native source, parent,
patch and binary checksum against the current catalogue before building or
signing anything; it never reuses assembled candidate images. A changed repair
patch or source must be rebuilt rather than seeded with a mismatching receipt.
