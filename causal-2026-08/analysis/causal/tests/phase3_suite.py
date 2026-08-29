#!/usr/bin/env python3
"""phase3_suite.py -- the Phase 3 test gate.

Written BEFORE the deterministic pair injectors exist, so its first run is the
RED evidence and its last run is the GREEN evidence.  The assertions do not
move between those two runs; only the implementation does.

Three families, and the separation matters:

  SRC-*   static tests over the REAL C++ sources.  They name the defect the
          accepted contract names -- a random branch where a deterministic
          injector is required, a missing hook -- and they read the same files
          the compiler reads.  No fixture.

  RUN-*   behavioural tests that EXECUTE the pilot cell with the real OMNeT++
          executable and assert over the producer's own hash-chained CSV.  The
          rows are parsed by `rawlog`, which is the exact inverse of
          Collector::serialise, so a test cannot pass against a shape the
          producer does not emit.

  ISO-*   truth-isolation and leakage negatives.  These hold the raw observable
          evidence fixed, mutate truth labels and scenario/config names, and
          require the prediction not to move.

Usage:
    python3 phase3_suite.py --stage red  --out <dir>
    python3 phase3_suite.py --stage green --out <dir>
    python3 phase3_suite.py --only RUN-SP-1-attack
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import sys
import tempfile
import traceback

sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, PKG)

import authority          # noqa: E402
import canonical          # noqa: E402
import inventory          # noqa: E402
import rawlog             # noqa: E402
import runcell            # noqa: E402

SIM_ROOT = os.path.abspath(os.path.join(PKG, "..", ".."))
SRC = os.path.join(SIM_ROOT, "src")

_TESTS = []
_RUN_CACHE = {}


def test(name, requirement):
    def wrap(function):
        _TESTS.append({"fn": function, "name": name, "requirement": requirement})
        return function
    return wrap


class Failure(AssertionError):
    pass


def require(condition, message):
    if not condition:
        raise Failure(message)


def source(filename):
    with open(os.path.join(SRC, filename), encoding="utf-8") as handle:
        return handle.read()


def strip_comments(text):
    """Comments describe intent; only code can implement a mechanism."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def body_of(text, signature):
    """The brace-balanced body of one function, or '' when it does not exist."""
    start = text.find(signature)
    if start < 0:
        return ""
    brace = text.find("{", start)
    if brace < 0:
        return ""
    depth, index = 0, brace
    while index < len(text):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[brace:index + 1]
        index += 1
    return text[brace:]


# ---------------------------------------------------------------------------
# cell execution, shared across the behavioural tests
# ---------------------------------------------------------------------------

def cell_of(run_id):
    for cell in inventory.full_inventory():
        if cell["run_id"] == run_id:
            return cell
    raise Failure(f"{run_id} is not in the derived pilot inventory")


def observed(run_id, outroot=None):
    """Runs the cell once per process and returns its parsed real output."""
    if run_id not in _RUN_CACHE:
        root = outroot or os.environ.get("PHASE3_RUN_ROOT") or \
            tempfile.mkdtemp(prefix="phase3-cell-")
        directory = os.path.join(root, run_id)
        result = runcell.run(cell_of(run_id), directory)
        events = rawlog.read_events(result["events"])
        rawlog.verify_chain(events)
        truth = rawlog.read_truth(result["truth"])
        _RUN_CACHE[run_id] = {
            "events": events,
            "canonical": canonical.canonical_events(events, run_id),
            "result": result,
            "truth": truth,
        }
    return _RUN_CACHE[run_id]


def target_truth(run_id, expected_class):
    rows = [t for t in observed(run_id)["truth"]
            if t["fields"].get("kind") == "intervention"]
    require(len(rows) == 1,
            f"exactly one intervention truth row required, found {len(rows)}")
    row = rows[0]
    require(row["fields"].get("intervention_class") == expected_class,
            f"intervention class {row['fields'].get('intervention_class')!r} "
            f"!= {expected_class!r}")
    return row


def canonical_of(run_id):
    return observed(run_id)["canonical"]


def cat(run_id, category):
    return [e for e in canonical_of(run_id) if e["category"] == category]


def first_pass_start(run_id):
    starts = cat(run_id, "pass.start")
    require(starts, "no pass.start event in the run")
    return starts[0]["time"]


def declared_onset(pair_id):
    contract = authority.contract()
    for pair in contract["pair_intervention_registry"]["pairs"]:
        if pair["pair_id"] == pair_id:
            return pair["onset_offset_s"]
    raise Failure(f"no pair {pair_id}")


# ===========================================================================
# SRC -- the mechanisms the accepted operational_closure requires
# ===========================================================================

@test("SRC-SP-1-attack-deterministic-tamper",
      "SP-1 attack: deterministic tamper-only injector, no drop/delay branch, "
      "no random gate on the causal path")
def _src_sp1_attack():
    text = strip_comments(source("OnPathAttacker.cc"))
    body = body_of(text, "void OnPathAttacker::causalDownlink")
    require(body, "OnPathAttacker::causalDownlink does not exist: the SP-1 "
                  "attack path is still the random drop/delay/tamper branch "
                  "(OnPathAttacker.cc:287-304)")
    require("uniform(" not in body and "intuniform(" not in body,
            "the causal downlink path draws a random number; the accepted "
            "contract requires a deterministic tamper-only injector")
    require("setBatteryVoltage" in body,
            "the causal downlink path never modifies batteryVoltage")


@test("SRC-SP-1-fault-sensor-bias-hook",
      "SP-1 fault: onboard sensor-bias term applied BEFORE the packet is written")
def _src_sp1_fault():
    text = strip_comments(source("CubeSat.cc"))
    body = body_of(text, "void CubeSat::generateTelemetry")
    require(body, "CubeSat::generateTelemetry not found")
    require("sensorBias" in body,
            "CubeSat::generateTelemetry adds only zero-mean noise "
            "(CubeSat.cc:120); no sensor-bias term exists")
    bias_index = body.find("sensorBias")
    write_index = body.find("setBatteryVoltage")
    require(0 <= bias_index < write_index,
            "the sensor bias is not applied before the packet field is written")


@test("SRC-SP-2-fault-command-free-degradation",
      "SP-2 fault: setDischargeRate reachable WITHOUT an accepted command")
def _src_sp2_fault():
    text = strip_comments(source("CubeSat.cc"))
    body = body_of(text, "void CubeSat::applyCausalDegradation")
    require(body, "CubeSat::applyCausalDegradation does not exist: dischargeRate "
                  "is reachable only through the CMD_UPDATE path "
                  "(CubeSat.cc:205-206), which would manufacture the attack "
                  "arm's own decisive evidence in the fault arm")
    require("setDischargeRate" in body,
            "the degradation injector never calls PowerModel::setDischargeRate")
    require("Telecommand" not in body and "tc.accept" not in body,
            "the command-free degradation path touches the telecommand path")


@test("SRC-SP-3-logical-alarm-link-fields",
      "SP-3: the logical d3.alarm publishes linkCmdId and linkSeq, with an "
      "explicit null when no command caused the state")
def _src_sp3():
    text = strip_comments(source("Twin.cc"))
    require("linkCmdId" in text and "linkSeq" in text,
            "Twin.cc publishes no linkCmdId/linkSeq on the logical channel; "
            "the accepted feature registry marks both PHASE 3 REQUIRED NEW FIELDS")
    body = body_of(text, "void Twin::emitAlarm")
    require(body, "no single alarm-emission path exists to carry the linkage")
    require("linkCmdId" in body and "linkSeq" in body,
            "the alarm emission path does not carry linkCmdId/linkSeq")
    require('"null"' in body,
            "no explicit-null linkage is emitted; an absent field is not an "
            "explicit null and the fault signature is is_null, not absence")


@test("SRC-SP-3-per-channel-alarm-rows",
      "d3.alarm is emitted once PER BREACHED CHANNEL so alarms_physical and "
      "alarms_logical can both exist on one observation")
def _src_alarm_rows():
    text = strip_comments(source("Twin.cc"))
    body = body_of(text, "void Twin::observeTelemetry")
    require(body, "Twin::observeTelemetry not found")
    require("emitAlarm" in body,
            "the twin still writes ONE d3.alarm row with a single winning "
            "channel, so a physical breach hides the logical alarm that SP-2's "
            "required_context_evidence (F-D3-LINK-CMDID) depends on")


@test("SRC-SP-4-attack-delay-only",
      "SP-4 attack: delay-only injector, deterministic target, no drop branch")
def _src_sp4_attack():
    text = strip_comments(source("OnPathAttacker.cc"))
    body = body_of(text, "void OnPathAttacker::causalDownlink")
    require(body, "no causal downlink injector exists")
    require("sendDelayed" in body,
            "the causal downlink path never delays the target observation")
    require("delete tm" not in body,
            "the causal downlink path still contains a drop branch; a dropped "
            "packet produces no arrival and is not the SP-4 observable")


@test("SRC-SP-4-fault-store-and-forward",
      "SP-4 fault: the link BUFFERS and RE-DELIVERS the same observation; a "
      "plain drop is a different observable")
def _src_sp4_fault():
    text = strip_comments(source("SpaceLink.cc"))
    body = body_of(text, "bool SpaceLink::causalCoverageGap")
    require(body, "SpaceLink::causalCoverageGap does not exist; the link drops "
                  "rather than buffers and no benign path re-delivers a late "
                  "observation")
    require("sendDelayed" in body,
            "the coverage gap never RE-DELIVERS the held observation; a plain "
            "drop produces no arrival and is a different observable")
    require("getDelayTarget" in body,
            "the re-delivery is not driven by the same declared delay as the "
            "attack arm, so the two arms would not match by construction")
    require('"coverage"' in body,
            "the coverage gap emits no link.drop reason=coverage evidence")


@test("SRC-SP-5-attack-rej-tamper",
      "SP-5 attack: on-path tamper extended to the telemetry payload field rej")
def _src_sp5_attack():
    text = strip_comments(source("OnPathAttacker.cc"))
    body = body_of(text, "void OnPathAttacker::causalDownlink")
    require(body, "no causal downlink injector exists")
    require("setRejectedCmdCount" in body,
            "the on-path tamper modifies batteryVoltage only and never rej "
            "(OnPathAttacker.cc:306-308)")


@test("SRC-SP-5-fault-ledger-loss",
      "SP-5 fault: genuine onboard rejections paired with deterministic loss of "
      "the corresponding ground-ledger rows")
def _src_sp5_fault():
    text = strip_comments(source("CubeSat.cc"))
    body = body_of(text, "void CubeSat::handleTelecommand")
    require(body, "CubeSat::handleTelecommand not found")
    require("suppressRejectLedger" in body or "ledgerLoss" in body,
            "no injector suppresses the ground-ledger rows of genuine "
            "rejections, so the fault arm cannot produce the matched jump")


@test("SRC-SP-6-attack-telemetry-replay",
      "SP-6 attack: a TELEMETRY frame is replayed byte-identical; the "
      "telecommand replay path may never stand in for it")
def _src_sp6_attack():
    text = strip_comments(source("OnPathAttacker.cc"))
    body = body_of(text, "void OnPathAttacker::replayCapturedTelemetry")
    require(body, "OnPathAttacker::replayCapturedTelemetry does not exist; only "
                  "replayCapturedCommand (a TELECOMMAND replay) is implemented, "
                  "and the accepted contract forbids substituting it")
    require("Telemetry" in body, "the replay does not re-inject a Telemetry frame")
    require('"groundOut"' in body,
            "the replayed frame is not delivered on the downlink gate")
    command_body = body_of(text, "void OnPathAttacker::replayCapturedCommand")
    require(command_body, "the telecommand replay path was removed rather than "
                          "kept apart; the two must remain distinguishable")
    require('"linkOut"' in command_body and '"groundOut"' not in command_body,
            "the telecommand replay now writes to the downlink: the two replay "
            "paths were merged, and the accepted contract forbids a "
            "freshness-rejected command standing in for a telemetry regression")


@test("SRC-SP-6-fault-reorder-buffer",
      "SP-6 fault: a benign reordering buffer delivers an earlier-sent frame "
      "for the FIRST time after later ones")
def _src_sp6_fault():
    text = strip_comments(source("SpaceLink.cc"))
    body = body_of(text, "bool SpaceLink::causalReorder")
    require(body, "SpaceLink::causalReorder does not exist; the link preserves "
                  "order and no benign path produces a first-delivery regression")
    require("reorderHeld" in body,
            "the reorder path holds no frame, so nothing can be delivered late")


@test("SRC-no-truth-in-packets",
      "R1: no ground-truth field may appear in the packet definitions")
def _src_no_truth_fields():
    # The file's own header names the banned identifiers in prose, to explain
    # why they are banned. Comments are not fields; only the declarations are
    # scanned, exactly as the compiler would see them.
    text = strip_comments(
        open(os.path.join(SRC, "LifesatPackets.msg"), encoding="utf-8").read())
    contract = authority.contract()
    banned = set(contract["truth_registry"]["all_aliases"])
    banned |= {f["truth_field"] for f in contract["truth_registry"]["fields"]}
    banned |= {"isAttack", "attackLabel", "groundTruth", "isMalicious", "tampered"}
    hit = sorted(name for name in banned
                 if re.search(rf"\b{re.escape(name)}\b", text))
    require(not hit, f"packet definitions carry truth field(s) {hit}")


@test("SRC-no-bytecode",
      "executable inventory: no compiled bytecode under the Phase 3 analysis tree")
def _src_no_bytecode():
    found = []
    for base, dirs, files in os.walk(PKG):
        if "__pycache__" in dirs:
            found.append(os.path.join(base, "__pycache__"))
        found.extend(os.path.join(base, f) for f in files if f.endswith(".pyc"))
    require(not found, f"runnable bytecode present: {found[:5]}")


# ===========================================================================
# RUN -- the accepted expected_observable_event_shape, per cell, per arm
# ===========================================================================

@test("RUN-inventory-identities",
      "every declared pilot cell runs and the observed identity set equals the "
      "expected one exactly")
def _run_inventory():
    cells = inventory.full_inventory()
    require(len(cells) == 48,
            f"expected 48 pilot cells derived from the contract, got {len(cells)}")
    # only the twelve inferential cells are executed by the suite; the pilot
    # driver runs all 48 and reconciles there.  This test proves the two lists
    # are the same object.
    ids = {c["run_id"] for c in cells}
    require(ids == inventory.expected_identity_set(),
            "the derived inventory is not stable")
    observed_ids = set()
    for cell in cells:
        if cell["kind"] == "inferential":
            observed(cell["run_id"])
            observed_ids.add(cell["run_id"])
    expected_inferential = {c["run_id"] for c in cells if c["kind"] == "inferential"}
    require(observed_ids == expected_inferential,
            f"missing {sorted(expected_inferential - observed_ids)}")


def _assert_registry_match(run_id, row):
    """The truth row's variable and magnitude ARE the registry's own strings.

    truth_reference_spec.intervention_rule requires exact equality with the pair
    registry entry, and the accepted validator checks it with `!=`. Comparing to
    a number parsed out of the string would test something weaker than the rule.
    """
    contract = authority.contract()
    cell = cell_of(run_id)
    pair = next(p for p in contract["pair_intervention_registry"]["pairs"]
                if p["pair_id"] == cell["pair_id"])
    spec = pair[f"{cell['arm']}_arm"]
    for truth_key, spec_key in (("variable", "manipulated_model_variable"),
                                ("magnitude", "magnitude"),
                                ("units", "units"),
                                ("intervention_class", "truth_intervention_class")):
        require(row["fields"].get(truth_key) == spec[spec_key],
                f"{run_id}: {truth_key} {row['fields'].get(truth_key)!r} != "
                f"registry {spec[spec_key]!r}")


def _assert_onset(run_id, pair_id, expected_class):
    row = target_truth(run_id, expected_class)
    contract = authority.contract()
    pair = next(p for p in contract["pair_intervention_registry"]["pairs"]
                if p["pair_id"] == pair_id)
    arm_key = f"{cell_of(run_id)['arm']}_arm"
    require(row["fields"].get("units") == pair[arm_key]["units"],
            f"unit {row['fields'].get('units')!r} != registry "
            f"{pair[arm_key]['units']!r}")
    # SP-6 is the one pair whose operational_closure states its own onset rule -- # "the third received observation of the contact" -- instead of the generic
    # offset, and whose fault arm's truth time is explicitly "the delayed
    # frame's send time". Its window is checked by the two SP-6 tests, at the
    # contact position the contract actually names, rather than against an
    # offset the pair overrides.
    if pair_id != "SP-6":
        ps = first_pass_start(run_id)
        require(row["time"] >= ps + declared_onset(pair_id) - 1e-6,
                f"intervention at t={row['time']} precedes the declared onset "
                f"{ps} + {declared_onset(pair_id)}")
    return row


@test("RUN-SP-1-attack", "tm.send{seq,vbat=v0} then tm.recv{seq,vbat=v0+0.15}, "
                         "physical d3.alarm, onboard record untouched, no drop, no delay")
def _run_sp1_attack():
    run_id = "SP-1-attack-0"
    row = _assert_onset(run_id, "SP-1", "telemetry_modification")
    seq = int(row["fields"]["target_seq"])
    sends = {e["fields"]["seq"]: e for e in cat(run_id, "tm.send")}
    recvs = [e for e in cat(run_id, "tm.recv") if e["fields"]["seq"] == seq]
    require(seq in sends, f"no tm.send for target seq {seq}")
    require(len(recvs) == 1, f"target seq {seq} received {len(recvs)} times")
    delta = recvs[0]["fields"]["vbat"] - sends[seq]["fields"]["vbat"]
    require(abs(delta - 0.15) < 1e-9,
            f"transit delta {delta!r} != +0.15 V")
    alarms = [e for e in cat(run_id, "d3.alarm")
              if e["fields"]["tmSeq"] == seq and e["fields"]["channel"] == "physical"]
    require(alarms, f"no physical d3.alarm on the target observation {seq}")
    require(alarms[0]["fields"]["deviationV"] > alarms[0]["fields"]["boundV"],
            "the physical alarm does not breach its own bound")
    others = [e for e in cat(run_id, "tm.send")
              if e["fields"]["seq"] != seq
              and e["fields"]["seq"] in {r["fields"]["seq"] for r in cat(run_id, "tm.recv")}]
    for send in others:
        recv = next(r for r in cat(run_id, "tm.recv")
                    if r["fields"]["seq"] == send["fields"]["seq"])
        require(abs(recv["fields"]["vbat"] - send["fields"]["vbat"]) < 1e-12,
                f"a non-target observation {send['fields']['seq']} was modified")


@test("RUN-SP-1-fault", "tm.send{seq,vbat=v0+0.15} and tm.recv equal to it -- the "
                        "SAME reported deviation, produced onboard")
def _run_sp1_fault():
    run_id = "SP-1-fault-0"
    row = _assert_onset(run_id, "SP-1", "sensor_bias")
    seq = int(row["fields"]["target_seq"])
    sends = {e["fields"]["seq"]: e for e in cat(run_id, "tm.send")}
    recvs = [e for e in cat(run_id, "tm.recv") if e["fields"]["seq"] == seq]
    require(len(recvs) == 1, f"target seq {seq} received {len(recvs)} times")
    require(abs(recvs[0]["fields"]["vbat"] - sends[seq]["fields"]["vbat"]) < 1e-12,
            "the fault arm changed the value in transit; it must not")
    alarms = [e for e in cat(run_id, "d3.alarm")
              if e["fields"]["tmSeq"] == seq and e["fields"]["channel"] == "physical"]
    require(alarms, "no physical d3.alarm on the target observation")


@test("RUN-SP-2-attack", "tc.accept at onset then the perturbed trajectory and a "
                         "physical alarm; the logical alarm resolves one-to-one")
def _run_sp2_attack():
    run_id = "SP-2-attack-0"
    row = _assert_onset(run_id, "SP-2", "hostile_config")
    _assert_registry_match(run_id, row)
    accepts = cat(run_id, "tc.accept")
    require(accepts, "no accepted command in the attack arm")
    logical = [e for e in cat(run_id, "d3.alarm")
               if e["fields"]["channel"] == "logical"]
    require(logical, "no logical d3.alarm; SP-2 required_context_evidence is "
                     "F-D3-LINK-CMDID and it lives on the logical channel")
    ids = {(a["fields"]["cmdId"], a["fields"]["seq"]) for a in accepts}
    resolved = [a for a in logical
                if (a["fields"].get("linkCmdId"), a["fields"].get("linkSeq")) in ids]
    require(resolved, "no logical alarm resolves one-to-one to an accepted command")


@test("RUN-SP-2-fault", "NO accepted configuration command; the same perturbed "
                        "trajectory; the logical alarm carries an explicit null")
def _run_sp2_fault():
    run_id = "SP-2-fault-0"
    row = _assert_onset(run_id, "SP-2", "degradation")
    _assert_registry_match(run_id, row)
    attack = target_truth("SP-2-attack-0", "hostile_config")
    require(row["fields"]["magnitude"] == attack["fields"]["magnitude"],
            f"the fault arm solved {row['fields']['magnitude']!r} but the attack "
            f"arm solved {attack['fields']['magnitude']!r}; both arms must solve "
            f"the SAME equation or the observables are equal only by resemblance")
    for a in cat(run_id, "tc.accept"):
        require(a["fields"].get("type") != 3,
                "the fault arm carries an accepted CMD_UPDATE: it manufactured "
                "the attack arm's own decisive evidence")
    logical = [e for e in cat(run_id, "d3.alarm")
               if e["fields"]["channel"] == "logical"]
    require(logical, "no logical d3.alarm in the fault arm")
    require(any(a["fields"].get("linkCmdId", "absent") is None for a in logical),
            "no logical alarm carries an EXPLICIT null link; absence is not null")


@test("RUN-SP-3-attack", "logical alarm whose linkCmdId/linkSeq resolve ONE-TO-ONE "
                         "to an accepted command row")
def _run_sp3_attack():
    run_id = "SP-3-attack-0"
    _assert_onset(run_id, "SP-3", "hostile_config")
    accepts = cat(run_id, "tc.accept")
    logical = [e for e in cat(run_id, "d3.alarm")
               if e["fields"]["channel"] == "logical"]
    require(logical, "no logical d3.alarm")
    ids = [(a["fields"]["cmdId"], a["fields"]["seq"]) for a in accepts]
    hit = [a for a in logical
           if (a["fields"].get("linkCmdId"), a["fields"].get("linkSeq")) in ids]
    require(hit, "no logical alarm names an accepted command")
    key = (hit[0]["fields"]["linkCmdId"], hit[0]["fields"]["linkSeq"])
    require(ids.count(key) == 1,
            f"the named command {key} resolves {ids.count(key)} times, not once")


@test("RUN-SP-3-fault", "logical alarm with an EXPLICIT null linkage and no "
                        "causing command")
def _run_sp3_fault():
    run_id = "SP-3-fault-0"
    _assert_onset(run_id, "SP-3", "store_corruption")
    logical = [e for e in cat(run_id, "d3.alarm")
               if e["fields"]["channel"] == "logical"]
    require(logical, "no logical d3.alarm")
    explicit = [a for a in logical if a["fields"].get("linkCmdId", "absent") is None]
    require(explicit, "no logical alarm carries an explicit null linkCmdId")
    require("linkSeq" in explicit[0]["fields"],
            "linkSeq is absent rather than explicitly null")


@test("RUN-SP-4-attack", "the target observation arrives exactly 30.0 s late while "
                         "other observations of the same contact are delivered")
def _run_sp4_attack():
    run_id = "SP-4-attack-0"
    row = _assert_onset(run_id, "SP-4", "telemetry_withholding")
    seq = int(row["fields"]["target_seq"])
    send = next(e for e in cat(run_id, "tm.send") if e["fields"]["seq"] == seq)
    recvs = [e for e in cat(run_id, "tm.recv") if e["fields"]["seq"] == seq]
    require(len(recvs) == 1, "the delayed observation was not delivered exactly once")
    _assert_sp4_delay(run_id, delay=recvs[0]["time"] - send["time"])
    during = [e for e in cat(run_id, "tm.recv")
              if send["time"] < e["time"] < recvs[0]["time"]]
    require(during, "no other observation was delivered during the delay; the "
                    "attack arm's positive evidence is that the link carried "
                    "traffic while this one was withheld")
    coverage = [e for e in cat(run_id, "link.drop")
                if e["fields"].get("reason") == "coverage"
                and send["time"] <= e["time"] <= recvs[0]["time"]]
    require(not coverage, "a coverage drop overlaps the attack arm's delay interval")


@test("RUN-SP-4-fault", "the SAME observation is re-delivered after the same 30.0 s "
                        "through a coverage interruption, with no other delivery")
def _run_sp4_fault():
    run_id = "SP-4-fault-0"
    row = _assert_onset(run_id, "SP-4", "coverage_buffering")
    seq = int(row["fields"]["target_seq"])
    send = next(e for e in cat(run_id, "tm.send") if e["fields"]["seq"] == seq)
    recvs = [e for e in cat(run_id, "tm.recv") if e["fields"]["seq"] == seq]
    require(len(recvs) == 1,
            "a plain drop is not a delayed packet: the observation must be "
            "RE-DELIVERED exactly once")
    _assert_sp4_delay(run_id, delay=recvs[0]["time"] - send["time"])
    coverage = [e for e in cat(run_id, "link.drop")
                if e["fields"].get("reason") == "coverage"
                and send["time"] <= e["time"] <= recvs[0]["time"]]
    require(coverage, "no link.drop reason=coverage overlaps the delay interval")
    during = [e for e in cat(run_id, "tm.recv")
              if send["time"] < e["time"] < recvs[0]["time"]]
    require(not during, "another observation was delivered inside the coverage "
                        "gap, which would make the attack signature true as well")


@test("RUN-SP-5-attack", "the ground copy of rej jumps by +3 between two "
                         "observations while the onboard copy does not move")
def _run_sp5_attack():
    run_id = "SP-5-attack-0"
    _assert_onset(run_id, "SP-5", "counter_tampering")
    pairs = _rej_pairs(run_id)
    hit = [p for p in pairs if p["gnd_delta"] == 3]
    require(hit, "no +3 ground-counter transition")
    require(hit[0]["src_delta"] == 0,
            f"the onboard counter moved by {hit[0]['src_delta']}, so this is "
            f"not the attack arm's evidence")


@test("RUN-SP-5-fault", "the ground copy jumps by +3 TOGETHER with the onboard "
                        "copy while the ground ledger records none of it")
def _run_sp5_fault():
    run_id = "SP-5-fault-0"
    _assert_onset(run_id, "SP-5", "ledger_loss")
    pairs = _rej_pairs(run_id)
    hit = [p for p in pairs if p["gnd_delta"] == 3]
    require(hit, "no +3 ground-counter transition")
    require(hit[0]["src_delta"] == 3,
            f"the onboard counter moved by {hit[0]['src_delta']}, not +3")
    require(hit[0]["ledger_delta"] != 3,
            "the ground ledger explains the jump; the rejection rows were not lost")


def _assert_sp4_delay(run_id, delay):
    """The delivered age must clear the contract's own STAGE A predicate.

    The predicate is `F-AGE-S >= (nominal_age_s + delay_target_s) - tau_second`.
    The reported age is the ordinary transfer age PLUS the declared 30 s, not a
    bare 30 s: the observation still crosses the same link. Asserting a bare
    30.0 would be asserting something the contract never says, and would fail on
    the physics rather than on the injector.
    """
    contract = authority.contract()
    nominal = contract["nominal_constants"]
    tau = next(t["value"] for t in contract["numeric_tolerance"]["per_unit"]
               if t["symbol"] == "tau_second")
    floor = nominal["nominal_age_s"] + nominal["delay_target_s"] - tau
    require(delay >= floor,
            f"{run_id}: reported age {delay!r} does not reach the declared "
            f"symptom floor {floor!r}")
    require(delay - nominal["delay_target_s"] < 1.0,
            f"{run_id}: reported age {delay!r} exceeds the declared delay by "
            f"more than one second of transfer; something other than the "
            f"declared injector moved this observation")


def _rej_pairs(run_id):
    sends = {e["fields"]["seq"]: e for e in cat(run_id, "tm.send")}
    recvs = sorted(cat(run_id, "tm.recv"), key=lambda e: (e["time"], e["event_id"]))
    rejects = cat(run_id, "tc.reject")
    rows = []
    for first, second in zip(recvs, recvs[1:]):
        s1 = sends.get(first["fields"]["seq"])
        s2 = sends.get(second["fields"]["seq"])
        if s1 is None or s2 is None:
            continue
        rows.append({
            "gnd_delta": second["fields"]["rej"] - first["fields"]["rej"],
            "ledger_delta": (sum(1 for r in rejects if r["time"] <= second["time"])
                             - sum(1 for r in rejects if r["time"] <= first["time"])),
            "src_delta": s2["fields"]["rej"] - s1["fields"]["rej"],
            "time": second["time"],
        })
    return rows


@test("RUN-SP-6-attack", "the third delivery repeats a previously received "
                         "telemetrySeq AND source time, byte-identical")
def _run_sp6_attack():
    run_id = "SP-6-attack-0"
    _assert_onset(run_id, "SP-6", "telemetry_replay")
    units = _first_contact_units(run_id)
    require(len(units) >= 3, f"only {len(units)} deliveries in the target contact")
    third = units[2]
    earlier = units[:2]
    require(any(u["seq"] == third["seq"] and abs(u["send_time"] - third["send_time"]) < 1e-12
                for u in earlier),
            f"the third delivery {third} is not a duplicate of an earlier frame "
            f"{earlier}")
    require(third["seq"] < max(u["seq"] for u in earlier),
            f"the third delivery {third} does not regress below the running "
            f"maximum of {earlier}")


@test("RUN-SP-6-fault", "the third delivery is the FIRST delivery of an "
                        "earlier-sent frame: the sequence regresses but the "
                        "source time has never been observed")
def _run_sp6_fault():
    run_id = "SP-6-fault-0"
    _assert_onset(run_id, "SP-6", "delivery_reordering")
    units = _first_contact_units(run_id)
    require(len(units) >= 3, f"only {len(units)} deliveries in the target contact")
    third = units[2]
    earlier = units[:2]
    require(third["seq"] < max(u["seq"] for u in earlier),
            f"the third delivery {third} does not regress below the running "
            f"maximum of {earlier}")
    require(all(abs(u["send_time"] - third["send_time"]) > 1e-12 for u in earlier),
            "the third delivery repeats a source time already observed; that is "
            "a replay, not a reordering")


def _first_contact_units(run_id):
    starts = [e["time"] for e in cat(run_id, "pass.start")]
    ends = [e["time"] for e in cat(run_id, "pass.end")]
    require(starts and ends, "no contact window in the run")
    begin, finish = starts[0], min(t for t in ends if t > starts[0])
    sends = {}
    for e in cat(run_id, "tm.send"):
        sends.setdefault(e["fields"]["seq"], e)
    units = []
    for e in sorted(cat(run_id, "tm.recv"), key=lambda x: (x["time"], x["event_id"])):
        if not begin <= e["time"] <= finish:
            continue
        send = sends.get(e["fields"]["seq"])
        units.append({"seq": e["fields"]["seq"], "time": e["time"],
                      "send_time": send["time"] if send else None})
    return units


@test("RUN-matched-symptom-tolerance",
      "each pair's two arms hit the same observable target within the frozen "
      "tolerance, by construction rather than by resemblance")
def _run_matching():
    contract = authority.contract()
    tolerances = {t["symbol"]: t["value"]
                  for t in contract["numeric_tolerance"]["per_unit"]}
    checks = []
    # SP-1: identical reported deviation at the ground
    a = _sp1_reported_delta("SP-1-attack-0")
    f = _sp1_reported_delta("SP-1-fault-0")
    checks.append(("SP-1", abs(a - f), tolerances["tau_volt"], a, f))
    # SP-4: identical arrival delay
    a = _sp4_delay("SP-4-attack-0")
    f = _sp4_delay("SP-4-fault-0")
    checks.append(("SP-4", abs(a - f), tolerances["tau_second"], a, f))
    # SP-5: identical ground-observed counter jump
    a = max(p["gnd_delta"] for p in _rej_pairs("SP-5-attack-0"))
    f = max(p["gnd_delta"] for p in _rej_pairs("SP-5-fault-0"))
    checks.append(("SP-5", abs(a - f), tolerances["tau_count"], a, f))
    bad = [c for c in checks if c[1] > c[2]]
    require(not bad, f"arms do not match within tolerance: {bad}")


def _sp1_reported_delta(run_id):
    row = [t for t in observed(run_id)["truth"]
           if t["fields"].get("kind") == "intervention"][0]
    seq = int(row["fields"]["target_seq"])
    alarm = next(e for e in cat(run_id, "d3.alarm")
                 if e["fields"]["tmSeq"] == seq and e["fields"]["channel"] == "physical")
    return alarm["fields"]["deviationV"]


def _sp4_delay(run_id):
    row = [t for t in observed(run_id)["truth"]
           if t["fields"].get("kind") == "intervention"][0]
    seq = int(row["fields"]["target_seq"])
    send = next(e for e in cat(run_id, "tm.send") if e["fields"]["seq"] == seq)
    recv = next(e for e in cat(run_id, "tm.recv") if e["fields"]["seq"] == seq)
    return recv["time"] - send["time"]


@test("RUN-truth-raw-time-agreement",
      "the intervention truth row's time equals the raw event it names")
def _run_truth_time():
    for pair_id in ("SP-1", "SP-4", "SP-5"):
        for arm in ("attack", "fault"):
            run_id = f"{pair_id}-{arm}-0"
            row = [t for t in observed(run_id)["truth"]
                   if t["fields"].get("kind") == "intervention"][0]
            seq = int(row["fields"]["target_seq"])
            send = next(e for e in cat(run_id, "tm.send")
                        if e["fields"]["seq"] == seq)
            require(abs(row["time"] - send["time"]) < 1e-9,
                    f"{run_id}: truth time {row['time']} != tm.send time "
                    f"{send['time']}")


@test("RUN-single-target-no-duplicate",
      "exactly one intervention per run and exactly one targeted observation")
def _run_single_target():
    for cell in inventory.full_inventory():
        if cell["kind"] != "inferential":
            continue
        rows = [t for t in observed(cell["run_id"])["truth"]
                if t["fields"].get("kind") == "intervention"]
        require(len(rows) == 1,
                f"{cell['run_id']}: {len(rows)} intervention rows, expected 1")


@test("RUN-episode-boundaries",
      "every run carries exactly one episode.begin and one episode.end truth "
      "row and the intervention lies between them")
def _run_boundaries():
    for cell in inventory.full_inventory():
        if cell["kind"] != "inferential":
            continue
        rows = observed(cell["run_id"])["truth"]
        begins = [t for t in rows if t["fields"].get("kind") == "episode.begin"]
        ends = [t for t in rows if t["fields"].get("kind") == "episode.end"]
        mids = [t for t in rows if t["fields"].get("kind") == "intervention"]
        require(len(begins) == 1 and len(ends) == 1,
                f"{cell['run_id']}: {len(begins)} begins, {len(ends)} ends")
        require(begins[0]["time"] <= mids[0]["time"] <= ends[0]["time"],
                f"{cell['run_id']}: intervention outside the episode window")


@test("RUN-run-identity-agreement",
      "run_id encodes and agrees with (pair_id, arm, run_seed_index) in every "
      "truth row of the run")
def _run_identity():
    for cell in inventory.full_inventory():
        if cell["kind"] != "inferential":
            continue
        for row in observed(cell["run_id"])["truth"]:
            fields = row["fields"]
            require(fields.get("run_id") == cell["run_id"],
                    f"{cell['run_id']}: truth row carries run_id "
                    f"{fields.get('run_id')!r}")
            require(fields.get("pair_id") == cell["pair_id"],
                    f"{cell['run_id']}: pairId mismatch")
            require(fields.get("arm") == cell["arm"],
                    f"{cell['run_id']}: arm mismatch")
            require(int(fields.get("seed_index", -1)) == cell["run_seed_index"],
                    f"{cell['run_id']}: seed_index mismatch")


# ===========================================================================
# ISO -- truth isolation and scenario-name leakage
# ===========================================================================

@test("ISO-no-truth-in-event-log",
      "no truth field, truth alias, arm name or scenario/config name appears in "
      "any raw EVENT row; the answer key lives only in the truth log")
def _iso_event_log():
    contract = authority.contract()
    banned = set(contract["truth_registry"]["all_aliases"])
    banned |= {f["truth_field"] for f in contract["truth_registry"]["fields"]}
    for cell in inventory.full_inventory():
        if cell["kind"] != "inferential":
            continue
        for event in observed(cell["run_id"])["events"]:
            keys = set(event["fields"])
            hit = keys & banned
            require(not hit, f"{cell['run_id']}: event {event['category']} "
                             f"carries truth field(s) {sorted(hit)}")
            blob = " ".join(f"{k}={v}" for k, v in event["fields"].items())
            for token in (cell["arm"], cell["pair_id"], cell["run_id"], "attack",
                          "fault", "Causal", cell["truth_intervention_class"]):
                require(token not in blob,
                        f"{cell['run_id']}: event {event['category']} leaks "
                        f"{token!r} into the observable record")


@test("ISO-prediction-invariant-under-truth-mutation",
      "mutating truth labels and scenario names while holding the raw "
      "observable evidence fixed does not change any prediction")
def _iso_truth_mutation():
    import episodes as ep
    contract = authority.contract()
    for cell in inventory.full_inventory():
        if cell["kind"] != "inferential":
            continue
        run = observed(cell["run_id"])
        base = ep.build_episode(contract, cell, run["canonical"], run["truth"])
        mutated_truth = copy.deepcopy(run["truth"])
        for row in mutated_truth:
            for key in ("arm", "cause", "intervention_class", "pair_id", "run_id"):
                if key in row["fields"]:
                    row["fields"][key] = "SCRAMBLED"
        mutated_cell = dict(cell, arm=("fault" if cell["arm"] == "attack" else "attack"),
                            run_id=cell["run_id"] + "-MUTATED")
        other = ep.build_episode(contract, mutated_cell, run["canonical"],
                                 mutated_truth, ignore_truth_binding=True)
        require(base["predicted_class"] == other["predicted_class"],
                f"{cell['run_id']}: prediction moved from "
                f"{base['predicted_class']} to {other['predicted_class']} when "
                f"only truth labels changed")
        require(base["abstention_reason_code"] == other["abstention_reason_code"],
                f"{cell['run_id']}: abstention reason moved under truth mutation")


@test("ISO-origin-join-canonical",
      "every source->availability join uses the canonical origin pair the "
      "accepted binding declares")
def _iso_origin():
    import episodes as ep
    contract = authority.contract()
    for cell in inventory.full_inventory():
        if cell["kind"] != "inferential":
            continue
        run = observed(cell["run_id"])
        episode = ep.build_episode(contract, cell, run["canonical"], run["truth"])
        index = {e["event_id"]: e for e in run["canonical"]}
        registry = {f["feature_id"]: f
                    for f in contract["feature_registry"]["features"]}
        for record in episode["evidence_records"]:
            entry = registry[record["feature_id"]]
            source = index[record["source_event_id"]]
            avail = index[record["availability_event_id"]]
            require(source["category"] == entry["source_event_category"],
                    f"{cell['run_id']}: {record['feature_id']} source category "
                    f"{source['category']} != {entry['source_event_category']}")
            require(avail["category"] == entry["availability_event_category"],
                    f"{cell['run_id']}: {record['feature_id']} availability "
                    f"category {avail['category']} != "
                    f"{entry['availability_event_category']}")
            require(abs(record["available_time"] - avail["time"]) < 1e-12,
                    f"{cell['run_id']}: {record['feature_id']} available_time "
                    f"is not the availability event's own time")


# ===========================================================================
# runner
# ===========================================================================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", default="run", choices=["red", "green", "run"])
    parser.add_argument("--out")
    parser.add_argument("--only")
    parser.add_argument("--run-root")
    args = parser.parse_args()

    if args.run_root:
        os.environ["PHASE3_RUN_ROOT"] = args.run_root
        os.makedirs(args.run_root, exist_ok=True)

    selected = [t for t in _TESTS if not args.only or args.only in t["name"]]
    results = []
    for entry in selected:
        try:
            entry["fn"]()
            results.append({"detail": "", "name": entry["name"], "outcome": "PASS",
                            "requirement": entry["requirement"]})
        except Exception as error:            # noqa: BLE001 - report, never hide
            detail = str(error) or error.__class__.__name__
            if not isinstance(error, (Failure, runcell.RunError, rawlog.RawLogError)):
                detail = f"{error.__class__.__name__}: {detail}\n" \
                         f"{traceback.format_exc(limit=3)}"
            results.append({"detail": detail, "name": entry["name"],
                            "outcome": "FAIL", "requirement": entry["requirement"]})

    width = max(len(r["name"]) for r in results)
    for row in results:
        print(f"{row['outcome']:<5} {row['name']:<{width}}")
        if row["outcome"] == "FAIL":
            for line in row["detail"].splitlines()[:4]:
                print(f"        {line}")
    passed = sum(1 for r in results if r["outcome"] == "PASS")
    print(f"\n{args.stage.upper()}: {passed}/{len(results)} passing, "
          f"{len(results) - passed} failing")

    if args.out:
        os.makedirs(args.out, exist_ok=True)
        path = os.path.join(args.out, f"{args.stage}_test_results.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"failing": len(results) - passed, "passing": passed,
                       "results": results, "stage": args.stage},
                      handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
        print(f"wrote {path}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
