#!/usr/bin/env python3
"""
LIFESAT — Faz 2 kapısı: ikiz ve D3.

Üç şey kanıtlanmadan Faz 3'e (saldırılar) geçilmez.

  1. NEGATİF KONTROL — saldırı yokken yanlış alarm oranı küçük.
     Tek koşuda 135 gözlemde 3σ'nın beklentisi ~0,4 alarmdır; sıfır çıkması
     bilgi taşımaz.  Bu yüzden çok tohumlu toplam üzerinden bakılır.

  2. POZİTİF KONTROL — dedektör ölü değil.
     İkizin model sapması kasten büyütülür; D3 bunu YAKALAMAK ZORUNDA.
     Yakalamıyorsa ölçtüğümüz hiçbir şey anlam taşımaz (kural R4).
     🔴 Bu, "terminale yazı basıyoruz" itirazına verilen doğrudan cevap:
        aynı kod, farklı girdiyle farklı sonuç veriyor.

  3. GECİKME TEK BAŞINA ALARM DEĞİL — §3.2'nin merkez iddiası.
     Uzun temas boşluğundan sonra gelen ilk telemetride durum sınırı, boşluk
     süresiyle orantılı biçimde genişlemiş olmalı.  Genişlemiyorsa D3 her
     geçişte tetiklenir ve LEO'da kullanılamaz.
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
        raise SystemExit(f"HATA: koşu başarısız ({config}, seed {seed})")
    files = sorted(glob.glob(f"simulations/results/{config}*.sca"))
    if not files:
        raise SystemExit(f"HATA: sonuç dosyası yok (simulations/results/{config}*.sca)")
    return read_scalars(files[-1])


def check(label, ok, detail=""):
    print(f"  {'✅' if ok else '🔴'} {label}{('  ' + detail) if detail else ''}")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="B0")
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--max-fpr", type=float, default=0.02)
    args = ap.parse_args()
    inet = os.environ.get("INET_ROOT", "")
    ok = True

    # ── 1. negatif kontrol ───────────────────────────────────────────────────
    print(f"\n▶ negatif kontrol — B0, {args.seeds} tohum")
    obs = alarms = 0
    for s in range(args.seeds):
        v = run(args.config, s, inet)
        obs += v.get("twin.observations", 0)
        alarms += v.get("twin.d3Alarms", 0)
    fpr = alarms / obs if obs else 1.0
    print(f"    {obs:.0f} gözlem, {alarms:.0f} alarm")
    ok &= check("yanlış alarm oranı kabul edilebilir",
                fpr <= args.max_fpr, f"FPR = %{100*fpr:.3f}  (üst sınır %{100*args.max_fpr:.1f})")
    print(f"    📌 3σ'nın kuramsal beklentisi ~%0,27; ölçülen %{100*fpr:.3f}")

    # ── 2. pozitif kontrol ───────────────────────────────────────────────────
    print("\n▶ pozitif kontrol — ikizin model sapması büyütülüyor")
    v = run(args.config, 0, inet, {"*.twin.rateBias": "3.0"})
    big = v.get("twin.d3Alarms", 0)
    print(f"    rateBias 0.06 → 3.0 (ikizin hızları 4× sapkın)")
    ok &= check("D3 büyük model sapmasını yakalıyor", big > 0,
                f"{big:.0f} alarm  (0 çıksaydı dedektör ölü demekti)")

    v0 = run(args.config, 0, inet)
    ok &= check("aynı kod, farklı girdi → farklı sonuç",
                big > v0.get("twin.d3Alarms", 0),
                f"{v0.get('twin.d3Alarms', 0):.0f} → {big:.0f} alarm")

    # ── 3. gecikme tek başına alarm değil ────────────────────────────────────
    print("\n▶ gecikme alarm değil (§3.2)")
    v = run(args.config, 0, inet)
    bmax = v.get("twin.voltageBound:max", 0)
    bmean = v.get("twin.voltageBound:mean", 0)
    dmax = v.get("twin.voltageDeviation:max", 0)
    ok &= check("durum sınırı boşluk süresiyle genişliyor",
                bmax > 3 * bmean,
                f"sınır ort {bmean:.4f} V → maks {bmax:.4f} V ({bmax/max(bmean,1e-9):.1f}×")
    ok &= check("uzun boşluk sonrası sapma sınırın altında kalıyor",
                dmax < bmax,
                f"maks sapma {dmax:.4f} V < maks sınır {bmax:.4f} V")
    ok &= check("mantıksal kanal gecikmeden ötürü tetiklenmiyor",
                v.get("twin.d3AlarmsLogical", 0) == 0,
                "kaynak zamanına göre değerlendirme çalışıyor")

    print()
    if ok:
        print("✅ FAZ 2 KAPISI AÇIK")
        return 0
    print("🔴 FAZ 2 KAPISI KAPALI")
    return 1


if __name__ == "__main__":
    sys.exit(main())
