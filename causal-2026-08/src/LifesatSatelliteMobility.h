//
// LIFESAT -- SatelliteMobility with a public forward position lookup.
//
#ifndef __LIFESAT_LIFESATSATELLITEMOBILITY_H
#define __LIFESAT_LIFESATSATELLITEMOBILITY_H

#include "inet/common/INETDefs.h"
#include "inet/mobility/single/SatelliteMobility.h"

namespace lifesat {

using namespace inet;

/**
 * SatelliteMobility, with `computeScenePosition` exposed.
 *
 * WHY THIS EXISTS (amendment v5, selection rule).
 * The amended SP-2 target is placed on "the FIRST ground contact of the run
 * whose duration is at least `sp2MinContactDurationS`". That predicate cannot
 * be evaluated at the instant the target must be placed: at contact start the
 * duration is not yet known, and waiting for the contact to end is too late to
 * put a target inside it.
 *
 * The resolution is NOT to weaken the rule. A pass schedule is a property of
 * the TLE and the epoch alone -- it does not depend on the arm, the seed, the
 * battery, or any outcome -- so it can be computed in advance, exactly as a real
 * mission plans its passes before the spacecraft flies over. INET's
 * SatelliteMobility already propagates SGP4 to an arbitrary Julian date in
 * `computeScenePosition`, but declares it protected. This subclass exposes it
 * and adds nothing else.
 *
 *  READING THE ORBIT'S FUTURE IS NOT READING AN OUTCOME'S FUTURE. The
 * contract's determinism requirement forbids the schedule from reading the
 * attack arm's acceptance, any attack state, the battery state or a scorer
 * result. A propagated ephemeris is none of those: it is a fixed input, and it
 * is identical in both arms of every seed.
 */
class LifesatSatelliteMobility : public SatelliteMobility
{
  public:
    /** ECEF metres at `julianDate`, propagated from the TLE. */
    virtual Coord positionAtJulianDate(double julianDate)
    {
        GeoCoord geographic = GeoCoord::NIL;
        return computeScenePosition(julianDate, geographic);
    }

    /** The epoch the run is propagated from, as a Julian date. */
    virtual double getEpochJulianDate() const { return epochJulianDate; }
};

} // namespace lifesat

#endif
