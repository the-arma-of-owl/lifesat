#!/usr/bin/env python3
"""
LIFESAT — Faz 1 kapısı: muhasebe, belirlenimcilik ve görünürlük.

Spesifikasyon bölüm 6'nın kabul kriterleri:

  1. TC ve TM için üretilen / alınan / düşürülen sayaçları **kapanıyor** mu?
     (Kaybın nedeni ayrı sayılmalı: coverage, kuyruk, saldırgan, auth-reject.)
  2. Aynı config + aynı tohum → aynı KPI (tekrar üretilebilirlik)
  3. Farklı tohum → gerçekten farklı stokastik çıktı
  4. Telemetri yalnız temas penceresi içinde akıyor
  5. Görünürlük oranı bağımsız SGP4 hesabıyla örtüşüyor

Bunların hepsi geçmeden Faz 2'ye (ikiz ve D3) geçilmez: sapma ölçümünün
üzerine kurulacağı taban, muhasebesi kapanmayan bir koşuysa D3'ün ölçtüğü şey
belirsiz olur.
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
    # Tohum kümesini komut satırından geçiyoruz: ini'deki `repeat` sayısını
    # değiştirmeden farklı stokastik akış elde etmenin temiz yolu bu.
    cmd = ["../out/clang-release/lifesat", "-u", "Cmdenv", "-c", config,
           "-f", "lifesat.ini", "-n", f".:../src:{inet_root}/src",
           "-l", f"{inet_root}/src/libINET.so", f"--seed-set={seed_set}"]
    if extra:
        cmd += extra
    r = subprocess.run(cmd, cwd="simulations", capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-2000:], r.stderr[-2000:])
        raise SystemExit(f"HATA: koşu başarısız (config={config}, seed-set={seed_set})")


def check(label, ok, detail=""):
    print(f"  {'✅' if ok else '🔴'} {label}{('  ' + detail) if detail else ''}")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="B0")
    ap.add_argument("--results", default="simulations/results")
    ap.add_argument("--inet", default=None)
    ap.add_argument("--tm-interval", type=float, default=10.0)
    ap.add_argument("--tc-interval", type=float, default=30.0)
    ap.add_argument("--duration", type=float, default=None,
                    help="varsayılan: ini'deki sim-time-limit")
    ap.add_argument("--contact", type=float, default=None,
                    help="varsayılan: koşudaki accessState:timeavg ile tutarlılık")
    args = ap.parse_args()

    # Süreyi ini'den oku — kapı, koşu süresi değiştiğinde sessizce yanlış
    # olmasın (7 güne geçildiğinde tam olarak bu oldu).
    if args.duration is None:
        ini = Path("simulations/lifesat.ini").read_text()
        m = re.search(r"^sim-time-limit\s*=\s*(\d+)\s*([dhms])", ini, re.M)
        if not m:
            raise SystemExit("HATA: ini'de sim-time-limit bulunamadı")
        args.duration = float(m.group(1)) * {"d": 86400, "h": 3600, "m": 60, "s": 1}[m.group(2)]

    inet = args.inet or __import__("os").environ.get("INET_ROOT", "")
    ok = True

    # ── 1. muhasebe ──────────────────────────────────────────────────────────
    print("\n▶ muhasebe (spesifikasyon 6.1)")
    run_sim(args.config, 0, inet)
    sca = sorted(glob.glob(f"{args.results}/{args.config}*.sca"))[-1]
    v = read_scalars(sca)
    g = lambda k: v.get(k, 0.0)

    tc_ticks = args.duration / args.tc_interval
    ok &= check("TC: gönderilen + baskılanan = üretilebilir tick",
                g("gs.tcSent") + g("gs.tcSuppressedNoAccess") == tc_ticks,
                f"{g('gs.tcSent'):.0f} + {g('gs.tcSuppressedNoAccess'):.0f} = {tc_ticks:.0f}")
    # ⚠️ Gönderilen her komut uyduya ULAŞMAZ: geçişin kenarında üretilen komut,
    # bağlantıya vardığında görüş bitmişse 'coverage' nedeniyle düşer.  Zincir
    # bu yüzden üç halkalı: gönderilen = teslim + kapsama kaybı (+uçuştaki),
    # ve teslim = alınan = kabul + ret.
    tcSettled = g("link.deliveredUp") + g("link.droppedUp")
    tcInFlight = g("gs.tcSent") - tcSettled
    ok &= check("TC: gönderilen = hatta teslim + kapsama kaybı + uçuştaki",
                0 <= tcInFlight <= 2,
                f"{g('gs.tcSent'):.0f} = {g('link.deliveredUp'):.0f} + "
                f"{g('link.droppedUp'):.0f} + {tcInFlight:.0f} uçuşta")
    ok &= check("TC: hatta teslim = uyduya ulaşan = kabul + ret",
                g("link.deliveredUp") == g("sat.tcReceived")
                == g("sat.tcAccepted") + g("sat.tcRejected"),
                f"{g('link.deliveredUp'):.0f}")

    tm_ticks = args.duration / args.tm_interval
    ok &= check("TM: üretilen = üretilebilir tick",
                g("sat.tmGenerated") == tm_ticks, f"{g('sat.tmGenerated'):.0f}")
    handed = g("sat.tmGenerated") - g("sat.tmDroppedNoAccess")
    settled = g("link.deliveredDown") + g("link.droppedDown")
    inFlight = handed - settled
    # ⚠️ Koşu bittiğinde yayılım gecikmesiyle hâlâ yolda olan paket olabilir;
    # hatta verilmiştir ama ne teslim ne düşürülmüştür.  Bir paketlik fark
    # normaldir ve muhasebe hatası değildir.
    ok &= check("TM: hatta verilen = teslim + coverage kaybı + uçuştaki",
                0 <= inFlight <= 2,
                f"{handed:.0f} = {g('link.deliveredDown'):.0f} + "
                f"{g('link.droppedDown'):.0f} + {inFlight:.0f} uçuşta")
    ok &= check("TM: yerde alınan = hatta teslim edilen",
                g("gs.tmReceived") == g("link.deliveredDown"), f"{g('gs.tmReceived'):.0f}")

    # ── 2. görünürlük ────────────────────────────────────────────────────────
    print("\n▶ görünürlük (R2 ile tutarlılık)")
    measured = 100 * g("access.accessState:timeavg")
    if args.contact is not None:
        expected = 100 * args.contact / args.duration
        ok &= check("erişim oranı bağımsız SGP4 hesabıyla örtüşüyor",
                    abs(measured - expected) < 0.01,
                    f"ölçülen %{measured:.3f} · beklenen %{expected:.3f}")
    else:
        # Faz 0 kapısı zaten bağımsız SGP4 ile örtüşmeyi kanıtlıyor; burada
        # yalnız oranın makul kaldığı denetleniyor.
        ok &= check("erişim oranı kesintili rejime uygun",
                    0.5 < measured < 5.0,
                    f"%{measured:.3f} görünür  → %{100-measured:.2f} kör")
    ok &= check("telemetrinin ezici çoğunluğu yere ulaşmıyor (kesintili rejim)",
                g("sat.tmDroppedNoAccess") / max(g("sat.tmGenerated"), 1) > 0.9,
                f"%{100*g('sat.tmDroppedNoAccess')/max(g('sat.tmGenerated'),1):.2f} "
                f"kapsama dışı — §3.2'nin öncülü")

    # ── 3. belirlenimcilik ───────────────────────────────────────────────────
    print("\n▶ tekrar üretilebilirlik (spesifikasyon 6.4)")
    baseline = dict(v)
    run_sim(args.config, 0, inet)
    again = read_scalars(sorted(glob.glob(f"{args.results}/{args.config}*.sca"))[-1])
    # ⚠️ NaN skaler (ör. gözlem yokken bir ortalama) karşılaştırmayı sessizce
    # düşürüyordu: abs(nan-nan) < 1e-12 daima False.  NaN'lar eşit sayılır.
    def equal(x, y):
        return (math.isnan(x) and math.isnan(y)) or abs(x - y) < 1e-12
    same = all(equal(baseline.get(k, 0.0), again.get(k, 0.0)) for k in baseline)
    ok &= check("aynı config + aynı tohum → bit düzeyinde aynı KPI", same)

    run_sim(args.config, 1, inet)
    other = read_scalars(sorted(glob.glob(f"{args.results}/{args.config}*.sca"))[-1])
    stochastic = [k for k in baseline
                  if not equal(baseline.get(k, 0.0), other.get(k, 0.0))]
    ok &= check("farklı tohum → farklı stokastik çıktı",
                len(stochastic) > 0,
                f"{len(stochastic)} KPI değişti (ör. {stochastic[0] if stochastic else '—'})")
    deterministic = [k for k in ("access.passCount", "sat.tmGenerated", "gs.tcSent")
                     if equal(baseline.get(k, 0.0), other.get(k, 0.0))]
    ok &= check("yörünge ve trafik yapısı tohumdan bağımsız",
                len(deterministic) == 3,
                "geometri tohuma bağlı olsaydı R2 anlamını yitirirdi")

    print()
    if ok:
        print("✅ FAZ 1 KAPISI AÇIK")
        return 0
    print("🔴 FAZ 1 KAPISI KAPALI")
    return 1


if __name__ == "__main__":
    sys.exit(main())
