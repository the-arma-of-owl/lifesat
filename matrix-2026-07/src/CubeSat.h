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

    // --- physical channel --------------------------------------------------
    PowerModel power;
    double epochJulianDate = 0;   // from the mobility module's epoch
    double voltageNoiseSigma = 0.01;
    bool illuminatedNow = true;

    // --- logical channel ---------------------------------------------------
    SatMode mode = MODE_NOMINAL;
    std::map<std::string, double> paramStore;

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

  public:
    virtual ~CubeSat();
};

} // namespace lifesat

#endif
