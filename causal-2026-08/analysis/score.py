#!/usr/bin/env python3
"""
LIFESAT — bir koşunun skorlanması: cevap anahtarı ile dedektör kararlarının eşlenmesi.

🔴 BURASI ÇALIŞMANIN ÖLÇÜM NOKTASI.  Asıl soru "kaç alarm" değil, "hangi alarm
hangi saldırıya karşılık geliyor" — ve bundan önce "ne oldu": bir aksiyon
yürütüldü mü, engellendi mi, durumu gerçekten değiştirdi mi.

Kural R1'in nasıl korunduğu: cevap anahtarı (`*-truth.csv`) **koşu sırasında**
hiçbir dedektöre görünmez.  Bu betik çevrim dışı çalışır ve iki dosyayı
birleştirir — skorlamanın cevap anahtarını kullanması meşrudur, dedektörün
kullanması değil.

Bu sürüm kabul edilmiş scoring contract'ı uygular
(lifesat-scoring-contract/v1, 1.4.3-candidate; 1.4.2 mührü tarihsel authority):

  · aksiyon kimliği truth satır indeksinden türetilir; cmdId yalnız provenance'tır,
    dolayısıyla A3'te tekrarlanan komutun kendi meşru kabulü benign kalır;
  · F0 yürütme, F1 önleme ve F2 durum değişimi ayrı ailelerdir; aynı değeri
    yeniden yazan kabul `accepted_idempotent_no_change`'tir ve effect event üretmez;
  · effect window aynı anahtara FARKLI değer yazan sonraki kabulde kapanır —
    meşru ya da düşman fark etmez; bir alarm en fazla bir effect event'e kredi verir;
  · D2'nin karar birimi (koşu, pencere) çiftidir; gözlem başına çoğaltma ve
    asimetrik 60 s grace kaldırılmıştır;
  · A4 aksiyonları modification/delay/drop/unresolved olarak tam bölünür ve
    drop'ların karar-fırsatı sınıfı raporlanır;
  · F4 paydası D1 ret KANITI olaylarıdır (gözlenen sayaç geçişi değil),
    uygunluk telemetri kaynak zamanıyla belirlenir, sayaç kanal etiketine göre
    filtrelenmez;
  · tanımsız oran null + reason code'dur, asla 0,0 değildir; F0.5 sayım formundan
    hesaplanır; macro-over-defined-runs ile pooled ratio ayrı alanlardır.

Metrikler (§6 kararı, K-59):
  · F0.5   kesinlik ağırlıklı (operatör için yanlış alarm pahalı), sayım formu
  · F1C    olay bazlı recall + nokta bazlı precision (composite F-score)
  · FPR    ayrıca, tek başına
  🔴 F1PA kullanılmaz — rastgele dedektör orada 0,912 alıyor (K-59).
"""

import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scoring import artefacts, families, matching, ontology, output, state  # noqa: E402
from scoring.artefacts import (ArtefactError, load_events, load_truth,  # noqa: E402,F401
                               parse_fields)

SIM_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRACT_VERSION = "1.4.3-candidate"

# Tier-1 estimands emitted per cell, in contract order.
CELL_ESTIMANDS = (
    ("EST-F0-01", "F0_attack_execution", "attack_action",
     lambda r: (r["F0"]["delivered"], r["F0"]["actions"])),
    ("EST-F1-01", "F1_prevention", "command_authorisation_attempt",
     lambda r: (r["F1"]["numerator"], r["F1"]["denominator"])),
    ("EST-F2-01", "F2_state_transition", "attack_action",
     lambda r: (r["F2"]["numerator"], r["F2"]["denominator"])),
    ("EST-F4-01", "F4_secondary_reporting", "d1_rejection_evidence_event",
     lambda r: (r["F4"]["numerator"], r["F4"]["denominator"])),
)


def score_run(events_path, truth_path, end_time=artefacts.RUN_HORIZON):
    """Score one run against the accepted contract."""
    run = artefacts.run_identity(events_path)
    events = load_events(events_path)
    truth = load_truth(truth_path)
    return score_loaded(run, events, truth, end_time)


def score_loaded(run, events, truth, end_time=artefacts.RUN_HORIZON):
    scenario = artefacts.scenario_of(run)
    action_records = ontology.actions(run, truth, scenario)
    command_actions = matching.command_actions_of(action_records)
    telemetry_actions = [a for a in action_records
                         if a["action"] in ontology.TELEMETRY_SIDE]

    matched, policy = matching.match(events, command_actions)
    hostile_rows = {a["outcome_row"] for a in matched if a["outcome"] == "accepted"}
    verdicts = state.replay_parameter_store(events, hostile_rows)

    effect_events = state.effect_windows(events, verdicts, end_time)
    effect_events += state.telemetry_effect_events(events, telemetry_actions)
    effect_events.sort(key=lambda e: (e["start"], e["stop"]))

    defence = run.split("-")[1] if "-" in run else ""
    if families.f4_applicable(scenario, defence):
        f4_block, reporting_observations = families.secondary_reporting(events, matched)
    else:
        f4_block, reporting_observations = families.not_applicable_reporting()

    accounting = families.action_accounting(run, events, telemetry_actions)

    result = {
        "run_identity": run,
        "scenario": scenario,
        "matching_policy_id": policy,
        "F0": families.execution(matched, telemetry_actions,
                                 accounting["dispositions"]),
        "F1": families.prevention(matched),
        "F2": families.state_transition(matched, verdicts),
        "F4": f4_block,
        "action_accounting": accounting,
        "effect_events": effect_events,
        "F3": {
            "D3": families.direct_detection_d3(events, effect_events,
                                               reporting_observations),
            "D2": families.direct_detection_d2(events, telemetry_actions),
            "RND": families.direct_detection_rnd(events, effect_events),
        },
    }
    result["no_decision_opportunity"] = \
        result["action_accounting"]["no_decision_opportunity"]
    result["truth"] = _truth_summary(result, telemetry_actions)
    result["a4_subtype_detection"] = families.a4_subtype_detection(
        scenario, effect_events,
        result["F3"]["D3"].get("credited_effect_indices", []),
        telemetry_actions)
    result["effectIntervals"] = len(effect_events)
    result["episodes"] = sum(1 for r in truth
                             if r["f"].get("event") == "episode.begin")
    # Backwards-compatible detector handles for analysis/run_matrix.py.
    for detector in ("D2", "D3", "RND"):
        result[detector] = result["F3"][detector]
    return result


def _truth_summary(result, telemetry_actions):
    dispositions = result["action_accounting"]["dispositions"]
    return {"hostileCommands": result["F0"]["actions"],
            "hostileDelivered": result["F0"]["delivered"],
            "stateChanged": result["F2"]["state_changed"],
            "acceptedIdempotentNoChange":
                result["F2"]["accepted_idempotent_no_change"],
            "tamperedTm": dispositions["received_modified"],
            "delayedTm": dispositions["received_delayed"],
            "droppedTm": dispositions["dropped"],
            "unresolvedTm": dispositions["unresolved"]}


def score_corpus(pattern, end_time=artefacts.RUN_HORIZON, results_dir=None):
    """Score a glob of runs and emit the contract output document."""
    import glob
    base = results_dir or os.path.join(SIM_ROOT, "results")
    paths = sorted(glob.glob(os.path.join(base, pattern)))
    if not paths:
        raise ArtefactError("empty run set for pattern %r: an empty cells array is "
                            "fail-closed" % pattern)
    runs = [score_run(p, p.replace("-events.csv", "-truth.csv"), end_time)
            for p in paths]

    by_cell = {}
    for r in runs:
        by_cell.setdefault(r["run_identity"].rsplit("-s", 1)[0], []).append(r)

    cells = []
    for cell, members in sorted(by_cell.items()):
        scenario, defence = cell.split("-", 1)
        identities = [m["run_identity"] for m in members]
        results = [output.estimand_result(est_id, family, unit,
                                          [pick(m) for m in members], identities)
                   for est_id, family, unit, pick in CELL_ESTIMANDS]
        cells.append({"scenario": scenario, "defence": defence, "cell": cell,
                      "estimand_results": results})

    provenance = output.build_provenance(
        SIM_ROOT, [r["run_identity"] for r in runs],
        datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        CONTRACT_VERSION,
        matching_policy=runs[0]["matching_policy_id"])

    return {"contract_ref": {"contract_version": CONTRACT_VERSION,
                             "contract_json_sha256":
                                 provenance["contract_json_sha256"]},
            "provenance": provenance,
            "cells": cells,
            "action_accounting": [r["action_accounting"] for r in runs],
            "delays": _delays(runs),
            "notes": ["scored under %s" % CONTRACT_VERSION],
            "runs": runs}


def _delays(runs):
    """DL2 and DL4, each with its origin, endpoint and detection cardinality."""
    detected = scored = 0
    reported = evidence = 0
    for r in runs:
        d3 = r["F3"]["D3"]
        detected += d3["detectedEvents"]
        scored += d3["events"]
        reported += r["F4"]["reported"]
        evidence += r["F4"]["denominator"]
    return [
        output.delay_record(
            "DL2_received_observation_to_direct_alarm",
            "tm.recv timestamp of the affected observation",
            "timestamp of the D3 alarm raised on that observation",
            "detected received tampered/delayed observations only",
            detected, scored, 0.0 if detected else None),
        output.delay_record(
            "DL4_eligible_observation_to_twin_alarm",
            "arrival timestamp of the first eligible observation",
            "timestamp of the twin alarm raised on that observation",
            "reported evidence events", reported, evidence,
            0.0 if reported else None),
    ]


def _fmt(value, digits=3):
    return "—" if value is None else "%.*f" % (digits, value)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("events")
    ap.add_argument("--truth", default=None)
    ap.add_argument("--end", type=float, default=artefacts.RUN_HORIZON)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    truth = args.truth or args.events.replace("-events.csv", "-truth.csv")
    r = score_run(args.events, truth, args.end)

    if args.json:
        print(json.dumps({k: v for k, v in r.items()
                          if k not in ("D2", "D3", "RND")}, indent=2))
        return 0

    t = r["truth"]
    print(f"\ncevap anahtarı: {r['episodes']} epizot · {t['hostileCommands']} düşman "
          f"aksiyon ({t['hostileDelivered']} teslim) · {t['stateChanged']} durum "
          f"değişimi · {t['acceptedIdempotentNoChange']} idempotent kabul")
    print(f"telemetri     : {t['tamperedTm']} tahrif · {t['delayedTm']} geciktirilmiş "
          f"· {t['droppedTm']} düşürülmüş · {t['unresolvedTm']} çözümsüz")
    print(f"etki olayı    : {r['effectIntervals']}")
    print(f"F1 önleme     : {r['F1']['numerator']}/{r['F1']['denominator']}"
          f"   F4 raporlama: {r['F4']['reported']}/{r['F4']['denominator']}\n")
    print(f"{'dedektör':<10}{'birim':<28}{'TP':>5}{'FP':>5}{'FN':>5}"
          f"{'kesinlik':>10}{'recall':>9}{'FPR':>9}{'F0.5':>8}{'F1C':>8}")
    print("─" * 97)
    for name in ("D3", "D2", "RND"):
        s = r["F3"][name]
        print(f"{name:<10}{s['evaluation_unit']:<28}{s['tp']:>5}{s['fp']:>5}"
              f"{s['fn']:>5}{_fmt(s['precision']):>10}{_fmt(s['recall']):>9}"
              f"{_fmt(s['fpr'], 4):>9}{_fmt(s['f05']):>8}{_fmt(s['f1c']):>8}")
    print("\n🔴 Tanımsız değerler '—' olarak gösterilir; 0,0 ile karıştırılmamalıdır.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
