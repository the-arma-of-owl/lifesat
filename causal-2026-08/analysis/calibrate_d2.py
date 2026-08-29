#!/usr/bin/env python3
"""
LIFESAT -- derives D2's thresholds from ATTACK-FREE runs.

Why this script is a separate step:

Many high-scoring methods look unsupervised while setting the threshold from the
test data. To avoid that, LIFESAT derives thresholds from a separate calibration
run and never from the run being scored.

The same thresholding procedure is applied to every detector variant -- the fair
comparison practice of K-59 (§5.4).

Usage:
    python calibrate_d2.py --seeds 30 --out results/d2_thresholds.txt
"""

import argparse
import glob
import math
import os
import re
import subprocess
import sys
from pathlib import Path


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=30)
    ap.add_argument("--out", default="results/d2_thresholds.txt")
    ap.add_argument("--sigma", type=float, default=3.0)
    args = ap.parse_args()
    inet = os.environ.get("INET_ROOT", "")

    print(f" D2 calibration -- {args.seeds} attack-free (B0) runs")
    print("  No attack run is examined (K-59, data leakage)\n")

    # window statistics are pooled across seeds: each run contributes its own mean
    # and variance, combined by weight.
    totalN = 0
    sumPps = sumSqPps = sumBps = sumSqBps = 0.0
    totalI = 0
    sumIat = sumSqIat = 0.0

    for s in range(args.seeds):
        cmd = ["../out/clang-release/lifesat", "-u", "Cmdenv", "-c", "Calib",
               "-f", "lifesat.ini", "-n", f".:../src:{inet}/src",
               "-l", f"{inet}/src/libINET.so", f"--seed-set={s}"]
        r = subprocess.run(cmd, cwd="simulations", capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stdout[-1200:], r.stderr[-1200:])
            raise SystemExit(f"ERROR: calibration run {s} failed")
        v = read_scalars(sorted(glob.glob("simulations/results/Calib-*.sca"))[-1])
        n = v.get("flow.calibWindows", 0)
        if n < 2:
            continue
        mp, sp = v["flow.calibMuPps"], v["flow.calibSigmaPps"]
        mb, sb = v["flow.calibMuBps"], v["flow.calibSigmaBps"]
        totalN += n
        sumPps += n * mp;  sumSqPps += n * (sp * sp + mp * mp)
        sumBps += n * mb;  sumSqBps += n * (sb * sb + mb * mb)
        ni = v.get("flow.calibIatWindows", 0)
        if ni >= 2:
            mi, si = v["flow.calibMuIat"], v["flow.calibSigmaIat"]
            totalI += ni
            sumIat += ni * mi;  sumSqIat += ni * (si * si + mi * mi)

    if totalN < 2:
        raise SystemExit("ERROR: no calibration window could be collected")

    muPps = sumPps / totalN
    muBps = sumBps / totalN
    sigmaPps = math.sqrt(max(0.0, sumSqPps / totalN - muPps * muPps))
    sigmaBps = math.sqrt(max(0.0, sumSqBps / totalN - muBps * muBps))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    muIat = sumIat / totalI if totalI else 0.0
    sigmaIat = math.sqrt(max(0.0, sumSqIat / totalI - muIat * muIat)) if totalI else 0.0

    out.write_text(f"# LIFESAT D2 thresholds -- from {args.seeds} attack-free runs\n"
                   f"# {totalN:.0f} traffic windows, {totalI:.0f} iat windows\n"
                   f"# threshold = mu +- {args.sigma} sigma\n"
                   f"muPps={muPps:.6f}\nsigmaPps={sigmaPps:.6f}\n"
                   f"muBps={muBps:.6f}\nsigmaBps={sigmaBps:.6f}\n"
                   f"muIat={muIat:.6f}\nsigmaIat={sigmaIat:.6f}\n")

    print(f"  traffic windows : {totalN:.0f}")
    print(f"  pps  mu = {muPps:.3f}   sigma = {sigmaPps:.3f}"
          f"   -> threshold [{muPps-args.sigma*sigmaPps:.3f}, {muPps+args.sigma*sigmaPps:.3f}]")
    print(f"  bps  mu = {muBps:.1f}   sigma = {sigmaBps:.1f}"
          f"   -> threshold [{muBps-args.sigma*sigmaBps:.1f}, {muBps+args.sigma*sigmaBps:.1f}]")
    print(f"  iat  mu = {muIat:.3f} s sigma = {sigmaIat:.3f}"
          f"   -> threshold [{muIat-args.sigma*sigmaIat:.3f}, {muIat+args.sigma*sigmaIat:.3f}]")
    print(f"\n[OK] yazildi: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
