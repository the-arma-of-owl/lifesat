#ifndef __LIFESAT_RANDOMDETECTOR_H
#define __LIFESAT_RANDOMDETECTOR_H

#include "inet/common/INETDefs.h"
#include "Collector.h"

namespace lifesat {
using namespace inet;

/** Triviality check: a detector that alarms with fixed probability (K-59). */
class RandomDetector : public cSimpleModule
{
  protected:
    bool enabled = false;
    double alarmProbability = 0.01;
    long alarms = 0, observations = 0;
    Collector *collector = nullptr;
    static simsignal_t randomAlarmSignal;

    virtual void initialize() override;
    virtual void handleMessage(cMessage *) override { throw cRuntimeError("no messages"); }
    virtual void finish() override;

  public:
    /** Called by the ground station on every telemetry observation. */
    virtual void observe();
};

} // namespace lifesat
#endif
