#!/usr/bin/env python3
"""
LIFESAT -- aggregation of the matrix results for §6.

Reporting rules:
  - per-scenario mean, not total
  - a 95% bootstrap confidence interval for every KPI
  · no F1PA
  - the random detector as a baseline in every cell
  - a detection rate below 100% reported as residual risk, unsmoothed
  If confidence intervals overlap, "outperforms" may not be written.
"""

import argparse
import json
import math
import random
import statistics
import sys
from pathlib import Path

SCENARIOS = ["B0", "A1", "A2", "A3", "A4"]
DEFENCES = ["D0", "D1", "D2", "D3"]
# which detector counts as the detector of a given cell
CELL_DETECTOR = {"D0": None, "D1": None, "D2": "D2", "D3": "D3"}


def ci(xs, reps=2000, alpha=0.05, seed=12345):
    xs = [x for x in xs if x is not None and not (isinstance(x, float) and math.isnan(x))]
    if not xs:
        return (float("nan"),) * 3
    m = statistics.fmean(xs)
    if len(xs) < 2:
        return m, m, m
    rng = random.Random(seed)
    means = sorted(sum(rng.choice(xs) for _ in range(len(xs))) / len(xs) for _ in range(reps))
    return m, means[int(alpha / 2 * reps)], means[int((1 - alpha / 2) * reps) - 1]


def fmt(m, lo, hi, d=3):
    if math.isnan(m):
        return " -- "
    return f"{m:.{d}f} [{lo:.{d}f},{hi:.{d}f}]"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--matrix", default="results/matrix.json")
    args = ap.parse_args()
    data = json.loads(Path(args.matrix).read_text())
    cells, n = data["cells"], data["seeds"]

    print(f"\n{'='*100}")
    print(f"LIFESAT -- tier 1 results   ({len(cells)} cells x {n} seeds, "
          f"run length {data['endTime']/86400:.0f} days)")
    print(f"{'='*100}")

    # 1. attack effect: how much each defence layer prevents
    print("\n COMMAND SECURITY -- adversarial commands accepted by the satellite")
    print(f"  {'scenario':<9}" + "".join(f"{d:>22}" for d in DEFENCES))
    for sc in SCENARIOS:
        row = f"  {sc:<9}"
        for d in DEFENCES:
            runs = cells.get(f"{sc}-{d}", [])
            if not runs:
                row += f"{' -- ':>22}"; continue
            acc = [r["scalars"].get("sat.tcAccepted") or 0 for r in runs]
            rej = [r["scalars"].get("sat.tcRejected") or 0 for r in runs]
            m, lo, hi = ci(rej)
            row += f"{'ret ' + fmt(m, lo, hi, 1):>22}"
        print(row)

    # 2. detection performance
    for det_label, picker in (("D2 (flow anomaly)", "D2"), ("D3 (twin deviation)", "D3")):
        print(f"\n {det_label}")
        print(f"  {'scenario':<9}{'F0.5':>22}{'F1C':>22}{'FPR':>22}{'delay':>12}")
        for sc in SCENARIOS:
            key = f"{sc}-{picker}"
            runs = cells.get(key, [])
            if not runs:
                print(f"  {sc:<9}{' -- ':>22}"); continue
            s = [r[picker] for r in runs]
            f05 = ci([x["f05"] for x in s])
            f1c = ci([x["f1c"] for x in s])
            fpr = ci([x["fpr"] for x in s])
            dl = [x["meanDetectionDelay"] for x in s if x["meanDetectionDelay"] is not None]
            dls = f"{statistics.fmean(dl):.0f} s" if dl else " -- "
            print(f"  {sc:<9}{fmt(*f05):>22}{fmt(*f1c):>22}{fmt(*fpr, 4):>22}{dls:>12}")

    # 3. triviality check
    # Not a hypothesis test. p = 0.01 is the random detector's per-observation alarm
    # probability, not a significance level. Two non-overlapping bootstrap intervals
    # are also not a paired significance test; with common random numbers, a formal
    # comparison would need a seed-paired difference bootstrap. Not done.
    print("\n TRIVIALITY CHECK -- random detector (alarm probability 0.01/observation)")
    print(f"  {'scenario':<9}{'RND F0.5':>22}{'D3 F0.5':>22}{'CIs disjoint':>20}")
    trivial = []
    for sc in SCENARIOS:
        runs3 = cells.get(f"{sc}-D3", [])
        if not runs3:
            continue
        r = ci([x["RND"]["f05"] for x in runs3])
        d = ci([x["D3"]["f05"] for x in runs3])
        # descriptive only: do the intervals overlap? if they do, "outperforms" is not
        # written. non-overlap is not a formal significance claim either.
        sep = d[1] > r[2] or r[1] > d[2]
        trivial.append((sc, sep))
        print(f"  {sc:<9}{fmt(*r):>22}{fmt(*d):>22}"
              f"{('[OK] disjoint' if sep else '[!] overlapping'):>20}")

    # 3b. which channel raised the D3 alarm
    # Without this table, "D3 caught all four attacks" is misleading. Since D3 is
    # D1 plus the twin, the source on command-side attacks is largely the security
    # channel: D1 rejects, the counter rises, the twin sees it. That is a real
    # detection but not one independent of D1.
    #
    # Two limits belong in the text:
    #   (1) Twin.cc writes one channel per row (priority: physical, logical,
    #       security), so this is the assigned-channel table, not an independent
    #       sum of simultaneous violations
    #   (2) the physical column includes the B0 baseline; the attributable part is
    #       the difference from B0, shown separately
    print("\n WHICH CHANNEL RAISED THE D3 ALARM (mean per run, priority channel)")
    print(f"  {'scenario':<9}{'physical':>12}{'(B0 delta)':>13}{'logical':>12}{'safety':>11}")
    logdir = Path(args.matrix).parent
    chan = {}
    for sc in SCENARIOS:
        files = sorted(logdir.glob(f"{sc}-D3-s??-r0-events.csv"))
        if not files:
            continue
        p = l = s = 0
        for f in files:
            for line in open(f, errors="replace"):
                if ",d3.alarm," not in line:
                    continue
                if "channel=physical" in line:
                    p += 1
                elif "channel=logical" in line:
                    l += 1
                elif "channel=security" in line:
                    s += 1
        n = len(files)
        chan[sc] = (p / n, l / n, s / n)
    base = chan.get("B0", (0.0, 0.0, 0.0))[0]
    for sc in SCENARIOS:
        if sc not in chan:
            continue
        p, l, s = chan[sc]
        delta = " -- " if sc == "B0" else f"{p - base:+.2f}"
        print(f"  {sc:<9}{p:>12.2f}{delta:>13}{l:>12.2f}{s:>11.2f}")
    if chan:
        print("  [!] Priority order is physical -> logical -> safety; on a simultaneous")
        print("     violation only the first is logged.  This is NOT an independent channel contribution.")

    # 4. residual risk
    print("\n RESIDUAL RISK (K-50 para. 422 -- reported unsmoothed)")
    for sc in SCENARIOS:
        if sc == "B0":
            continue
        runs = cells.get(f"{sc}-D3", [])
        if not runs:
            continue
        miss = ci([1 - x["D3"]["recallEvent"] for x in runs])
        ev = statistics.fmean([x["D3"]["events"] for x in runs])
        print(f"  {sc}: miss rate per event {fmt(*miss)}   "
              f"(mean {ev:.1f} impact windows/run)")

    print(f"\n{'='*100}")
    print("Writing rule: for any pair whose intervals above overlap, the words")
    print("   'outperforms' or 'significantly better' may not be used.")
    print("Disjoint intervals are also not a formal significance claim.")
    print("   No paired hypothesis test was run; 'disjoint CIs' is a descriptive observation.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
