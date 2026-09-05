#!/usr/bin/env python3
"""
LIFESAT — D2'nin eşiklerini SALDIRISIZ koşulardan türetir.

🔴 Bu betik neden ayrı bir adım:

K-59 (S-12) belgeliyor ki birçok yüksek başarımlı yöntem "gözetimsiz görünürken
aslında eşiği test verisinden belirliyor" (veri sızıntısı).  LIFESAT bu tuzağa
düşmemek için eşiği ayrı bir kalibrasyon koşusundan üretir ve dosyaya yazar;
saldırı koşuları o dosyayı **okur**, kendi verisine bakmaz.

Aynı eşikleme yordamı bütün dedektör varyantlarına uygulanır — K-59'un adil
karşılaştırma pratiği (§5.4).

Kullanım:
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

    print(f"▶ D2 kalibrasyonu — {args.seeds} saldırısız (B0) koşu")
    print("  🔴 Hiçbir saldırı koşusuna bakılmıyor (K-59, veri sızıntısı)\n")

    # Pencere istatistikleri tohumlar arasında havuzlanır: her koşu kendi
    # ortalamasını ve varyansını verir, biz ağırlıklı birleştiriyoruz.
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
            raise SystemExit(f"HATA: kalibrasyon koşusu {s} başarısız")
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
        raise SystemExit("HATA: kalibrasyon penceresi toplanamadı")

    muPps = sumPps / totalN
    muBps = sumBps / totalN
    sigmaPps = math.sqrt(max(0.0, sumSqPps / totalN - muPps * muPps))
    sigmaBps = math.sqrt(max(0.0, sumSqBps / totalN - muBps * muBps))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    muIat = sumIat / totalI if totalI else 0.0
    sigmaIat = math.sqrt(max(0.0, sumSqIat / totalI - muIat * muIat)) if totalI else 0.0

    out.write_text(f"# LIFESAT D2 esikleri — {args.seeds} saldirisiz kosudan\n"
                   f"# {totalN:.0f} trafikli pencere, {totalI:.0f} iat penceresi\n"
                   f"# esik = mu +- {args.sigma} sigma\n"
                   f"muPps={muPps:.6f}\nsigmaPps={sigmaPps:.6f}\n"
                   f"muBps={muBps:.6f}\nsigmaBps={sigmaBps:.6f}\n"
                   f"muIat={muIat:.6f}\nsigmaIat={sigmaIat:.6f}\n")

    print(f"  trafikli pencere : {totalN:.0f}")
    print(f"  pps  mu = {muPps:.3f}   sigma = {sigmaPps:.3f}"
          f"   -> esik [{muPps-args.sigma*sigmaPps:.3f}, {muPps+args.sigma*sigmaPps:.3f}]")
    print(f"  bps  mu = {muBps:.1f}   sigma = {sigmaBps:.1f}"
          f"   -> esik [{muBps-args.sigma*sigmaBps:.1f}, {muBps+args.sigma*sigmaBps:.1f}]")
    print(f"  iat  mu = {muIat:.3f} s sigma = {sigmaIat:.3f}"
          f"   -> esik [{muIat-args.sigma*sigmaIat:.3f}, {muIat+args.sigma*sigmaIat:.3f}]")
    print(f"\n✅ yazildi: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
