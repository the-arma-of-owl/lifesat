#ifndef __LIFESAT_ONPATHATTACKER_H
#define __LIFESAT_ONPATHATTACKER_H

#include <string>
#include "inet/common/INETDefs.h"
#include "AccessModel.h"
#include "Collector.h"
#include "LifesatPackets_m.h"

namespace lifesat {
using namespace inet;

/**
 * On-path attacker implementing the A1 -- A4, A6, A7c and A8 attacks.
 *
 *   A1 MITM-TC       modifies a field of a valid command and forwards it
 *   A2 forged-TC     injects a command the ground station never produced -- NO tag,
 *                    D1 rejects it at authentication.  This is NOT abuse of a TRUST
 *                    RELATIONSHIP, it is an unauthenticated forgery (§4.4 correction)
 *   A2v valid-cred    the real claim of §4.4: the attacker re-signs a legitimate
 *                    command with a stolen key.  The crypto is VALID and D1 lets it
 *                    through; if it is to be caught, the twin's LOGICAL channel must
 *                    catch it (the ground never approved that value).  This is the run
 *                    that tests the claim "once credentials are legitimate, the
 *                    remaining defence is behavioural"
 *   A3 replay        replays a captured command with an old sequence number
 *   A4 MITM-TM       delays, drops or alters a field of telemetry
 *   A6 unauth-update injects an unauthorised CMD_UPDATE (§6: TIER 2, single run)
 *   A7c counter-forge falsifies on the downlink the count of commands D1 rejected
 *                    (rejectedCmdCount) -- together with an A2-style injection,
 *                    "attack, then erase the trace" (§6: TIER 2)
 *   A8 resync-hijack injects a fake telemetry at the start of a pass, before or
 *                    alongside the real first telemetry; it targets the twin's wide
 *                    Δt tolerance at the resync instant (§6: TIER 2)
 *
 *  R1: every intervention is recorded through recordGroundTruth(); no label is
 * placed in a packet.  Detectors see only the effect, never the cause.
 */
class OnPathAttacker : public cSimpleModule, public cListener
{
  protected:
    std::string scenario = "B0";
    AccessModel *access = nullptr;
    Collector *collector = nullptr;

    // episode state
    bool episodeActive = false;
    cMessage *episodeStart = nullptr;
    cMessage *episodeEnd = nullptr;
    cMessage *injectTimer = nullptr;
    long episodeCount = 0;

    double attackedPassFraction = 0.5;
    double episodeStartFraction = 0.2;
    double episodeSpanFraction = 0.5;

    // values derived from the severity profile
    double affectedFractionTc = 0.30;   // command direction
    double affectedFractionTm = 0.12;   // telemetry direction (3x more frequent traffic)
    simtime_t addedDelay;
    simtime_t injectionInterval;
    double paramDelta = 0.5;
    double voltageDelta = 0.15;

    // command captured for A3
    Telecommand *captured = nullptr;

    /**
     * A2v: compromised command authorisation key.
     *
     *  This is not a violation of the "crypto is real, nothing is assumed valid"
     * rule: the key is not broken, it is assumed stolen, and the HMAC is genuinely
     * recomputed. The attacker model treats credential compromise as an explicit
     * initial-access condition.
     */
    std::string compromisedKey;

    // A7c: baseline rejection count to hide behind this episode (-1: not yet seen)
    long frozenRejectedCount = -1;
    // A8: the last real telemetry observed, used as material for the spoofed resync
    // packet. the attacker copies what was on the wire and never reaches satellite
    // internals.
    Telemetry *lastSeen = nullptr;

    long observed = 0, tampered = 0, injected = 0, replayed = 0, dropped = 0;
    long forgedId = 900000;

    static simsignal_t observedSignal, tamperedSignal, injectedSignal;
    static simsignal_t replayedSignal, droppedSignal, episodeActiveSignal;

    virtual void initialize(int stage) override;
    virtual int numInitStages() const override { return NUM_INIT_STAGES; }
    virtual void handleMessage(cMessage *msg) override;
    virtual void finish() override;

    /** Listens to AccessModel's passStart signal -- episodes align with passes. */
    virtual void receiveSignal(cComponent *src, simsignal_t id, const SimTime& t, cObject *) override;

    virtual void applySeverityProfile();
    virtual void beginEpisode();
    virtual void endEpisode();
    virtual void injectForgedCommand();
    virtual void replayCapturedCommand();
    virtual void injectMaliciousUpdate();
    virtual void spoofResync();

    /** Applies the scenario's effect to a command heading for the satellite. */
    virtual bool handleUplink(cMessage *msg);
    /** Applies the scenario's effect to telemetry heading for the ground. */
    virtual bool handleDownlink(cMessage *msg);

    void truth(const Collector::Fields& f)
    {
        if (collector) collector->recordGroundTruth(f);
    }

  public:
    virtual ~OnPathAttacker();
};

} // namespace lifesat
#endif
