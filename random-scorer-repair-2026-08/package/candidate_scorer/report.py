#!/usr/bin/env python3
"""
LIFESAT — matris sonuçlarının §6 için toplanması.

Raporlama kuralları (spesifikasyon bölüm 3 ve 5, K-59 / K-50):
  · senaryo başına **ortalama**, toplam değil (K-59 ¶76)
  · her KPI için %95 bootstrap güven aralığı (K-34)
  · 🔴 F1PA yok
  · rastgele dedektör her hücrede taban çizgisi olarak
  · %100 olmayan tespit oranı **artık risk** olarak, düzeltilmeden (K-50 ¶422)
  🔴 Güven aralıkları çakışıyorsa "outperforms" yazılmaz.
"""

import argparse
import json
import math
import random
import statistics
import sys
from pathlib import Path

SCENARIOS = ["B0", "A1", "A2", "A3", "A4"]
DEFENCES = ["D0", "D1", "D2", "D3"]
# Hangi hücrede hangi dedektör "o hücrenin dedektörü"dür
CELL_DETECTOR = {"D0": None, "D1": None, "D2": "D2", "D3": "D3"}


def ci(xs, reps=2000, alpha=0.05, seed=12345):
    xs = [x for x in xs if x is not None and not (isinstance(x, float) and math.isnan(x))]
    if not xs:
        return (float("nan"),) * 3
    m = statistics.fmean(xs)
    if len(xs) < 2:
        return m, m, m
    rng = random.Random(seed)
    means = sorted(sum(rng.choice(xs) for _ in range(len(xs))) / len(xs) for _ in range(reps))
    return m, means[int(alpha / 2 * reps)], means[int((1 - alpha / 2) * reps) - 1]


def fmt(m, lo, hi, d=3):
    if math.isnan(m):
        return "—"
    return f"{m:.{d}f} [{lo:.{d}f},{hi:.{d}f}]"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--matrix", default="results/matrix.json")
    args = ap.parse_args()
    data = json.loads(Path(args.matrix).read_text())
    cells, n = data["cells"], data["seeds"]

    print(f"\n{'='*100}")
    print(f"LIFESAT — Kademe 1 sonuçları   ({len(cells)} hücre × {n} tohum, "
          f"koşu süresi {data['endTime']/86400:.0f} gün)")
    print(f"{'='*100}")

    # ── 1. Saldırı etkisi: savunma katmanları ne kadarını engelliyor ──────────
    print("\n▶ KOMUT GÜVENLİĞİ — uydunun kabul ettiği düşman komut")
    print(f"  {'senaryo':<9}" + "".join(f"{d:>22}" for d in DEFENCES))
    for sc in SCENARIOS:
        row = f"  {sc:<9}"
        for d in DEFENCES:
            runs = cells.get(f"{sc}-{d}", [])
            if not runs:
                row += f"{'—':>22}"; continue
            acc = [r["scalars"].get("sat.tcAccepted") or 0 for r in runs]
            rej = [r["scalars"].get("sat.tcRejected") or 0 for r in runs]
            m, lo, hi = ci(rej)
            row += f"{'ret ' + fmt(m, lo, hi, 1):>22}"
        print(row)

    # ── 2. Tespit başarımı ───────────────────────────────────────────────────
    for det_label, picker in (("D2 (akış anomalisi)", "D2"), ("D3 (ikiz sapma)", "D3")):
        print(f"\n▶ {det_label}")
        print(f"  {'senaryo':<9}{'F0.5':>22}{'F1C':>22}{'FPR':>22}{'gecikme':>12}")
        for sc in SCENARIOS:
            key = f"{sc}-{picker}"
            runs = cells.get(key, [])
            if not runs:
                print(f"  {sc:<9}{'—':>22}"); continue
            s = [r[picker] for r in runs]
            f05 = ci([x["f05"] for x in s])
            f1c = ci([x["f1c"] for x in s])
            fpr = ci([x["fpr"] for x in s])
            dl = [x["meanDetectionDelay"] for x in s if x["meanDetectionDelay"] is not None]
            dls = f"{statistics.fmean(dl):.0f} s" if dl else "—"
            print(f"  {sc:<9}{fmt(*f05):>22}{fmt(*f1c):>22}{fmt(*fpr, 4):>22}{dls:>12}")

    # ── 3. Önemsizlik denetimi ───────────────────────────────────────────────
    # ⚠️ Bu bir HİPOTEZ TESTİ DEĞİLDİR.  p = 0,01 rastgele dedektörün gözlem
    # başına alarm verme OLASILIĞIDIR, anlamlılık düzeyi değil.  Ayrıca iki ayrı
    # bootstrap aralığının çakışmaması eşleştirilmiş bir anlamlılık testi yerine
    # geçmez; CRN kullanıldığı için formal bir karşılaştırma istenirse tohum
    # bazında eşleştirilmiş fark bootstrap'ı gerekir.  Yapılmadı.
    print("\n▶ ÖNEMSİZLİK DENETİMİ — rastgele dedektör (alarm olasılığı 0,01/gözlem)")
    print(f"  {'senaryo':<9}{'RND F0.5':>22}{'D3 F0.5':>22}{'CI ayrık mı':>20}")
    trivial = []
    for sc in SCENARIOS:
        runs3 = cells.get(f"{sc}-D3", [])
        if not runs3:
            continue
        r = ci([x["RND"]["f05"] for x in runs3])
        d = ci([x["D3"]["f05"] for x in runs3])
        # ⚠️ Yalnız betimsel: aralıklar çakışıyor mu?  Çakışıyorsa "outperforms"
        # YAZILMAZ.  Çakışmaması da formal anlamlılık İDDİASI DEĞİLDİR.
        sep = d[1] > r[2] or r[1] > d[2]
        trivial.append((sc, sep))
        print(f"  {sc:<9}{fmt(*r):>22}{fmt(*d):>22}"
              f"{('✅ ayrık' if sep else '⚠️ çakışıyor'):>20}")

    # ── 3b. D3'ün alarmı HANGİ KANALDAN geldi ────────────────────────────────
    # 🔴 Bu tablo olmadan "D3 dört saldırıyı da yakaladı" cümlesi yanıltıcıdır.
    # D3 = D1 + ikiz olduğu için, komut tarafı saldırılarında alarmın kaynağı
    # büyük ölçüde GÜVENLİK kanalıdır: D1 düşman komutu reddeder, sayaç artar,
    # ikiz artışı görür.  Bu gerçek bir tespittir (§4.4) ama D1'den BAĞIMSIZ bir
    # davranışsal tespit DEĞİLDİR ve öyle sunulamaz.
    #
    # ⚠️ İki sınır, metne yazılacak:
    #  (1) Twin.cc olay günlüğüne yalnız TEK kanal yazar (öncelik: fiziksel →
    #      mantıksal → güvenlik).  Bu tablo "alarmın atandığı öncelikli kanal"
    #      tablosudur, eşzamanlı ihlallerin bağımsız toplamı değil.
    #  (2) Fiziksel sütun B0 tabanını içerir; saldırıya atfedilebilen kısım
    #      B0 farkıdır ve ayrıca gösterilir.
    print("\n▶ D3 ALARMI HANGİ KANALDAN GELDİ (koşu başına ortalama, öncelikli kanal)")
    print(f"  {'senaryo':<9}{'fiziksel':>12}{'(B0 farkı)':>13}{'mantıksal':>12}{'güvenlik':>11}")
    logdir = Path(args.matrix).parent
    chan = {}
    for sc in SCENARIOS:
        files = sorted(logdir.glob(f"{sc}-D3-s??-r0-events.csv"))
        if not files:
            continue
        p = l = s = 0
        for f in files:
            for line in open(f, errors="replace"):
                if ",d3.alarm," not in line:
                    continue
                if "channel=physical" in line:
                    p += 1
                elif "channel=logical" in line:
                    l += 1
                elif "channel=security" in line:
                    s += 1
        n = len(files)
        chan[sc] = (p / n, l / n, s / n)
    base = chan.get("B0", (0.0, 0.0, 0.0))[0]
    for sc in SCENARIOS:
        if sc not in chan:
            continue
        p, l, s = chan[sc]
        delta = "—" if sc == "B0" else f"{p - base:+.2f}"
        print(f"  {sc:<9}{p:>12.2f}{delta:>13}{l:>12.2f}{s:>11.2f}")
    if chan:
        print("  ⚠️ Öncelik sırası fiziksel → mantıksal → güvenlik; eşzamanlı ihlalde")
        print("     yalnız ilki günlüğe yazılır.  Bağımsız kanal katkısı DEĞİLDİR.")

    # ── 4. Artık risk ────────────────────────────────────────────────────────
    print("\n▶ ARTIK RİSK (K-50 ¶422 — düzeltilmeden raporlanır)")
    for sc in SCENARIOS:
        if sc == "B0":
            continue
        runs = cells.get(f"{sc}-D3", [])
        if not runs:
            continue
        miss = ci([1 - x["D3"]["recallEvent"] for x in runs])
        ev = statistics.fmean([x["D3"]["events"] for x in runs])
        print(f"  {sc}: olay başına yakalanamama oranı {fmt(*miss)}   "
              f"(ortalama {ev:.1f} etki aralığı/koşu)")

    print(f"\n{'='*100}")
    print("🔴 Yazım kuralı: yukarıdaki CI'lar çakışan hiçbir çift için 'outperforms',")
    print("   'significantly better' gibi ifadeler kullanılamaz (§8).")
    print("🔴 Aralıkların AYRIK olması da formal anlamlılık iddiası değildir —")
    print("   eşleştirilmiş hipotez testi yapılmadı; 'CI ayrık' betimsel bir gözlemdir.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
