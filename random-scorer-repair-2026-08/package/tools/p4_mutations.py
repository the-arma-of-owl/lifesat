#!/usr/bin/env python3
"""p4_mutations.py — one owning mutant per Phase 4 detector.

The five the plan names by hand are MUT-01..MUT-05:

    n->tmSeq, ordinal shift, duplicate ordinal, missing observation,
    out-of-range ordinal

and the rest close the guards those five do not reach — silent drops, untyped
dispositions, oracle disagreement, corpus substitution and invariance.

Every mutant operates on the REAL events of the fixture run, loaded from the
immutable corpus and then damaged IN MEMORY. Nothing here writes to the corpus,
the historical package, the seal, or the candidate scorer.
"""

from __future__ import annotations

import copy
import os
import sys

sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import p4_authority as PA         # noqa: E402
import p4_checks as PC            # noqa: E402
import p4_identity as PI          # noqa: E402
import p4_reference_oracle as REF  # noqa: E402
import p4_settlement as PS        # noqa: E402

sys.path.insert(0, PA.CANDIDATE_SCORER)

import score as SCORE                       # noqa: E402
from scoring import rndjoin                 # noqa: E402

FIXTURE_RUN = "A1-D3-s00-r0"
_CACHE = {}


def _detectors(findings):
    return {row["detector_id"] for row in findings}


def fixture():
    """The real events/truth of the fixture run, loaded once."""
    if "fixture" not in _CACHE:
        run = next(r for r in PA.corpus()["runs"]
                   if r["identity"] == FIXTURE_RUN)
        events_path, truth_path = PA.run_paths(run)
        problems = PA.verify_run_inputs(run)
        if problems:
            raise SystemExit(f"fixture source drifted: {problems}")
        _CACHE["fixture"] = {
            "events": SCORE.load_events(events_path),
            "events_path": events_path,
            "run": run,
            "scored": SCORE.score_run(events_path, truth_path),
            "truth_path": truth_path,
        }
    return _CACHE["fixture"]


def _events():
    return copy.deepcopy(fixture()["events"])


def _bind_and_check(events):
    """Bind mutated events and run every binding guard over the result."""
    binding = rndjoin.bind(events)
    conservation = binding.conservation
    findings = []
    findings += PC.check_conservation(conservation, events)
    findings += PC.check_dispositions(binding)
    findings += PC.check_ordinal_health(conservation)
    findings += PC.check_time_witness(conservation)
    findings += PC.check_join_is_ordinal(events, binding.alarmed_ordinals)
    return _detectors(findings)


# ---------------------------------------------------------------------------
# MUT-01..MUT-05 — the five the plan names
# ---------------------------------------------------------------------------

def mut_consumer_reads_tmseq(_workdir):
    """THE ORIGINAL DEFECT, reproduced: the consumer reads `tmSeq`.

    Not described — executed. A regression nobody can watch fail is a
    regression nobody has tested. The legacy read credits NOTHING, because
    `tmSeq` is absent from every alarm row.
    """
    events = _events()
    legacy = PC._legacy_alarmed(events)                    # noqa: SLF001
    return _detectors(PC.check_join_is_ordinal(events, legacy))


def mut_ordinal_shift(_workdir):
    """The ordinal is read as 0-based instead of 1-based."""
    events = _events()
    binding = rndjoin.bind(events)
    shifted = {k - 1 for k in binding.alarmed_ordinals if k > 1}
    return _detectors(PC.check_join_is_ordinal(events, shifted))


def mut_duplicate_ordinal(_workdir):
    """A second alarm claims an ordinal already claimed in this run."""
    events = _events()
    alarm = next(row for row in events if row["cat"] == "rnd.alarm")
    clone = copy.deepcopy(alarm)
    clone["t"] = alarm["t"] + 1e-6
    events.insert(events.index(alarm) + 1, clone)
    return _bind_and_check(events)


def mut_missing_observation(_workdir):
    """An observation is absent, so every later ordinal addresses the wrong row.

    The tail alarm also falls out of range once the sequence is one short; the
    OWNING detector is the time witness, because the first thing that breaks is
    that a matched pair no longer shares its instant.
    """
    events = _events()
    binding = rndjoin.bind(events)
    first = min(binding.alarmed_ordinals)
    position = 0
    for index, row in enumerate(events):
        if row["cat"] != "tm.recv":
            continue
        position += 1
        if position == first:
            del events[index]
            break
    return _bind_and_check(events)


def mut_ordinal_out_of_range(_workdir):
    """An alarm names an observation the run does not have."""
    events = _events()
    observations = sum(1 for row in events if row["cat"] == "tm.recv")
    alarm = next(row for row in events if row["cat"] == "rnd.alarm")
    alarm["f"]["n"] = str(observations + 1)
    return _bind_and_check(events)


# ---------------------------------------------------------------------------
# the guards the five do not reach
# ---------------------------------------------------------------------------

def mut_silent_drop(_workdir):
    """A binder that filters unmatched rows and balances its own books.

    This is the failure mode the conservation equation exists for: the binding
    is internally consistent and still lost rows. Only an anchor to the raw log
    catches it.
    """
    events = _events()
    events[len(events) // 2] = dict(events[len(events) // 2])
    alarm = next(row for row in events if row["cat"] == "rnd.alarm")
    alarm["f"] = {"n": "999999"}                 # will be unmatched
    binding = rndjoin.bind(events)
    binding.rows = [row for row in binding.rows
                    if row["disposition"] == "matched"]   # the drop
    return _detectors(PC.check_conservation(binding.conservation, events))


def mut_missing_ordinal_field(_workdir):
    """An alarm row carries no `n` at all."""
    events = _events()
    alarm = next(row for row in events if row["cat"] == "rnd.alarm")
    alarm["f"] = {}
    binding = rndjoin.bind(events)
    rows = binding.rows
    if any(r["disposition"] == "unmatched_missing_ordinal_field" for r in rows):
        # typed, not dropped — now prove an UNTYPED row is refused
        rows[0] = dict(rows[0], disposition=None)
        return _detectors(PC.check_dispositions(binding))
    return set()


def mut_undeclared_disposition(_workdir):
    """A binder invents a disposition outside the declared set."""
    events = _events()
    binding = rndjoin.bind(events)
    binding.rows[0] = dict(binding.rows[0], disposition="probably_fine")
    return _detectors(PC.check_dispositions(binding))


def mut_oracle_disagreement(_workdir):
    """The production join credits an observation the time witness does not."""
    data = fixture()
    events = _events()
    binding = rndjoin.bind(events)
    binding.alarmed_ordinals = set(binding.alarmed_ordinals) | {7}
    return _detectors(REF.compare(events, data["scored"]["effect_events"],
                                  data["scored"]["F3"]["RND"], binding))


def mut_registry_declares_tmseq(_workdir):
    """The field registry claims the producer emits `tmSeq`."""
    saved = dict(rndjoin.PRODUCER["fields"])
    try:
        rndjoin.PRODUCER["fields"]["tmSeq"] = "a field nobody emits"
        return _detectors(PC.check_field_registry())
    finally:
        rndjoin.PRODUCER["fields"] = saved


def mut_registry_seq_as_key(_workdir):
    """The registry stops marking `seq` as provenance only."""
    saved = dict(rndjoin.CONSUMER["fields"])
    try:
        rndjoin.CONSUMER["fields"]["seq"] = "telemetry sequence number"
        return _detectors(PC.check_field_registry())
    finally:
        rndjoin.CONSUMER["fields"] = saved


def mut_oracle_ambiguous(_workdir):
    """Two observations share an instant, so the time witness cannot resolve.

    The duplicated observation must be one an alarm actually points at —
    duplicating an arbitrary row creates an ambiguity nothing ever consults, and
    the mutant would pass while proving nothing.
    """
    events = _events()
    alarmed = rndjoin.bind(events).alarmed_ordinals
    target = min(alarmed)
    position, index = 0, None
    for candidate, row in enumerate(events):
        if row["cat"] != "tm.recv":
            continue
        position += 1
        if position == target:
            index = candidate
            break
    events.insert(index + 1, copy.deepcopy(events[index]))
    binding = rndjoin.bind(events)
    return _detectors(REF.compare(events, [], {"tp": 0, "fp": 0, "fn": 0,
                                               "tn": 0}, binding))


# ---------------------------------------------------------------------------
# invariance, anchors and the immutable inputs
# ---------------------------------------------------------------------------

def _successor_path():
    return os.path.join(PA.PHASE4_ROOT, "successor", "package",
                        "CORRECTED_RESULTS.json")


def _mutated_package(workdir, name, mutate):
    """A copy of the successor package with one value damaged."""
    import p4_invariance as INV                                  # noqa: F401
    payload = PA.load_json(_successor_path(), dict)
    mutate(payload)
    path = os.path.join(workdir, name + ".json")
    PA.write_json(path, payload)
    return path


def mut_non_random_estimand_moved(workdir):
    """An estimand that does not read the random detector changed."""
    def mutate(payload):
        for cell in payload["cells"]:
            for estimand in cell["estimands"]:
                if estimand["estimand_id"] == "EST-F3-RND-01":
                    continue
                for node in estimand["arms"].values():
                    node["value"] = -1.0
                    return
    path = _mutated_package(workdir, "MUT-invariance", mutate)
    result = _import_invariance().compare(
        os.path.join(PA.HISTORICAL_PACKAGE, "CORRECTED_RESULTS.json"), path,
        "mutant")
    return _detectors(result["findings"])


def mut_repair_did_not_reach_output(workdir):
    """The random estimand comes back byte-identical to the historical one."""
    historical = PA.load_json(
        os.path.join(PA.HISTORICAL_PACKAGE, "CORRECTED_RESULTS.json"), dict)
    index = {}
    for cell in historical["cells"]:
        for estimand in cell["estimands"]:
            for arm, node in estimand["arms"].items():
                index[(cell["cell"], estimand["estimand_id"], arm)] = node

    def mutate(payload):
        for cell in payload["cells"]:
            for estimand in cell["estimands"]:
                if estimand["estimand_id"] != "EST-F3-RND-01":
                    continue
                for arm in list(estimand["arms"]):
                    key = (cell["cell"], estimand["estimand_id"], arm)
                    if key in index:
                        estimand["arms"][arm] = copy.deepcopy(index[key])
    path = _mutated_package(workdir, "MUT-repair-effect", mutate)
    result = _import_invariance().compare(
        os.path.join(PA.HISTORICAL_PACKAGE, "CORRECTED_RESULTS.json"), path,
        "mutant")
    return _detectors(result["findings"])


def mut_anchor_mismatch(workdir):
    """The scored alarm count no longer reproduces the plan's audit anchor."""
    def mutate(payload):
        for cell in payload["cells"]:
            for estimand in cell["estimands"]:
                if estimand["estimand_id"] != "EST-F3-RND-01":
                    continue
                node = estimand["arms"].get("precision")
                if node and node.get("denominator"):
                    node["denominator"] = node["denominator"] + 1
    path = _mutated_package(workdir, "MUT-anchor", mutate)
    result = _import_invariance().compare(
        os.path.join(PA.HISTORICAL_PACKAGE, "CORRECTED_RESULTS.json"), path,
        "mutant")
    return _detectors(result["findings"])


def _import_invariance():
    import p4_invariance
    return p4_invariance


def mut_corpus_substituted(_workdir):
    """A raw input is not the byte the historical manifest recorded."""
    INV = _import_invariance()
    run = dict(next(r for r in PA.corpus()["runs"]), events_sha256="f" * 64)
    findings = [PC.finding("D-P4-CORPUS-IDENTITY-01", problem, run["identity"])
                for problem in PA.verify_run_inputs(run)]
    del INV
    return _detectors(findings)


def mut_historical_package_changed(workdir):
    """The rollback target moved."""
    INV = _import_invariance()
    saved = dict(PA._CACHE.get("historical", {}))                # noqa: SLF001
    try:
        info = PA.historical()
        damaged = dict(info)
        damaged["digests"] = dict(info["digests"])
        damaged["digests"]["CORRECTED_RESULTS.json"] = "a" * 64
        PA._CACHE["historical"] = damaged                        # noqa: SLF001
        return _detectors(INV.check_historical_untouched())
    finally:
        if saved:
            PA._CACHE["historical"] = saved                      # noqa: SLF001


# ---------------------------------------------------------------------------
# RAW — the corpus total, and the scope it was counted over
# ---------------------------------------------------------------------------

def mut_stale_corpus_total(workdir):
    """An artefact keeps the stale total after the raw corpus says otherwise.

    This is the defect the Hermes audit found, made permanent: the first round
    stated 9828 and nothing recomputed it, so it survived into the contract, the
    report and the join module's own docstring.
    """
    import p4_rawtotals as RAW

    totals = RAW.derived()
    stale = RAW.claim_line(dict(totals, alarm_rows=totals["alarm_rows"] + 16))
    path = os.path.join(workdir, "STALE_CLAIM.md")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(f"a report that went stale\n\n{stale}\n")
    return _detectors(RAW.check_claims(workdir, totals, ["STALE_CLAIM.md"]))


def mut_no_checkable_total(workdir):
    """An artefact states no canonical total, so nothing can be checked."""
    import p4_rawtotals as RAW

    path = os.path.join(workdir, "NO_CLAIM.md")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("roughly ten thousand alarms, give or take\n")
    return _detectors(RAW.check_claims(workdir, RAW.derived(), ["NO_CLAIM.md"]))


def mut_overglob_scope(_workdir):
    """The total is recounted over a run set that is not the accepted corpus.

    Reproduces the ACTUAL root cause rather than its symptom: the glob
    `*-s*-r0-events.csv` also matches the two illustrative A6s-safe runs, giving
    1202 runs and 9828 alarms. A tally taken over the wrong scope is right about
    nothing, so the guard checks the run set, not just the number.
    """
    import p4_rawtotals as RAW

    runs = list(PA.corpus()["runs"])
    extra = dict(runs[0])
    extra["identity"] = "A6s-safe"
    extra["events_sha256"] = None
    totals = dict(RAW.derived())
    totals["identities"] = [run["identity"] for run in runs] + [extra["identity"]]
    totals["runs"] = len(totals["identities"])
    return _detectors(RAW.check_scope(totals, "over-glob"))


# ---------------------------------------------------------------------------
# SET / IDN — the settlement and this root's own executables
# ---------------------------------------------------------------------------

def _stage_root(workdir, name):
    """A Phase 4 root whose runnables are symlinks and whose JSON is real."""
    import shutil

    root = os.path.join(workdir, name)
    os.makedirs(root)
    for sub in ("tools", "candidate_scorer"):
        source_root = os.path.join(PA.PHASE4_ROOT, sub)
        for base, dirs, files in os.walk(source_root):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for filename in sorted(files):
                source = os.path.join(base, filename)
                relative = os.path.relpath(source, PA.PHASE4_ROOT)
                target = os.path.join(root, relative)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                os.symlink(source, target)
    shutil.copy2(os.path.join(PA.PHASE4_ROOT, "PHASE4_MANIFEST.json"),
                 os.path.join(root, "PHASE4_MANIFEST.json"))
    shutil.copy2(os.path.join(PA.PHASE4_ROOT, PI.INVENTORY_NAME),
                 os.path.join(root, PI.INVENTORY_NAME))
    return root


def _resettle(root, mutate=None, canonical=None, regenerate_inventory=True):
    if regenerate_inventory:
        inventory = PA.write_json(os.path.join(root, PI.INVENTORY_NAME),
                                  PI.build(root))
    else:
        inventory = PA.sha256_file(os.path.join(root, PI.INVENTORY_NAME))
    manifest_path = os.path.join(root, "PHASE4_MANIFEST.json")
    manifest = PA.sha256_file(manifest_path) if os.path.exists(manifest_path) \
        else "0" * 64
    contract = PA.sha256_file(os.path.join(PA.PHASE4_ROOT,
                                           "PHASE4_CONTRACT.json"))
    settlement = PS.build(contract, "PHASE4_MANIFEST.json", manifest, inventory,
                          canonical or [PA.SUCCESSOR_RELATIVE])
    if mutate:
        settlement = mutate(settlement)
    return PA.write_json(os.path.join(root, PS.SETTLEMENT_NAME), settlement)


def _load(root, pin):
    try:
        PS.load(root, pin)
    except PS.SettlementFinding as error:
        return {error.detector}
    return set()


def set_no_pin(workdir):
    root = _stage_root(workdir, "SET-no-pin")
    _resettle(root)
    return _load(root, None)


def set_wrong_pin(workdir):
    root = _stage_root(workdir, "SET-wrong-pin")
    _resettle(root)
    return _load(root, "0" * 64)


def set_absent(workdir):
    root = _stage_root(workdir, "SET-absent")
    digest = _resettle(root)
    os.remove(os.path.join(root, PS.SETTLEMENT_NAME))
    return _load(root, digest)


def set_array_root(workdir):
    import json as _json
    root = _stage_root(workdir, "SET-array-root")
    _resettle(root)
    path = os.path.join(root, PS.SETTLEMENT_NAME)
    with open(path, "w", encoding="utf-8") as handle:
        _json.dump(["not", "an", "object"], handle)
    return _load(root, PA.sha256_file(path))


def set_extra_key(workdir):
    root = _stage_root(workdir, "SET-extra-key")

    def mutate(settlement):
        settlement["convenience_override"] = True
        return settlement
    return _load(root, _resettle(root, mutate))


def set_short_digest(workdir):
    root = _stage_root(workdir, "SET-short-digest")

    def mutate(settlement):
        settlement["old_raw_tree_sha256"] = "deadbeef"
        return settlement
    return _load(root, _resettle(root, mutate))


def set_seal_binding(workdir):
    root = _stage_root(workdir, "SET-seal-binding")

    def mutate(settlement):
        settlement["historical_seal_sha256"] = "b" * 64
        return settlement
    return _load(root, _resettle(root, mutate))


def set_scorer_not_repaired(workdir):
    """The settlement declares the successor was scored by the OLD scorer."""
    root = _stage_root(workdir, "SET-scorer-unrepaired")

    def mutate(settlement):
        settlement["repaired_scorer_sha256"] = \
            settlement["pre_repair_scorer_sha256"]
        return settlement
    return _load(root, _resettle(root, mutate))


def set_two_members(workdir):
    root = _stage_root(workdir, "SET-two-members")

    def mutate(settlement):
        settlement["successor_canonical_paths"] = [
            PA.SUCCESSOR_RELATIVE, "successor/A_SECOND_PACKAGE.json"]
        return settlement
    return _load(root, _resettle(root, mutate))


def idn_scorer_edited(workdir):
    """The candidate SCORER is edited after the inventory was settled."""
    import shutil

    root = _stage_root(workdir, "IDN-scorer-edited")
    _resettle(root)
    target = os.path.join(root, "candidate_scorer", "scoring", "rndjoin.py")
    real = os.path.realpath(target)
    os.remove(target)
    shutil.copy2(real, target)
    with open(target, "a", encoding="utf-8") as handle:
        handle.write("\n# an edit nobody declared\n")
    inventory = PA.sha256_file(os.path.join(root, PI.INVENTORY_NAME))
    return _detectors(PI.verify(root, inventory))


def idn_bytecode(workdir):
    root = _stage_root(workdir, "IDN-bytecode")
    _resettle(root)
    cache = os.path.join(root, "candidate_scorer", "scoring", "__pycache__")
    os.makedirs(cache, exist_ok=True)
    with open(os.path.join(cache, "rndjoin.cpython-313.pyc"), "wb") as handle:
        handle.write(b"\x00\x00\x00\x00")
    inventory = PA.sha256_file(os.path.join(root, PI.INVENTORY_NAME))
    return _detectors(PI.verify(root, inventory))


def idn_inventory_not_settled(workdir):
    root = _stage_root(workdir, "IDN-unsettled")
    _resettle(root)
    return _detectors(PI.verify(root, "0" * 64))


MUTANTS = [
    ("MUT-01-consumer-reads-tmSeq", "D-P4-JOIN-KEY-01", mut_consumer_reads_tmseq),
    ("MUT-02-ordinal-shift-0-based", "D-P4-JOIN-KEY-01", mut_ordinal_shift),
    ("MUT-03-duplicate-ordinal", "D-P4-ORDINAL-DUPLICATE-01",
     mut_duplicate_ordinal),
    ("MUT-04-missing-observation", "D-P4-TIME-WITNESS-01",
     mut_missing_observation),
    ("MUT-05-ordinal-out-of-range", "D-P4-ORDINAL-RANGE-01",
     mut_ordinal_out_of_range),
    ("MUT-06-silent-drop-of-unmatched-rows", "D-P4-CONSERVATION-01",
     mut_silent_drop),
    ("MUT-07-untyped-disposition", "D-P4-DISPOSITION-01",
     mut_missing_ordinal_field),
    ("MUT-08-undeclared-disposition", "D-P4-DISPOSITION-01",
     mut_undeclared_disposition),
    ("MUT-09-oracle-disagreement", "D-P4-ORACLE-AGREEMENT-01",
     mut_oracle_disagreement),
    ("MUT-10-registry-declares-tmSeq", "D-P4-JOIN-KEY-01",
     mut_registry_declares_tmseq),
    ("MUT-11-registry-treats-seq-as-key", "D-P4-JOIN-KEY-01",
     mut_registry_seq_as_key),
    ("MUT-12-oracle-time-witness-ambiguous", "D-P4-ORACLE-AMBIGUOUS-01",
     mut_oracle_ambiguous),
    ("MUT-13-non-random-estimand-moved", "D-P4-INVARIANCE-01",
     mut_non_random_estimand_moved),
    ("MUT-14-repair-did-not-reach-output", "D-P4-REPAIR-EFFECT-01",
     mut_repair_did_not_reach_output),
    ("MUT-15-plan-anchor-mismatch", "D-P4-ANCHOR-01", mut_anchor_mismatch),
    ("MUT-16-corpus-input-substituted", "D-P4-CORPUS-IDENTITY-01",
     mut_corpus_substituted),
    ("MUT-17-historical-package-changed", "D-P4-HISTORICAL-IMMUTABLE-01",
     mut_historical_package_changed),
    ("MUT-18-stale-corpus-total-claim", "D-P4-RAW-TOTAL-01",
     mut_stale_corpus_total),
    ("MUT-19-no-checkable-corpus-total", "D-P4-RAW-TOTAL-01",
     mut_no_checkable_total),
    ("MUT-20-total-counted-over-wrong-scope", "D-P4-RAW-TOTAL-01",
     mut_overglob_scope),
    ("SET-01-no-external-pin", "D-P4-SETTLEMENT-PIN-01", set_no_pin),
    ("SET-02-wrong-external-pin", "D-P4-SETTLEMENT-PIN-01", set_wrong_pin),
    ("SET-03-settlement-absent", "D-P4-SETTLEMENT-PRESENT-01", set_absent),
    ("SET-04-settlement-array-root", "D-P4-SETTLEMENT-MALFORMED-01",
     set_array_root),
    ("SET-05-binding-not-a-digest", "D-P4-SETTLEMENT-MALFORMED-01",
     set_short_digest),
    ("SET-06-settlement-extra-key", "D-P4-SETTLEMENT-KEYS-01", set_extra_key),
    ("SET-07-seal-binding-wrong", "D-P4-SETTLEMENT-BINDING-01", set_seal_binding),
    ("SET-08-successor-scored-by-old-scorer", "D-P4-SCORER-IDENTITY-01",
     set_scorer_not_repaired),
    ("SET-09-successor-set-grows", "D-P4-MEMBERSHIP-SINGLE-01", set_two_members),
    ("IDN-01-candidate-scorer-edited", "D-P4-WRAPPER-EXECUTABLE-IDENTITY-01",
     idn_scorer_edited),
    ("IDN-02-compiled-bytecode", "D-P4-WRAPPER-EXECUTABLE-IDENTITY-01",
     idn_bytecode),
    ("IDN-03-inventory-not-the-settled-one",
     "D-P4-WRAPPER-EXECUTABLE-IDENTITY-01", idn_inventory_not_settled),
]
