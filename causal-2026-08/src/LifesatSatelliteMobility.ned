//
// LIFESAT -- SatelliteMobility with a public forward position lookup.
//
package lifesat;

import inet.mobility.single.SatelliteMobility;

//
// SatelliteMobility that exposes SGP4 propagation to an arbitrary Julian date,
// so the ground-contact schedule can be precomputed from the TLE and the epoch
// alone. It adds no parameter and changes no behaviour.
//
simple LifesatSatelliteMobility extends SatelliteMobility
{
    // Fully qualified: a NED type that `extends` inherits the parent's
    // @class, which would instantiate inet::SatelliteMobility instead.
    @class(::lifesat::LifesatSatelliteMobility);
}
