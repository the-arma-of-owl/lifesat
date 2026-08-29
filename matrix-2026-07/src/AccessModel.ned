//
// LIFESAT -- contact window model
//
package lifesat;

//
// Computes the geometric access (visibility) between a ground station and a
// satellite from the satellite's propagated ECEF position and the ground
// station's geodetic position.
//
// Nothing here is configurable in a way that could manufacture a convenient
// contact schedule: the satellite position comes from ~SatelliteMobility, which
// propagates a real two-line element set with SGP4, and the only free parameter
// is the elevation mask, which is a property of the ground station antenna.
// The resulting pass times, pass durations and gaps are consequences of the
// orbit, not of this module.  See the R2 rule in the coding plan.
//
simple AccessModel
{
    parameters:
        string satelliteMobilityModule;      // path to the satellite's SatelliteMobility submodule
        double groundStationLatitude @unit(deg);
        double groundStationLongitude @unit(deg);
        double groundStationAltitude @unit(m) = default(0m);
        double elevationMask @unit(deg) = default(10deg);   // antenna horizon; below this there is no link
        double updateInterval @unit(s) = default(1s);       // access sampling period

        @signal[elevation](type=double);      // deg
        @signal[slantRange](type=double);     // m
        @signal[accessState](type=long);      // 1 = visible, 0 = not visible
        @signal[passStart](type=simtime_t);
        @signal[passEnd](type=simtime_t);

        @statistic[elevation](title="elevation angle"; unit=deg; record=vector,max);
        @statistic[slantRange](title="slant range"; unit=m; record=vector,min);
        @statistic[accessState](title="access state"; record=vector,timeavg);
        @statistic[passStart](title="pass start times"; record=vector);
        @statistic[passEnd](title="pass end times"; record=vector);

        @display("i=block/timer");
}
