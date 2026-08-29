//
// LIFESAT -- contact window model
//
#ifndef __LIFESAT_ACCESSMODEL_H
#define __LIFESAT_ACCESSMODEL_H

#include "inet/common/INETDefs.h"
#include "inet/common/geometry/common/Coord.h"
#include "inet/common/geometry/common/GeographicCoordinateSystem.h"
#include "inet/mobility/single/SatelliteMobility.h"

#include "LifesatSatelliteMobility.h"

#include "Collector.h"

namespace lifesat {

using namespace inet;

/**
 * Geometric access between one ground station and one satellite.
 *
 * The satellite position is taken from a SatelliteMobility module configured
 * with coordinateSystemModule="", which reports raw geocentric ECEF metres.
 * The ground station is fixed geodetic.  Elevation is the angle of the
 * line-of-sight vector above the local geodetic horizon:
 *
 *     up  = (cos(lat)cos(lon), cos(lat)sin(lon), sin(lat))     (geodetic normal)
 *     los = satEcef - gsEcef
 *     el  = asin( up . los / |los| )
 *
 * Access holds while el >= elevationMask.  Other modules query isVisible() and
 * the pass bookkeeping; nothing may set the access state directly.
 */
class AccessModel : public cSimpleModule
{
  protected:
    SatelliteMobility *satelliteMobility = nullptr;
    LifesatSatelliteMobility *lifesatMobility = nullptr;
    Collector *collector = nullptr;   // write direction only: nothing is read back from here

    Coord gsEcef = Coord::ZERO;   // ground station, ECEF metres
    Coord gsUp = Coord::ZERO;     // geodetic up unit vector at the ground station

    double elevationMaskDeg = 10;
    simtime_t updateInterval;
    cMessage *sampleTimer = nullptr;

    // --- access bookkeeping (read-only for other modules) -------------------
    bool visible = false;
    simtime_t currentPassStart = -1;
    simtime_t passStartOfCurrent = -1;   // for the duration computation
    simtime_t lastPassEnd = -1;       // end of the most recent completed pass
    simtime_t lastVisibleTime = -1;   // last instant at which access held
    long passCount = 0;

    // --- precomputed pass schedule (amendment v5) ---------------------------
    // A property of the TLE and the epoch alone: identical in both arms of
    // every seed, and independent of every outcome.
    struct ScheduledPass { simtime_t start; simtime_t end; };
    std::vector<ScheduledPass> scheduledPasses;
    bool scheduleReady = false;

    double lastElevationDeg = -90;
    double lastRangeM = NaN;

    static simsignal_t elevationSignal;
    static simsignal_t slantRangeSignal;
    static simsignal_t accessStateSignal;
    static simsignal_t passStartSignal;
    static simsignal_t passEndSignal;

  protected:
    virtual void initialize(int stage) override;
    virtual int numInitStages() const override { return NUM_INIT_STAGES; }
    virtual void handleMessage(cMessage *msg) override;
    virtual void finish() override;

    /** Samples the geometry once and updates the access state. */
    virtual void sample();

    /** Precomputes the whole pass schedule from the propagated orbit. */
    virtual void buildPassSchedule();

    /** Elevation of the satellite above the ground station horizon, in degrees. */
    virtual double computeElevationDeg(const Coord& satEcef, double& rangeOut) const;

  public:
    virtual ~AccessModel();

    /** True while the satellite is above the elevation mask. */
    virtual bool isVisible() const { return visible; }

    /** Start of the pass currently in progress, or -1 when not in a pass. */
    virtual simtime_t getCurrentPassStart() const { return currentPassStart; }

    /** End of the most recent completed pass, or -1 before the first pass. */
    virtual simtime_t getLastPassEnd() const { return lastPassEnd; }

    /** The first scheduled pass lasting at least `minDuration`, or (-1, -1). */
    virtual bool firstPassAtLeast(simtime_t minDuration, simtime_t& startOut,
                                  simtime_t& endOut) const
    {
        for (const auto& pass : scheduledPasses) {
            if (pass.end - pass.start >= minDuration) {
                startOut = pass.start;
                endOut = pass.end;
                return true;
            }
        }
        startOut = -1; endOut = -1;
        return false;
    }

    /** The scheduled end of the pass containing `t`, or -1. */
    virtual simtime_t scheduledPassEndAt(simtime_t t) const
    {
        for (const auto& pass : scheduledPasses)
            if (pass.start <= t && t <= pass.end)
                return pass.end;
        return -1;
    }

    virtual size_t getScheduledPassCount() const { return scheduledPasses.size(); }
    virtual bool isScheduleReady() const { return scheduleReady; }

    /**
     * Time since access last held, i.e. the age of the freshest telemetry the
     * ground could possibly hold.  Zero while a pass is in progress.  This is
     * the quantity the twin's temporal bound is derived from (see §3.2).
     */
    virtual simtime_t getTimeSinceLastAccess() const;

    virtual double getElevationDeg() const { return lastElevationDeg; }
    virtual double getSlantRangeM() const { return lastRangeM; }
    virtual long getPassCount() const { return passCount; }
};

} // namespace lifesat

#endif
