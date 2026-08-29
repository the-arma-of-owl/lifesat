//
// LIFESAT random detector (triviality baseline)
//
package lifesat;

//
// Alarms with probability p on every observation, looking at nothing.
//
// This is a control, not a defence. A random detector scores 0.912 point-adjusted F1
// on satellite telemetry, which is why F1PA is excluded and this baseline is
// mandatory. If D3 cannot clearly beat it, the D3 result is not publishable.
//
simple RandomDetector
{
    parameters:
        bool enabled = default(false);
        double alarmProbability = default(0.01);   // K-59'un p=0,01'i

        @signal[randomAlarm](type=long);
        @statistic[randomAlarm](title="random detector alarms"; record=count);
        @display("i=block/dice");
}
