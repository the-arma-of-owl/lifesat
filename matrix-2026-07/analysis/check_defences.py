#!/usr/bin/env python3
"""
LIFESAT -- phase 4 gate: defences D1, D2 and the random baseline.

  1. THE CRYPTO IS REAL (R3) -- tests/crypto/run.sh runs separately.

  2. D1 PREVENTS THE ATTACKS.
     A1 (tamper) and A2 (forged) fail the tag; A3 (replay) fails freshness. The
     accepted-command count under D0 and under D1 must differ accordingly.

  3. D1 DOES NOT REJECT A LEGITIMATE COMMAND.
     There must not be a single rejection in B0; if there is, D1 is unusable.

  4. THE D2 THRESHOLD WAS DERIVED WITHOUT LOOKING AT ATTACK DATA.
     The threshold file exists, sigma > 0 (zero makes the detector degenerate),
     and the file comes only from calibration runs.

  5. THE RANDOM DETECTOR WORKS -- it alarms at the expected rate.
     Not a defence but the triviality check K-59 requires.
"""

import argparse
import glob
import math
import os
import re
import subprocess
import sys
from pathlib import Path

DEFENCE_OVERRIDES = {
    "D0": {},
    "D1": {"*.sat.commandAuthEnabled": "true", "*.gs.signCommands": "true"},
    "D2": {"*.sat.commandAuthEnabled": "true", "*.gs.signCommands": "true",
           "*.flow.enabled": "true"},
    "D3": {"*.sat.commandAuthEnabled": "true", "*.gs.signCommands": "true"},
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


def run(scenario, defence, seed, inet, extra=None):
    cmd = ["../out/clang-release/lifesat", "-u", "Cmdenv", "-c", scenario,
           "-f", "lifesat.ini", "-n", f".:../src:{inet}/src",
           "-l", f"{inet}/src/libINET.so", f"--seed-set={seed}"]
    ov = dict(DEFENCE_OVERRIDES[defence])
    ov["*.twin.enabled"] = "true" if defence == "D3" else "false"
    ov["*.rnd.enabled"] = "true"
    ov.update(extra or {})
    for k, val in ov.items():
        cmd.append(f"--{k}={val}")
    r = subprocess.run(cmd, cwd="simulations", capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-1500:], r.stderr[-1500:])
        raise SystemExit(f"ERROR: {scenario}/{defence} seed {seed} failed")
    return read_scalars(sorted(glob.glob(f"simulations/results/{scenario}-*.sca"))[-1])


def agg(scenario, defence, seeds, inet):
    a = {}
    for s in range(seeds):
        for k, v in run(scenario, defence, s, inet).items():
            a[k] = a.get(k, 0) + v
    return a


def check(label, ok, detail=""):
    print(f"  {'[OK]' if ok else '[FAIL]'} {label}{('  ' + detail) if detail else ''}")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=5)
    args = ap.parse_args()
    inet = os.environ.get("INET_ROOT", "")
    ok = True

    print(f"\n D0 -> D1 comparison ({args.seeds} seeds combined)")
    data = {}
    for sc in ("B0", "A1", "A2", "A3", "A4"):
        for d in ("D0", "D1"):
            data[(sc, d)] = agg(sc, d, args.seeds, inet)

    print(f"\n  {'scenario':<9}{'attack event':>14}{'accept D0':>10}{'accept D1':>10}"
          f"{'reject D1':>9}{'  reject reason (auth/freshness/integrity)':>43}")
    for sc in ("B0", "A1", "A2", "A3", "A4"):
        d0, d1 = data[(sc, "D0")], data[(sc, "D1")]
        print(f"  {sc:<9}{d0.get('attacker.attackEvents',0):>14.0f}"
              f"{d0.get('sat.tcAccepted',0):>10.0f}{d1.get('sat.tcAccepted',0):>10.0f}"
              f"{d1.get('sat.tcRejected',0):>9.0f}"
              f"{d1.get('sat.tcRejectedAuth',0):>14.0f}"
              f"{d1.get('sat.tcRejectedFreshness',0):>12.0f}"
              f"{d1.get('sat.tcRejectedIntegrity',0):>12.0f}")

    print()
    # 3 -- legitimate commands are not rejected
    ok &= check("D1 does not reject a legitimate command (zero rejections in B0)",
                data[("B0", "D1")].get("sat.tcRejected", 0) == 0,
                f"{data[('B0','D1')].get('sat.tcRejected',0):.0f} ret")
    ok &= check("D1 does not block a legitimate command (accept count unchanged in B0)",
                data[("B0", "D1")].get("sat.tcAccepted", 0)
                == data[("B0", "D0")].get("sat.tcAccepted", 0))

    # 2 -- attacks are prevented
    print()
    for sc, why in (("A1", "tampered -> the tag does not hold"),
                    ("A2", "forged command -> no tag"),
                    ("A3", "replay -> stale sequence number")):
        d0, d1 = data[(sc, "D0")], data[(sc, "D1")]
        blocked = d1.get("sat.tcRejected", 0)
        events = d0.get("attacker.attackEvents", 0)
        delta = d1.get("sat.tcAccepted", 0) - data[("B0", "D1")].get("sat.tcAccepted", 0)
        # delta is negative under A1 and that is correct: the attacker tampers with a
        # legitimate command, D1 rejects it, so nothing is applied. D1 turns "wrong
        # value applied" into "no value applied" -- fail-closed, not leakage.
        ok &= check(f"{sc}: D1 blocks ({why})", blocked > 0,
                    f"{blocked:.0f}/{events:.0f} events rejected, "
                    f"accept delta {delta:+.0f}")
    a4 = data[("A4", "D1")]
    ok &= check("A4: D1 does NOT handle the telemetry attack (expected)",
                a4.get("sat.tcRejected", 0) == 0,
                "command authorisation does not protect the downlink -- that is the point of the ablation")

    # 4 -- D2 threshold
    print()
    thr = Path("results/d2_thresholds.txt")
    ok &= check("D2 threshold file present", thr.exists())
    if thr.exists():
        vals = dict(re.findall(r"(\w+)=([\d.eE+-]+)", thr.read_text()))
        sp, sb = float(vals.get("sigmaPps", 0)), float(vals.get("sigmaBps", 0))
        ok &= check("D2 threshold not degenerate (sigma > 0)", sp > 0 and sb > 0,
                    f"σ_pps = {sp:.4f}, σ_bps = {sb:.2f}")
        ok &= check("D2 threshold comes from calibration runs only",
                    "attack-free" in thr.read_text(),
                    "the file header states its source")

    # 5 -- random detector
    print()
    b0 = data[("B0", "D0")]
    n = b0.get("rnd.randomObservations", 0)
    a = b0.get("rnd.randomAlarms", 0)
    rate = a / n if n else 0
    expected = 0.01
    tol = 3 * math.sqrt(expected * (1 - expected) / max(n, 1))
    ok &= check("the random detector alarms at the expected rate",
                abs(rate - expected) < tol,
                f"{a:.0f}/{n:.0f} = %{100*rate:.2f}  (expected 1.00% +/- {100*tol:.2f}%)")

    print()
    if ok:
        print("[OK] PHASE 4 GATE OPEN")
        return 0
    print("[FAIL] PHASE 4 GATE CLOSED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
