#ifndef __LIFESAT_SPACELINK_H
#define __LIFESAT_SPACELINK_H

#include "inet/common/INETDefs.h"
#include "AccessModel.h"
#include "CausalScenario.h"
#include "Collector.h"
#include "LifesatPackets_m.h"

namespace lifesat {
using namespace inet;

/** Line-of-sight gate + propagation delay computed from the geometry. */
class SpaceLink : public cSimpleModule
{
  protected:
    AccessModel *access = nullptr;
    Collector *collector = nullptr;
    CausalScenario *causal = nullptr;
    double bitrateUp = 9600, bitrateDown = 38400, c = 299792458;
    long deliveredUp = 0, deliveredDown = 0, droppedNoAccess = 0;
    // per direction: a combined counter mixed TC and TM losses and made the
    // accounting check show a spurious one-packet difference.
    long droppedUp = 0, droppedDown = 0;

    // --- phase 3: benign link faults ---------------------------------------
    //
    // SP-4 fault: coverage outage. the target observation is held and redelivered after
    // the same interval; a plain drop is a different observable and the accepted
    // contract rejects it explicitly.
    bool coverageGapOpen = false;
    simtime_t coverageGapEnd = -1;

    // SP-6 fault: reordering buffer. the first frame of the contact is held, the second
    // and third pass, then the first is delivered for the first time.
    cMessage *reorderHeld = nullptr;
    simtime_t reorderHeldDelay = 0;
    int reorderReleaseAfter = 2;

    static simsignal_t deliveredUpSignal, deliveredDownSignal;
    static simsignal_t droppedNoAccessSignal, propagationDelaySignal;

    virtual void initialize(int stage) override;
    virtual int numInitStages() const override { return NUM_INIT_STAGES; }
    virtual void handleMessage(cMessage *msg) override;
    virtual void finish() override;

    /** Forwards with the delay if there is line of sight, otherwise drops with reason 'coverage'. */
    virtual void forward(cMessage *msg, const char *gate, double bitrate, const char *dir);

    /**
     * SP-4 fault: opens a coverage outage, holds the target frame and drops every
     * downlink frame arriving during the outage with `reason=coverage`.
     * Returns true once consumed.
     */
    virtual bool causalCoverageGap(cMessage *msg, simtime_t transferDelay);

    /** SP-6 fault: benign reordering.  Returns true once consumed. */
    virtual bool causalReorder(cMessage *msg, simtime_t transferDelay);

  public:
    virtual ~SpaceLink();
};

} // namespace lifesat
#endif
