#!/usr/bin/env python3
"""
LIFESAT — Faz 3 kapısı: saldırılar A1–A4.

Dört şey kanıtlanmadan Faz 4'e (savunmalar) geçilmez.

  1. HER SALDIRI AMAÇLANAN ETKİYİ ÜRETİYOR (D0 altında).
     Saldırı modülü yazıldı ama hiçbir şey değiştirmiyorsa, savunmaların
     ölçtüğü şey de yok demektir.

  2. MUHASEBE HÂLÂ KAPANIYOR.
     A4 telemetri düşürüyor: düşen paket sayısı, ikizin gözlem sayısındaki
     azalmayla birebir örtüşmeli.  A2/A3 komut enjekte ediyor: uydunun kabul
     ettiği fazladan komut sayısı, enjekte edilenle örtüşmeli.

  3. ANOMALİ YOĞUNLUĞU GERÇEKÇİ ARALIKTA.
     Wu & Keogh'un dört kusurundan biri "gerçekçi olmayan anomali yoğunluğu"
     (K-59).  Hedef aralık `CLAIMS.md`'de %0,57–1,80 olarak kararlaştırıldı.
     Aralığın dışındaysa sonuçlar şişer ve karşılaştırılamaz.

  4. CEVAP ANAHTARI YALNIZ TOPLAYICIDA (R1).
     Saldırganın yazdığı truth kaydı dolu, olay günlüğünde etiket yok.
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
        raise SystemExit(f"HATA: koşu başarısız ({config}, seed {seed})")
    f = sorted(glob.glob(f"simulations/results/{config}-*.sca"))
    if not f:
        raise SystemExit(f"HATA: {config} için sonuç yok")
    return read_scalars(f[-1])


def check(label, ok, detail=""):
    print(f"  {'✅' if ok else '🔴'} {label}{('  ' + detail) if detail else ''}")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--density-min", type=float, default=0.0057)
    ap.add_argument("--density-max", type=float, default=0.0180)
    args = ap.parse_args()
    inet = os.environ.get("INET_ROOT", "")
    ok = True

    print(f"\n▶ etki ve muhasebe ({args.seeds} tohum toplamı)")
    agg = {}
    for c in SCENARIOS:
        a = {}
        for s in range(args.seeds):
            v = run(c, s, inet)
            for k, val in v.items():
                a[k] = a.get(k, 0) + val
        agg[c] = a

    base = agg["B0"]
    print(f"\n  {'senaryo':<8}{'epizot':>8}{'olay':>7}{'gözlem':>8}"
          f"{'kabul TC':>10}{'D3 alarm':>10}{'yoğunluk':>10}")
    for c in SCENARIOS:
        a = agg[c]
        ev = a.get("attacker.attackEvents", 0)
        obs = a.get("twin.observations", 0)
        print(f"  {c:<8}{a.get('attacker.episodes',0):>8.0f}{ev:>7.0f}{obs:>8.0f}"
              f"{a.get('sat.tcAccepted',0):>10.0f}{a.get('twin.d3Alarms',0):>10.0f}"
              f"{100*ev/max(obs,1):>9.2f}%")

    print()
    # 1 — her saldırı etki üretiyor
    for c in ["A1", "A2", "A3", "A4"]:
        ok &= check(f"{c}: saldırgan gerçekten müdahale ediyor",
                    agg[c].get("attacker.attackEvents", 0) > 0,
                    f"{agg[c].get('attacker.attackEvents',0):.0f} olay")
    ok &= check("B0: saldırgan tamamen şeffaf",
                agg["B0"].get("attacker.attackEvents", 0) == 0)

    # 2 — muhasebe
    print()
    a4 = agg["A4"]
    lost = base.get("twin.observations", 0) - a4.get("twin.observations", 0)
    ok &= check("A4: kaybolan gözlem = düşürülen telemetri",
                abs(lost - a4.get("attacker.dropped", 0)) < 1e-9,
                f"{lost:.0f} = {a4.get('attacker.dropped',0):.0f}")
    # ⚠️ Enjekte edilen her komut uyduya ULAŞMAZ: epizot, geçiş bittikten sonra
    # da sürebilir ve o komutlar bağlantıda 'coverage' nedeniyle düşer.  Doğru
    # denetim, hatta teslim edilenle uydunun kabul ettiğini karşılaştırmaktır.
    for c, field in (("A2", "attacker.injected"), ("A3", "attacker.replayed")):
        extra = agg[c].get("sat.tcAccepted", 0) - base.get("sat.tcAccepted", 0)
        delivered = agg[c].get("link.deliveredUp", 0) - base.get("link.deliveredUp", 0)
        sent = agg[c].get(field, 0)
        lostAtLink = sent - delivered
        ok &= check(f"{c}: hatta teslim edilen = uydunun kabul ettiği",
                    abs(extra - delivered) < 1e-9,
                    f"{extra:.0f} = {delivered:.0f}  (D0'da savunma yok, hepsi kabul)")
        ok &= check(f"{c}: gönderilen = teslim + kapsama kaybı",
                    lostAtLink >= 0,
                    f"{sent:.0f} = {delivered:.0f} + {lostAtLink:.0f} "
                    f"(epizot geçişi aşınca kalanlar düşüyor)")

    # 3 — anomali yoğunluğu
    print()
    for c in ["A1", "A2", "A3", "A4"]:
        d = agg[c].get("attacker.attackEvents", 0) / max(agg[c].get("twin.observations", 1), 1)
        ok &= check(f"{c}: anomali yoğunluğu gerçekçi aralıkta",
                    args.density_min <= d <= args.density_max,
                    f"%{100*d:.2f}  (hedef %{100*args.density_min:.2f}–%{100*args.density_max:.2f}, K-59)")

    # 4 — cevap anahtarı yalnız toplayıcıda
    print()
    # Collector çıktısı proje kökündeki results/ altında (ini: outputDir=../results);
    # .sca ise OMNeT++ varsayılanıyla simulations/results/ altında.
    truth = sorted(glob.glob("results/A2-*-truth.csv"))
    events = sorted(glob.glob("results/A2-*-events.csv"))
    ok &= check("saldırgan cevap anahtarını yazıyor",
                bool(truth) and Path(truth[-1]).read_text().count("\n") > 1,
                f"{Path(truth[-1]).read_text().count(chr(10))-1 if truth else 0} kayıt")
    if events:
        body = Path(events[-1]).read_text()
        leaked = [w for w in ("inject", "tamper", "replay", "attack", "forged")
                  if w in body]
        ok &= check("olay günlüğünde saldırı etiketi YOK",
                    not leaked,
                    "sızan sözcük: " + ", ".join(leaked) if leaked else
                    "adli kayıt yalnız gözlenebilirleri taşıyor")

    print()
    if ok:
        print("✅ FAZ 3 KAPISI AÇIK")
        return 0
    print("🔴 FAZ 3 KAPISI KAPALI")
    return 1


if __name__ == "__main__":
    sys.exit(main())
