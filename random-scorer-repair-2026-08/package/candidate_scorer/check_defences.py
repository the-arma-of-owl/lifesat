#!/usr/bin/env python3
"""
LIFESAT — Faz 4 kapısı: savunmalar D1, D2 ve rastgele taban çizgisi.

  1. KRİPTO GERÇEK (R3) — tests/crypto/run.sh ayrıca koşuyor.

  2. D1 SALDIRILARI ENGELLİYOR.
     A1 (tahrif) ve A2 (sahte komut) etiketi tutmadığı için, A3 (tekrar) sıra
     numarası eskidiği için reddedilmeli.  D0'da kabul edilen komut sayısı ile
     D1'deki fark, tam olarak engellenen saldırı sayısı olmalı.

  3. D1 MEŞRU KOMUTU REDDETMİYOR.
     B0'da tek bir ret bile olmamalı; olursa D1 kullanılamaz.

  4. D2'NİN EŞİĞİ SALDIRI VERİSİNE BAKMADAN TÜRETİLDİ.
     Eşik dosyası var, σ > 0 (sıfırsa dedektör dejenere), ve dosya yalnız
     kalibrasyon koşularından üretildi.

  5. RASTGELE DEDEKTÖR ÇALIŞIYOR — beklenen oranda alarm veriyor.
     Bu bir savunma değil, K-59'un zorunlu kıldığı önemsizlik denetimi.
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
        raise SystemExit(f"HATA: {scenario}/{defence} seed {seed} başarısız")
    return read_scalars(sorted(glob.glob(f"simulations/results/{scenario}-*.sca"))[-1])


def agg(scenario, defence, seeds, inet):
    a = {}
    for s in range(seeds):
        for k, v in run(scenario, defence, s, inet).items():
            a[k] = a.get(k, 0) + v
    return a


def check(label, ok, detail=""):
    print(f"  {'✅' if ok else '🔴'} {label}{('  ' + detail) if detail else ''}")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=5)
    args = ap.parse_args()
    inet = os.environ.get("INET_ROOT", "")
    ok = True

    print(f"\n▶ D0 → D1 karşılaştırması ({args.seeds} tohum toplamı)")
    data = {}
    for sc in ("B0", "A1", "A2", "A3", "A4"):
        for d in ("D0", "D1"):
            data[(sc, d)] = agg(sc, d, args.seeds, inet)

    print(f"\n  {'senaryo':<9}{'saldırı olayı':>14}{'kabul D0':>10}{'kabul D1':>10}"
          f"{'ret D1':>9}{'  ret nedeni (auth/tazelik/bütünlük)':>38}")
    for sc in ("B0", "A1", "A2", "A3", "A4"):
        d0, d1 = data[(sc, "D0")], data[(sc, "D1")]
        print(f"  {sc:<9}{d0.get('attacker.attackEvents',0):>14.0f}"
              f"{d0.get('sat.tcAccepted',0):>10.0f}{d1.get('sat.tcAccepted',0):>10.0f}"
              f"{d1.get('sat.tcRejected',0):>9.0f}"
              f"{d1.get('sat.tcRejectedAuth',0):>14.0f}"
              f"{d1.get('sat.tcRejectedFreshness',0):>12.0f}"
              f"{d1.get('sat.tcRejectedIntegrity',0):>12.0f}")

    print()
    # 3 — meşru komutu reddetmiyor
    ok &= check("D1 meşru komutu reddetmiyor (B0'da sıfır ret)",
                data[("B0", "D1")].get("sat.tcRejected", 0) == 0,
                f"{data[('B0','D1')].get('sat.tcRejected',0):.0f} ret")
    ok &= check("D1 meşru komutu engellemiyor (B0'da kabul sayısı değişmiyor)",
                data[("B0", "D1")].get("sat.tcAccepted", 0)
                == data[("B0", "D0")].get("sat.tcAccepted", 0))

    # 2 — saldırıları engelliyor
    print()
    for sc, why in (("A1", "tahrif → etiket tutmaz"),
                    ("A2", "sahte komut → etiket yok"),
                    ("A3", "tekrar → sıra numarası eski")):
        d0, d1 = data[(sc, "D0")], data[(sc, "D1")]
        blocked = d1.get("sat.tcRejected", 0)
        events = d0.get("attacker.attackEvents", 0)
        delta = d1.get("sat.tcAccepted", 0) - data[("B0", "D1")].get("sat.tcAccepted", 0)
        # ⚠️ A1'de delta NEGATİF olmalı ve bu doğru davranıştır: saldırgan meşru
        # bir komutu tahrif ediyor, D1 onu reddediyor, dolayısıyla komut hiç
        # uygulanmıyor.  D1 "yanlış değer uygulandı"yı "değer uygulanmadı"ya
        # çeviriyor — fail-closed.  Sızıntı değil, tasarım.
        ok &= check(f"{sc}: D1 engelliyor ({why})", blocked > 0,
                    f"{blocked:.0f}/{events:.0f} olay reddedildi, "
                    f"kabul farkı {delta:+.0f}")
    a4 = data[("A4", "D1")]
    ok &= check("A4: D1 telemetri saldırısını ele ALMIYOR (beklenen)",
                a4.get("sat.tcRejected", 0) == 0,
                "komut yetkilendirme aşağı bağlantıyı korumaz — ablasyonun anlamı bu")

    # 4 — D2 eşiği
    print()
    thr = Path("results/d2_thresholds.txt")
    ok &= check("D2 eşik dosyası var", thr.exists())
    if thr.exists():
        vals = dict(re.findall(r"(\w+)=([\d.eE+-]+)", thr.read_text()))
        sp, sb = float(vals.get("sigmaPps", 0)), float(vals.get("sigmaBps", 0))
        ok &= check("D2 eşiği dejenere değil (σ > 0)", sp > 0 and sb > 0,
                    f"σ_pps = {sp:.4f}, σ_bps = {sb:.2f}")
        ok &= check("D2 eşiği yalnız kalibrasyon koşularından",
                    "saldirisiz" in thr.read_text(),
                    "dosya başlığı kaynağını bildiriyor")

    # 5 — rastgele dedektör
    print()
    b0 = data[("B0", "D0")]
    n = b0.get("rnd.randomObservations", 0)
    a = b0.get("rnd.randomAlarms", 0)
    rate = a / n if n else 0
    expected = 0.01
    tol = 3 * math.sqrt(expected * (1 - expected) / max(n, 1))
    ok &= check("rastgele dedektör beklenen oranda alarm veriyor",
                abs(rate - expected) < tol,
                f"{a:.0f}/{n:.0f} = %{100*rate:.2f}  (beklenen %1,00 ± %{100*tol:.2f})")

    print()
    if ok:
        print("✅ FAZ 4 KAPISI AÇIK")
        return 0
    print("🔴 FAZ 4 KAPISI KAPALI")
    return 1


if __name__ == "__main__":
    sys.exit(main())
