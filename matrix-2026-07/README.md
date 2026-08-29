# Historical detection matrix

Produces the 20-cell detection results: five scenarios crossed with four defence
layers, 60 seed-indexed seven-day runs per cell, 1,200 runs in total.

## Scenarios and defences

| | |
|---|---|
| `B0` | baseline, no attack |
| `A1` | on-path command-field manipulation |
| `A2` | unsigned forged-command injection |
| `A3` | captured command replayed |
| `A4` | on-path telemetry drop, delay or modification |

| | |
|---|---|
| `D0` | none |
| `D1` | command authorisation (HMAC-SHA256, integrity, freshness) |
| `D2` | D1 plus flow anomaly detection |
| `D3` | D1 plus twin deviation detection |

D2 and D3 are independent variants over a shared D1 base. They are not fused.

A random detector runs in every cell as a triviality baseline. Point-adjusted F1
is excluded: a random detector scores 0.912 on satellite telemetry under that
metric.

## Reproduce

```bash
export OMNETPP_ROOT=/path/to/omnetpp-6.4.0
export INET_ROOT=/path/to/inet-4.7.0
source ./setenv
make MODE=release -j$(nproc)

python3 analysis/calibrate_d2.py          # derives D2 thresholds from B0 only
python3 analysis/run_matrix.py            # 1,200 runs, about 20 minutes
```

`results/d2_thresholds.txt` must exist before any D2 cell runs. FlowDetector
refuses to run uncalibrated, so a threshold fitted to the run being scored
cannot enter by accident.

Output goes to `results/matrix.json`.

### Spot check

A single cell and seed, scored against its own truth file:

```bash
python3 - <<'PY'
import sys; sys.path.insert(0, "analysis")
import run_matrix as RM
from score import score_run
RM.run_cell("A1", "D3", 0, "$INET_ROOT", "A1-D3")
s = score_run("results/A1-D3-s00-r0-events.csv",
              "results/A1-D3-s00-r0-truth.csv", 604800.0)["D3"]
print(s["tp"], s["fp"], s["recall"], s["f05"])
PY
```

Expected: `8 1 1.0 0.9090909090909091`

## Gates

```bash
bash tests/gate.sh 0        # orbital geometry against an independent SGP4
bash tests/gate.sh          # every defined gate
python3 tests/check_label_isolation.py
```

`check_label_isolation.py` scans the detector sources and packet definitions for
any path to the answer key. Ground truth is written only through
`Collector::recordGroundTruth()`, on a path the detectors cannot reach.

## Layout

```
src/          simulation modules
simulations/  network and ini configuration, TLE input
analysis/     scoring, calibration, checks, reporting
tests/        phase gates, label isolation, crypto vectors
```

## Notes

Detector outputs are reported in their native units. D3 scores received
telemetry observations, D2 scores 60 s flow windows. The two are not ranked
against each other.

At the fixed cap of 60 seeds, 2 of 5 interval-carrying A1-D3 estimand arms did
not reach the declared 5% relative half-width objective. This is reported as an
unmet precision objective rather than restated as achieved.
