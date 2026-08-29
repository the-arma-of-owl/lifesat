#!/usr/bin/env python3
"""write_sums.py -- the exact checksum inventory of the Phase 3 pilot root.

Every artefact under the pilot root is listed with its SHA-256, including the
48 raw run logs and their anchors, so an accepting party can verify the whole
tree with a single `sha256sum -c`.

Two things this deliberately does NOT do:

  * it does not hash itself into its own output;
  * it does not include PHASE3_PILOT_REVIEW_REPORT.md, which is written by hand
    AFTER this runs.  A digest of a file that quotes this digest cannot exist,
    and pretending otherwise is the hash cycle the accepted round removed.  The
    report says so in its own identity table rather than printing a number that
    cannot be true.

Compiled bytecode is refused rather than skipped: a `.pyc` under the pilot root
would be a runnable artefact outside the inventory.
"""

from __future__ import annotations

import hashlib
import os
import sys

sys.dont_write_bytecode = True

PILOT_ROOT = os.environ.get("LIFESAT_PILOT_ROOT", "runs/pilot")
SUMS_NAME = "SHA256SUMS.txt"
REPORT_NAME = "PHASE3_PILOT_REVIEW_REPORT.md"
FORBIDDEN = (".pyc", ".pyo")


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 16), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    rows, forbidden = [], []
    for base, dirs, files in os.walk(PILOT_ROOT):
        if "__pycache__" in dirs:
            forbidden.append(os.path.join(base, "__pycache__"))
        for name in sorted(files):
            if name in (SUMS_NAME, REPORT_NAME):
                continue
            full = os.path.join(base, name)
            if name.endswith(FORBIDDEN):
                forbidden.append(full)
                continue
            rows.append((os.path.relpath(full, PILOT_ROOT), sha256_file(full)))
    if forbidden:
        raise SystemExit(f"runnable bytecode under the pilot root: {forbidden[:5]}")

    rows.sort()
    path = os.path.join(PILOT_ROOT, SUMS_NAME)
    with open(path, "w", encoding="utf-8") as handle:
        for relative, digest in rows:
            handle.write(f"{digest}  {relative}\n")
    print(f"{len(rows)} artefacts")
    print(f"{SUMS_NAME} sha256 {sha256_file(path)}")
    print(f"NOTE: {REPORT_NAME} is written after this and is not covered here.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
