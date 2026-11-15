# A51 cumulative source patches

Select the Phase 3 or Phase 4 pair; they are alternative cumulative snapshots,
not patches to apply sequentially. Common patches apply to HakiOS commit
`63fc2b4633bac3af8e57dadab9f5a8d4cb940438`. XNU patches apply after that
common version's `xnu/apply.sh` has generated its overlays on XNU commit
`c54f35ca767986246321eb901baf8f5ff7923f6a` (`xnu-8796.121.2`).

The common patches include the A51 descriptor/configuration and platform or
driver sources. Native patches retain the matching low-level entry, return,
interrupt, configuration and driver integration changes. Generated source
configuration headers needed by the captured native tree are retained;
binary build output and incidental build-directory files are excluded.

Before/after file identities are in `PUBLICATION-MANIFEST.json`. Patch checks
materialize only the affected baseline files in temporary directories, check
application, apply the patch there and compare every resulting file hash.
The original pinned and experimental source checkouts remain untouched.

See [the build guide](../docs/PUBLIC-BUILD.md) for limitations. Phase 4 hardware
qualification is still pending, regardless of successful patch application.
