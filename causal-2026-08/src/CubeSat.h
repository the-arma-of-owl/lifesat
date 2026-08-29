//
// LIFESAT satellite side
//
#ifndef __LIFESAT_CUBESAT_H
#define __LIFESAT_CUBESAT_H

#include <map>
#include <string>

#include "inet/common/INETDefs.h"
#include "inet/mobility/single/SatelliteMobility.h"

#include "AccessModel.h"
#include "CausalScenario.h"
#include "Collector.h"
#include "HashChain.h"
#include "LifesatPackets_m.h"
#include "Hmac.h"
#include "PowerModel.h"

namespace lifesat {

using namespace inet;

/**
 * The canonical body over which a command's authentication tag is computed.
 *
 * The ground and the satellite must produce the **same** body; this is a protocol
 * definition, not an internal detail of the class.  Hence a free function.
 */
std::string authenticatedBody(const Telecommand *tc);

/**
 * Satellite: command handler + parameter store + telemetry generator.
 *
 * This is the source of the three state channels; the twin produces the expected
 * value of the same channels independently and compares. They do not share code:
 * sharing it would make the deviation vanish by construction.
 */
class CubeSat : public cSimpleModule
{
  protected:
    AccessModel *access = nullptr;
    SatelliteMobility *mobility = nullptr;
    Collector *collector = nullptr;
    CausalScenario *causal = nullptr;

    // --- phase 3: causal injector state ------------------------------------
    double sensorBias = 0.0;         // SP-1 fault, applied on a single observation
    int sensorBiasObservations = 0;  // observations remaining
    long suppressRejectLedger = 0;   // SP-5 fault, ledger rows to be lost
    Telecommand *lastAcceptedCopy = nullptr;  // SP-5 fault, material for the redelivery
    simtime_t eclipseSince = -1;     // start of the eclipse segment currently in progress
    double eclipseSecondsPerOrbit = 1786.0;

    // --- physical channel --------------------------------------------------
    PowerModel power;
    double epochJulianDate = 0;   // from the mobility module's epoch
    double voltageNoiseSigma = 0.01;
    bool illuminatedNow = true;

    // --- logical channel ---------------------------------------------------
    SatMode mode = MODE_NOMINAL;
    std::map<std::string, double> paramStore;
    // the accepted command that last wrote the logical state. an uncommanded write
    // (phase 3 fault arms) resets it to -1 and the twin then publishes an explicit null.
    // this is command lineage, not a label.
    long modeWriteCmdId = -1;
    long modeWriteSeq = -1;
    // key -> (cmdId, seq); an uncommanded write enters (-1, -1)
    std::map<std::string, std::pair<long, long>> paramProvenance;

    // --- security channel --------------------------------------------------
    long rejectedCmdCount = 0;
    long acceptedCmdCount = 0;

    // --- D1 ---------------------------------------------------------------
    bool commandAuthEnabled = false;
    std::string authKey;
    long lastAcceptedSequence = 0;   // freshness: the sequence number must strictly increase
    long rejAuth = 0, rejFresh = 0, rejIntegrity = 0;

    // --- telemetri ---------------------------------------------------------
    simtime_t telemetryInterval;
    cMessage *telemetryTimer = nullptr;
    long telemetrySeq = 0;

    // accounting (phase 1 gate)
    long tmGeneratedCount = 0;
    long tmDroppedNoAccess = 0;
    long tcReceivedCount = 0;

    static simsignal_t batteryVoltageSignal;
    static simsignal_t batteryVoltageMeasuredSignal;
    static simsignal_t illuminatedSignal;
    static simsignal_t tmGeneratedSignal;
    static simsignal_t tcAcceptedSignal;
    static simsignal_t tcRejectedSignal;
    static simsignal_t tcRejectReasonSignal;

  protected:
    virtual void initialize(int stage) override;
    virtual int numInitStages() const override { return NUM_INIT_STAGES; }
    virtual void handleMessage(cMessage *msg) override;
    virtual void finish() override;

    virtual void handleTelecommand(Telecommand *tc);
    virtual void generateTelemetry();
    virtual void updatePhysicalState();

    /** Order-independent digest of the parameter store -- the twin must produce the same one. */
    virtual std::string paramStoreDigest() const;

    /** Per-key command provenance of the parameter store, in telemetry form. */
    virtual std::string paramProvenanceString() const;

    // --- phase 3: onboard causal injectors ----------------------------------
    /** Selects the target observation and, if selected, arms the arm's onboard mechanism. */
    virtual void considerCausalTarget(long seq);

    /**
     * SP-2 fault: COMMANDLESS corruption of the discharge rate.
     * Going through an accepted command would manufacture, in the fault arm, the
     * very evidence that identifies the attack arm; PowerModel::setDischargeRate
     * is therefore called directly and the command ledger is left untouched.
     */
    virtual void applyCausalDegradation();
    /** Amendment v5: command-free SUNLIT-branch degradation (SP-2 fault arm). */
    virtual void applyCausalChargeDegradation();
    /** Records one coefficient write with everything the equality needs. */
    virtual void recordActivation(const char *arm, const char *coefficient,
                                  double before, double after);
    /** True when the onboard true voltage can hold the whole window. */
    virtual bool hasVoltageHeadroom() const;

    /** SP-3 fault: commandless onboard state corruption (mode +1 ordinal). */
    virtual void applyCausalStoreCorruption();

    /**
     * SP-5 fault: REAL onboard rejections plus the ground ledger losing those rows.
     * The rejections go through the freshness path the contract itself points at
     * (CubeSat.cc:177-180); this is not a manufactured counter increment.
     */
    virtual void applyCausalLedgerFault();

    /** RB-third-cause: an unmodelled, simultaneous third cause. */
    virtual void applyCausalThirdCause();

    /** SP-2/SP-3 attack arm: the row is written the moment the command is ACCEPTED. */
    virtual void recordHostileConfigIntervention(const Telecommand *tc);

    /** SP-2's "window entirely in eclipse" condition, from the measured eclipse duration. */
    virtual bool eclipseWindowClear(int steps) const;

  public:
    virtual ~CubeSat();
};

} // namespace lifesat

#endif
