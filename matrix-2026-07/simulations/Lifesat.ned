//
// LIFESAT phase 1 network
//
package lifesat.simulations;

import inet.mobility.single.SatelliteMobility;
import lifesat.AccessModel;
import lifesat.Collector;
import lifesat.CubeSat;
import lifesat.GroundStation;
import lifesat.OnPathAttacker;
import lifesat.SpaceLink;
import lifesat.FlowDetector;
import lifesat.RandomDetector;
import lifesat.Twin;

module SatelliteNode2
{
    parameters:
        @networkNode;
        @display("i=misc/satellite2");
    submodules:
        mobility: SatelliteMobility { @display("p=100,60"); }
}

//
// Phase 1 topology, the five logical components of specification 2.1:
//
//   GroundStation, OnPathAttacker, SpaceLink, CubeSat
//   AccessModel, SatelliteMobility (SGP4)
//
// Collector records everything; the attacker writes the answer key directly to it,
// with no path to the detectors.
//
network Lifesat
{
    submodules:
        satellite: SatelliteNode2 { @display("p=100,60"); }
        access: AccessModel       { @display("p=100,180"); }
        collector: Collector      { @display("p=100,300"); }

        gs: GroundStation         { @display("p=300,300"); }
        twin: Twin                { @display("p=300,180"); }
        flow: FlowDetector        { @display("p=300,60"); }
        rnd: RandomDetector       { @display("p=460,60"); }
        attacker: OnPathAttacker  { @display("p=460,300"); }
        link: SpaceLink           { @display("p=620,300"); }
        sat: CubeSat              { @display("p=620,160"); }
    connections allowunconnected:
        gs.radioOut       --> attacker.groundIn;
        attacker.groundOut --> gs.radioIn;

        attacker.linkOut  --> link.groundIn;
        link.groundOut    --> attacker.linkIn;

        link.satOut       --> sat.radioIn;
        sat.radioOut      --> link.satIn;
}
