# A51 HakiOS work package

Read README.md, docs/PUBLIC-STATUS.md, docs/PUBLICATION.md,
docs/PUBLIC-BUILD.md, docs/INDEX.md, docs/IMPLEMENTATION-LOG.md and
docs/ROADMAP.md before changing this repository.

Phase 4 is incomplete. Preserve the distinction between original device
evidence, derived publication summaries, host models and QEMU results.
Do not infer a working iOS UI, display/input/storage support, GPU acceleration,
Safari, Apple services or a no-flash boot from compilation or fixed markers.

Keep proprietary runtime/SDK material, vendor firmware, phone backups,
personal logs/inventory and generated binaries out of commits. Preserve
licenses and attribution. Record changes, meaningful checks, limitations and
rollback in docs/IMPLEMENTATION-LOG.md; use scripts/run.py for consequential
commands. Do not overwrite historical evidence when sources change.

The portable smoke checks use only host parsers and native protocol models.
Hardware/candidate/restore scripts have separate dependencies and can write
or reboot a device. Publishing this repository is not a hardware operation.
User instructions override these guidelines; do not invent additional approvals.
