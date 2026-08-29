//
// LIFESAT satellite side
//
#include "CubeSat.h"

#include <sstream>

#include "inet/common/geometry/common/Wgs84.h"

namespace lifesat {

Define_Module(CubeSat);

simsignal_t CubeSat::batteryVoltageSignal = cComponent::registerSignal("batteryVoltage");
simsignal_t CubeSat::batteryVoltageMeasuredSignal = cComponent::registerSignal("batteryVoltageMeasured");
simsignal_t CubeSat::illuminatedSignal = cComponent::registerSignal("illuminated");
simsignal_t CubeSat::tmGeneratedSignal = cComponent::registerSignal("tmGenerated");
simsignal_t CubeSat::tcAcceptedSignal = cComponent::registerSignal("tcAccepted");
simsignal_t CubeSat::tcRejectedSignal = cComponent::registerSignal("tcRejected");
simsignal_t CubeSat::tcRejectReasonSignal = cComponent::registerSignal("tcRejectReason");

CubeSat::~CubeSat()
{
    cancelAndDelete(telemetryTimer);
}

void CubeSat::initialize(int stage)
{
    cSimpleModule::initialize(stage);

    if (stage == INITSTAGE_LOCAL) {
        telemetryInterval = par("telemetryInterval");
        voltageNoiseSigma = par("voltageNoiseSigma");
        power.configure(par("nominalVoltage").doubleValue(),
                        par("minVoltage").doubleValue(),
                        par("maxVoltage").doubleValue(),
                        par("chargeRate").doubleValue(),
                        par("dischargeRate").doubleValue());
        mode = (SatMode)par("initialMode").intValue();
        commandAuthEnabled = par("commandAuthEnabled");
        authKey = par("authKey").stdstringValue();
    }
    else if (stage == INITSTAGE_SINGLE_MOBILITY) {
        access = check_and_cast<AccessModel *>(getModuleByPath(par("accessModule")));
        mobility = check_and_cast<SatelliteMobility *>(
                       getModuleByPath(par("satelliteMobilityModule")));
        cModule *c = getModuleByPath("^.collector");
        if (c != nullptr)
            collector = check_and_cast<Collector *>(c);

        // take the epoch from the mobility module: defined once in the ini, not
        // copied here. empty falls back to the TLE's own epoch.
        const char *epoch = mobility->par("epoch");
        if (*epoch) {
            int y, mo, d, h, mi; double s;
            if (sscanf(epoch, "%d-%d-%dT%d:%d:%lf", &y, &mo, &d, &h, &mi, &s) != 6)
                throw cRuntimeError("cannot parse mobility epoch '%s'", epoch);
            epochJulianDate = wgs84::julianDateFromUtc(y, mo, d, h, mi, s);
        }
        else
            throw cRuntimeError("mobility epoch must be set explicitly for the power model");

        telemetryTimer = new cMessage("telemetryTick");
        scheduleAt(simTime() + telemetryInterval, telemetryTimer);
    }
}

void CubeSat::handleMessage(cMessage *msg)
{
    if (msg == telemetryTimer) {
        updatePhysicalState();
        generateTelemetry();
        scheduleAt(simTime() + telemetryInterval, telemetryTimer);
        return;
    }
    if (auto *tc = dynamic_cast<Telecommand *>(msg)) {
        handleTelecommand(tc);
        return;
    }
    throw cRuntimeError("CubeSat received unexpected message '%s'", msg->getName());
}

void CubeSat::updatePhysicalState()
{
    // illumination from real geometry: the ECEF position is rotated to ECI, the sun
    // direction comes from the almanac, and a cylindrical shadow test is applied.
    Coord ecef = mobility->getCurrentPosition();

    // ECEF to ECI(TEME): inverse rotation by GMST. the Julian date derives from the
    // mobility module's epoch so the ini stays the single definition.
    double jd = epochJulianDate + simTime().dbl() / 86400.0;
    double g = wgs84::gmst(jd);
    Coord eci(std::cos(g) * ecef.x - std::sin(g) * ecef.y,
              std::sin(g) * ecef.x + std::cos(g) * ecef.y,
              ecef.z);

    illuminatedNow = PowerModel::isIlluminated(eci, PowerModel::sunDirectionEci(jd));
    power.step(illuminatedNow, telemetryInterval.dbl());

    emit(batteryVoltageSignal, power.getVoltage());
    emit(illuminatedSignal, (long)(illuminatedNow ? 1 : 0));
}

std::string CubeSat::paramStoreDigest() const
{
    std::ostringstream s;
    for (const auto& kv : paramStore)          // std::map => deterministic order
        s << kv.first << '=' << kv.second << ';';
    return Sha256::hex(s.str()).substr(0, 16);
}

void CubeSat::generateTelemetry()
{
    auto *tm = new Telemetry("TM");
    tm->setTelemetrySeq(++telemetrySeq);
    tm->setSourceTime(simTime());
    // measurement noise: the twin sees the noisy measurement, not the true value. both
    // are recorded separately, and the width of D3's tolerance is calibrated from their
    // difference.
    double measured = power.getVoltage() + normal(0, voltageNoiseSigma);
    tm->setBatteryVoltage(measured);
    emit(batteryVoltageMeasuredSignal, measured);
    tm->setIlluminated(illuminatedNow);
    tm->setMode(mode);
    tm->setParamDigest(paramStoreDigest().c_str());
    tm->setRejectedCmdCount(rejectedCmdCount);
    tm->setAcceptedCmdCount(acceptedCmdCount);
    tm->setByteLength(64);

    tmGeneratedCount++;
    emit(tmGeneratedSignal, 1L);

    // with no visibility telemetry is produced but cannot be transmitted; the loss
    // reason is coverage. a real mission would write to onboard storage (L5).
    if (!access->isVisible()) {
        tmDroppedNoAccess++;
        if (collector)
            collector->count("tm.droppedNoAccess");
        delete tm;
        return;
    }

    if (collector)
        collector->logEvent("tm.send", {{"seq", std::to_string(telemetrySeq)},
                                        {"vbat", std::to_string(tm->getBatteryVoltage())},
                                        {"mode", std::to_string((int)mode)},
                                        {"rej", std::to_string(rejectedCmdCount)}});
    send(tm, "radioOut");
}

std::string authenticatedBody(const Telecommand *tc)
{
    // the tag covers every field carrying command meaning, sequence included. A1's
    // field tampering and A3's replay therefore both keep a valid tag but fail the
    // freshness check.
    std::ostringstream s;
    s << tc->getCommandId() << '|' << tc->getSequence() << '|'
      << tc->getIssuedAt() << '|' << tc->getCommandType() << '|'
      << tc->getParamKey() << '|' << tc->getParamValue() << '|' << tc->getTargetMode();
    return s.str();
}

void CubeSat::handleTelecommand(Telecommand *tc)
{
    tcReceivedCount++;

    bool accepted = true;
    long reason = 0;

    if (commandAuthEnabled) {
        // the three behaviours, in order.
        // 1) authentication: compute the tag and compare
        std::string expected = hmacSha256Hex(authKey, authenticatedBody(tc));
        if (!constantTimeEquals(expected, tc->getAuthTag())) {
            accepted = false; reason = 1; rejAuth++;
        }
        // 2) freshness: the sequence number must strictly increase (a command count
        //    or nonce against replay and spoofing)
        else if (tc->getSequence() <= lastAcceptedSequence) {
            accepted = false; reason = 2; rejFresh++;
        }
        // 3) integrity: recompute the body digest
        else if (std::string(tc->getPayloadDigest())
                 != Sha256::hex(authenticatedBody(tc)).substr(0, 16)) {
            accepted = false; reason = 3; rejIntegrity++;
        }
    }

    if (accepted) {
        lastAcceptedSequence = tc->getSequence();
        acceptedCmdCount++;
        emit(tcAcceptedSignal, 1L);
        switch (tc->getCommandType()) {
            case CMD_SET_PARAM:
                paramStore[tc->getParamKey()] = tc->getParamValue();
                break;
            case CMD_UPDATE:
                // A6: a configuration update writes to the logical channel (the
                // parameter store) and, when it declares a physical effect, to the
                // power model. without the second, a behaviourally unsafe update
                // could not be measured at all: every update would be a digest change
                // and pre-uplink validation would have nothing to check.
                paramStore[tc->getParamKey()] = tc->getParamValue();
                if (std::string(tc->getParamKey()) == "dischargeRate")
                    power.setDischargeRate(tc->getParamValue());
                break;
            case CMD_SET_MODE:
                mode = (SatMode)tc->getTargetMode();
                break;
            default:
                break;
        }
        if (collector)
            collector->logEvent("tc.accept", {{"cmdId", std::to_string(tc->getCommandId())},
                                              {"seq", std::to_string(tc->getSequence())},
                                              {"type", std::to_string(tc->getCommandType())}});
    }
    else {
        rejectedCmdCount++;
        emit(tcRejectedSignal, 1L);
        emit(tcRejectReasonSignal, reason);
        if (collector)
            collector->logEvent("tc.reject", {{"cmdId", std::to_string(tc->getCommandId())},
                                              {"seq", std::to_string(tc->getSequence())},
                                              {"reason", reason == 1 ? "auth"
                                                        : reason == 2 ? "freshness" : "integrity"}});
    }
    delete tc;
}

void CubeSat::finish()
{
    recordScalar("tmGenerated", tmGeneratedCount);
    recordScalar("tmDroppedNoAccess", tmDroppedNoAccess);
    recordScalar("tcReceived", tcReceivedCount);
    recordScalar("tcAccepted", acceptedCmdCount);
    recordScalar("tcRejected", rejectedCmdCount);
    recordScalar("tcRejectedAuth", rejAuth);
    recordScalar("tcRejectedFreshness", rejFresh);
    recordScalar("tcRejectedIntegrity", rejIntegrity);
    recordScalar("finalVoltage", power.getVoltage());
}

} // namespace lifesat
