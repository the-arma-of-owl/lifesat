#!/usr/bin/env python3
"""p4_rawtotals.py — corpus totals RECOUNTED from raw CSV, and the claims checked.

⚠️ WHY THIS EXISTS. The first Phase 4 round stated "9828 of 9828 alarms" as a
corpus fact. It was wrong, and the arithmetic was never the problem — the SCOPE
was. The number came from a shell glob `*-s*-r0-events.csv`, which also matches
`A6s-safe-r0-events.csv` and `A6s-safe-large-r0-events.csv`: two illustrative
runs that are NOT in the accepted 1200-run corpus. 1202 runs, 9828 alarms. The
accepted corpus is 1200 runs and 9812 alarms.

A stale literal survived into the contract, the report and the join module's own
docstring, because nothing recomputed it. So:

  * the total is DERIVED here, by parsing the raw CSV of exactly the runs the
    historical INPUT_MANIFEST lists — never a constant, never a glob;
  * the run set is checked to BE that manifest's identities, so a scope error
    is caught as a scope error rather than surfacing as a wrong number;
  * every artefact that states the total carries one canonical, machine-readable
    claim line, and `check_claims` recomputes and compares.

This module deliberately does not import the scorer or `rndjoin`. It parses the
CSV itself, so it cannot inherit an assumption from the code it is checking.
"""

from __future__ import annotations

import csv
import os
import re
import sys

sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import p4_authority as PA  # noqa: E402
import p4_checks as PC     # noqa: E402

DETECTOR = "D-P4-RAW-TOTAL-01"

# The one canonical, machine-readable form. Every artefact that states the
# corpus total states it exactly like this, and the check below re-derives each
# captured number instead of trusting any of them.
CLAIM_PATTERN = re.compile(
    r"ACCEPTED-CORPUS RAW RANDOM-ALARM ROWS: (\d+) over (\d+) runs; "
    r"seq == n in (\d+)")

CLAIM_TEMPLATE = ("ACCEPTED-CORPUS RAW RANDOM-ALARM ROWS: {rows} over {runs} "
                  "runs; seq == n in {seq_equals_n}")

# Artefacts that make the claim, relative to the Phase 4 root.
CLAIM_ARTEFACTS = (
    "candidate_scorer/scoring/rndjoin.py",
    "PHASE4_CONTRACT.json",
    "PHASE4_REPORT.md",
)

_CACHE = {}


def _parse(path):
    rows = []
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        next(reader)
        for record in reader:
            if len(record) < 4:
                continue
            fields = dict(kv.split("=", 1)
                          for kv in record[3].split(";") if "=" in kv)
            rows.append((record[2], fields))
    return rows


def recount(runs=None):
    """Recount the corpus totals straight from raw CSV.

    `runs` defaults to the historical manifest's run list — the ONLY scope that
    is the accepted corpus. It is a parameter so a mutant can prove that
    counting over a different run set is caught.
    """
    if runs is None:
        runs = PA.corpus()["runs"]
    totals = {"alarm_rows": 0, "observations": 0, "runs": 0, "seq_equals_n": 0}
    identities = []
    for run in runs:
        events_path, _truth = PA.run_paths(run)
        parsed = _parse(events_path)
        observations = [fields for category, fields in parsed
                        if category == "tm.recv"]
        for category, fields in parsed:
            if category != "rnd.alarm":
                continue
            totals["alarm_rows"] += 1
            raw = fields.get("n")
            try:
                ordinal = int(raw)
            except (TypeError, ValueError):
                continue
            if 1 <= ordinal <= len(observations):
                if observations[ordinal - 1].get("seq") == str(ordinal):
                    totals["seq_equals_n"] += 1
        totals["observations"] += len(observations)
        totals["runs"] += 1
        identities.append(run["identity"])
    totals["identities"] = identities
    return totals


def derived(runs=None):
    """Cached recount over the accepted corpus."""
    if runs is not None:
        return recount(runs)
    if "derived" not in _CACHE:
        _CACHE["derived"] = recount()
    return _CACHE["derived"]


def claim_line(totals):
    return CLAIM_TEMPLATE.format(rows=totals["alarm_rows"],
                                 runs=totals["runs"],
                                 seq_equals_n=totals["seq_equals_n"])


def check_scope(totals, location=None):
    """The recount was taken over the manifest's run set, and only that."""
    findings = []
    expected = [run["identity"] for run in PA.corpus()["runs"]]
    observed = totals.get("identities", [])
    if sorted(observed) != sorted(expected):
        extra = sorted(set(observed) - set(expected))[:5]
        missing = sorted(set(expected) - set(observed))[:5]
        findings.append(PC.finding(
            DETECTOR,
            f"the corpus total was recounted over {len(observed)} runs, not the "
            f"{len(expected)} the historical INPUT_MANIFEST lists "
            f"({len(set(observed) - set(expected))} extra {extra}, "
            f"{len(set(expected) - set(observed))} missing {missing}); a total "
            f"taken over the wrong run set is a scope error, not a tally error",
            location))
    return findings


def check_claims(root, totals, artefacts=None, location=None):
    """Every stated corpus total equals the recounted one.

    Each artefact must carry the canonical claim line at least once, and every
    number it captures is compared against the recount. A missing claim is a
    finding too: an artefact that stops stating the total cannot be checked, and
    silently dropping the claim is how the stale one survived.
    """
    findings = []
    expected = (totals["alarm_rows"], totals["runs"], totals["seq_equals_n"])
    for relative in (artefacts if artefacts is not None else CLAIM_ARTEFACTS):
        path = os.path.join(root, relative)
        if not os.path.exists(path):
            findings.append(PC.finding(
                DETECTOR, f"{relative} is absent and cannot state the corpus "
                          f"total", relative))
            continue
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        matches = CLAIM_PATTERN.findall(text)
        if not matches:
            findings.append(PC.finding(
                DETECTOR,
                f"{relative} carries no canonical corpus-total claim; the "
                f"total it states cannot be checked against the raw recount",
                relative))
            continue
        for match in matches:
            observed = tuple(int(value) for value in match)
            if observed != expected:
                findings.append(PC.finding(
                    DETECTOR,
                    f"{relative} claims {observed[0]} raw random-alarm rows "
                    f"over {observed[1]} runs with seq == n in {observed[2]}; "
                    f"the raw CSV of the accepted corpus gives {expected[0]}, "
                    f"{expected[1]}, {expected[2]}", relative))
    return findings


def main():
    totals = derived()
    print(f"runs                 {totals['runs']}")
    print(f"raw alarm rows       {totals['alarm_rows']}")
    print(f"observations         {totals['observations']}")
    print(f"seq == n             {totals['seq_equals_n']}")
    print()
    print(claim_line(totals))
    print()
    scope = check_scope(totals)
    claims = check_claims(PA.PHASE4_ROOT, totals)
    print(f"scope findings       {len(scope)}")
    print(f"claim findings       {len(claims)}")
    for row in scope + claims:
        print(f"  RED {row['detector_id']}  {row['message'][:180]}")
    return 0 if not (scope or claims) else 1


if __name__ == "__main__":
    raise SystemExit(main())
