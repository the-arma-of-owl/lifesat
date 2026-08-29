//
// LIFESAT on-path attacker
//
package lifesat;

//
// Sits between the ground station and the space link (the on-path attacker of
// section 4.3; 48 of 72 recorded space attacks establish this position).
//
// The module writes what it did straight to Collector::recordGroundTruth() and puts
// no label on any packet. Detectors cannot reach that record, and
// tests/check_label_isolation.py enforces it.
//
// Episode timing follows the reference template: non-overlapping windows, start and
// duration uniform. Episodes are placed inside contact windows because contact
// timing is public information, so an attacker finds traffic by schedule rather
// than by chance.
//
simple OnPathAttacker
{
    parameters:
        string scenario = default("B0");    // B0 · A1 · A2 · A2v · A3 · A4 · A6 · A7c · A8
        string accessModule;

        // A2v: compromised command-authorisation key. empty disables A2v. the crypto
        // is not broken, it is assumed stolen, and the HMAC is genuinely recomputed.
        // credential compromise is the default starting point of the attack tree.
        string compromisedKey = default("");

        // --- episode timing -------------------------------------------------
        double attackedPassFraction = default(0.5);   // probability that a pass is attacked
        double episodeStartFraction = default(0.2);   // how far into the pass it starts
        double episodeSpanFraction = default(0.5);    // how much of the pass it spans

        // --- severity ---------------------------------------------------------
        // fixed before the runs. the literature gives no single validated value for
        // this configuration, so this is a design assumption.
        string severity = default("medium");          // low · medium · high

        @signal[observed](type=long);
        @signal[tampered](type=long);
        @signal[injected](type=long);
        @signal[replayed](type=long);
        @signal[dropped](type=long);
        @signal[episodeActive](type=long);

        @statistic[observed](title="packets observed"; record=count);
        @statistic[tampered](title="packets modified"; record=count);
        @statistic[injected](title="packets forged"; record=count);
        @statistic[replayed](title="packets replayed"; record=count);
        @statistic[dropped](title="packets dropped"; record=count);
        @statistic[episodeActive](title="episode active"; record=vector,timeavg);

        @display("i=block/star;i2=status/excl3");
    gates:
        input groundIn;
        output groundOut;
        input linkIn;
        output linkOut;
}
