#!/usr/bin/env python3
"""
LIFESAT — Faz 5 kapısı: matris sonuçlarının yayımlanabilir olması.

  1. ÖNEMSİZLİK DENETİMİ (K-59, R4).  D3 rastgele dedektörü belirgin biçimde
     yenmeli; CI'lar çakışıyorsa sonuç yayımlanamaz.

  2. TABAN ÇİZGİSİ TEMİZ.  B0'da (saldırı yok) yanlış alarm oranı küçük ve
     raporlanmış olmalı.

  3. D1 MEŞRU TRAFİĞİ ENGELLEMİYOR.  B0'da ret sayısı sıfır.

  4. ARTIK RİSK RAPORLANMIŞ.  Yakalanamayan olaylar düzeltilmeden yazılmış
     olmalı (K-50 ¶422).  Her senaryoda %100 tespit çıkıyorsa bu bir uyarıdır:
     ya saldırı fazla kolay ya etiketleme kendi lehimize.

  5. HAM GÜNLÜKLER KORUNMUŞ.  Her koşunun adli kaydı ayrı dosyada — çevrim dışı
     yeniden skorlama mümkün olmalı.  Adli hazırlık iddia eden bir çalışmada
     bu bir tutarlılık koşuludur.
"""

import argparse
import glob
import json
import math
import random
import statistics
import sys
from pathlib import Path

SCENARIOS = ["A1", "A2", "A3", "A4"]


def ci(xs, reps=2000, alpha=0.05, seed=12345):
    xs = [x for x in xs if x is not None and not (isinstance(x, float) and math.isnan(x))]
    if len(xs) < 2:
        return (float("nan"),) * 3
    rng = random.Random(seed)
    means = sorted(sum(rng.choice(xs) for _ in range(len(xs))) / len(xs) for _ in range(reps))
    return (statistics.fmean(xs), means[int(alpha / 2 * reps)],
            means[int((1 - alpha / 2) * reps) - 1])


def check(label, ok, detail=""):
    print(f"  {'✅' if ok else '🔴'} {label}{('  ' + detail) if detail else ''}")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--matrix", default="results/matrix.json")
    ap.add_argument("--max-fpr", type=float, default=0.01)
    args = ap.parse_args()
    data = json.loads(Path(args.matrix).read_text())
    cells, n = data["cells"], data["seeds"]
    ok = True

    print(f"\n▶ matris: {len(cells)} hücre × {n} tohum")
    ok &= check("yirmi hücrenin tamamı koşuldu", len(cells) == 20, f"{len(cells)} hücre")

    print("\n▶ önemsizlik denetimi (K-59, R4)")
    for sc in SCENARIOS:
        runs = cells.get(f"{sc}-D3", [])
        if not runs:
            ok &= check(f"{sc}/D3 sonucu var", False); continue
        r = ci([x["RND"]["f05"] for x in runs])
        d = ci([x["D3"]["f05"] for x in runs])
        ok &= check(f"{sc}: D3, rastgele dedektörü belirgin biçimde yeniyor",
                    d[1] > r[2],
                    f"D3 {d[0]:.3f}[{d[1]:.3f},{d[2]:.3f}] vs "
                    f"RND {r[0]:.3f}[{r[1]:.3f},{r[2]:.3f}]")

    print("\n▶ taban çizgisi (B0)")
    b0 = cells.get("B0-D3", [])
    if b0:
        f = ci([x["D3"]["fpr"] for x in b0])
        ok &= check("B0'da D3 yanlış alarm oranı kabul edilebilir",
                    f[0] <= args.max_fpr, f"FPR = {f[0]:.4f} [{f[1]:.4f},{f[2]:.4f}]")
        ok &= check("B0'da yanlış alarm oranı SIFIR DEĞİL (eşik dejenere değil)",
                    f[0] > 0, f"{f[0]:.4f}")
    b0d1 = cells.get("B0-D1", [])
    if b0d1:
        rej = statistics.fmean([r["scalars"].get("sat.tcRejected") or 0 for r in b0d1])
        ok &= check("D1 meşru trafiği engellemiyor", rej == 0, f"{rej:.1f} ret")

    print("\n▶ artık risk (K-50 ¶422)")
    perfect = []
    for sc in SCENARIOS:
        runs = cells.get(f"{sc}-D3", [])
        if not runs:
            continue
        miss = ci([1 - x["D3"]["recallEvent"] for x in runs])
        print(f"    {sc}: yakalanamama {miss[0]:.3f} [{miss[1]:.3f},{miss[2]:.3f}]")
        if miss[0] <= 0:
            perfect.append(sc)
    ok &= check("hiçbir senaryoda %100 tespit iddia edilmiyor",
                len(perfect) < len(SCENARIOS),
                f"tam tespit: {', '.join(perfect) if perfect else 'yok'}"
                + ("  ⚠️ hepsi tamsa etiketleme kendi lehimize olabilir" if perfect else ""))

    print("\n▶ ham günlüklerin korunması")
    logs = glob.glob("results/*-s*-r0-events.csv")
    expected = 20 * n
    ok &= check("her koşunun adli kaydı ayrı dosyada",
                len(logs) >= expected,
                f"{len(logs)} / {expected} günlük")

    print()
    if ok:
        print("✅ FAZ 5 KAPISI AÇIK — sonuçlar §6'ya yazılabilir")
        return 0
    print("🔴 FAZ 5 KAPISI KAPALI")
    return 1


if __name__ == "__main__":
    sys.exit(main())
