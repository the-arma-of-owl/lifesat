#!/usr/bin/env python3
"""
LIFESAT — Faz 0 kapısı: adli günlüğün karma zinciri (kural R3).

İki iş yapar:

  doğrula   CSV'deki zinciri sıfırdan yeniden hesaplar ve dosyadaki değerlerle
            karşılaştırır.  Bir uyuşmazlık varsa **hangi indekste** koptuğunu
            söyler — A7 senaryosunun ölçtüğü şey bu (§5.2: "zincir kırılması
            yerelleşti mi").

  kurcala   Verilen indeksteki kaydı siler / zaman damgasını değiştirir ve
            kırılmanın gerçekten orada başladığını gösterir.  Kapının kanıtı
            budur: mekanizmanın işe yaradığını iddia etmiyoruz, kırıyoruz.

Zincir:  H_t = SHA256(H_{t-1} || record_t),  H_0 = SHA256("LIFESAT-GENESIS")
record_t = "idx,time,category,fields"  (CSV satırının ilk dört alanı)
"""

import argparse
import csv
import hashlib
import sys
from pathlib import Path

GENESIS_INPUT = "LIFESAT-GENESIS"


def sha256_hex(*parts):
    d = hashlib.sha256()
    for p in parts:
        d.update(p.encode())
    return d.hexdigest()


def read_log(path):
    csv.field_size_limit(sys.maxsize)
    rows = []
    with open(path, newline="") as f:
        for row in csv.reader(f):
            if not row or row[0] == "idx":
                continue
            # record = ilk dört alan; son iki alan prev ve chain
            rows.append({"record": ",".join(row[:4]), "prev": row[4], "chain": row[5]})
    return rows


def recompute(rows):
    """Zinciri baştan hesaplar; ilk uyuşmazlığın indeksini döndürür (yoksa None)."""
    head = sha256_hex(GENESIS_INPUT)
    first_break = None
    for i, r in enumerate(rows):
        expected_prev = head
        head = sha256_hex(head, r["record"])
        if first_break is None and (r["prev"] != expected_prev or r["chain"] != head):
            first_break = i
    return head, first_break


def cmd_verify(args):
    rows = read_log(args.log)
    head, brk = recompute(rows)
    print(f"kayıt sayısı : {len(rows)}")
    print(f"hesaplanan uç: {head}")

    anchor = Path(args.log).with_name(Path(args.log).name.replace("-events.csv", "-anchor.txt"))
    if anchor.exists():
        fields = dict(l.split("=", 1) for l in anchor.read_text().splitlines() if "=" in l)
        print(f"çıpadaki uç  : {fields.get('chainHead')}")
        if fields.get("chainHead") != head:
            print("🔴 Çıpa ile hesaplanan uç uyuşmuyor — günlük değişmiş.")
            if brk is not None:
                print(f"   İlk kopma indeksi: {brk}")
            return 1

    if brk is not None:
        print(f"🔴 Zincir {brk}. kayıtta kopuyor.")
        return 1
    print("✅ Zincir tutarlı — hiçbir kayıt değişmemiş, silinmemiş, yeniden sıralanmamış.")
    return 0


def cmd_tamper(args):
    """Kapının kanıtı: kaydı gerçekten bozup kırılmanın yerelleştiğini gösterir."""
    rows = read_log(args.log)
    if not rows:
        sys.exit("HATA: günlük boş")
    idx = args.index if args.index >= 0 else len(rows) // 2
    if idx >= len(rows):
        sys.exit(f"HATA: indeks {idx} > kayıt sayısı {len(rows)}")

    print(f"özgün günlük : {len(rows)} kayıt")
    head_before, brk_before = recompute(rows)
    print(f"  → zincir {'tutarlı' if brk_before is None else f'{brk_before} indeksinde kopuk'}")

    for mode in (["delete", "timestamp"] if args.mode == "both" else [args.mode]):
        work = [dict(r) for r in rows]
        if mode == "delete":
            removed = work.pop(idx)
            print(f"\nA7a — {idx}. kayıt SİLİNDİ: {removed['record'][:70]}")
        else:
            r = work[idx]
            parts = r["record"].split(",", 2)
            old = parts[1]
            parts[1] = str(float(old) + 3600) if old.replace(".", "").isdigit() else old + "X"
            r["record"] = ",".join(parts)
            print(f"\nA7b — {idx}. kaydın zaman damgası {old} → {parts[1]}")

        _, brk = recompute(work)
        if brk is None:
            print("  🔴 KAPI KAPALI — kurcalama tespit EDİLMEDİ.")
            return 1
        print(f"  ✅ kopma indeksi {brk} (beklenen {idx})")
        if brk != idx:
            print(f"  🔴 KAPI KAPALI — kopma {idx} yerine {brk}'de yerelleşti.")
            return 1
        surviving = idx if mode == "delete" else idx
        print(f"  ✅ {surviving} kayıt hâlâ doğrulanabilir; olay sırası o noktaya kadar kurulabilir")

    print("\n✅ KAPI AÇIK — silme ve zaman damgası tahrifi tespit ediliyor ve")
    print("   kırılma doğru indekste yerelleşiyor (R3, §5.2'nin A7 ölçütü).")
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("verify", help="zinciri yeniden hesapla ve doğrula")
    v.add_argument("log")
    v.set_defaults(func=cmd_verify)

    t = sub.add_parser("tamper", help="kurcala ve kırılmanın yerelleştiğini göster")
    t.add_argument("log")
    t.add_argument("--index", type=int, default=-1, help="-1: ortadaki kayıt")
    t.add_argument("--mode", choices=["delete", "timestamp", "both"], default="both")
    t.set_defaults(func=cmd_tamper)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
