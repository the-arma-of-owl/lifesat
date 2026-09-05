#!/usr/bin/env python3
"""write_p4_sums.py — checksum inventory of the Phase 4 root.

Neither SHA256SUMS.txt nor PHASE4_REPORT.md is hashed into SHA256SUMS.txt: the
report is written afterwards and quotes that digest. Compiled bytecode is
refused rather than skipped.
"""
from __future__ import annotations
import os, sys
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import p4_authority as PA  # noqa: E402
SUMS, REPORT = "SHA256SUMS.txt", "PHASE4_REPORT.md"


def main():
    root, rows, bad = PA.PHASE4_ROOT, [], []
    for base, dirs, files in os.walk(root):
        if "__pycache__" in dirs:
            bad.append(os.path.join(base, "__pycache__"))
        for name in sorted(files):
            if name in (SUMS, REPORT):
                continue
            full = os.path.join(base, name)
            if name.endswith((".pyc", ".pyo")):
                bad.append(full); continue
            rows.append((os.path.relpath(full, root), PA.sha256_file(full)))
    if bad:
        raise SystemExit(f"runnable bytecode under the Phase 4 root: {bad[:5]}")
    rows.sort()
    path = os.path.join(root, SUMS)
    with open(path, "w", encoding="utf-8") as handle:
        for relative, digest in rows:
            handle.write(f"{digest}  {relative}\n")
    print(f"{len(rows)} artefacts")
    print(f"{SUMS} sha256 {PA.sha256_file(path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
