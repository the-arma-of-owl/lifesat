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

### 1. System packages

Debian and Ubuntu:

```bash
sudo apt install build-essential clang bison flex perl python3 python3-pip \
                 python3-venv libxml2-dev zlib1g-dev
```

macOS:

```bash
brew install bison flex libxml2
```

Xcode command line tools provide the compiler. On Windows, use WSL2 with
Ubuntu and follow the Debian steps; the native toolchain that ships with
OMNeT++ also works, but the analysis scripts assume a POSIX shell.

Nothing here needs the OMNeT++ IDE or the Qt graphical environment. The runs
are launched with `Cmdenv`, so the `-core` distribution is enough and Qt is not
a dependency.

### 2. OMNeT++ and INET

Download `omnetpp-6.4.0-core.tgz` from the OMNeT++ 6.4.0 release and
`inet-4.7.0-src.tgz` from the INET 4.7.0 release, unpack both, then:

```bash
cd omnetpp-6.4.0 && source setenv && ./configure WITH_QTENV=no WITH_OSG=no && make -j$(nproc)
cd ../inet-4.7.0  && source setenv && make makefiles && make -j$(nproc) MODE=release
```

`source setenv` must be sourced, not piped: `source setenv | tail` runs it in a
subshell and the environment never reaches your shell.

### 3. Python packages

One package is needed, and only for the independent orbital-contact check. A
virtual environment inside the experiment directory is picked up automatically
by `setenv`:

```bash
cd lifesat/matrix-2026-07          # and again in causal-2026-08
python3 -m venv .venv
./.venv/bin/pip install -r ../requirements.txt
```

Without it the R2 gate stops with a message naming the package. Everything
else, including the build and the other gates, runs on a bare Python 3.10.

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

The raw forensic records and the scored result sets are deposited separately,
because they are large. The deposit holds every raw record of both experiment
generations, the scored layer for both, and the twin ablation results, and it
is the citable companion to this repository:

    https://doi.org/10.5281/zenodo.22262545

The accepted contract root that the analysis pins itself to is not released.
Several of its pins are digests of files produced by the accepting party rather
than by this code, and its identity is the digest of its bytes.
`causal-2026-08/README.md` lists the environment variables that point the
analysis at it if you hold it.

## Citation

This code supports

> Efe Cam, "A Forensic-Ready Digital Twin Framework for Full-Lifecycle
> Cybersecurity in LEO CubeSats", 77th International Astronautical Congress
> (IAC 2026), Antalya, Turkiye, 5 to 9 October 2026. Paper IAC-26-D5.4.11.

If you use this code or the deposited result sets in academic work, please
cite that paper and the deposit:

> https://doi.org/10.5281/zenodo.22262545
 `CITATION.cff` carries the same
information in machine-readable form, and GitHub renders it as a
"Cite this repository" button.

## License

MIT, see `LICENSE`. The licence requires that the copyright and licence
notices are preserved in copies and substantial portions. It does not by
itself require academic citation; the request above does.

The simulator and its model library are separate works with their own terms:
OMNeT++ 6.4.0 is distributed under the Academic Public License, which is free
for academic and other non-commercial use, and INET 4.7.0 under the LGPL-3.0.
Neither is included here; both are obtained separately, and running this code
requires accepting their terms.

## Citation

See `causal-2026-08/CITATION.cff`.
