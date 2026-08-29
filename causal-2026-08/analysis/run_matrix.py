#!/usr/bin/env python3
"""
LIFESAT -- running and scoring the tier 1 matrix.

  20 cells = {B0, A1, A2, A3, A4} x {D0, D1, D2, D3}

Defence layers:
  D0 = none, D1 = command authorisation
  D2 = D1 plus flow anomaly, D3 = D1 plus twin deviation detector
D2 and D3 are not fused; D1 is the shared base, so each layer stays visible.

Seed plan (Hoad et al.):
  No fixed repetition count. A pilot starts at 30 seeds; more are added until the
  95% confidence half-width of the primary KPIs falls below 5% of the cumulative
  mean and stays there.

CRN (K-34): B0 and the attack conditions share the same seed stream, so the
comparison is paired.
"""

import argparse
import glob
import json
import math
import os
import random
import re
import statistics
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from score import score_run  # noqa: E402

SCENARIOS = ["B0", "A1", "A2", "A3", "A4"]
DEFENCES = ["D0", "D1", "D2", "D3"]

OVERRIDES = {
    "D0": {"*.sat.commandAuthEnabled": "false", "*.gs.signCommands": "false",
           "*.flow.enabled": "false", "*.twin.enabled": "false"},
    "D1": {"*.sat.commandAuthEnabled": "true", "*.gs.signCommands": "true",
           "*.flow.enabled": "false", "*.twin.enabled": "false"},
    # the D2 threshold file is required: FlowDetector refuses to run uncalibrated.
    # the path is relative to the run directory (simulations/) and quoted because it
    # is a string.
    "D2": {"*.sat.commandAuthEnabled": "true", "*.gs.signCommands": "true",
           "*.flow.enabled": "true", "*.twin.enabled": "false",
           "*.flow.thresholdFile": '"../results/d2_thresholds.txt"',
           "*.flow.windowSize": "60s"},
    "D3": {"*.sat.commandAuthEnabled": "true", "*.gs.signCommands": "true",
           "*.flow.enabled": "false", "*.twin.enabled": "true"},
}
# the random detector runs in every cell as the triviality baseline
ALWAYS = {"*.rnd.enabled": "true"}

# Primary KPIs and precision criteria. A relative 5% criterion on a quantity near
# 0.001 would need hundreds of seeds and teach nothing, so near-zero KPIs use an
# absolute threshold. Both were fixed before the runs.
PRIMARY_KPIS = {
    "f05":    {"rel": 0.05, "abs": None},
    "recall": {"rel": 0.05, "abs": None},
    "fpr":    {"rel": 0.05, "abs": 0.005},   # 0.5 percentage points
}


def read_scalars(path):
    v = {}
    for line in open(path):
        m = re.match(r"scalar\s+Lifesat\.(\S+)\s+(\S+)\s+([-\d.eE+]+)", line)
        if m:
            try:
                v[f"{m.group(1)}.{m.group(2)}"] = float(m.group(3))
            except ValueError:
                pass
    return v


def run_cell(scenario, defence, seed, inet, label):
    # the seed goes into the file name. without it each run erases the previous
    # forensic log and offline rescoring becomes impossible.
    label = f"{label}-s{seed:02d}"
    cmd = ["../out/clang-release/lifesat", "-u", "Cmdenv", "-c", scenario,
           "-f", "lifesat.ini", "-n", f".:../src:{inet}/src",
           "-l", f"{inet}/src/libINET.so", f"--seed-set={seed}",
           # string parameters must be quoted on the command line; OMNeT++ cannot
           # parse them otherwise.
           f'--*.collector.runLabel="{label}"']
    ov = dict(OVERRIDES[defence]); ov.update(ALWAYS)
    for k, v in ov.items():
        cmd.append(f"--{k}={v}")
    r = subprocess.run(cmd, cwd="simulations", capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-1200:], r.stderr[-1200:])
        raise SystemExit(f"ERROR: {scenario}/{defence} seed {seed}")
    return read_scalars(sorted(glob.glob(f"simulations/results/{scenario}-*.sca"))[-1])


def bootstrap_ci(xs, reps=2000, alpha=0.05, rng=None):
    """Bootstrap 95% confidence interval (K-34: bootstrap rather than the delta method)."""
    xs = [x for x in xs if x is not None and not math.isnan(x)]
    if len(xs) < 2:
        return (float("nan"), float("nan"))
    rng = rng or random.Random(12345)
    means = []
    n = len(xs)
    for _ in range(reps):
        means.append(sum(rng.choice(xs) for _ in range(n)) / n)
    means.sort()
    return (means[int(alpha / 2 * reps)], means[int((1 - alpha / 2) * reps) - 1])


def converged(xs, crit):
    """Hoad's stopping rule: has the relative OR the absolute precision been met?"""
    xs = [x for x in xs if x is not None and not math.isnan(x)]
    if len(xs) < 2:
        return False, float("inf")
    mean = statistics.fmean(xs)
    lo, hi = bootstrap_ci(xs)
    hw = (hi - lo) / 2
    if crit["abs"] is not None and hw <= crit["abs"]:
        return True, hw
    if abs(mean) < 1e-12:
        return True, hw       # mean is zero: the half-width is zero too
    return hw / abs(mean) <= crit["rel"], hw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", type=int, default=30, help="K-45: number of pilot seeds")
    ap.add_argument("--max-seeds", type=int, default=60)
    ap.add_argument("--lookahead", type=int, default=5)
    ap.add_argument("--precision", type=float, default=0.05,
                    help="(informational; the criteria are fixed in PRIMARY_KPIS)")
    ap.add_argument("--end", type=float, default=604800.0)
    ap.add_argument("--rule-cells", default="A2/D3,A1/D3",
                    help="cells where the replication rule applies IN FULL (K-45)")
    ap.add_argument("--out", default="results/matrix.json")
    ap.add_argument("--cells", default="", help="these cells only (debugging)")
    args = ap.parse_args()
    inet = os.environ.get("INET_ROOT", "")

    cells = [(s, d) for s in SCENARIOS for d in DEFENCES]
    if args.cells:
        want = {tuple(c.split("/")) for c in args.cells.split(",")}
        cells = [c for c in cells if c in want]

    rule_cells = {tuple(c.split("/")) for c in args.rule_cells.split(",") if c}

    # 1. replication rule: applied fully on a few cells, the resulting N propagates
    print(f" replication rule (K-45) -- cells where it applies in full: "
          f"{', '.join('/'.join(c) for c in sorted(rule_cells))}")
    print(f"  pilot {args.pilot} · lookahead {args.lookahead} · "
          f"target half-width <= {100*args.precision:.0f}% of the mean\n")

    required_n = args.pilot
    for cell in sorted(rule_cells):
        sc, de = cell
        series = {k: [] for k in PRIMARY_KPIS}
        n_at = None
        for seed in range(args.max_seeds):
            label = f"{sc}-{de}"
            run_cell(sc, de, seed, inet, label)
            r = score_run(f"results/{label}-s{seed:02d}-r0-events.csv",
                          f"results/{label}-s{seed:02d}-r0-truth.csv", args.end)["D3" if de == "D3" else
                                                                     "D2" if de == "D2" else "RND"]
            for k in PRIMARY_KPIS:
                series[k].append(r[k])
            n = seed + 1
            if n < max(args.pilot, 10):
                continue
            states = {k: converged(series[k], PRIMARY_KPIS[k]) for k in PRIMARY_KPIS}
            if all(ok for ok, _ in states.values()):
                # look-ahead: must stay below on the next five seeds too
                if n_at is None:
                    n_at = n
                elif n - n_at >= args.lookahead:
                    break
            else:
                n_at = None
        got = n_at or args.max_seeds
        detail = []
        for k in PRIMARY_KPIS:
            m = statistics.fmean(series[k])
            sd = statistics.pstdev(series[k])
            _, hw = converged(series[k], PRIMARY_KPIS[k])
            detail.append(f"{k}={m:.3f}±{hw:.3f} (σ/µ={sd/max(abs(m),1e-9):.2f})")
        print(f"  {sc}/{de}: N = {got}   " + "  ".join(detail))
        required_n = max(required_n, got)

    print(f"\n  -> N to be used in the matrix = {required_n}\n")

    # 2. full matrix
    print(f" matrix: {len(cells)} cells x {required_n} seeds = "
          f"{len(cells)*required_n} runs")
    out = {}
    for i, (sc, de) in enumerate(cells, 1):
        label = f"{sc}-{de}"
        runs = []
        for seed in range(required_n):
            scal = run_cell(sc, de, seed, inet, label)
            s = score_run(f"results/{label}-s{seed:02d}-r0-events.csv",
                          f"results/{label}-s{seed:02d}-r0-truth.csv", args.end)
            s["scalars"] = {k: scal.get(k) for k in
                            ("sat.tcAccepted", "sat.tcRejected", "twin.observations",
                             "attacker.attackEvents", "link.deliveredUp")}
            runs.append(s)
        out[label] = runs
        print(f"  [{i:>2}/{len(cells)}] {label} tamam")

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(
        {"seeds": required_n, "endTime": args.end, "cells": out}, indent=1))
    print(f"\n[OK] written: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
