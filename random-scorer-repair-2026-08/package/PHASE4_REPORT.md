# Phase 4 — Random scorer P0 repair and successor rescoring

**Status:** CANDIDATE, pending independent Hermes audit.
**Validation verdict:** **PHASE4_CONFORMANT** — 0 residual findings.
**Suite verdict:** GREEN — 29/29 mutants rejected, 21/21 detectors owned.

No new simulation. The immutable raw corpus, the historical corrected package
and the accepted seal are byte-exact; every number below comes from rescoring
bytes that already existed.

---

## 1. The defect, and why it survived review

The producer emits, once per observation on which it fired
(`src/RandomDetector.cc:27`):

```cpp
collector->logEvent("rnd.alarm", {{"n", std::to_string(observations)}});
```

The consumer read a field that does not exist on that row
(`analysis/scoring/families.py:240`):

```python
alarmed = {r["f"].get("tmSeq") for r in events if r["cat"] == "rnd.alarm"}
has_alarm = row["f"].get("seq") in alarmed
```

`tmSeq` is absent from every alarm row, so the key set collapsed to `{None}` and
no observation carrying a `seq` could ever match. **The scorer reported zeros
instead of raising.** The random baseline looked like a detector that never
fires.

It is **two errors, not one**, and fixing only the first would still be wrong:

1. **Wrong field name** — `tmSeq` is not emitted; `n` is.
2. **Wrong unit** — even spelled correctly, a telemetry *sequence number* is not
   an *arrival ordinal*. `seq` is assigned on the spacecraft and skips on
   in-flight loss. Recounted from the raw CSV of the accepted corpus, **`seq`
   equals `n` for not one alarm** — they are never interchangeable, not even
   accidentally:

   ```
   ACCEPTED-CORPUS RAW RANDOM-ALARM ROWS: 9812 over 1200 runs; seq == n in 0
   ```

**Why it survived:** the repository's own reference oracle
(`analysis/tests/reference_scorer.py:297`) carried the **identical** defect. Two
implementations agreed because one had copied the other's mistake, and an oracle
that shares the assumption under test cannot falsify it.

## 2. The join, and how it was proved rather than assumed

`GroundStation::handleTelemetry` logs `tm.recv` and *then* calls
`randomDet->observe()`, inside one call. `observe()` pre-increments
`observations`, so the k-th call carries `n == k` and addresses the k-th
`tm.recv` row of that run.

That reasoning is checkable independently of itself: two rows written inside one
call must share a simulation time.

| check, over the accepted 1200-run corpus | result |
|---|---|
| alarms where the n-th `tm.recv` shares the alarm's instant | **9812 / 9812** |
| alarms with an ordinal out of range | **0** |
| alarms where `seq == n` (i.e. the old unit would have worked) | **0** |

### Correction — the first round stated 9828

The first Phase 4 round put **9828** in the contract, the report and the join
module's docstring. It is wrong, and the arithmetic was never the problem: the
number came from a shell glob `*-s*-r0-events.csv`, which also matches
`A6s-safe-r0-events.csv` and `A6s-safe-large-r0-events.csv` — two illustrative
runs that are **not** in the accepted corpus. That glob gives 1202 runs and 9828
alarms; the accepted corpus is **1200 runs and 9812 alarms**. The scope error
was noted when the glob was written and then allowed to reach the settled
artefacts, because nothing recomputed the figure.

`tools/p4_rawtotals.py` now derives every corpus total by parsing the raw CSV of
exactly the runs the historical `INPUT_MANIFEST` lists. It imports neither the
scorer nor `rndjoin`, so it cannot inherit an assumption from the code it
checks, and it verifies the **run set** as well as the tally — because the
failure mode was scope, not counting. `D-P4-RAW-TOTAL-01` fails the validation
when a stated total disagrees with the recount, when an artefact states no
checkable total at all, or when the recount is taken over the wrong run set.

## 3. Conservation — every raw alarm has one terminal disposition

`raw_alarm_rows == matched + Σ unmatched`, anchored to the **raw log**, not to
the binder's own bookkeeping. A binder that filters unmatched rows balances its
own books perfectly — that is exactly how a silent drop hides — so the raw rows
are recounted and compared.

```
1200 runs   9812 raw alarm rows  ==  9812 matched + 0 unmatched
            0 out-of-range   0 duplicate   0 malformed   0 missing-field
            0 time-inconsistent matches
```

Plan audit anchors reproduced exactly, per scenario per defence cell:

| scenario | plan anchor | scored |
|---|---|---|
| B0 | 455 | 455 |
| A1 | 481 | 481 |
| A2 | 513 | 513 |
| A3 | 513 | 513 |
| A4 | 491 | 491 |

Under the old join this cross-check was **not even expressible**: `tp + fp` was
0, so the precision denominator was undefined.

## 4. What the rescoring changed

145 estimand arms compared against the historical package. **123 invariant, 22
moved, and all 22 are `EST-F3-RND-01`.** Not one non-random estimand moved.

| cell | alarms | precision was | precision now | fpr was | fpr now |
|---|---|---|---|---|---|
| B0-D2 / B0-D3 | 455 | undefined | 0.0 | 0.0 | 0.009270579 |
| A1-D2 / A1-D3 | 481 | undefined | 0.0 | 0.0 | 0.009800326 |
| A2-D2 / A2-D3 | 513 | undefined | 0.0 | 0.0 | 0.010452323 |
| A3-D2 / A3-D3 | 513 | undefined | 0.0 | 0.0 | 0.010452323 |
| A4-D2 / A4-D3 | 491 | undefined | 0.011612739 | 0.0 | 0.010016792 |

The measured false-positive rate now lands on the configured
`alarmProbability = 0.01` (`src/RandomDetector.ned:18`) in every cell. That is
the signature of a correctly scored random baseline, and it is exactly what the
broken join hid by reporting 0.0.

**The substantive correction:** the random detector's precision was previously
*undefined everywhere* — the scorer believed it made no predictions at all. It
is now **0.0** in nine of ten cells and 0.0116 in A4. The random baseline was
materially understated, and the direction matters: a comparison against a
baseline that appears never to fire flatters every real detector.

### Two arms were legitimately allowed not to move

- **`recall`** moved in 2 cells and stayed `null` in 8, with the declared reason
  `no_defined_run_in_cell` on **both** sides. The repair cannot move a quantity
  with no defined run to compute it from.
- **`event_recall`** is computed by `state.credit_alarms(alarm_times,
  effect_events)` (`scoring/state.py:101`), which takes alarm **times** and never
  reads the join key. It was correct before the repair, and the contract
  requires it to stay identical — **if it had moved, that would be the finding**
  (`D-P4-INVARIANCE-01`).

## 5. The repair is minimal, and declared line by line

Candidate scorer tree: **51 files — 1 new, 4 modified, 46 unchanged, 0 removed,
0 undeclared changes.**

| file | state | change |
|---|---|---|
| `scoring/rndjoin.py` | NEW | field registry, join key, dispositions, conservation |
| `scoring/families.py` | MODIFIED | `direct_detection_rnd` joins on the ordinal; block carries its conservation. One import line. |
| `scoring/output.py` | MODIFIED | `scorer_digest` split so the candidate tree is digested by the **accepted** recipe; behaviour preserved |
| `build_corrected_package_v1.py` | MODIFIED | explicit read-only `SIM`, digest from the candidate root, scorer pin moved to the repaired digest |
| `tests/reference_scorer.py` | MODIFIED | `_score_rnd` re-derived from the **time witness**; it previously carried the identical defect |

There is **no side scorer**. The repaired `families.py` is the one and only
scoring path, and the successor was produced by it.

**Why the repair is in a candidate tree.** The v7 `analysis/` tree is historical
authority. Repairing it in place would have moved a pinned artefact before the
accepting party had seen the repair. The candidate is a full copy; the v7 tree's
scorer digest is verified still `de16e29c…` on every validation run, under
`D-P4-HISTORICAL-IMMUTABLE-01` — so "the repair went into the candidate, not in
place" is checked, not promised.

## 6. Independent oracle

`tools/p4_reference_oracle.py` never reads `n` and never counts positions. It
pairs each alarm with the observation sharing its instant — the **clock**, where
production uses the **ordinal**. They share the raw file and nothing else, so
agreement is evidence rather than an echo. Where two observations share an
instant the oracle **refuses** the row instead of guessing
(`D-P4-ORACLE-AMBIGUOUS-01`).

Over all 1200 runs the two derivations agree on the alarmed set and on
`tp/fp/fn/tn`, with zero ambiguous rows.

## 7. Mutants — 29, all rejected by their owning detector

The five the plan names by hand, all REJECTED:

| mutant | owning detector |
|---|---|
| `MUT-01-consumer-reads-tmSeq` | `D-P4-JOIN-KEY-01` |
| `MUT-02-ordinal-shift-0-based` | `D-P4-JOIN-KEY-01` |
| `MUT-03-duplicate-ordinal` | `D-P4-ORDINAL-DUPLICATE-01` |
| `MUT-04-missing-observation` | `D-P4-TIME-WITNESS-01` |
| `MUT-05-ordinal-out-of-range` | `D-P4-ORDINAL-RANGE-01` |

MUT-01 is the original defect **executed**, not described: it credits 0
observations while the fixture run carries 10 raw alarm rows. Plus 24 more
covering silent drops, untyped dispositions, oracle disagreement and ambiguity,
invariance, repair-reached-output, the plan anchors, corpus substitution,
historical mutation, the settlement family and executable identity.

One mutant escaped during construction and was fixed rather than reclassified:
`MUT-12` duplicated an arbitrary observation, creating an ambiguity nothing ever
consulted. It now duplicates an **alarmed** observation.

## 8. Fixture

`fixtures/RND_ALARM_REGRESSION_FIXTURE.json` — real CSV lines copied byte-for-byte
from `A1-D3-s00-r0` at recorded source indices, with the run's manifest digest.
Copied, not written: a hand-authored fixture would have reproduced the very
assumption under test. It carries the three preconditions that made the failure
silent — alarm rows have no `tmSeq`, observation rows do have `seq`, and `seq`
never equals the ordinal.

## 9. Determinism and integrity

The successor package was built twice: **all six files byte-identical**.

| artefact | result |
|---|---|
| `results-v2-corrected/` (rollback target, 6 files) | BYTE-EXACT |
| accepted seal `5c575f3c…` | BYTE-EXACT |
| historical v7 scorer `de16e29c…` | BYTE-EXACT |
| `results/` raw tree (3726 files) | BYTE-EXACT, `09893fc4…` |
| `results-v2-iss06/` rerun tree (541 files) | BYTE-EXACT, `f7e1d5fe…` |
| corpus inputs verified against `INPUT_MANIFEST` | 1200 / 1200 |

No commit, push, seal or checkpoint.

## 10. Known limits

- The successor is a **candidate**. It does not replace
  `results-v2-corrected/`, which remains the rollback target and is bound in the
  settlement.
- The repair is scoped to one join. `D-P4-INVARIANCE-01` proves nothing else in
  the package moved; it does not revalidate the other estimands' own
  correctness, which is the accepted contract's business and was settled in v7.
- Phase 5 unifies this successor with the Phase 3 causal package. Phase 3 is
  still **RED** on three SP-2 findings, so Phase 5 remains blocked by that, not
  by this phase.
