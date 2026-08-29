//
// LIFESAT -- ground station
//
package lifesat;

//
// Produces telecommands and receives telemetry. Commands can only be sent inside a
// contact window, which is the link itself rather than a design choice.
//
// Operator gate (section 3.1): no twin output reaches the satellite automatically.
// Phase 1 carries nominal commands only; the patch flow arrives with A6.
//
simple GroundStation
{
    parameters:
        string accessModule;
        string twinModule = default("");           // empty means no D3
        string flowDetectorModule = default("");   // empty means no D2
        string randomDetectorModule = default(""); // empty means no baseline
        bool signCommands = default(false);        // mandatory while D1 is on
        string authKey = default("LIFESAT-TC-KEY");
        double commandInterval @unit(s) = default(30s);   // command period within a contact

        // --- candidate update and pre-uplink validation (A6s)
        // with proposeUpdates on, the ground periodically offers a validly signed
        // configuration update; with twinValidation on, that update is first
        // forward-simulated on the twin and uplinked only if it stays inside the
        // safety envelope.
        // the two flags are separate so an update can be proposed without the gate
        // (the A6s control arm), which is what makes the gate's contribution
        // measurable.
        bool proposeUpdates = default(false);
        bool twinValidation = default(false);
        double updateInterval @unit(s) = default(12h);
        // outside contact the candidate waits in the queue and is retried at this
        // interval; at 1.4% coverage, dropping it would make the experiment unrunnable.
        double updateRetryInterval @unit(s) = default(60s);
        // which parameter to propose. dischargeRate is the only one the twin's
        // envelope covers; any other name yields an UNSUPPORTED verdict and the
        // update is not uplinked (L10).
        string updateKey = default("dischargeRate");
        double updateValue = default(0.00008);    // V/s -- the proposed new discharge rate
        bool commandsOnlyDuringPass = default(true);

        @signal[tcGenerated](type=long);
        @signal[tcSent](type=long);
        @signal[tmReceived](type=long);
        @signal[tmLatency](type=simtime_t);
        @signal[tmAge](type=simtime_t);          // age of the data the twin sees

        @statistic[tcGenerated](title="telecommands generated"; record=count);
        @statistic[tcSent](title="telecommands sent"; record=count);
        @statistic[tmReceived](title="telemetry received"; record=count);
        @statistic[tmLatency](title="telemetry latency"; unit=s; record=vector,mean,max);
        @statistic[tmAge](title="telemetry age at reception"; unit=s; record=vector,mean,max);

        @display("i=device/receiverdish");
    gates:
        input radioIn;
        output radioOut;
}
