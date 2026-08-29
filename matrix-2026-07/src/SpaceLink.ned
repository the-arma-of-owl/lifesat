//
// LIFESAT space link
//
package lifesat;

//
// Bidirectional link between ground and satellite.
//
// Two properties are computed, not chosen:
//   visibility: the AccessModel elevation mask, from SGP4 geometry
//   propagation delay: slant range / c, from the same geometry
//
// Not modelled: modulation, bit error rate, coding, antenna pattern. Section 5.1 and
// L1 state this. The abstraction follows from the literature offering no single
// defensible RF parameter set for this configuration.
//
simple SpaceLink
{
    parameters:
        string accessModule;
        double bitrateUp @unit(bps) = default(9600bps);     // TC uplink [DESIGN ASSUMPTION]
        double bitrateDown @unit(bps) = default(38400bps);  // TM downlink, K-61: TM > TC
        double propagationSpeed @unit(mps) = default(299792458mps);

        @signal[deliveredUp](type=long);
        @signal[deliveredDown](type=long);
        @signal[droppedNoAccess](type=long);
        @signal[propagationDelay](type=simtime_t);

        @statistic[deliveredUp](title="TC delivered"; record=count);
        @statistic[deliveredDown](title="TM delivered"; record=count);
        @statistic[droppedNoAccess](title="dropped, no access"; record=count);
        @statistic[propagationDelay](title="propagation delay"; unit=s; record=vector,mean,max);

        @display("i=block/wheelbarrow");
    gates:
        input groundIn;
        output groundOut;
        input satIn;
        output satOut;
}
