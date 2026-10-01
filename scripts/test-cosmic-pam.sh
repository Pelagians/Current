#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# Exercise the shared reconciler's current PAM ownership contract in fixtures.
python3 scripts/tests/test-workstation-dm.py \
  Reconciliation.test_cosmic_selects_native_greeter_with_vendor_pam \
  Reconciliation.test_current_pam_override_is_retired_and_admin_overrides_preserved \
  Reconciliation.test_current_pam_override_requires_vendor_before_cleanup
