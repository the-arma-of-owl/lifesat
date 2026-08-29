//
// LIFESAT D2: flow anomaly detector
//
package lifesat;

//
// Measures packets/s and bits/s of the received telemetry stream in 1 s windows and
// flags anything outside mu +/- k*sigma.
//
// Thresholds come from B0 only: mu and sigma are derived from attack-free runs and
// written to a file that attack runs read. They are never fitted to the run being
// scored. This is the documented pitfall where a method looks unsupervised while
// setting its threshold from the test data.
//
// Section 5.4 reports D2 as a triviality check rather than a contribution: without
// knowing how much a simple threshold catches, the D3 result cannot be read.
//
simple FlowDetector
{
    parameters:
        bool enabled = default(false);
        bool calibrationMode = default(false);   // true: collect mu,sigma · false: threshold
        string thresholdFile = default("");      // calibration output
        // window size cannot be carried over from the literature: the reference uses
        // 1 s windows at ~1200 pps baseline traffic, while telemetry here arrives every
        // 10 s (0.1 pps). a 1 s window holds exactly one packet, giving sigma = 0 and a
        // degenerate zero-width band. the method (mu +/- k*sigma) transfers, the
        // parameter does not. 60 s gives about six windows per pass.
        double windowSize @unit(s) = default(60s);   // [TASARIM VARSAYIMI]
        double sigmaFactor = default(3.0);       // the mu+/-3sigma of Rodrigues et al.

        // resolution floor. some attack-free statistics are exactly deterministic
        // (telemetry arrives at 10.000 s intervals, so sigma_iat = 0). a zero-width
        // band makes the detector alarm on everything or nothing, both degenerate.
        // the measurement resolution is declared instead: differences below it are
        // not claimed to be distinguishable. enters the sensitivity sweep.
        double sigmaFloorFraction = default(0.05);   // sigma_eff = max(sigma, fraction * mu)

        @signal[windowPps](type=double);
        @signal[windowBps](type=double);
        @signal[d2Alarm](type=long);

        @statistic[windowPps](title="packets per window"; record=vector,mean,max);
        @statistic[windowBps](title="bits per window"; record=vector,mean,max);
        @statistic[d2Alarm](title="D2 alarms"; record=count);

        @display("i=block/timer");
}
