#ifndef __LIFESAT_GROUNDSTATION_H
#define __LIFESAT_GROUNDSTATION_H

#include "inet/common/INETDefs.h"
#include "AccessModel.h"
#include "Collector.h"
#include "LifesatPackets_m.h"
#include "Hmac.h"
#include "FlowDetector.h"
#include "RandomDetector.h"
#include "Twin.h"

namespace lifesat {
using namespace inet;

/**
 * Ground station: produces telecommands, receives telemetry.
 *
 * Two quantities are measured for every received telemetry:
 *   latency -- from send to receive
 *   age     -- relative to the telemetry's source time, i.e. how stale the picture
 *              the twin sees may be
 */
class GroundStation : public cSimpleModule
{
  protected:
    AccessModel *access = nullptr;
    Collector *collector = nullptr;
    Twin *twin = nullptr;   // forward direction only: we feed the detectors, we do not read the answer key from them
    FlowDetector *flow = nullptr;
    RandomDetector *randomDet = nullptr;

    simtime_t commandInterval;
    bool commandsOnlyDuringPass = true;
    bool signCommands = false;
    std::string authKey;
    cMessage *commandTimer = nullptr;

    // --- candidate configuration update (A6s) ------------------------------
    // in-orbit workflow: patch, validate on the twin, uplink, confirm. this update is
    // not an injected packet but a validly signed candidate from the operator chain
    // (a bad build, a supply-chain artefact, a wrongly approved parameter). the threat
    // enters through the trusted channel, so D1 passes it by definition.
    bool proposeUpdates = false;
    bool twinValidation = false;
    simtime_t updateInterval;
    simtime_t retryInterval;
    std::string updateKey;
    double updateValue = 0;
    cMessage *updateTimer = nullptr;
    long updatesProposed = 0, updatesBlocked = 0, updatesUplinked = 0;
    long updatesUnsupported = 0;

    long commandId = 0, sequence = 0;
    long tcGenerated = 0, tcSent = 0, tcSuppressedNoAccess = 0, tmReceived = 0;

    static simsignal_t tcGeneratedSignal, tcSentSignal, tmReceivedSignal;
    static simsignal_t tmLatencySignal, tmAgeSignal;

    virtual void initialize(int stage) override;
    virtual int numInitStages() const override { return NUM_INIT_STAGES; }
    virtual void handleMessage(cMessage *msg) override;
    virtual void finish() override;

    virtual void generateTelecommand();
    virtual void handleTelemetry(Telemetry *tm);
    /**
     * Tries the candidate update on the twin and uplinks it only if it validates.
     * @return false: there was no contact, the candidate stayed queued (will be retried)
     */
    virtual bool proposeConfigurationUpdate();

  public:
    virtual ~GroundStation();
};

} // namespace lifesat
#endif
