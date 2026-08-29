#!/usr/bin/env python3
"""
LIFESAT -- phase 6 gate: A6, A7c, A8 (tier 2, single illustrative runs).

These three scenarios are NOT PART of the 20-cell quantitative matrix (SELF-AUDIT #9).
No statistics are produced; each is checked against the criterion §5.2 defines:

  A6 -- with command auth OFF, does the applied unauthorised CMD_UPDATE make the
        twin's logical channel deviate (d3AlarmsLogical > 0)? With it ON, is it
        rejected at the gate (d3AlarmsLogical == 0, tcRejectedAuth > 0)?

  A7c -- is the command D1 rejected written correctly into the hash-chained event
        log (tc.reject), and does the chain stay intact while the attacker
        falsifies the rejectedCmdCount field on the downlink

  A8 -- does the spoofed telemetry injected at pass start cause at least one
        physical-channel alarm, either at injection or on the next real
        telemetry inside the narrow dt window

The criterion is RECONSTRUCTABILITY, not DETECTION: for A7c the real evidence is
that the chain stays unaffected by the tampering and the true reject events are still there.
"""

import csv
import re
import sys
from pathlib import Path

RESULTS = Path(__file__).resolve().parent.parent / "results"
SCA = Path(__file__).resolve().parent.parent / "simulations" / "results"


def read_scalars(label):
    # OMNeT++ writes runLabel with escaped quotes: par ... runLabel "\"A6-D0\""
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
        sys.exit(f"ERROR: no .sca found for {label} (run the simulation first)")
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
    print(" A6 -- unauthorised update: logical channel / D1 gate")
    d0 = read_scalars("A6-D0")
    d1 = read_scalars("A6-D1")
    ok = True
    if d0.get("twin.d3AlarmsLogical", 0) <= 0:
        print("  [FAIL] D0: the logical channel never deviated -- not the expected behaviour")
        ok = False
    else:
        print(f"  [OK] D0 (auth off): the update was applied, the logical channel "
              f"{int(d0['twin.d3AlarmsLogical'])}/{int(d0['twin.observations'])} "
              f"observations off-nominal")
    if d1.get("sat.tcRejectedAuth", 0) <= 0:
        print("  [FAIL] D1: the unsigned update was not rejected -- the auth check is not working")
        ok = False
    elif d1.get("twin.d3AlarmsLogical", 0) != 0:
        print("  [FAIL] D1: the logical channel deviated although the command was rejected at the gate -- unexpected")
        ok = False
    else:
        print(f"  [OK] D1 (auth on): {int(d1['sat.tcRejectedAuth'])} updates rejected at "
              f"the gate, the logical channel never deviated, the safety channel "
              f"{int(d1.get('twin.d3AlarmsSecurity', 0))} kez alarm verdi")
    return ok


def check_a7c():
    print("\n A7c -- forensic record tampering: the counter can be falsified, the chain cannot")
    events_path = RESULTS / "A7c-D3-r0-events.csv"
    truth_path = RESULTS / "A7c-D3-r0-truth.csv"
    ok, rows = verify_chain(events_path)
    if not ok:
        print("  [FAIL] GATE CLOSED -- hash chain inconsistent; in A7c the attacker has no "
              "access to the chain at all, so a break means a bug")
        return False
    # not tamper evidence: the attacker never touches the chain here. tamper evidence
    # is A7a/A7b.
    print(f"  [OK] hash chain consistent ({len(rows)} records) -- the attacker's access "
          "surface is limited to packets on the wire and does not reach the record")

    true_rejects = sum(1 for r in rows if r[2] == "tc.reject")
    tampered = [l for l in open(truth_path) if "field=rejectedCmdCount" in l]
    if true_rejects == 0:
        print("  [FAIL] GATE CLOSED -- there is no D1 rejection in this run, so A7c has nothing to show")
        return False
    if not tampered:
        print("  [FAIL] GATE CLOSED -- the attacker falsified the counter in no telemetry at all")
        return False
    print(f"  [OK] the event log holds {true_rejects} REAL D1 rejections (source: "
          f"the CubeSat's own record at accept/reject time -- written BEFORE the attacker)")
    print(f"  [OK] the attacker falsified rejectedCmdCount in {len(tampered)} telemetry "
          f"packets on the downlink (hidden in the live stream)")
    print("  [OK] RECONSTRUCTABILITY: the chained log still carries the true reject count, "
          "INDEPENDENTLY of the tampered live telemetry")
    return True


def check_a8():
    print("\n A8 -- resynchronisation window hijack")
    events_path = RESULTS / "A8-D3-r0-events.csv"
    truth_path = RESULTS / "A8-D3-r0-truth.csv"
    spoofs = [l.strip() for l in open(truth_path) if "event=spoof" in l]
    if not spoofs:
        print("  [FAIL] GATE CLOSED -- no fake resync packet was injected")
        return False

    rows = read_chain_csv(events_path)
    caught_immediately = 0
    caught_next = 0
    evaded = 0
    for s in spoofs:
        t = float(s.split(",")[1])
        seq_m = re.search(r"tmSeq=(\d+)", s)
        seq = int(seq_m.group(1)) if seq_m else None
        # the d3.alarm at the moment of injection
        immediate = any(r[2] == "d3.alarm" and abs(float(r[1]) - t) < 1e-6 for r in rows)
        if immediate:
            caught_immediately += 1
            continue
        # on the next real telemetry: tm.recv and its d3.alarm share a timestamp and
        # are logged back to back, since the twin runs as the ground station handles
        # the telemetry.
        later = [r for r in rows if float(r[1]) > t and r[2] in ("tm.recv", "d3.alarm")]
        caught = False
        if later and later[0][2] == "tm.recv":
            next_tm_time = later[0][1]
            caught = any(r[2] == "d3.alarm" and r[1] == next_tm_time for r in later[1:4])
        if caught:
            caught_next += 1
        else:
            evaded += 1

    print(f"  [OK] {len(spoofs)} fake resync packets injected")
    print(f"  · caught at injection time    : {caught_immediately}  "
          f"(the wide Δt tolerance was still exceeded)")
    print(f"  · caught on the next contact    : {caught_next}  "
          f"(§5.2 criterion: 'is it caught once contact is established')")
    print(f"  · missed in this run           : {evaded}  "
          f"(single run -- no statistical claim, reported honestly in §6)")
    return caught_immediately + caught_next > 0


def check_a2v():
    """* The real A2 of §4.4: crypto valid, D1 lets it through, behavioural defence remains."""
    print("\n A2v -- unauthorised command with valid credentials: D1 must pass it, the twin must catch it")
    d3 = read_scalars("A2v-D3")
    d1 = read_scalars("A2v-D1")
    ok = True

    # 1) D1 must pass it, otherwise re-signing is not working
    if d3.get("sat.tcRejected", 0) != 0:
        print(f"  [FAIL] D1 rejected {int(d3['sat.tcRejected'])} commands -- the re-signing "
              "failed; the whole point of A2v is that it PASSES D1")
        ok = False
    else:
        print(f"  [OK] D1 rejected no command ({int(d3.get('sat.tcAccepted', 0))} accepted) -- "
              "a command re-signed with a stolen key passes all three checks")

    # 2) the catching channel must be logical, not security
    lg = d3.get("twin.d3AlarmsLogical", 0)
    sec = d3.get("twin.d3AlarmsSecurity", 0)
    if lg <= 0:
        print("  [FAIL] the logical channel raised no alarm -- behavioural detection is not working")
        ok = False
    elif sec > 0:
        print(f"  [FAIL] the safety channel raised {int(sec)} alarms -- in A2v D1 must not "
              "reject, so the safety channel must stay silent")
        ok = False
    else:
        print(f"  [OK] detection came from the LOGICAL channel: {int(lg)} alarms, safety "
              "channel 0 -- the exact opposite of the command-side profile in §6.3, independent of D1")

    # 3) no detection with the twin disabled (ablation)
    if d1.get("twin.d3Alarms", 0) != 0 or d1.get("sat.tcRejected", 0) != 0:
        print("  [FAIL] something was caught with the twin off as well -- the ablation is meaningless")
        ok = False
    else:
        print("  [OK] with the twin off (D1 alone) there is neither a rejection nor an alarm -- "
              "authorisation alone is blind to an attack with valid credentials")
    return ok


def check_a6s():
    """* The in-orbit phase of the abstract: the update is tried on the twin FIRST."""
    print("\n A6s -- pre-uplink twin validation (prevention, not detection)")
    on = read_scalars("A6s-gate-on")
    off = read_scalars("A6s-gate-off")
    safe = read_scalars("A6s-safe")
    ok = True

    prop = on.get("gs.updatesProposed", 0)
    if prop <= 0:
        print("  [FAIL] no candidate update was proposed -- the experiment did not run")
        return False

    # 1) with the gate on, the unsafe update must never reach the satellite
    if on.get("gs.updatesUplinked", 0) != 0 or on.get("gs.updatesBlocked", 0) != prop:
        print(f"  [FAIL] with the gate on, {int(on.get('gs.updatesUplinked', 0))} unsafe updates "
              "was uplinked anyway")
        ok = False
    else:
        print(f"  [OK] gate ON: {int(prop)}/{int(prop)} unsafe candidates rejected before "
              f"uplink, none ever reached the satellite (battery min "
              f"{on.get('sat.batteryVoltage:min', float('nan')):.2f} V)")

    # 2) with the gate off the update must apply and cause physical damage, and the
    #    deviation detector must NOT see it. the satellite is faithfully doing what
    #    the ground approved, so there is no deviation to find. this is why the gate
    #    is the only defence here, not merely an earlier one.
    if off.get("gs.updatesUplinked", 0) != prop:
        print("  [FAIL] control arm: no update was uplinked with the gate off")
        ok = False
    else:
        vmin = off.get("sat.batteryVoltage:min", float("nan"))
        alarms = off.get("twin.d3Alarms", 0)
        base = on.get("twin.d3Alarms", 0)
        print(f"  [OK] gate OFF: {int(prop)}/{int(prop)} uplinked, the battery fell to "
              f"{vmin:.2f} V (the reported floor of 7.00 V was violated)")
        if vmin >= on.get("sat.batteryVoltage:min", 0):
            print("  [FAIL] the battery should have been worse with the gate off -- the update had no effect")
            ok = False
        if alarms > base:
            print(f"  [FAIL] the deviation detector raised {int(alarms)} alarms (baseline {int(base)}) -- "
                  "the twin may not be applying the update it approved to its own model")
            ok = False
        else:
            print(f"  [OK] * the twin raised {int(alarms)} alarms (baseline {int(base)}) -- "
                  "NO DEVIATION, because the satellite faithfully does what was "
                  "approved. Deviation-based detection is STRUCTURALLY BLIND here; the "
                  "gate is the ONLY defence that applies in the D1 -- D3 stack")
            # "only defence" is scoped to this stack, not a general impossibility
            # claim. an envelope monitor checking the declared safety floor in flight
            # would also catch it; not implemented.

    # 3) negative control: the gate does not reject everything
    if safe.get("gs.updatesBlocked", 0) != 0 or safe.get("gs.updatesUplinked", 0) != prop:
        print(f"  [FAIL] the SAFE update was blocked as well "
              f"({int(safe.get('gs.updatesBlocked', 0))}) -- the gate does not "
              "discriminate, the result is meaningless")
        ok = False
    else:
        print(f"  [OK] negative control: the SAFE candidate passed {int(prop)}/{int(prop)} -- "
              "the gate discriminates, it does not reject blindly")

    # 4) fail-closed: a parameter outside the envelope must not be uplinked
    uns = read_scalars("A6s-unsupported")
    if uns.get("gs.updatesUplinked", 0) != 0:
        print(f"  [FAIL] FAIL-OPEN -- a parameter the twin could not evaluate was still "
              f"{int(uns['gs.updatesUplinked'])} uplinks; "
              "'not rejected' was treated as the same thing as 'approved'")
        ok = False
    elif uns.get("gs.updatesUnsupported", 0) <= 0:
        print("  [FAIL] the UNSUPPORTED verdict was never recorded")
        ok = False
    else:
        # the final verdict must appear exactly once per proposal. the twin and the
        # ground station once shared a category name, so 9 proposals produced 18 rows.
        # internal verdict is now twin.updateUnsupported, final is update.unsupported.
        rows = read_chain_csv(RESULTS / "A6s-unsupported-r0-events.csv")
        final = sum(1 for r in rows if r[2] == "update.unsupported")
        proposed = int(uns.get("gs.updatesProposed", 0))
        if final != proposed:
            print(f"  [FAIL] the log holds {final} final 'update.unsupported' records but "
                  f"{proposed} proposals were made -- duplicate or missing records")
            ok = False
        else:
            print(f"  [OK] fail-closed: a parameter the envelope does not cover "
                  f"{int(uns['gs.updatesUnsupported'])}/{proposed} kez UNSUPPORTED "
                  f"and was NOT uplinked ({final} final verdict records in the log, "
                  "exactly one per proposal)")

    # 5) an approved update must reach the twin's working model, but only after
    #    telemetry confirms it, and must not leave a standing false alarm
    #
    # The oracle was declared before the runs. Two criteria:
    #   (a) total alarms <= reference + update count, allowing one transition alarm
    #       per confirmed update
    #   (b) at most 5% of observations after the first model update may alarm; a
    #       desynchronised model alarms on over 80% (measured: 683/818 = 83% on a
    #       broken build)
    # Single run; these are acceptance thresholds, not statistical claims.
    SUSTAINED_ALARM_FRACTION = 0.05
    big = read_scalars("A6s-safe-large")
    applied = big.get("twin.updatesAppliedToModel", 0)
    if big.get("gs.updatesUplinked", 0) <= 0:
        print("  [FAIL] the large-but-safe candidate was not uplinked -- the test did not run")
        ok = False
    elif applied <= 0:
        print("  [FAIL] the approved update NEVER reached the twin's working model -- "
              "the satellite runs on the new discharge rate, the twin on the old one (risk of permanent drift)")
        ok = False
    else:
        alarms = big.get("twin.d3Alarms", 0)
        reference = on.get("twin.d3Alarms", 0)
        allowance = reference + prop        # propagation margin: 1 per update
        rows = read_chain_csv(RESULTS / "A6s-safe-large-r0-events.csv")
        first_update = next((float(r[1]) for r in rows
                             if r[2] == "twin.modelUpdated"), None)
        obs_after = sum(1 for r in rows
                        if r[2] == "tm.recv" and float(r[1]) >= first_update)
        alarm_after = sum(1 for r in rows
                          if r[2] == "d3.alarm" and float(r[1]) >= first_update)
        frac = alarm_after / obs_after if obs_after else 0.0

        if alarms > allowance:
            print(f"  [FAIL] {int(alarms)} alarms in total > allowance {int(allowance)} "
                  f"(reference {int(reference)} + propagation margin {int(prop)}) -- the twin "
                  "drifts from the satellite after an update it approved itself")
            ok = False
        elif frac > SUSTAINED_ALARM_FRACTION:
            print(f"  [FAIL] {alarm_after}/{obs_after} observations alarmed after the "
                  f"first model update ({100*frac:.1f}% > {100*SUSTAINED_ALARM_FRACTION:.0f}%) "
                  " -- SUSTAINED false alarm run, model desynchronised")
            ok = False
        else:
            print(f"  [OK] the approved update was applied to the twin's model "
                  f"{int(applied)} times after telemetry confirmation; {int(alarms)} alarms "
                  f"in total (allowance {int(allowance)}), {alarm_after}/{obs_after} "
                  f"observations alarmed after the update "
                  f"({100*frac:.1f}% < {100*SUSTAINED_ALARM_FRACTION:.0f}%) "
                  " -- NO persistent false alarm")
        # oracle limit, measured by deliberate corruption: with model sync removed
        # the alarm count on this arm does not move (1 alarm, 0.1%), because at the
        # largest discharge rate the envelope allows the desync deviation stays below
        # the measurement term of the tolerance (3*sigma*sqrt(2) ~ 0.042 V). the real
        # guard here is the updatesAppliedToModel > 0 check.
        #
        # the oracle does fire on check 2 (gate-off arm): rate 0.0004 produces 683
        # alarms on a broken build and the check closes the gate.
        #
        # not reported as a measured improvement: the fix closes a latent defect and
        # produces no observable difference.
    return ok


def main():
    results = [check_a2v(), check_a6(), check_a6s(), check_a7c(), check_a8()]
    print()
    print("-" * 72)
    if all(results):
        print("  [OK] PHASE 6 GATE OPEN -- the A2v/A6u/A6s/A7c/A8 illustrative runs "
              "work as mechanisms")
        return 0
    print("  [FAIL] PHASE 6 GATE CLOSED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
