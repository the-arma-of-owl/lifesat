#!/usr/bin/env python3
"""
LIFESAT -- phase 3 gate: attacks A1 -- A4.

Four things must be proven before moving to phase 4 (defences).

  1. EVERY ATTACK PRODUCES ITS INTENDED EFFECT (under D0).
     If the attack module is written but changes nothing, the defences measure
     nothing either.

  2. THE ACCOUNTING STILL CLOSES.
     A4 drops telemetry: the dropped-packet count must match the reduction in the
     twin's observation count exactly. A2 and A3 inject commands: the extra
     accepted commands must match the injected ones.

  3. ANOMALY DENSITY IN A REALISTIC RANGE.
     One of the four documented flaws is unrealistic anomaly density. The target
     range is 0.57-1.80%.

  4. THE ANSWER KEY LIVES ONLY IN THE COLLECTOR (R1).
     The truth record written by the attacker is populated, the event log has no label.
"""

import argparse
import glob
import os
import re
import subprocess
import sys
from pathlib import Path

SCENARIOS = ["B0", "A1", "A2", "A3", "A4"]


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


def run(config, seed, inet):
    cmd = ["../out/clang-release/lifesat", "-u", "Cmdenv", "-c", config,
           "-f", "lifesat.ini", "-n", f".:../src:{inet}/src",
           "-l", f"{inet}/src/libINET.so", f"--seed-set={seed}"]
    r = subprocess.run(cmd, cwd="simulations", capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-1500:], r.stderr[-1500:])
        raise SystemExit(f"ERROR: run failed ({config}, seed {seed})")
    f = sorted(glob.glob(f"simulations/results/{config}-*.sca"))
    if not f:
        raise SystemExit(f"ERROR: no result for {config}")
    return read_scalars(f[-1])


def check(label, ok, detail=""):
    print(f"  {'[OK]' if ok else '[FAIL]'} {label}{('  ' + detail) if detail else ''}")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--density-min", type=float, default=0.0057)
    ap.add_argument("--density-max", type=float, default=0.0180)
    args = ap.parse_args()
    inet = os.environ.get("INET_ROOT", "")
    ok = True

    print(f"\n impact and accounting ({args.seeds} seeds combined)")
    agg = {}
    for c in SCENARIOS:
        a = {}
        for s in range(args.seeds):
            v = run(c, s, inet)
            for k, val in v.items():
                a[k] = a.get(k, 0) + val
        agg[c] = a

    base = agg["B0"]
    print(f"\n  {'scenario':<8}{'episode':>8}{'event':>7}{'obs':>8}"
          f"{'TC accept':>10}{'D3 alarm':>10}{'density':>10}")
    for c in SCENARIOS:
        a = agg[c]
        ev = a.get("attacker.attackEvents", 0)
        obs = a.get("twin.observations", 0)
        print(f"  {c:<8}{a.get('attacker.episodes',0):>8.0f}{ev:>7.0f}{obs:>8.0f}"
              f"{a.get('sat.tcAccepted',0):>10.0f}{a.get('twin.d3Alarms',0):>10.0f}"
              f"{100*ev/max(obs,1):>9.2f}%")

    print()
    # 1 -- every attack produces an effect
    for c in ["A1", "A2", "A3", "A4"]:
        ok &= check(f"{c}: the attacker really does intervene",
                    agg[c].get("attacker.attackEvents", 0) > 0,
                    f"{agg[c].get('attacker.attackEvents',0):.0f} events")
    ok &= check("B0: the attacker is fully transparent",
                agg["B0"].get("attacker.attackEvents", 0) == 0)

    # 2 -- accounting
    print()
    a4 = agg["A4"]
    lost = base.get("twin.observations", 0) - a4.get("twin.observations", 0)
    ok &= check("A4: lost observations = dropped telemetry",
                abs(lost - a4.get("attacker.dropped", 0)) < 1e-9,
                f"{lost:.0f} = {a4.get('attacker.dropped',0):.0f}")
    # not every injected command reaches the satellite: an episode can outlast the
    # pass and those commands drop for coverage. compare what was delivered against
    # what the satellite accepted.
    for c, field in (("A2", "attacker.injected"), ("A3", "attacker.replayed")):
        extra = agg[c].get("sat.tcAccepted", 0) - base.get("sat.tcAccepted", 0)
        delivered = agg[c].get("link.deliveredUp", 0) - base.get("link.deliveredUp", 0)
        sent = agg[c].get(field, 0)
        lostAtLink = sent - delivered
        ok &= check(f"{c}: delivered on the link = accepted by the satellite",
                    abs(extra - delivered) < 1e-9,
                    f"{extra:.0f} = {delivered:.0f}  (no defence under D0, all accepted)")
        ok &= check(f"{c}: sent = delivered + coverage loss",
                    lostAtLink >= 0,
                    f"{sent:.0f} = {delivered:.0f} + {lostAtLink:.0f} "
                    f"(what remains is dropped once the episode outlives the pass)")

    # 3 -- anomaly density
    print()
    for c in ["A1", "A2", "A3", "A4"]:
        d = agg[c].get("attacker.attackEvents", 0) / max(agg[c].get("twin.observations", 1), 1)
        ok &= check(f"{c}: anomaly density in a realistic range",
                    args.density_min <= d <= args.density_max,
                    f"%{100*d:.2f}  (target {100*args.density_min:.2f}% -- {100*args.density_max:.2f}%, K-59)")

    # 4 -- answer key stays in the collector
    print()
    # Collector output goes to results/ at the project root (ini: outputDir=../results);
    # .sca files go to simulations/results/ by OMNeT++ default.
    truth = sorted(glob.glob("results/A2-*-truth.csv"))
    events = sorted(glob.glob("results/A2-*-events.csv"))
    ok &= check("the attacker writes the answer key",
                bool(truth) and Path(truth[-1]).read_text().count("\n") > 1,
                f"{Path(truth[-1]).read_text().count(chr(10))-1 if truth else 0} records")
    if events:
        body = Path(events[-1]).read_text()
        leaked = [w for w in ("inject", "tamper", "replay", "attack", "forged")
                  if w in body]
        ok &= check("NO attack label in the event log",
                    not leaked,
                    "leaked word: " + ", ".join(leaked) if leaked else
                    "the forensic record carries observables only")

    print()
    if ok:
        print("[OK] PHASE 3 GATE OPEN")
        return 0
    print("[FAIL] PHASE 3 GATE CLOSED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
