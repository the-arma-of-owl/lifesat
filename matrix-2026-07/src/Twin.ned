//
// LIFESAT twin and deviation detector (D3)
//
package lifesat;

//
// The twin propagates the expected satellite state independently and compares it
// against incoming telemetry. The two-part tolerance of section 3.2 is applied here.
//
// Model mismatch is deliberate. Running the satellite's own parameters would leave
// only measurement noise and make D3 look artificially perfect, i.e. a detector that
// cannot be falsified. The twin's charge/discharge rates therefore differ by
// rateBias, and the twin knows only an upper bound (rateUncertainty).
//
// Model error accumulates across the contact gap, so the state bound must widen
// with dt.
//
// The module never sees ground truth: telemetry and the ground's own approved
// command history are its only inputs.
//
simple Twin
{
    parameters:
        bool enabled = default(true);   // with D3 off the twin takes no observations
        string accessModule;
        string satelliteMobilityModule;
        double updateInterval @unit(s) = default(10s);       // the twin's own step

        // --- the twin's physical channel model ------------------------------
        double nominalVoltage @unit(V) = default(7.4V);
        double minVoltage @unit(V) = default(6.0V);
        double maxVoltage @unit(V) = default(8.4V);
        double chargeRate = default(0.00005);
        double dischargeRate = default(0.00008);

        // how far the model actually drifts: the twin's rates are offset by this much.
        // zero makes the twin perfect and the results unpublishable.
        double rateBias = default(0.06);        // +6% systematic model error
        // the bound the twin declares; it does not know the actual offset
        double rateUncertainty = default(0.10); // %10

        // --- tolerans ------------------------------------------------------
        double noiseSigma = default(0.01);      // V, calibrated from B0
        double sigmaFactor = default(3.0);      // how many sigma (same family as D2's mu+/-3sigma)
        double maxTemporalBound @unit(s) = default(24h);  // beyond this it is "unknown"

        // longest time a command may take to reach the satellite. this is the
        // uncertainty window over which commands may or may not be in effect in
        // delayed telemetry; the twin cannot alarm inside it.
        double uplinkDelayBound @unit(s) = default(1s);

        bool resyncOnMatch = default(true);
        // realign to the observed value inside the bound but not outside, or an
        // attacker could drag the twin along.

        // --- pre-uplink validation envelope (A6s) --------------------------
        // the update is tried on the twin first and sent only if it validates. this
        // gate is independent of the cryptographic check: a validly signed but
        // behaviourally unsafe update passes D1 and fails here.
        // all three values are declared, not learned: period and illuminated fraction
        // were measured from pre-flight geometry, the floor was declared by the
        // mission.
        double validationHorizon @unit(s) = default(24h);
        double orbitalPeriod @unit(s) = default(5724s);   // FUNCUBE-1, 95,4 dk
        double illuminationDuty = default(0.688);         // measured, not assumed
        double safetyFloorVoltage = default(7.0);         // V, the reported safety floor

        @signal[voltageDeviation](type=double);
        @signal[voltageBound](type=double);
        @signal[temporalLag](type=simtime_t);
        @signal[d3Alarm](type=long);
        @signal[d3AlarmChannel](type=long);   // 0 physical, 1 logical, 2 safety

        @statistic[voltageDeviation](title="|expected - observed| voltage"; unit=V; record=vector,mean,max);
        @statistic[voltageBound](title="state bound in force"; unit=V; record=vector,mean,max);
        @statistic[temporalLag](title="telemetry age at evaluation"; unit=s; record=vector,mean,max);
        @statistic[d3Alarm](title="D3 alarms"; record=count);
        @statistic[d3AlarmChannel](title="alarming channel"; record=vector);

        @display("i=block/cogwheel");
}
