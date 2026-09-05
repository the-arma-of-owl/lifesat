#!/usr/bin/env python3
"""
LIFESAT — Faz 6 kapısı: A6, A7c, A8 (Kademe 2, tek örnek koşu).

Bu üç senaryo 20 hücrelik nicel matrisin PARÇASI DEĞİL (ÖZDENETİM #9). İstatistik
üretilmez; her biri için §5.2'nin tanımladığı ölçüt sağlanıyor mu diye bakılır:

  A6  — komut auth KAPALIYKEN uygulanan yetkisiz CMD_UPDATE ikizin mantıksal
        kanalını sapkınlaştırıyor mu (d3AlarmsLogical > 0)? AÇIKKEN kapıda
        reddediliyor mu (d3AlarmsLogical == 0, tcRejectedAuth > 0)?

  A7c — D1'in reddettiği komut karma-zincirli olay günlüğüne (tc.reject) doğru
        yazılıyor mu; saldırgan aşağı bağlantıdaki rejectedCmdCount alanını
        tahrif ederken zincir bundan etkilenmeden tutarlı kalıyor mu (kanıt:
        zincir doğrulanır VE tc.reject sayısı, tahrif edilmemiş TABAN sayıdan
        büyük — "sayaç tahrif edilebilir, zincir edilemez")?

  A8  — geçiş başında enjekte edilen sahte telemetri en az bir kez fiziksel
        kanalda bir alarma yol açıyor mu (ya enjeksiyon anında ya da bir
        sonraki gerçek telemetride, dar Δt penceresinde)?

Ölçüt TESPİT değil YENİDEN KURGULANABİLİRLİK: A7c için asıl kanıt, zincirin
kurcalamadan etkilenmemiş kalması ve gerçek ret olaylarının hâlâ orada olması.
"""

import csv
import re
import sys
from pathlib import Path

RESULTS = Path(__file__).resolve().parent.parent / "results"
SCA = Path(__file__).resolve().parent.parent / "simulations" / "results"


def read_scalars(label):
    # runLabel OMNeT++ tarafından kaçışlı tırnaklarla yazılır: par ... runLabel "\"A6-D0\""
    needle = f'\\"{label}\\"'
    candidates = list(SCA.glob("*-#0.sca"))
    target = None
    for p in candidates:
        for line in open(p):
            if line.startswith("par Lifesat.collector runLabel") and needle in line:
                target = p
                break
        if target:
            break
    if target is None:
        sys.exit(f"HATA: {label} için .sca bulunamadı (önce koşuyu çalıştırın)")
    v = {}
    for line in open(target):
        m = re.match(r"scalar\s+Lifesat\.(\S+)\s+(\S+)\s+([-\d.eE+]+)", line)
        if m:
            try:
                v[f"{m.group(1)}.{m.group(2)}"] = float(m.group(3))
            except ValueError:
                pass
    return v


def read_chain_csv(path):
    csv.field_size_limit(sys.maxsize)
    rows = []
    with open(path, newline="") as f:
        for row in csv.reader(f):
            if not row or row[0] == "idx":
                continue
            rows.append(row)
    return rows


def verify_chain(path):
    import hashlib

    def h(*parts):
        d = hashlib.sha256()
        for p in parts:
            d.update(p.encode())
        return d.hexdigest()

    rows = read_chain_csv(path)
    ok = True
    head = h("LIFESAT-GENESIS")
    for r in rows:
        record = ",".join(r[:4])
        expected_prev = head
        head = h(head, record)
        if r[4] != expected_prev or r[5] != head:
            ok = False
            break
    return ok, rows


def check_a6():
    print("▶ A6 — yetkisiz güncelleme: mantıksal kanal / D1 kapısı")
    d0 = read_scalars("A6-D0")
    d1 = read_scalars("A6-D1")
    ok = True
    if d0.get("twin.d3AlarmsLogical", 0) <= 0:
        print("  🔴 D0: mantıksal kanal hiç sapmadı — beklenen davranış değil")
        ok = False
    else:
        print(f"  ✅ D0 (auth kapalı): güncelleme uygulandı, mantıksal kanal "
              f"{int(d0['twin.d3AlarmsLogical'])}/{int(d0['twin.observations'])} "
              f"gözlemde sapkın")
    if d1.get("sat.tcRejectedAuth", 0) <= 0:
        print("  🔴 D1: imzasız güncelleme reddedilmedi — auth denetimi çalışmıyor")
        ok = False
    elif d1.get("twin.d3AlarmsLogical", 0) != 0:
        print("  🔴 D1: komut kapıda reddedildiği hâlde mantıksal kanal sapmış — beklenmedik")
        ok = False
    else:
        print(f"  ✅ D1 (auth açık): {int(d1['sat.tcRejectedAuth'])} güncelleme kapıda "
              f"reddedildi, mantıksal kanal hiç sapmadı, güvenlik kanalı "
              f"{int(d1.get('twin.d3AlarmsSecurity', 0))} kez alarm verdi")
    return ok


def check_a7c():
    print("\n▶ A7c — adli kayıt tahrifi: sayaç tahrif edilebilir, zincir edilemez")
    events_path = RESULTS / "A7c-D3-r0-events.csv"
    truth_path = RESULTS / "A7c-D3-r0-truth.csv"
    ok, rows = verify_chain(events_path)
    if not ok:
        print("  🔴 KAPI KAPALI — karma zinciri tutarsız; A7c'de saldırganın zincire hiç "
              "erişimi yok, dolayısıyla kopma bir hata demektir")
        return False
    # ⚠️ Bu bir tamper-evidence kanıtı DEĞİL: saldırgan zincire zaten dokunmuyor.
    # Tamper-evidence kanıtı A7a/A7b'dir (verify_chain.py tamper, Faz 0 kapısı).
    print(f"  ✅ karma zinciri tutarlı ({len(rows)} kayıt) — saldırganın erişim yüzeyi "
          "telin üzerindeki paketlerle sınırlı, kayda uzanmıyor")

    true_rejects = sum(1 for r in rows if r[2] == "tc.reject")
    tampered = [l for l in open(truth_path) if "field=rejectedCmdCount" in l]
    if true_rejects == 0:
        print("  🔴 KAPI KAPALI — bu koşuda hiç D1 reddi yok, A7c'nin göstereceği bir şey yok")
        return False
    if not tampered:
        print("  🔴 KAPI KAPALI — saldırgan hiçbir telemetride sayacı tahrif etmemiş")
        return False
    print(f"  ✅ olay günlüğü {true_rejects} GERÇEK D1 reddini taşıyor (kaynak: "
          f"CubeSat'ın kendi kabul/ret anındaki kaydı — saldırgandan ÖNCE yazılır)")
    print(f"  ✅ saldırgan aşağı bağlantıda {len(tampered)} telemetri paketinde "
          f"rejectedCmdCount alanını tahrif etti (canlı akışta gizlendi)")
    print("  ✅ YENİDEN KURGULANABİLİRLİK: zincir-korumalı günlük, tahrif edilmiş canlı "
          "telemetriden BAĞIMSIZ olarak gerçek ret sayısını taşımaya devam ediyor")
    return True


def check_a8():
    print("\n▶ A8 — yeniden senkronizasyon penceresi ele geçirme")
    events_path = RESULTS / "A8-D3-r0-events.csv"
    truth_path = RESULTS / "A8-D3-r0-truth.csv"
    spoofs = [l.strip() for l in open(truth_path) if "event=spoof" in l]
    if not spoofs:
        print("  🔴 KAPI KAPALI — hiç sahte resync paketi enjekte edilmemiş")
        return False

    rows = read_chain_csv(events_path)
    caught_immediately = 0
    caught_next = 0
    evaded = 0
    for s in spoofs:
        t = float(s.split(",")[1])
        seq_m = re.search(r"tmSeq=(\d+)", s)
        seq = int(seq_m.group(1)) if seq_m else None
        # enjeksiyon anındaki d3.alarm
        immediate = any(r[2] == "d3.alarm" and abs(float(r[1]) - t) < 1e-6 for r in rows)
        if immediate:
            caught_immediately += 1
            continue
        # bir sonraki gerçek telemetride (t'den sonraki ilk tm.recv'e denk gelen d3.alarm) —
        # tm.recv ve ona bağlı d3.alarm AYNI zaman damgasıyla, art arda loglanır (Twin,
        # GroundStation'ın telemetriyi işlediği anda çağrılır).
        later = [r for r in rows if float(r[1]) > t and r[2] in ("tm.recv", "d3.alarm")]
        caught = False
        if later and later[0][2] == "tm.recv":
            next_tm_time = later[0][1]
            caught = any(r[2] == "d3.alarm" and r[1] == next_tm_time for r in later[1:4])
        if caught:
            caught_next += 1
        else:
            evaded += 1

    print(f"  ✅ {len(spoofs)} sahte resync paketi enjekte edildi")
    print(f"  · enjeksiyon anında yakalanan : {caught_immediately}  "
          f"(geniş Δt toleransı yine de aşıldı)")
    print(f"  · bir sonraki temasta yakalanan: {caught_next}  "
          f"(§5.2 ölçütü: 'temas kurulunca yakalanıyor mu')")
    print(f"  · bu koşuda yakalanamayan      : {evaded}  "
          f"(tek koşu — istatistiksel iddia yok, §6'da dürüstçe bildirilecek)")
    return caught_immediately + caught_next > 0


def check_a2v():
    """⭐ §4.4'ün asıl A2'si: kripto geçerli, D1 geçirir, davranışsal savunma kalır."""
    print("\n▶ A2v — geçerli kimlikli yetkisiz komut: D1 geçirmeli, ikiz yakalamalı")
    d3 = read_scalars("A2v-D3")
    d1 = read_scalars("A2v-D1")
    ok = True

    # 1) D1 GEÇİRMELİ — yoksa yeniden imzalama çalışmıyor demektir
    if d3.get("sat.tcRejected", 0) != 0:
        print(f"  🔴 D1 {int(d3['sat.tcRejected'])} komut reddetti — yeniden imzalama "
              "başarısız; A2v'nin tüm anlamı D1'i GEÇMESİ")
        ok = False
    else:
        print(f"  ✅ D1 hiçbir komutu reddetmedi ({int(d3.get('sat.tcAccepted', 0))} kabul) — "
              "ele geçirilmiş anahtarla yeniden imzalanan komut üç denetimi de geçiyor")

    # 2) Yakalayan kanal MANTIKSAL olmalı, güvenlik DEĞİL
    lg = d3.get("twin.d3AlarmsLogical", 0)
    sec = d3.get("twin.d3AlarmsSecurity", 0)
    if lg <= 0:
        print("  🔴 mantıksal kanal hiç alarm vermedi — davranışsal tespit çalışmıyor")
        ok = False
    elif sec > 0:
        print(f"  🔴 güvenlik kanalı {int(sec)} alarm verdi — A2v'de D1 ret yapmamalı, "
              "dolayısıyla güvenlik kanalı sessiz olmalı")
        ok = False
    else:
        print(f"  ✅ tespit MANTIKSAL kanaldan: {int(lg)} alarm, güvenlik kanalı 0 — "
              "§6.3'ün komut tarafı profilinin tam tersi, D1'den bağımsız")

    # 3) İkiz kapalıyken tespit OLMAMALI (ablasyon)
    if d1.get("twin.d3Alarms", 0) != 0 or d1.get("sat.tcRejected", 0) != 0:
        print("  🔴 ikiz kapalıyken de bir şey yakalandı — ablasyon anlamsız")
        ok = False
    else:
        print("  ✅ ikiz kapalıyken (D1 tek başına) ne ret ne alarm var — "
              "geçerli kimlikli saldırıya karşı yetkilendirme tek başına kör")
    return ok


def check_a6s():
    """⭐ Abstract'ın in-orbit fazı: güncelleme ÖNCE ikizde denenir."""
    print("\n▶ A6s — gönderim öncesi ikiz doğrulaması (önleme, tespit değil)")
    on = read_scalars("A6s-gate-on")
    off = read_scalars("A6s-gate-off")
    safe = read_scalars("A6s-safe")
    ok = True

    prop = on.get("gs.updatesProposed", 0)
    if prop <= 0:
        print("  🔴 hiç aday güncelleme önerilmedi — deney koşmadı")
        return False

    # 1) Kapı açıkken güvensiz güncelleme uyduya HİÇ ulaşmamalı
    if on.get("gs.updatesUplinked", 0) != 0 or on.get("gs.updatesBlocked", 0) != prop:
        print(f"  🔴 kapı açıkken {int(on.get('gs.updatesUplinked', 0))} güvensiz güncelleme "
              "yine de uplink edildi")
        ok = False
    else:
        print(f"  ✅ kapı AÇIK: {int(prop)}/{int(prop)} güvensiz aday gönderim öncesi "
              f"reddedildi, uyduya hiç ulaşmadı (batarya min "
              f"{on.get('sat.batteryVoltage:min', float('nan')):.2f} V)")

    # 2) Kapı kapalıyken uygulanmalı, fiziksel hasar oluşmalı — ve ⭐ SAPMA
    #    DEDEKTÖRÜ BUNU GÖREMEMELİ.  Uydu yerin ONAYLADIĞI şeyi sadakatle
    #    yapıyor; ortada sapma yok, dolayısıyla sapma tabanlı tespit yapısal
    #    olarak kör.  Kapının "daha erken" değil **tek** savunma olmasının nedeni.
    if off.get("gs.updatesUplinked", 0) != prop:
        print("  🔴 kontrol kolu: kapı kapalıyken güncelleme uplink edilmedi")
        ok = False
    else:
        vmin = off.get("sat.batteryVoltage:min", float("nan"))
        alarms = off.get("twin.d3Alarms", 0)
        base = on.get("twin.d3Alarms", 0)
        print(f"  ✅ kapı KAPALI: {int(prop)}/{int(prop)} uplink edildi, batarya "
              f"{vmin:.2f} V'a düştü (bildirilmiş taban 7,00 V ihlal edildi)")
        if vmin >= on.get("sat.batteryVoltage:min", 0):
            print("  🔴 kapı kapalıyken batarya daha kötü olmalıydı — güncelleme etkisiz")
            ok = False
        if alarms > base:
            print(f"  🔴 sapma dedektörü {int(alarms)} alarm verdi (taban {int(base)}) — "
                  "ikiz kendi onayladığı güncellemeyi modeline işlemiyor olabilir")
            ok = False
        else:
            print(f"  ✅ ⭐ ikiz {int(alarms)} alarm verdi (taban {int(base)}) — "
                  "SAPMA YOK, çünkü uydu onaylanan şeyi sadakatle yapıyor. "
                  "Sapma tabanlı tespit bu vakada YAPISAL OLARAK KÖR; kapı, "
                  "D1–D3 yığınında uygulanmış TEK savunma")
            # ⚠️ "Tek savunma" ifadesi bu yığınla sınırlı — genel bir imkânsızlık
            # iddiası DEĞİL.  Bildirilmiş güvenlik tabanını uçuş sırasında
            # denetleyen bir zarf monitörü de yakalardı; uygulanmadı (§7).

    # 3) NEGATİF KONTROL: kapı her şeyi reddetmiyor
    if safe.get("gs.updatesBlocked", 0) != 0 or safe.get("gs.updatesUplinked", 0) != prop:
        print(f"  🔴 GÜVENLİ güncelleme de engellendi "
              f"({int(safe.get('gs.updatesBlocked', 0))}) — kapı ayırt etmiyor, "
              "sonuç anlamsız")
        ok = False
    else:
        print(f"  ✅ negatif kontrol: GÜVENLİ aday {int(prop)}/{int(prop)} geçti — "
              "kapı ayırt ediyor, körü körüne reddetmiyor")

    # 4) 🔴 FAIL-CLOSED: zarfın kapsamadığı parametre uplink EDİLMEMELİ
    uns = read_scalars("A6s-unsupported")
    if uns.get("gs.updatesUplinked", 0) != 0:
        print(f"  🔴 FAIL-OPEN — ikizin değerlendiremediği parametre yine de "
              f"{int(uns['gs.updatesUplinked'])} kez uplink edildi; "
              "'reddedilmedi' ile 'onaylandı' aynı şey sayılmış")
        ok = False
    elif uns.get("gs.updatesUnsupported", 0) <= 0:
        print("  🔴 UNSUPPORTED verdict'i hiç kaydedilmemiş")
        ok = False
    else:
        # ⚠️ Nihai karar olayı günlükte öneri başına TAM BİR KEZ görünmeli.
        # Eskiden ikiz ve yer istasyonu aynı kategori adını yazıyordu ve 9 öneri
        # 18 kayıt üretiyordu; sayım bozuluyordu.  İç değerlendirme artık
        # `twin.updateUnsupported`, nihai karar `update.unsupported`.
        rows = read_chain_csv(RESULTS / "A6s-unsupported-r0-events.csv")
        final = sum(1 for r in rows if r[2] == "update.unsupported")
        proposed = int(uns.get("gs.updatesProposed", 0))
        if final != proposed:
            print(f"  🔴 günlükte {final} nihai 'update.unsupported' kaydı var ama "
                  f"{proposed} öneri yapıldı — çift kayıt ya da eksik kayıt")
            ok = False
        else:
            print(f"  ✅ fail-closed: zarfın kapsamadığı parametre "
                  f"{int(uns['gs.updatesUnsupported'])}/{proposed} kez UNSUPPORTED "
                  f"olarak kaydedildi ve uplink EDİLMEDİ (günlükte {final} nihai "
                  "karar kaydı, öneri başına tam bir tane)")

    # 5) Onaylanan güncelleme ikizin ÇALIŞAN modeline yansımalı — ama yalnız
    #    telemetri doğruladıktan sonra — ve SONRASINDA kalıcı yanlış alarm
    #    üretmemeli.
    #
    # 🔴 ORACLE, koşulardan ÖNCE ilan edildi.  Önceki sürümde alarm sayısı
    # yalnız EKRANA YAZILIYORDU: model senkronizasyonu yeniden bozulup 683
    # alarm üretse bile test geçerdi ve "kalıcı yanlış alarm yok" mesajı
    # yalan olurdu.  İki ölçüt:
    #   (a) toplam alarm ≤ referans + güncelleme sayısı  — her doğrulanan
    #       güncellemeye bir geçiş alarmı payı bırakılır (referans: aynı
    #       tohumda kapı açık kolu, orada güncelleme hiç uygulanmaz)
    #   (b) İLK model güncellemesinden SONRAKİ gözlemlerin en fazla %5'i
    #       alarmlı olabilir — model desenkronizasyonu %80'in üzerinde
    #       sürekli alarm üretir (ölçüldü: kusurlu sürümde 683/818 = %83)
    # ⚠️ Tek koşu; bunlar kabul eşiğidir, istatistiksel iddia değil.
    SUSTAINED_ALARM_FRACTION = 0.05
    big = read_scalars("A6s-safe-large")
    applied = big.get("twin.updatesAppliedToModel", 0)
    if big.get("gs.updatesUplinked", 0) <= 0:
        print("  🔴 büyük-güvenli aday uplink edilmedi — test koşmadı")
        ok = False
    elif applied <= 0:
        print("  🔴 onaylanan güncelleme ikizin çalışan modeline HİÇ yansımadı — "
              "uydu yeni deşarj hızıyla, ikiz eskisiyle yürüyor (kalıcı sapma riski)")
        ok = False
    else:
        alarms = big.get("twin.d3Alarms", 0)
        reference = on.get("twin.d3Alarms", 0)
        allowance = reference + prop        # geçiş payı: güncelleme başına 1
        rows = read_chain_csv(RESULTS / "A6s-safe-large-r0-events.csv")
        first_update = next((float(r[1]) for r in rows
                             if r[2] == "twin.modelUpdated"), None)
        obs_after = sum(1 for r in rows
                        if r[2] == "tm.recv" and float(r[1]) >= first_update)
        alarm_after = sum(1 for r in rows
                          if r[2] == "d3.alarm" and float(r[1]) >= first_update)
        frac = alarm_after / obs_after if obs_after else 0.0

        if alarms > allowance:
            print(f"  🔴 toplam {int(alarms)} alarm > kabul eşiği {int(allowance)} "
                  f"(referans {int(reference)} + geçiş payı {int(prop)}) — ikiz "
                  "onayladığı güncellemeden sonra uydudan sapıyor")
            ok = False
        elif frac > SUSTAINED_ALARM_FRACTION:
            print(f"  🔴 ilk model güncellemesinden sonra {alarm_after}/{obs_after} "
                  f"gözlem alarmlı (%{100*frac:.1f} > %{100*SUSTAINED_ALARM_FRACTION:.0f}) "
                  "— SÜREKLİ yanlış alarm serisi, model desenkronize")
            ok = False
        else:
            print(f"  ✅ onaylanan güncelleme telemetriyle doğrulandıktan sonra ikizin "
                  f"modeline {int(applied)} kez uygulandı; toplam {int(alarms)} alarm "
                  f"(eşik {int(allowance)}), güncelleme sonrası {alarm_after}/{obs_after} "
                  f"gözlem alarmlı (%{100*frac:.1f} < %{100*SUSTAINED_ALARM_FRACTION:.0f}) "
                  "— kalıcı yanlış alarm YOK")
        # ⚠️⚠️ ORACLE'IN KENDİ SINIRI — kasıtlı bozma testiyle ÖLÇÜLDÜ (28 Tem).
        # Model senkronizasyonu bilerek kaldırıldığında bu koldaki alarm sayısı
        # DEĞİŞMİYOR (1 alarm, %0,1) — yani yukarıdaki iki ölçüt safe-large
        # kolunda ateşlenemiyor.  Nedeni: zarfın izin verdiği en büyük deşarj
        # hızında (~0,00011) bile desenkronizasyon sapması, toleransın ölçüm
        # terimi (3σ√2 ≈ 0,042 V) altında kalıyor.  Bu koldaki gerçek koruma
        # `updatesAppliedToModel > 0` kontrolüdür.
        #
        # ✅ Alarm oracle'ının GERÇEKTEN çalıştığı yer 2 numaralı kontroldür
        # (gate-off kolu): orada uygulanan hız 0,0004 ve desenkronizasyon
        # bozuk sürümde 683 alarm üretiyor, kontrol kapıyı kapatıyor.  Doğrulama:
        #   analysis/check_illustrative.py, bozuk Twin.cc ile → "🔴 sapma
        #   dedektörü 683 alarm verdi (taban 1)" ve FAZ 6 KAPISI KAPALI.
        #
        # 🔴 §6'da "ölçülen bir iyileşme" diye SUNULMAYACAK — düzeltme gizli
        # kalan bir kusuru kapatıyor, gözlenebilir bir fark üretmiyor.
        #
        # 📌 GELECEK İŞ (isteğe bağlı, yapılmadı): bu oracle'ı ateşlenebilir hâle
        # getirmek için makale senaryolarından AYRI bir *test-only* profil
        # kullanılabilir — ölçüm toleransı daraltılır (ör. voltageNoiseSigma ve
        # sigmaFactor küçültülür), böylece zarf içi bir desenkronizasyon
        # gözlenebilir alarm üretir ve safe-large kolu da gerçek bir regresyon
        # koruması kazanır.
        # ⚠️ O profil §6'ya GİRMEZ ve 20 hücrelik nicel matrise dokunmaz; yalnız
        # test amaçlıdır.  Aksi hâlde toleransı sonuca göre ayarlamış oluruz —
        # §5.4'ün veri sızıntısı kuralının ihlali.
    return ok


def main():
    results = [check_a2v(), check_a6(), check_a6s(), check_a7c(), check_a8()]
    print()
    print("─" * 72)
    if all(results):
        print("  ✅ FAZ 6 KAPISI AÇIK — A2v/A6u/A6s/A7c/A8 illustrative koşuları "
              "mekanizma olarak çalışıyor")
        return 0
    print("  🔴 FAZ 6 KAPISI KAPALI")
    return 1


if __name__ == "__main__":
    sys.exit(main())
