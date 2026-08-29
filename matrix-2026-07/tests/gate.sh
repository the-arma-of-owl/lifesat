#!/usr/bin/env bash
# LIFESAT phase gates. All must pass before the next phase.
#
#   ./tests/gate.sh 0     phase 0 gates
#   ./tests/gate.sh       every defined gate
#
set -u
cd "$(dirname "$0")/.."
source ./setenv >/dev/null 2>&1

PY="$LIFESAT_PY"
FAILED=0
PHASE="${1:-all}"

hr()  { printf -- '-%.0s' {1..72}; echo; }
head2() { hr; echo "  $*"; hr; }

run() {
    local title="$1"; shift
    echo
    echo " $title"
    if "$@"; then :; else FAILED=1; fi
}

if [[ "$PHASE" == "0" || "$PHASE" == "all" ]]; then
    head2 "PHASE 0 -- ground and falsifiability"

    echo " build"
    if make -j4 MODE=release >/dev/null 2>&1; then
        echo "  [OK] lifesat built"
    else
        echo "  [FAIL] build failed"; FAILED=1
    fi

    echo
    echo " access run"
    ( cd simulations && ../out/clang-release/lifesat -u Cmdenv -f access.ini \
        -n .:../src:"$INET_ROOT"/src -l "$INET_ROOT"/src/libINET.so >/dev/null 2>&1 ) \
        && echo "  [OK] 24 h run complete" || { echo "  [FAIL] run failed"; FAILED=1; }

    run "R2 -- contact windows verified against independent SGP4" \
        "$PY" analysis/verify_access.py

    run "R3 -- hash chain consistent" \
        "$PY" analysis/verify_chain.py verify results/phase0-access-r0-events.csv

    run "R3 -- tampering detected and localised" \
        "$PY" analysis/verify_chain.py tamper results/phase0-access-r0-events.csv --index 4

    run "R1 -- ground-truth label isolated from the detectors" \
        "$PY" tests/check_label_isolation.py
fi

if [[ "$PHASE" == "1" || "$PHASE" == "all" ]]; then
    head2 "PHASE 1 -- B0 benign baseline"

    run "accounting, visibility and reproducibility" \
        "$PY" analysis/check_accounting.py

    run "R3 -- chain of the B0 log is consistent" \
        "$PY" analysis/verify_chain.py verify results/B0-D0-r0-events.csv

    run "R1 -- label isolation (with the phase 1 sources)" \
        "$PY" tests/check_label_isolation.py
fi

if [[ "$PHASE" == "2" || "$PHASE" == "all" ]]; then
    head2 "PHASE 2 -- twin and D3"

    run "negative + positive control, delay discrimination" \
        "$PY" analysis/check_d3.py --seeds 10

    run "R1 -- the twin cannot see the answer key" \
        "$PY" tests/check_label_isolation.py
fi

if [[ "$PHASE" == "3" || "$PHASE" == "all" ]]; then
    head2 "PHASE 3 -- attacks A1 -- A4"

    run "impact, accounting, anomaly density and answer-key isolation" \
        "$PY" analysis/check_attacks.py --seeds 5
fi

if [[ "$PHASE" == "4" || "$PHASE" == "all" ]]; then
    head2 "PHASE 4 -- defences D1, D2 and the random baseline"

    run "R3 -- SHA-256 and HMAC-SHA256 match the published test vectors" \
        bash tests/crypto/run.sh

    echo
    echo " D2 threshold calibration (from attack-free runs only)"
    "$PY" analysis/calibrate_d2.py --seeds 10 >/dev/null 2>&1 \
        && echo "  [OK] thresholds derived" || { echo "  [FAIL] calibration failed"; FAILED=1; }

    run "D1 blocks without rejecting legitimate commands; the D2 threshold is sound" \
        "$PY" analysis/check_defences.py --seeds 5
fi

if [[ "$PHASE" == "5" || "$PHASE" == "all" ]]; then
    head2 "PHASE 5 -- full matrix and scoring"
    echo "  [!] The matrix itself is not run here (~25 min).  First:"
    echo "     \$LIFESAT_PY analysis/calibrate_d2.py --seeds 30"
    echo "     \$LIFESAT_PY analysis/run_matrix.py --pilot 30"

    run "triviality check, baseline, residual risk, log preservation" \
        "$PY" analysis/check_matrix.py
fi

if [[ "$PHASE" == "6" || "$PHASE" == "all" ]]; then
    head2 "PHASE 6 -- tier 2 (single illustrative runs, no statistics)"
    echo "  [!] The runs are not launched here -- run them first (from simulations/), each"
    echo "     with --seed-set=0 and '--*.rnd.enabled=true':"
    echo "       -c A2v         (A2v-D3)   valid-credential command, twin on"
    echo "       -c A2v-D1      (A2v-D1)   same, twin off -- ablation"
    echo "       -c A6          (A6-D0)    unsigned update, auth off"
    echo "       -c A6-D1       (A6-D1)    unsigned update, auth on"
    echo "       -c A6s         (A6s-gate-on)   unsafe update, gate on"
    echo "       -c A6s-nogate  (A6s-gate-off)  same, gate off -- control"
    echo "       -c A6s-safe    (A6s-safe)      safe update -- negative control"
    echo "       -c A7c         (A7c-D3)   tampering with the detector telemetry"
    echo "       -c A8          (A8-D3)    resynchronisation window"

    run "A2v behavioural detection · A6u authorisation · A6s pre-uplink validation · A7c reconstruction · A8 resync" \
        "$PY" analysis/check_illustrative.py

    echo
    echo " A7a/A7b -- tamper-evidence of the chain (mechanism test reported in §6.4)"
    echo "  [!] the SAME test as the phase 0 gate; run explicitly here as well so it"
    echo "     can be tied to §6, since §5.2 promises all three A7 variants."
    run "A7a deletion and A7b timestamp tampering localise" \
        "$PY" analysis/verify_chain.py tamper results/A7c-D3-r0-events.csv --index 100
fi

echo
hr
if [[ $FAILED -eq 0 ]]; then
    echo "  [OK] ALL GATES OPEN"
else
    echo "  [FAIL] AT LEAST ONE GATE CLOSED -- do not move to the next phase"
fi
hr
exit $FAILED
