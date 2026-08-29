# LIFESAT

Simulation code and analysis for a forensic-ready digital twin framework for
cybersecurity in LEO CubeSats.

The framework separates three questions that anomaly detection in a spacecraft
usually merges: whether a command is authentic, whether the received state is
consistent with what the ground approved, and whether a candidate configuration
update is safe before it is uplinked. Contact with a LEO CubeSat is intermittent,
so the twin predicts across the gap and the admissible deviation grows with the
elapsed observation gap rather than staying fixed.

## Repository layout

Two experiment generations produced the results in the paper. They use different
scoring contracts and are kept apart on purpose.

| directory | produces | runs |
|---|---|---|
| `matrix-2026-07/` | the historical detection matrix | 20 cells x 60 seeds = 1,200 |
| `causal-2026-08/` | the cause-discrimination fleet and the twin ablation | 1,116 inferential + 288 robustness = 1,404 |
| `dtaas/` | the on-demand twin instantiation service | deployment demonstration |

Running a matrix cell under `causal-2026-08/` will not reproduce the matrix
numbers, and the reverse is also true. Each directory reproduces its own results.

Both directories hold the tree that actually produced the published results.
For the cause-discrimination fleet this is the frozen producer rather than its
later hardened successor. What a rerun does and does not reproduce, and why the
published digest differs from the recorded one, is set out in
`causal-2026-08/README.md`.

Neither directory reproduces the figures and tables in the paper. The scripts
that built those read from a working layout outside this repository and were
not included.

## Requirements

- OMNeT++ 6.4.0
- INET 4.7.0
- C++17 compiler
- Python 3.10 or later
- `sgp4==2.27`, for the independent orbital-contact check only

## Install from scratch

### Linux

```bash
sudo apt install build-essential clang bison flex perl python3 python3-pip \
                 qtbase5-dev libxml2-dev zlib1g-dev
```

Download OMNeT++ 6.4.0 and INET 4.7.0, then:

```bash
cd omnetpp-6.4.0 && source setenv && ./configure && make -j$(nproc)
cd ../inet-4.7.0  && source setenv && make makefiles && make -j$(nproc)
```

### macOS

```bash
brew install bison flex qt@5 libxml2
```

Then build OMNeT++ and INET as above. Xcode command line tools provide the
compiler.

### Windows

Use WSL2 with Ubuntu and follow the Linux steps. The native Windows toolchain
that ships with OMNeT++ also works, but the analysis scripts assume a POSIX
shell.

## Build and run

```bash
export OMNETPP_ROOT=/path/to/omnetpp-6.4.0
export INET_ROOT=/path/to/inet-4.7.0
cd matrix-2026-07        # or causal-2026-08
source ./setenv
make MODE=release -j$(nproc)
```

Reproduction commands and expected values are in each directory's own README.

## Scope

The evaluation is simulation-based. No result was obtained on flown hardware.
RF propagation realism, flight-software timing and operational ground-station
procedure are not represented. Cause discrimination holds within six predeclared
matched symptom classes, five of which take their episode boundaries from
declared truth, so the evaluation is truth-windowed and is not interpretable as
operational diagnosis.

"Forensic-ready" and "full-lifecycle" are framework-scope labels. They do not
mean that end-to-end technical, organisational or legal forensic readiness was
demonstrated.

## Data

This repository holds source, configuration and the TLE input. It does not hold
run outputs.

The forensic logs, the scored result sets and the accepted contract root that
the analysis pins itself to are archived separately, because they are large and
because several of the pins are digests of files produced by the accepting
party rather than by this code. `causal-2026-08/README.md` lists the
environment variables that point the analysis at them.

The archive reference and its checksums are added here when the deposit is
made.

## License

MIT, see `LICENSE`.

The simulator and its model library are separate works with their own terms:
OMNeT++ 6.4.0 is distributed under the Academic Public License, which is free
for academic and other non-commercial use, and INET 4.7.0 under the LGPL-3.0.
Neither is included here; both are obtained separately, and running this code
requires accepting their terms.

## Citation

See `causal-2026-08/CITATION.cff`.
