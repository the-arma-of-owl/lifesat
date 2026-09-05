#!/usr/bin/env python3
"""
LIFESAT — Kademe 1 matrisinin koşulması ve skorlanması.

  20 hücre = {B0, A1, A2, A3, A4} × {D0, D1, D2, D3}

Savunma katmanları (27 Tem kararı):
  D0 = hiçbiri · D1 = komut yetkilendirme
  D2 = D1 + akış anomalisi · D3 = D1 + ikiz sapma dedektörü
D2 ve D3 füzyon yapılmaz (§3.4); ortak taban D1 olduğu için her katmanın
katkısı ayrı görünür.

Tohum planı (K-45 / Hoad vd., S-08):
  Sabit tekrar sayısı YOK.  Pilot 30 tohumla başlanır; ardından birincil
  KPI'ların %95 güven aralığı yarı-genişliği kümülatif ortalamanın %5'inin
  altına inene kadar tohum eklenir (ileri bakış 5, mutlak alt sınır 10).
  σ/µ her KPI için raporlanır — tekrar sayısı yorumlanabilir olsun diye.

CRN (K-34): B0 ve saldırı koşulları aynı tohum akışını paylaşır, karşılaştırma
eşleştirilmiş olur.
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
    # ⚠️ D2 eşik dosyası ZORUNLU — FlowDetector kalibre edilmemiş eşikle koşmayı
    # reddediyor (K-59, veri sızıntısı koruması).  Yol, koşu dizininden
    # (simulations/) göreli verilir ve dize olduğu için tırnaklı.
    "D2": {"*.sat.commandAuthEnabled": "true", "*.gs.signCommands": "true",
           "*.flow.enabled": "true", "*.twin.enabled": "false",
           "*.flow.thresholdFile": '"../results/d2_thresholds.txt"',
           "*.flow.windowSize": "60s"},
    "D3": {"*.sat.commandAuthEnabled": "true", "*.gs.signCommands": "true",
           "*.flow.enabled": "false", "*.twin.enabled": "true"},
}
# Rastgele dedektör HER hücrede koşar — önemsizlik denetimi taban çizgisidir (K-59).
ALWAYS = {"*.rnd.enabled": "true"}

# Birincil KPI'lar ve hassasiyet ölçütleri.
# ⚠️ Spesifikasyon bölüm 4 "bağıl/mutlak hassasiyet eşiği" diyor ve bunun nedeni
# burada görünüyor: FPR ≈ 0,001 mertebesinde bir büyüklük için BAĞIL %5 ölçütü
# yüzlerce tohum ister ve hiçbir şey öğretmez.  Yakına-sıfır KPI'lar için mutlak
# eşik kullanılır.  Her iki eşik de koşulardan önce sabitlendi.
PRIMARY_KPIS = {
    "f05":    {"rel": 0.05, "abs": None},
    "recall": {"rel": 0.05, "abs": None},
    "fpr":    {"rel": 0.05, "abs": 0.005},   # 0,5 yüzde puanı
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
    # ⚠️ Tohum, dosya adına girer.  Girmezse her koşu bir öncekinin adli
    # günlüğünü siler ve çevrim dışı yeniden skorlama imkânsız olur — adli
    # hazırlık iddia eden bir çalışmada kabul edilemez bir kusur.
    label = f"{label}-s{seed:02d}"
    cmd = ["../out/clang-release/lifesat", "-u", "Cmdenv", "-c", scenario,
           "-f", "lifesat.ini", "-n", f".:../src:{inet}/src",
           "-l", f"{inet}/src/libINET.so", f"--seed-set={seed}",
           # ⚠️ Dize parametreleri komut satırında TIRNAKLI verilmeli; tırnaksız
           # OMNeT++ değeri ayrıştıramıyor.
           f'--*.collector.runLabel="{label}"']
    ov = dict(OVERRIDES[defence]); ov.update(ALWAYS)
    for k, v in ov.items():
        cmd.append(f"--{k}={v}")
    r = subprocess.run(cmd, cwd="simulations", capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-1200:], r.stderr[-1200:])
        raise SystemExit(f"HATA: {scenario}/{defence} seed {seed}")
    return read_scalars(sorted(glob.glob(f"simulations/results/{scenario}-*.sca"))[-1])


def bootstrap_ci(xs, reps=2000, alpha=0.05, rng=None):
    """Bootstrap %95 güven aralığı (K-34: δ-yöntemi yerine bootstrap)."""
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
    """Hoad kuralının durdurma ölçütü: bağıl VEYA mutlak hassasiyet sağlandı mı?"""
    xs = [x for x in xs if x is not None and not math.isnan(x)]
    if len(xs) < 2:
        return False, float("inf")
    mean = statistics.fmean(xs)
    lo, hi = bootstrap_ci(xs)
    hw = (hi - lo) / 2
    if crit["abs"] is not None and hw <= crit["abs"]:
        return True, hw
    if abs(mean) < 1e-12:
        return True, hw       # ortalama sıfır: yarı-genişlik de sıfır
    return hw / abs(mean) <= crit["rel"], hw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", type=int, default=30, help="K-45: pilot tohum sayısı")
    ap.add_argument("--max-seeds", type=int, default=60)
    ap.add_argument("--lookahead", type=int, default=5)
    ap.add_argument("--precision", type=float, default=0.05,
                    help="(bilgi amaçlı; ölçütler PRIMARY_KPIS'te sabit)")
    ap.add_argument("--end", type=float, default=604800.0)
    ap.add_argument("--rule-cells", default="A2/D3,A1/D3",
                    help="replikasyon kuralının TAM uygulanacağı hücreler (K-45)")
    ap.add_argument("--out", default="results/matrix.json")
    ap.add_argument("--cells", default="", help="yalnız bu hücreler (hata ayıklama)")
    args = ap.parse_args()
    inet = os.environ.get("INET_ROOT", "")

    cells = [(s, d) for s in SCENARIOS for d in DEFENCES]
    if args.cells:
        want = {tuple(c.split("/")) for c in args.cells.split(",")}
        cells = [c for c in cells if c in want]

    rule_cells = {tuple(c.split("/")) for c in args.rule_cells.split(",") if c}

    # ── 1. Replikasyon kuralı: birkaç hücrede TAM uygulanır, çıkan N yayılır ──
    print(f"▶ replikasyon kuralı (K-45) — tam uygulanan hücreler: "
          f"{', '.join('/'.join(c) for c in sorted(rule_cells))}")
    print(f"  pilot {args.pilot} · ileri bakış {args.lookahead} · "
          f"hedef yarı-genişlik ≤ ortalamanın %{100*args.precision:.0f}'i\n")

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
                # ileri bakış: sonraki 5 tohumda da altında kalmalı
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

    print(f"\n  → matriste kullanılacak N = {required_n}\n")

    # ── 2. Tüm matris ────────────────────────────────────────────────────────
    print(f"▶ matris: {len(cells)} hücre × {required_n} tohum = "
          f"{len(cells)*required_n} koşu")
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
    print(f"\n✅ yazıldı: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
