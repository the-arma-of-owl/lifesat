# Random-scorer join repair

The random detector is the paper's comparator baseline. Its scored values are
**Table 13**. This directory holds the repair that produced them, the successor
result package they are read from, and a regression test that fails on the
defect.

## The defect

The producer emits one row per alarm, carrying an arrival ordinal and nothing
else (`causal-2026-08/src/RandomDetector.cc:27`):

```cpp
collector->logEvent("rnd.alarm", {{"n", std::to_string(observations)}});
```

The consumer read a field that is not on that row
(`causal-2026-08/analysis/scoring/families.py:240`):

```python
alarmed = {r["f"].get("tmSeq") for r in events if r["cat"] == "rnd.alarm"}
has_alarm = row["f"].get("seq") in alarmed
```

`tmSeq` is absent from every alarm row, so the key set collapsed to `{None}` and
no observation carrying a `seq` could match. The scorer reported zeros instead
of raising, and the random baseline looked like a detector that never fires. The
canonical schema states the row shape that makes this unambiguous:
`analysis/causal/canonical.py:47` declares `"rnd.alarm": {"n": int}`.

It is two errors, and fixing only the first would still be wrong. `tmSeq` is not
emitted; and even spelled correctly, a telemetry **sequence number** is not an
**arrival ordinal**. `seq` is assigned on the spacecraft and skips on in-flight
loss. Over the accepted corpus, `seq` equals `n` for not one alarm:

```
ACCEPTED-CORPUS RAW RANDOM-ALARM ROWS: 9812 over 1200 runs; seq == n in 0
```

The repository's own reference oracle
(`causal-2026-08/analysis/tests/reference_scorer.py:297`) carried the identical
defect, which is why review did not catch it. An oracle that shares the
assumption under test cannot falsify it.

## The repair

`package/candidate_scorer/scoring/rndjoin.py` registers the producer and
consumer fields, joins on the arrival ordinal, and carries a conservation
equation so that a dropped row surfaces as arithmetic rather than as a missing
number. `GroundStation::handleTelemetry` logs `tm.recv` and then calls
`observe()` inside one call, so the k-th alarm addresses the k-th `tm.recv` row
of that run and must share its timestamp. That witness holds for all 9,812
alarms of the accepted corpus with no exceptions.

## Why the historical scorer was not edited in place

`causal-2026-08/analysis/` stays byte-exact. Its composite scorer digest
`de16e29c73b7d2dcac87a114d755e130874eb892215be0947134afcf6f61a4cc` is pinned by
`build_corrected_package_v1.py`, by the acceptance seal and by the historical
package's own `VALIDATION.json`. Editing it in place would break the rebuild of
Tables 11, 12 and 14 and would rewrite an accepted provenance record.

The repaired scorer is therefore a **successor**, digest
`8eaa4663270190ad907e2d5e5fc8ea7b420bd4e1295681517135090cca65c677`. The
historical corrected package survives untouched as the rollback target, and the
successor set is a single member. This is what
`package/PHASE4_SETTLEMENT.json` binds.

## What the repair moved, and what it was not allowed to move

Both scorers were run over the same 1,200 raw records and every estimand arm was
compared:

```
estimand arms compared    : 145
invariant                 : 123
moved                     :  22
undefined both sides      :   8
```

All 22 moved arms are `EST-F3-RND-01`. Tables 8, 9, 10, 11, 12 and 14 are
untouched by the repair. Only Table 13 is affected, and Table 13 already
reports the repaired values: every one of its fifteen cells is bound in the
manuscript provenance record to `successor/PHASE4_SUCCESSOR_RESULT_PACKAGE.json`,
digest `eeb3d738e59dcf9e9db8aae6c7362f1aae3f2f2b40412c54ba8084f8874594fb`.

## Running the regression test

The test needs the raw records and nothing else. It reproduces both recipes
independently of the shipped code, from the producer source rather than from the
scorer, so agreement is a check and not an echo.

```bash
unzip lifesat-raw-matrix-1200.zip          # gives ./results
LIFESAT_RAW=$PWD/results python3 test_rnd_join_regression.py
```

To put the shipped join itself under test, add the scoring package:

```bash
LIFESAT_RAW=$PWD/results \
LIFESAT_SCORER=$PWD/random-scorer-repair-2026-08/package/candidate_scorer \
python3 test_rnd_join_regression.py
```

Expected on the repaired scorer:

```
runs scanned              : 1218
received observations     : 994512
raw random-alarm rows     : 9952
pre-repair recipe credited: 0   (must be 0)
repaired recipe bound     : 9952   (must equal the alarm rows)
seq == n                  : 0   (must be 0)
shipped scoring.rndjoin   : agreed on 1218 of 1218 runs

PASS
```

Pointed at `causal-2026-08/analysis`, the same command exits 1 and reports that
the package carries no `scoring.rndjoin`, which is the pre-repair scorer.

The counts reconcile with the canonical claim above: the raw tree holds the
1,200 selected corpus runs, which carry 9,812 alarm rows, plus 18 single-run
illustrative and calibration runs (`A2v`, `A6`, `A6s`, `A7c`, `A8`, `Calib`,
`phase0-access`) carrying the remaining 140. Restrict the scan to
`*-s??-r0-events.csv` to see 1,200 and 9,812 exactly.

## Running the full Phase 4 validation

`package/tools/validate_phase4.py` is the harness that produced the verdict. It
checks its own executables first, then the settlement, then the byte-exactness
of the historical package, then corpus identity over all 1,200 inputs, then the
join over the whole corpus, then invariance.

It is published **unedited**, because its own closed-set executable inventory is
part of what it verifies: a repair whose scorer can be edited without anything
noticing is not a repair anyone can rely on. One consequence is that
`package/tools/p4_authority.py:29` still carries the absolute working path the
run used:

```python
V7_ROOT = "/home/topya/lifesat_correction_round_v7/simulation"
```

Reproducing that run therefore needs the raw tree, the rerun tree and the
historical corrected package laid out under a directory of that name, or the
line changed, in which case the inventory and the settlement pin must be
rebuilt with `package/tools/p4_identity.py` and `package/tools/write_p4_sums.py`
and the run is no longer the accepted one. The regression test above needs none
of this and is the check a reader should start from.

The recorded verdict is in `package/evidence/PHASE4_VALIDATION.json`:

```
executable identity        : VERIFIED
corpus runs verified       : 1200
raw alarm rows             : 9812   matched 9812   unmatched 0
time-inconsistent matches  : 0
residual findings          : 0
VERDICT                    : PHASE4_CONFORMANT
```

`package/SHA256SUMS.txt` covers all 79 files of the package.
