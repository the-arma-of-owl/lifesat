#!/usr/bin/env python3
"""
LIFESAT -- phase 5 gate: are the matrix results publishable.

  1. TRIVIALITY CHECK (K-59, R4).  D3 must beat the random detector by a clear
     margin; if the CIs overlap, the result cannot be published.

  2. CLEAN BASELINE.  In B0 (no attack) the false alarm rate must be small and
     reported.

  3. D1 DOES NOT BLOCK LEGITIMATE TRAFFIC.  Zero rejections in B0.

  4. RESIDUAL RISK IS REPORTED. Undetected events must be written without being
     smoothed over. A 100% detection rate in every scenario is a warning sign:
     either the attack is too easy or the scoring is wrong.

  5. RAW LOGS ARE PRESERVED. Each run's forensic record is in its own file so
     offline rescoring stays possible. In a study claiming forensic readiness this
     is a consistency condition.
"""

import argparse
import glob
import json
import math
import random
import statistics
import sys
from pathlib import Path

SCENARIOS = ["A1", "A2", "A3", "A4"]


def ci(xs, reps=2000, alpha=0.05, seed=12345):
    xs = [x for x in xs if x is not None and not (isinstance(x, float) and math.isnan(x))]
    if len(xs) < 2:
        return (float("nan"),) * 3
    rng = random.Random(seed)
    means = sorted(sum(rng.choice(xs) for _ in range(len(xs))) / len(xs) for _ in range(reps))
    return (statistics.fmean(xs), means[int(alpha / 2 * reps)],
            means[int((1 - alpha / 2) * reps) - 1])


def check(label, ok, detail=""):
    print(f"  {'[OK]' if ok else '[FAIL]'} {label}{('  ' + detail) if detail else ''}")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--matrix", default="results/matrix.json")
    ap.add_argument("--max-fpr", type=float, default=0.01)
    args = ap.parse_args()
    if not Path(args.matrix).exists():
        raise SystemExit(
            "no matrix results at %s. The matrix is not run by the gate script "
            "because it takes about 25 minutes; run it first:\n"
            "  python3 analysis/calibrate_d2.py --seeds 30\n"
            "  python3 analysis/run_matrix.py --pilot 30" % args.matrix)
    data = json.loads(Path(args.matrix).read_text())
    cells, n = data["cells"], data["seeds"]
    ok = True

    print(f"\n matrix: {len(cells)} cells x {n} seeds")
    ok &= check("all twenty cells were run", len(cells) == 20, f"{len(cells)} cells")

    print("\n triviality check (K-59, R4)")
    for sc in SCENARIOS:
        runs = cells.get(f"{sc}-D3", [])
        if not runs:
            ok &= check(f"{sc}/D3 result present", False); continue
        r = ci([x["RND"]["f05"] for x in runs])
        d = ci([x["D3"]["f05"] for x in runs])
        ok &= check(f"{sc}: D3 beats the random detector by a clear margin",
                    d[1] > r[2],
                    f"D3 {d[0]:.3f}[{d[1]:.3f},{d[2]:.3f}] vs "
                    f"RND {r[0]:.3f}[{r[1]:.3f},{r[2]:.3f}]")

    print("\n baseline (B0)")
    b0 = cells.get("B0-D3", [])
    if b0:
        f = ci([x["D3"]["fpr"] for x in b0])
        ok &= check("D3 false alarm rate in B0 is acceptable",
                    f[0] <= args.max_fpr, f"FPR = {f[0]:.4f} [{f[1]:.4f},{f[2]:.4f}]")
        ok &= check("the false alarm rate in B0 is NOT ZERO (threshold not degenerate)",
                    f[0] > 0, f"{f[0]:.4f}")
    b0d1 = cells.get("B0-D1", [])
    if b0d1:
        rej = statistics.fmean([r["scalars"].get("sat.tcRejected") or 0 for r in b0d1])
        ok &= check("D1 does not block legitimate traffic", rej == 0, f"{rej:.1f} rejections")

    print("\n residual risk (K-50 para. 422)")
    perfect = []
    for sc in SCENARIOS:
        runs = cells.get(f"{sc}-D3", [])
        if not runs:
            continue
        miss = ci([1 - x["D3"]["recallEvent"] for x in runs])
        print(f"    {sc}: yakalanamama {miss[0]:.3f} [{miss[1]:.3f},{miss[2]:.3f}]")
        if miss[0] <= 0:
            perfect.append(sc)
    ok &= check("no scenario claims 100% detection",
                len(perfect) < len(SCENARIOS),
                f"perfect detection: {', '.join(perfect) if perfect else 'none'}"
                + ("  [!] if every cell is perfect the labelling may be favouring us" if perfect else ""))

    print("\n preservation of raw logs")
    logs = glob.glob("results/*-s*-r0-events.csv")
    expected = 20 * n
    ok &= check("each run's forensic record is in its own file",
                len(logs) >= expected,
                f"{len(logs)} / {expected} logs")

    print()
    if ok:
        print("[OK] PHASE 5 GATE OPEN -- the results can be written into §6")
        return 0
    print("[FAIL] PHASE 5 GATE CLOSED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
