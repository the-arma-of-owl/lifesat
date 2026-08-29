#!/usr/bin/env python3
"""
LIFESAT -- phase 2 gate: twin and D3.

Three things must be proven before moving to phase 3 (attacks).

  1. NEGATIVE CONTROL: a small false-alarm rate with no attack.
     In a single run of 135 observations, 3 sigma predicts about 0.4 alarms, so a
     zero carries no information. This is measured over a multi-seed total.

  2. POSITIVE CONTROL: the detector is not dead.
     The twin's model deviation is deliberately enlarged and D3 must catch it.
     If it does not, nothing measured here means anything.

  3. DELAY ALONE IS NOT AN ALARM, the central claim of section 3.2.
     On the first telemetry after a long contact gap the state bound must have
     widened in proportion to the gap.
"""

import argparse
import glob
import re
import subprocess
import sys
import os


def read_scalars(path):
    v = {}
    for line in open(path):
        m = re.match(r"scalar\s+\S*?\.(\S+)\s+(\S+)\s+([-\d.eE+]+)", line)
        if m:
            try:
                v[f"{m.group(1)}.{m.group(2)}"] = float(m.group(3))
            except ValueError:
                pass
    return v


def run(config, seed, inet, overrides=None):
    cmd = ["../out/clang-release/lifesat", "-u", "Cmdenv", "-c", config,
           "-f", "lifesat.ini", "-n", f".:../src:{inet}/src",
           "-l", f"{inet}/src/libINET.so", f"--seed-set={seed}"]
    for k, val in (overrides or {}).items():
        cmd.append(f"--{k}={val}")
    r = subprocess.run(cmd, cwd="simulations", capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-1500:], r.stderr[-1500:])
        raise SystemExit(f"ERROR: run failed ({config}, seed {seed})")
    files = sorted(glob.glob(f"simulations/results/{config}*.sca"))
    if not files:
        raise SystemExit(f"ERROR: no result file (simulations/results/{config}*.sca)")
    return read_scalars(files[-1])


def check(label, ok, detail=""):
    print(f"  {'[OK]' if ok else '[FAIL]'} {label}{('  ' + detail) if detail else ''}")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="B0")
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--max-fpr", type=float, default=0.02)
    args = ap.parse_args()
    inet = os.environ.get("INET_ROOT", "")
    ok = True

    # 1. negatif kontrol
    print(f"\n negative control -- B0, {args.seeds} seeds")
    obs = alarms = 0
    for s in range(args.seeds):
        v = run(args.config, s, inet)
        obs += v.get("twin.observations", 0)
        alarms += v.get("twin.d3Alarms", 0)
    fpr = alarms / obs if obs else 1.0
    print(f"    {obs:.0f} observations, {alarms:.0f} alarms")
    ok &= check("false alarm rate acceptable",
                fpr <= args.max_fpr, f"FPR = {100*fpr:.3f}%  (limit {100*args.max_fpr:.1f}%)")
    print(f"     theoretical 3-sigma expectation ~0.27%; measured {100*fpr:.3f}%")

    # 2. pozitif kontrol
    print("\n positive control -- the twin's model deviation is enlarged")
    v = run(args.config, 0, inet, {"*.twin.rateBias": "3.0"})
    big = v.get("twin.d3Alarms", 0)
    print(f"    rateBias 0.06 -> 3.0 (the twin's rates are off by 4x)")
    ok &= check("D3 catches a large model deviation", big > 0,
                f"{big:.0f} alarms  (0 would mean a dead detector)")

    v0 = run(args.config, 0, inet)
    ok &= check("same code, different input -> different result",
                big > v0.get("twin.d3Alarms", 0),
                f"{v0.get('twin.d3Alarms', 0):.0f} -> {big:.0f} alarm")

    # 3. delay alone is not an alarm
    print("\n delay is not an alarm (§3.2)")
    v = run(args.config, 0, inet)
    bmax = v.get("twin.voltageBound:max", 0)
    bmean = v.get("twin.voltageBound:mean", 0)
    dmax = v.get("twin.voltageDeviation:max", 0)
    ok &= check("the state bound widens with the gap length",
                bmax > 3 * bmean,
                f"bound mean {bmean:.4f} V -> max {bmax:.4f} V ({bmax/max(bmean,1e-9):.1f}x")
    ok &= check("deviation after a long gap stays under the bound",
                dmax < bmax,
                f"max deviation {dmax:.4f} V < max bound {bmax:.4f} V")
    ok &= check("the logical channel is not triggered by delay",
                v.get("twin.d3AlarmsLogical", 0) == 0,
                "evaluation against source time works")

    print()
    if ok:
        print("[OK] PHASE 2 GATE OPEN")
        return 0
    print("[FAIL] PHASE 2 GATE CLOSED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
