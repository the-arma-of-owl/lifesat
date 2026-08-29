#ifndef __LIFESAT_FLOWDETECTOR_H
#define __LIFESAT_FLOWDETECTOR_H

#include <cmath>
#include <string>
#include "inet/common/INETDefs.h"
#include "Collector.h"

namespace lifesat {
using namespace inet;

/**
 * D2 -- flow anomaly (mu +- k*sigma), at the ground station.
 *
 *  R1: only packet count and size enter.  It sees no label, and it does not look
 * at packet contents either.
 */
class FlowDetector : public cSimpleModule
{
  protected:
    bool enabled = false, calibrationMode = false;
    std::string thresholdFile;
    simtime_t windowSize;
    double sigmaFactor = 3.0;
    double sigmaFloorFraction = 0.05;

    cMessage *windowTimer = nullptr;
    long windowPackets = 0, windowBits = 0;

    // Inter-arrival time. The first version carried PPS/BPS only and D2 caught
    // nothing; giving the baseline an incomplete instrument makes the comparison
    // unfair. A4's delay attack shows up exactly here (nominal 10 s, +30 s under
    // attack).
    simtime_t lastArrival = -1;
    double windowIatSum = 0;
    long windowIatCount = 0;
    double sumIat = 0, sumSqIat = 0;
    long nIatWindows = 0;
    double muIat = 0, sigmaIat = 0;

    // calibration accumulators
    long nWindows = 0;
    double sumPps = 0, sumSqPps = 0, sumBps = 0, sumSqBps = 0;

    // detection thresholds (from file)
    double muPps = 0, sigmaPps = 0, muBps = 0, sigmaBps = 0;
    bool thresholdsLoaded = false;

    Collector *collector = nullptr;
    long alarms = 0;

    static simsignal_t windowPpsSignal, windowBpsSignal, d2AlarmSignal;

    virtual void initialize() override;
    virtual void handleMessage(cMessage *msg) override;
    virtual void finish() override;
    virtual void closeWindow();
    virtual void loadThresholds();
    /** Effective sigma that prevents a degenerate band: max(sigma, floor ratio * mu). */
    double effectiveSigma(double sigma, double mu) const
    { return std::max(sigma, sigmaFloorFraction * std::fabs(mu)); }

  public:
    virtual ~FlowDetector();
    /** The ground station reports every packet it receives here. */
    virtual void observePacket(long bits);
};

} // namespace lifesat
#endif
