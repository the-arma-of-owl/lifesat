//
// LIFESAT satellite side
//
package lifesat;

//
// Satellite command handler, parameter store and telemetry generator.
//
// Telemetry carries three state channels (section 5.1):
//   physical  battery voltage, from the illumination model
//   logical   operating mode and parameter store, changed only by accepted commands
//   security  rejected-command counter, the observable of D1's action
//
// No defence lives here; D1 arrives as a separate submodule. Under B0 every command
// is accepted.
//
simple CubeSat
{
    parameters:
        string accessModule;                       // AccessModel yolu
        string satelliteMobilityModule;            // path to SatelliteMobility (for illumination)

        double telemetryInterval @unit(s) = default(10s);   // TM generation period

        // --- physical channel [DESIGN ASSUMPTION] -------------------------
        double nominalVoltage @unit(V) = default(7.4V);
        double minVoltage @unit(V) = default(6.0V);
        double maxVoltage @unit(V) = default(8.4V);
        double chargeRate = default(0.00012);       // V/s in sunlight
        double dischargeRate = default(0.00008);    // V/s in eclipse
        double voltageNoiseSigma = default(0.01);   // V, measurement noise

        // --- logical channel ----------------------------------------------
        int initialMode = default(0);               // MODE_NOMINAL

        // --- D1: command authorisation ------------------------------------
        // three behaviours: verify identity, drop the unverifiable, drop the corrupted.
        // freshness covers the command-count/nonce requirement. every command is
        // accepted when disabled (D0).
        bool commandAuthEnabled = default(false);
        string authKey = default("LIFESAT-TC-KEY");   // shared symmetric key

        // --- phase 3: causal scenario controller ---------------------------
        // left empty by default, no causal injector is attached and the module behaves
        // exactly as in phases 1 and 2.
        string causalModule = default("^.causal");
        // model_authority.eclipse_seconds_per_orbit -- SP-2's window condition
        double eclipseSecondsPerOrbit @unit(s) = default(1786s);

        @signal[batteryVoltage](type=double);          // the true (model) value
        @signal[batteryVoltageMeasured](type=double);  // the noisy measurement that enters telemetry
        @signal[illuminated](type=long);
        @signal[tmGenerated](type=long);
        @signal[tcAccepted](type=long);
        @signal[tcRejected](type=long);
        @signal[tcRejectReason](type=long);   // 1 auth · 2 freshness · 3 integrity

        @statistic[batteryVoltage](title="battery voltage, true"; unit=V; record=vector,mean,min,max);
        @statistic[batteryVoltageMeasured](title="battery voltage, as telemetered"; unit=V; record=vector,mean,min,max);
        @statistic[illuminated](title="illumination"; record=vector,timeavg);
        @statistic[tmGenerated](title="telemetry generated"; record=count);
        @statistic[tcAccepted](title="telecommands accepted"; record=count);
        @statistic[tcRejected](title="telecommands rejected"; record=count);
        @statistic[tcRejectReason](title="rejection reason"; record=vector);

        @display("i=block/control");
    gates:
        input radioIn;
        output radioOut;
}
