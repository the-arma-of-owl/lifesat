//
// LIFESAT collector and forensic log
//
package lifesat;

//
// Records every observable event of a run into a hash-chained CSV log, and is
// the **only** module that holds ground truth.
//
// R1 (see the coding plan): the ground-truth label is never carried in a packet
// and is never visible to a detector.  The attacker reports what it did by
// calling recordGroundTruth() on this module directly; detectors report what
// they decided by emitting the detectorDecision signal, which travels in the
// opposite direction.  A detector therefore cannot read the answer even by
// accident, because there is no path from here to it.
//
simple Collector
{
    parameters:
        string runLabel = default("");        // scenario × defence cell, e.g. "A2-D3"
        string outputDir = default("results");
        bool writeEventLog = default(true);

        @signal[detectorDecision](type=long);
        @statistic[detectorDecision](title="detector decisions"; record=count);

        @display("i=block/sink");
}
