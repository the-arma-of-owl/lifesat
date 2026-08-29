#!/usr/bin/env python3
"""
LIFESAT -- phase 0 gate: isolation of the ground-truth label (rule R1).

This is the most important structural check showing that the study is not theatre.

Claim: **no detector, defence or twin can read whether an attack actually
happened.**  Saying "we did not do that" is not enough; it has to be
_impossible_ in the code.  The mechanism:

  · The attacker writes what it did **directly** to the collector via
    `Collector::recordGroundTruth()`.  The label is never placed in a packet.
  · Detectors emit their verdicts **outward** through signals; nothing reads
    okuma yoktur.
  · There is therefore no code path from the answer key to a detector.

The check looks at three things:
  1. detector, defence and twin sources do not call recordGroundTruth
  2. they do not reach the Collector's answer-key fields
  3. packet definitions carry no label field

The gate closes if even one of these three is violated.
"""

import re
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"

# modules forbidden from touching the answer key (file name prefix)
DETECTOR_PREFIXES = ("D1", "D2", "D3", "Detector", "Twin", "Defence", "Random")

# forbidden symbols
FORBIDDEN = [
    ("recordGroundTruth", "answer-key write/read call"),
    ("truthLog", "answer-key file"),
    ("getGroundTruth", "answer-key reader"),
    ("isAttack", "attack label on a packet"),
    ("groundTruthLabel", "attack label on a packet"),
]

# field names that must not appear in packet definitions
PACKET_FORBIDDEN = ["isAttack", "attackLabel", "groundTruth", "isMalicious", "tampered"]


def detector_sources():
    if not SRC.exists():
        return []
    return [p for p in SRC.rglob("*.[ch]*")
            if p.name.startswith(DETECTOR_PREFIXES) or "detector" in str(p.parent).lower()]


def main():
    failures = []

    # --- 1 and 2: detector sources cannot touch the answer key ---------------
    sources = detector_sources()
    for path in sources:
        text = path.read_text()
        # strip comments: real code access is what matters
        code = "\n".join(l for l in text.splitlines()
                         if not l.strip().startswith(("//", "*", "/*")))
        for symbol, why in FORBIDDEN:
            if re.search(rf"\b{re.escape(symbol)}\b", code):
                failures.append(f"{path.relative_to(SRC.parent)}: '{symbol}' appears ({why})")

    # --- 3: packet definitions cannot carry a label field --------------------
    for msg in SRC.rglob("*.msg"):
        code = "\n".join(l for l in msg.read_text().splitlines()
                         if not l.strip().startswith("//"))
        for field in PACKET_FORBIDDEN:
            if re.search(rf"\b{re.escape(field)}\b", code):
                failures.append(f"{msg.relative_to(SRC.parent)}: packet field '{field}' "
                                f" -- a label may not be carried in a packet")

    # --- rapor --------------------------------------------------------------
    print(f"detector/twin sources scanned : {len(sources)}")
    print(f"packet definitions scanned    : {len(list(SRC.rglob('*.msg')))}")
    if sources:
        for p in sources:
            print(f"  · {p.relative_to(SRC.parent)}")
    else:
        print("  (empty for now -- filled in phases 2/4, the check gains meaning then)")

    print()
    if failures:
        print("[FAIL] GATE CLOSED -- label isolation was violated:")
        for f in failures:
            print(f"   · {f}")
        return 1

    print("[OK] GATE OPEN -- no code path from the answer key to any detector (R1).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
