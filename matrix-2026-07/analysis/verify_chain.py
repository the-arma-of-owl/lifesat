#!/usr/bin/env python3
"""
LIFESAT -- phase 0 gate: hash chain of the forensic log (rule R3).

It does two things:

  verify    recomputes the chain from scratch and compares it against the values
            in the file. On a mismatch it reports the index where the chain
            breaks, which is what the A7 scenario measures.

  tamper    deletes the record at the given index or alters its timestamp, and
            shows that the break really starts there. That is the gate's evidence:
            the mechanism localises the edit.

Chain:  H_t = SHA256(H_{t-1} || record_t),  H_0 = SHA256("LIFESAT-GENESIS")
record_t = "idx,time,category,fields"  (the first four fields of the CSV row)
"""

import argparse
import csv
import hashlib
import sys
from pathlib import Path

GENESIS_INPUT = "LIFESAT-GENESIS"


def sha256_hex(*parts):
    d = hashlib.sha256()
    for p in parts:
        d.update(p.encode())
    return d.hexdigest()


def read_log(path):
    csv.field_size_limit(sys.maxsize)
    rows = []
    with open(path, newline="") as f:
        for row in csv.reader(f):
            if not row or row[0] == "idx":
                continue
            # record = first four fields; the last two are prev and chain
            rows.append({"record": ",".join(row[:4]), "prev": row[4], "chain": row[5]})
    return rows


def recompute(rows):
    """Recomputes the chain from the start; returns the index of the first mismatch (None if clean)."""
    head = sha256_hex(GENESIS_INPUT)
    first_break = None
    for i, r in enumerate(rows):
        expected_prev = head
        head = sha256_hex(head, r["record"])
        if first_break is None and (r["prev"] != expected_prev or r["chain"] != head):
            first_break = i
    return head, first_break


def cmd_verify(args):
    rows = read_log(args.log)
    head, brk = recompute(rows)
    print(f"record count : {len(rows)}")
    print(f"computed head: {head}")

    anchor = Path(args.log).with_name(Path(args.log).name.replace("-events.csv", "-anchor.txt"))
    if anchor.exists():
        fields = dict(l.split("=", 1) for l in anchor.read_text().splitlines() if "=" in l)
        print(f"head in the anchor : {fields.get('chainHead')}")
        if fields.get("chainHead") != head:
            print("[FAIL] The head computed from the anchor does not match -- the log has been altered.")
            if brk is not None:
                print(f"   First break at index: {brk}")
            return 1

    if brk is not None:
        print(f"[FAIL] The chain breaks at record {brk}.")
        return 1
    print("[OK] Chain consistent -- no record was altered, deleted or reordered.")
    return 0


def cmd_tamper(args):
    """The gate's evidence: it really corrupts the record and shows that the break localises."""
    rows = read_log(args.log)
    if not rows:
        sys.exit("ERROR: the log is empty")
    idx = args.index if args.index >= 0 else len(rows) // 2
    if idx >= len(rows):
        sys.exit(f"ERROR: index {idx} > record count {len(rows)}")

    print(f"original log : {len(rows)} records")
    head_before, brk_before = recompute(rows)
    print(f"  -> chain {'consistent' if brk_before is None else f'broken at index {brk_before}'}")

    for mode in (["delete", "timestamp"] if args.mode == "both" else [args.mode]):
        work = [dict(r) for r in rows]
        if mode == "delete":
            removed = work.pop(idx)
            print(f"\nA7a -- record {idx} DELETED: {removed['record'][:70]}")
        else:
            r = work[idx]
            parts = r["record"].split(",", 2)
            old = parts[1]
            parts[1] = str(float(old) + 3600) if old.replace(".", "").isdigit() else old + "X"
            r["record"] = ",".join(parts)
            print(f"\nA7b -- timestamp of record {idx} {old} -> {parts[1]}")

        _, brk = recompute(work)
        if brk is None:
            print("  [FAIL] GATE CLOSED -- the tampering was NOT detected.")
            return 1
        print(f"  [OK] break index {brk} (expected {idx})")
        if brk != idx:
            print(f"  [FAIL] GATE CLOSED -- the break localised at {brk} instead of {idx}.")
            return 1
        surviving = idx if mode == "delete" else idx
        print(f"  [OK] {surviving} records still verify; the event order can be reconstructed up to that point")

    print("\n[OK] GATE OPEN -- deletion and timestamp tampering are detected and")
    print("   the break localises at the correct index (R3, the A7 criterion of §5.2).")
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("verify", help="recompute and verify the chain")
    v.add_argument("log")
    v.set_defaults(func=cmd_verify)

    t = sub.add_parser("tamper", help="tamper with it and show that the break localises")
    t.add_argument("log")
    t.add_argument("--index", type=int, default=-1, help="-1: the middle record")
    t.add_argument("--mode", choices=["delete", "timestamp", "both"], default="both")
    t.set_defaults(func=cmd_tamper)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
