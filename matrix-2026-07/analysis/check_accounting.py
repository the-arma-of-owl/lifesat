#!/usr/bin/env python3
"""
LIFESAT -- phase 1 gate: accounting, determinism and visibility.

Acceptance criteria of specification section 6:

  1. Do the produced / received / dropped counters close for TC and TM?
     (Loss reasons are counted separately: coverage, queue, attacker, auth-reject.)
  2. Same config plus same seed gives the same KPI (determinism).

None of this may be skipped before phase 2 (twin and D3): if the baseline the
deviation measurement is built on is a run whose accounting does not close, what
becomes undefined.
"""

import argparse
import glob
import math
import re
import subprocess
import sys
from pathlib import Path


def read_scalars(path):
    v = {}
    for line in open(path):
        m = re.match(r"scalar\s+\S*?\.(\S+)\s+(\S+)\s+([-\d.eE+naN]+)", line)
        if m:
            try:
                v[f"{m.group(1)}.{m.group(2)}"] = float(m.group(3))
            except ValueError:
                pass
    return v


def run_sim(config, seed_set, inet_root, extra=None):
    # the seed set is passed on the command line, which changes the stochastic
    # stream without editing repeat in the ini.
    cmd = ["../out/clang-release/lifesat", "-u", "Cmdenv", "-c", config,
           "-f", "lifesat.ini", "-n", f".:../src:{inet_root}/src",
           "-l", f"{inet_root}/src/libINET.so", f"--seed-set={seed_set}"]
    if extra:
        cmd += extra
    r = subprocess.run(cmd, cwd="simulations", capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-2000:], r.stderr[-2000:])
        raise SystemExit(f"ERROR: run failed (config={config}, seed-set={seed_set})")


def check(label, ok, detail=""):
    print(f"  {'[OK]' if ok else '[FAIL]'} {label}{('  ' + detail) if detail else ''}")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="B0")
    ap.add_argument("--results", default="simulations/results")
    ap.add_argument("--inet", default=None)
    ap.add_argument("--tm-interval", type=float, default=10.0)
    ap.add_argument("--tc-interval", type=float, default=30.0)
    ap.add_argument("--duration", type=float, default=None,
                    help="default: sim-time-limit from the ini")
    ap.add_argument("--contact", type=float, default=None,
                    help="default: consistency with accessState:timeavg in the run")
    args = ap.parse_args()

    # read the horizon from the ini so the gate does not go silently wrong when the
    # run length changes.
    if args.duration is None:
        ini = Path("simulations/lifesat.ini").read_text()
        m = re.search(r"^sim-time-limit\s*=\s*(\d+)\s*([dhms])", ini, re.M)
        if not m:
            raise SystemExit("ERROR: no sim-time-limit found in the ini")
        args.duration = float(m.group(1)) * {"d": 86400, "h": 3600, "m": 60, "s": 1}[m.group(2)]

    inet = args.inet or __import__("os").environ.get("INET_ROOT", "")
    ok = True

    # 1. accounting
    print("\n accounting (specification 6.1)")
    run_sim(args.config, 0, inet)
    sca = sorted(glob.glob(f"{args.results}/{args.config}*.sca"))[-1]
    v = read_scalars(sca)
    g = lambda k: v.get(k, 0.0)

    tc_ticks = args.duration / args.tc_interval
    ok &= check("TC: sent + suppressed = producible ticks",
                g("gs.tcSent") + g("gs.tcSuppressedNoAccess") == tc_ticks,
                f"{g('gs.tcSent'):.0f} + {g('gs.tcSuppressedNoAccess'):.0f} = {tc_ticks:.0f}")
    # not every sent command reaches the satellite: one issued at the edge of a pass
    # is dropped for coverage if visibility ends before it arrives. the chain is
    # sent = delivered + coverage loss (+ in flight), and delivered = received =
    # accepted + rejected.
    tcSettled = g("link.deliveredUp") + g("link.droppedUp")
    tcInFlight = g("gs.tcSent") - tcSettled
    ok &= check("TC: sent = delivered on the link + coverage loss + in flight",
                0 <= tcInFlight <= 2,
                f"{g('gs.tcSent'):.0f} = {g('link.deliveredUp'):.0f} + "
                f"{g('link.droppedUp'):.0f} + {tcInFlight:.0f} in flight")
    ok &= check("TC: delivered on the link = reaching the satellite = accepted + rejected",
                g("link.deliveredUp") == g("sat.tcReceived")
                == g("sat.tcAccepted") + g("sat.tcRejected"),
                f"{g('link.deliveredUp'):.0f}")

    tm_ticks = args.duration / args.tm_interval
    ok &= check("TM: produced = producible ticks",
                g("sat.tmGenerated") == tm_ticks, f"{g('sat.tmGenerated'):.0f}")
    handed = g("sat.tmGenerated") - g("sat.tmDroppedNoAccess")
    settled = g("link.deliveredDown") + g("link.droppedDown")
    inFlight = handed - settled
    # a packet may still be in propagation when the run ends: issued but neither
    # delivered nor dropped. a one-packet difference is normal.
    ok &= check("TM: handed to the link = delivered + coverage loss + in flight",
                0 <= inFlight <= 2,
                f"{handed:.0f} = {g('link.deliveredDown'):.0f} + "
                f"{g('link.droppedDown'):.0f} + {inFlight:.0f} in flight")
    ok &= check("TM: received on the ground = delivered on the link",
                g("gs.tmReceived") == g("link.deliveredDown"), f"{g('gs.tmReceived'):.0f}")

    # 2. visibility
    print("\n visibility (consistency with R2)")
    measured = 100 * g("access.accessState:timeavg")
    if args.contact is not None:
        expected = 100 * args.contact / args.duration
        ok &= check("access ratio agrees with the independent SGP4 computation",
                    abs(measured - expected) < 0.01,
                    f"measured {measured:.3f}% · expected {expected:.3f}%")
    else:
        # the phase 0 gate already proves agreement with an independent SGP4; this
        # only checks that the fraction stays plausible.
        ok &= check("access ratio matches the intermittent regime",
                    0.5 < measured < 5.0,
                    f"{measured:.3f}% visible  -> {100-measured:.2f}% blind")
    ok &= check("the overwhelming majority of telemetry never reaches the ground (intermittent regime)",
                g("sat.tmDroppedNoAccess") / max(g("sat.tmGenerated"), 1) > 0.9,
                f"%{100*g('sat.tmDroppedNoAccess')/max(g('sat.tmGenerated'),1):.2f} "
                f"out of coverage -- the premise of §3.2")

    # 3. determinism
    print("\n reproducibility (specification 6.4)")
    baseline = dict(v)
    run_sim(args.config, 0, inet)
    again = read_scalars(sorted(glob.glob(f"{args.results}/{args.config}*.sca"))[-1])
    # a NaN scalar silently dropped the comparison, since abs(nan-nan) < 1e-12 is
    # always False. NaNs now compare equal.
    def equal(x, y):
        return (math.isnan(x) and math.isnan(y)) or abs(x - y) < 1e-12
    same = all(equal(baseline.get(k, 0.0), again.get(k, 0.0)) for k in baseline)
    ok &= check("same config + same seed -> bit-identical KPIs", same)

    run_sim(args.config, 1, inet)
    other = read_scalars(sorted(glob.glob(f"{args.results}/{args.config}*.sca"))[-1])
    stochastic = [k for k in baseline
                  if not equal(baseline.get(k, 0.0), other.get(k, 0.0))]
    ok &= check("different seed -> different stochastic output",
                len(stochastic) > 0,
                f"{len(stochastic)} KPIs changed (e.g. {stochastic[0] if stochastic else ' -- '})")
    deterministic = [k for k in ("access.passCount", "sat.tmGenerated", "gs.tcSent")
                     if equal(baseline.get(k, 0.0), other.get(k, 0.0))]
    ok &= check("orbit and traffic structure independent of the seed",
                len(deterministic) == 3,
                "if the geometry depended on the seed, R2 would lose its meaning")

    print()
    if ok:
        print("[OK] PHASE 1 GATE OPEN")
        return 0
    print("[FAIL] PHASE 1 GATE CLOSED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
