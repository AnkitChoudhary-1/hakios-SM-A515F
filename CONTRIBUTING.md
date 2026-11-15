# Contributing

Keep changes focused and record the exact source/build identity, verification, limitations and recovery/revert procedure. Preserve failed results and distinguish host models, QEMU execution and physical A51 observations.

Phase 4 is incomplete. A fixed success string, register snapshot or compiled driver is insufficient to mark display, input or storage operational. Hardware results need attributable logs and the corresponding visible/physical events or independent data hashes.

Keep firmware, Apple runtime/SDK files, backups, personal inventory/log dumps and generated binary images out of commits. Retain each source file's license and attribution; XNU-derived work is not covered by the repository's default MIT license.

Run `python3 scripts/public-smoke.py` for the portable checks and any checks appropriate to your change. Keep publication summaries separate from complete original evidence. Document changes in `docs/IMPLEMENTATION-LOG.md` and update current status only when the matching gate has execution evidence.

This repository is a development work package. Upstream registration and shared-code PRs should follow the pinned HakiOS device-publishing and contribution instructions, after the relevant layout/checks and evidence are ready.
