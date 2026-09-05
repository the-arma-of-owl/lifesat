#!/usr/bin/env python3
"""p4_identity.py — this root's own executables, inventoried and pinned.

Closed set over BOTH the tools and the candidate scorer: a repair whose scorer
can be edited without anything noticing is not a repair anyone can rely on.
Missing, extra, duplicate, bytecode and hash mismatch are each RED under
`D-P4-WRAPPER-EXECUTABLE-IDENTITY-01`, and the check runs FIRST.
"""

from __future__ import annotations

import os
import sys

sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import p4_authority as PA  # noqa: E402

DETECTOR = "D-P4-WRAPPER-EXECUTABLE-IDENTITY-01"
INVENTORY_NAME = "EXECUTABLE_INVENTORY.json"
SCHEMA = "lifesat-v8-phase4-executable-inventory/v1"

RUNNABLE_EXTENSIONS = (".py", ".sh")
FORBIDDEN_EXTENSIONS = (".pyc", ".pyo")
FORBIDDEN_DIRECTORIES = ("__pycache__",)


def scan(root):
    entries, bytecode = {}, []
    for base, dirs, files in os.walk(root):
        for name in list(dirs):
            if name in FORBIDDEN_DIRECTORIES:
                bytecode.append(os.path.relpath(os.path.join(base, name), root))
        for name in sorted(files):
            full = os.path.join(base, name)
            relative = os.path.relpath(full, root)
            if name.endswith(FORBIDDEN_EXTENSIONS):
                bytecode.append(relative)
            elif name.endswith(RUNNABLE_EXTENSIONS):
                entries[relative] = PA.sha256_file(full)
    return entries, bytecode


def build(root):
    entries, bytecode = scan(root)
    if bytecode:
        raise SystemExit(
            f"runnable bytecode under the Phase 4 root: {sorted(bytecode)[:5]}. "
            f"The inventory is NOT written: describing less than what can run is "
            f"the defect this exists to prevent.")
    return {
        "closed_set_rule": (
            "This is the COMPLETE set of runnable files under the Phase 4 root, "
            "INCLUDING the repaired candidate scorer. A path on disk but absent "
            "here, a path here but absent on disk, a duplicate path, any "
            "compiled bytecode, or any content whose digest differs, are each "
            "RED under " + DETECTOR + "."),
        "entries": [{"path": path, "sha256": digest}
                    for path, digest in sorted(entries.items())],
        "runnable_extensions": list(RUNNABLE_EXTENSIONS),
        "schema": SCHEMA,
        "scope": (
            "Binds this root's executables to the settlement and through it to "
            "the external pin. It does not defend against a validator edited to "
            "skip this check; that is covered out of band by "
            "sha256sum -c SHA256SUMS.txt and by the external settlement pin."),
    }


def verify(root, expected_inventory_sha=None):
    findings = []

    def fail(message, location=None):
        findings.append({"detector_id": DETECTOR, "location": location,
                         "message": message})

    path = os.path.join(root, INVENTORY_NAME)
    if not os.path.exists(path):
        fail(f"{INVENTORY_NAME} is absent; this root's executables are bound to "
             f"nothing", path)
        return findings
    live_sha = PA.sha256_file(path)
    if expected_inventory_sha is not None and live_sha != expected_inventory_sha:
        fail(f"{INVENTORY_NAME} is {live_sha}, the settlement binds "
             f"{expected_inventory_sha}", path)

    try:
        payload = PA.load_json(path)
    except Exception as error:                      # noqa: BLE001
        fail(f"{INVENTORY_NAME} is unreadable: {error}", path)
        return findings
    if not isinstance(payload, dict):
        fail(f"{INVENTORY_NAME} root is {type(payload).__name__}", path)
        return findings
    if payload.get("schema") != SCHEMA:
        fail(f"inventory schema {payload.get('schema')!r} != {SCHEMA!r}", path)

    rows = payload.get("entries")
    if not isinstance(rows, list):
        fail("inventory entries is not a list", path)
        return findings

    declared = {}
    for row in rows:
        if not isinstance(row, dict) or "path" not in row or "sha256" not in row:
            fail(f"inventory entry {row!r} is not a path/sha256 pair", path)
            continue
        if row["path"] in declared:
            fail(f"inventory lists {row['path']!r} more than once", path)
            continue
        declared[row["path"]] = row["sha256"]

    live, bytecode = scan(root)
    for relative in sorted(bytecode):
        fail(f"compiled bytecode is present and is runnable: {relative}", relative)
    for relative in sorted(set(declared) - set(live)):
        fail(f"the inventory declares {relative!r}, which is not on disk", relative)
    for relative in sorted(set(live) - set(declared)):
        fail(f"{relative!r} is a runnable file the inventory does not declare",
             relative)
    for relative in sorted(set(declared) & set(live)):
        if declared[relative] != live[relative]:
            fail(f"{relative}: live {live[relative]} != inventoried "
                 f"{declared[relative]}", relative)
    return findings


def main():
    root = PA.PHASE4_ROOT
    digest = PA.write_json(os.path.join(root, INVENTORY_NAME), build(root))
    payload = PA.load_json(os.path.join(root, INVENTORY_NAME))
    print(f"runnable files : {len(payload['entries'])}")
    print(f"{INVENTORY_NAME} sha256 {digest}")
    findings = verify(root, digest)
    print(f"self-check     : {'CLEAN' if not findings else findings}")
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
