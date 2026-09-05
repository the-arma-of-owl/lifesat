#!/usr/bin/env python3
"""build_phase4_membership.py — the single-member manifest and the settlement.

The manifest is DETACHED: it carries the successor package's file digests, so no
package file contains the SHA-256 of itself. The settlement carries the expected
manifest digest, the historical authority, both scorer digests and this root's
executable inventory. Its own digest is what the accepting party pins.
"""

from __future__ import annotations

import os
import sys

sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import p4_authority as PA     # noqa: E402
import p4_identity as PI      # noqa: E402
import p4_settlement as PS    # noqa: E402

# The successor package is a directory of views. The canonical member is the
# result file; the companions travel with it and are digested in the manifest.
SUCCESSOR_COMPANIONS = ("POOLED_RESULTS.json", "RUN_LEVEL_RESULTS.json",
                        "INPUT_MANIFEST.json", "VALIDATION.json",
                        "CORRECTED_RESULTS.sha256")


def main():
    canonical = [PA.SUCCESSOR_RELATIVE]
    package_dir = os.path.join(PA.PHASE4_ROOT, "successor", "package")
    target = os.path.join(PA.PHASE4_ROOT, PA.SUCCESSOR_RELATIVE)

    # the builder writes CORRECTED_RESULTS.json; the canonical member is that
    # file under its Phase 4 name, linked once and never rewritten
    source = os.path.join(package_dir, "CORRECTED_RESULTS.json")
    if not os.path.exists(source):
        raise SystemExit(f"the successor package {source} does not exist")
    if not os.path.exists(target):
        os.link(source, target)
    if PA.sha256_file(target) != PA.sha256_file(source):
        raise SystemExit("the canonical successor member is not the built one")

    files = [{"path": PA.SUCCESSOR_RELATIVE,
              "result_file_sha256": PA.sha256_file(target)}]
    for name in SUCCESSOR_COMPANIONS:
        path = os.path.join(package_dir, name)
        if os.path.exists(path):
            files.append({"path": os.path.relpath(path, PA.PHASE4_ROOT),
                          "result_file_sha256": PA.sha256_file(path)})

    manifest_path = os.path.join(PA.PHASE4_ROOT, "PHASE4_MANIFEST.json")
    manifest_digest = PA.write_json(manifest_path, {
        "canonical_member": PA.SUCCESSOR_RELATIVE,
        "files": files,
        "rule": (
            "SINGLE canonical member, detached. The successor does NOT replace "
            "the historical corrected package: results-v2-corrected and its "
            "seal stay byte-exact as the rollback target, and both are bound in "
            "the settlement."),
        "schema": "lifesat-v8-phase4-manifest/v1",
    })

    inventory_digest = PA.write_json(
        os.path.join(PA.PHASE4_ROOT, PI.INVENTORY_NAME),
        PI.build(PA.PHASE4_ROOT))

    contract_digest = PA.sha256_file(
        os.path.join(PA.PHASE4_ROOT, "PHASE4_CONTRACT.json"))

    settlement_digest = PA.write_json(
        os.path.join(PA.PHASE4_ROOT, PS.SETTLEMENT_NAME),
        PS.build(contract_digest, "PHASE4_MANIFEST.json", manifest_digest,
                 inventory_digest, canonical))

    print(f"EXECUTABLE_INVENTORY.json   {inventory_digest}")
    print(f"PHASE4_MANIFEST.json        {manifest_digest}  ({len(files)} files)")
    print(f"PHASE4_SETTLEMENT.json      {settlement_digest}")
    print()
    print("Pin the settlement from outside:")
    print(f"  --expect-phase4-settlement-sha256 {settlement_digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
