//
// LIFESAT phase 0 verification network
//
// Orbital geometry only. Its single purpose is to show that the contact windows
// OMNeT++ produces with SGP4 agree with an independent SGP4 implementation given the
// same TLE and epoch.
//
package lifesat.simulations;

import inet.mobility.single.SatelliteMobility;
import lifesat.AccessModel;
import lifesat.Collector;

module SatelliteNode
{
    parameters:
        @networkNode;
        @display("i=misc/satellite2");
    submodules:
        // coordinateSystemModule left empty: position is raw geocentric ECEF (metres)
        mobility: SatelliteMobility {
            @display("p=100,100");
        }
}

network AccessOnly
{
    submodules:
        satellite: SatelliteNode {
            @display("p=100,100");
        }
        access: AccessModel {
            @display("p=300,100");
        }
        collector: Collector {
            @display("p=500,100");
        }
}
