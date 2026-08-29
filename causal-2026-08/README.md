# Cause-discrimination fleet

Produces the matched attack-versus-fault evaluation and the twin ablation:
1,116 inferential runs and 288 robustness runs, 1,404 in total, across six
predeclared symptom classes.

## Relationship to the published results

This is the tree the accepted fleet was run on, with two qualifications a
reader should have before relying on it.

The fleet's production record is reproduced at
`provenance/PRODUCTION_DIGESTS.json`. Its `producing_code_tree_digest` names
the source tree the 1,404 runs executed on. **This directory does not carry
that digest**: comments, docstrings and console messages were translated from
Turkish to English before release, which changes the bytes of `src/` and so
changes its digest. The behaviour is unchanged, and that was checked rather
than assumed: twelve cells covering all six symptom pairs and both arms were
rerun from this tree and from the untranslated one, and the forensic logs are
byte-identical, 24 files out of 24.

Against the accepted fleet output itself, the same twelve cells reproduce 20 of
24 files byte for byte. The four that differ are the two `SP-2` runs, whose
onset was moved by an amendment to the experiment contract that the fleet
driver applies at run time. Neither the driver nor the amendment is part of
this repository, so a rerun driven from the base contract places the `SP-2`
episode later. The untranslated tree produces exactly the same four files, so
this is a missing input rather than a difference in the code.

## The sealed contract package

The scoring contract, the rescore decision matrix and the rerun authorisation
dossier are **not** in this repository. They are deposited with the run
artefacts.

The reason is that their identity is the digest of their bytes. Each is bound
by a checksum manifest, each names the digests of the others, and the analysis
code here pins the contract digest directly
(`analysis/tests/contract_oracle.py`). Re-encoding them in any way, including
editing prose, breaks that chain, so they are published exactly as accepted
rather than reformatted to match this repository. Their two verification
scripts additionally pin the source tree the correction round was executed on,
which is a third tree, archived alongside them.

The same applies to the accepted tools package (`causal_core.py` and its
siblings), which the episode and generator-closure analyses import. It is bound
by digest in the same way and is deposited alongside the contract.

Point both at the deposit to run the parts that need them:

```bash
export LIFESAT_SPECS=/path/to/specs-sealed
export LIFESAT_TOOLS=/path/to/tools-accepted
python3 analysis/tests/run_red_tests.py
```

Without them, the code that needs them stops with a message saying so rather
than running on a substitute. The simulation itself, the phase gates, the R1
label-isolation check and the crypto vectors need neither.

## Four falsifiability rules

The rules answer the objection that a simulation study can print whatever it
likes. Each phase gate checks them.

| | |
|---|---|
| **R1** | Detectors cannot see the ground-truth label. The label is never carried in a packet; the attacker calls `Collector::recordGroundTruth()` directly and there is no code path back. Checked by `tests/check_label_isolation.py` |
| **R2** | The contact geometry is not invented. A real TLE (FUNCUBE-1) is propagated with SGP4 and compared against an independent implementation (`analysis/verify_access.py`) |
| **R3** | The crypto is real. SHA-256 and HMAC-SHA256 are verified against the FIPS 180-4 and RFC 4231 test vectors (`tests/crypto/run.sh`) |
| **R4** | Negative controls are mandatory. A random detector (p = 0.01) runs in every cell; if D3 does not beat it by a clear margin the result cannot be published |

## Symptom classes

Six matched pairs, each with an attack arm and a fault arm producing the same
observable:

| | |
|---|---|
| `SP-1` | battery decline |
| `SP-2` | digest mismatch |
| `SP-3` | telemetry value offset |
| `SP-4` | contact-start inconsistency |
| `SP-5` | counter jump |
| `SP-6` | telemetry loss or delay |

Three robustness arms probe the decision rule outside its support: model
mismatch, sensor error, and an unmodelled third cause.

## Build

```bash
export OMNETPP_ROOT=/path/to/omnetpp-6.4.0
export INET_ROOT=/path/to/inet-4.7.0
source ./setenv
make MODE=release -j$(nproc)

python3 -m venv .venv                                  # for the R2 gate only
./.venv/bin/pip install -r ../requirements.txt
```

## Run

```bash
python3 analysis/causal/runpilot.py       # writes to $LIFESAT_PILOT_ROOT
bash tests/gate.sh                        # phase gates
```

Paths are read from the environment with repository-relative defaults:

| variable | default |
|---|---|
| `LIFESAT_PILOT_ROOT` | `runs/pilot` |
| `LIFESAT_ACCEPTED_ROOT` | `runs/accepted` |
| `LIFESAT_TOOLS` | `tools/` (archived separately, see below) |
| `LIFESAT_SEAL_DIR` | `specs/seal/` |
| `LIFESAT_SPECS` | `specs/` (see below; the package is archived separately) |

The accepted root holds the contract and the membership settlement the analysis
pins itself to. It is distributed with the run artefacts rather than with the
source, because the pins are digests of files the accepting party produced.

## Expected values

| quantity | value |
|---|---|
| decisive coverage, full evidence | 1,388 / 1,404 |
| decisive coverage, twin evidence withheld | 702 / 1,404 |
| SP-1, SP-2, SP-3 without twin evidence | 0 / 234 each |
| SP-4, SP-5, SP-6 without twin evidence | 234 / 234 each |
| unsafe-confident errors, all conditions | 0 |
| RB-third-cause, without twin | 48 / 96 decisive |
| RB-third-cause, with twin | 80 / 96 decisive, every one wrong by construction |

The last row is a negative result and is reported as one. Withholding twin
evidence moves episodes to abstention rather than to confident error, but the
twin also increases decisiveness where the declared model does not match the
episode.

## Tests

```bash
python3 tests/check_label_isolation.py            # rule R1
bash tests/crypto/run.sh                          # rule R3
python3 -m unittest -v analysis.tests.test_green_02_semantic_guards
bash tests/gate.sh

# with the sealed contract package present:
LIFESAT_SPECS=/path/to/specs-sealed python3 analysis/tests/run_red_tests.py
LIFESAT_SPECS=/path/to/specs-sealed python3 /path/to/specs-sealed/validate_contract.py /path/to/specs-sealed
```
