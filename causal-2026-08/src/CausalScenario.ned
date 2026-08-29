//
// LIFESAT -- phase 3 causal scenario controller
//
package lifesat;

//
// The single authority for WHICH deterministic intervention a causal run
// performs, WHEN it performs it, and WITH WHAT magnitude.
//
// Every parameter below is supplied from the accepted Phase 2 v7 contract by
// analysis/causal/runcell.py.  None of them has a value in an ini file, on
// purpose: a number that lives in two places is a number that can disagree
// with itself, and the contract is the one that counts.
//
// R1 boundary.  This module routes execution and writes the answer key.  It
// is queried by the producer modules with questions of the form "is THIS
// sequence the target", never "which arm am I".  No observable value and no
// oracle input is derived from anything here; the leakage tests in
// analysis/causal/tests/phase3_suite.py hold the raw record fixed and scramble
// every field of this module's truth output to prove it.
//
simple CausalScenario
{
    parameters:
        // run identity
        string pairId = default("");            // "" disables causal mode entirely
        string arm = default("");               // attack | fault
        string robustnessArm = default("");     // "" | RB-model-mismatch | ...
        string runId = default("");
        int runSeedIndex = default(0);

        // schedule, from pair_intervention_registry
        double onsetOffsetS @unit(s) = default(0s);
        int durationObservations = default(1);

        // magnitudes, from operational_closure / nominal_constants
        double targetDeviationV = default(0.15);        // SP-1
        double perturbedDischargeRate = default(0.00048);  // SP-2, V/s
        int eclipseSteps = default(100);                // SP-2 (accepted, retained)
        // Amendment v5, SP-2
        double perturbedChargeRate = default(-0.00043);      // V/s, sunlit branch
        double sp2MinContactDurationS @unit(s) = default(360s);
        double sp2WindowS @unit(s) = default(300s);
        double activationGuardS @unit(s) = default(1s);
        double minVoltageV = default(6.0);
        double clippingMarginV = default(0.05);
        int modeOrdinalDelta = default(1);               // SP-3
        double delayTargetS @unit(s) = default(30s);     // SP-4
        int counterTargetDelta = default(3);             // SP-5
        int replayWindowObservations = default(3);       // SP-6

        // robustness perturbation magnitude, from robustness_spec.arms
        double robustnessMagnitude = default(0.0);

        // model_authority.telemetry_interval_s -- the step the end rules count in
        double telemetryIntervalS @unit(s) = default(10s);

        string collectorModule = default("^.collector");
        string accessModule = default("^.access");
        @display("i=block/control");
    gates:
}
