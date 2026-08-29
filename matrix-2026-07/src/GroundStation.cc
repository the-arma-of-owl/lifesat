#include "GroundStation.h"

#include "CubeSat.h"

namespace lifesat {

Define_Module(GroundStation);

simsignal_t GroundStation::tcGeneratedSignal = cComponent::registerSignal("tcGenerated");
simsignal_t GroundStation::tcSentSignal = cComponent::registerSignal("tcSent");
simsignal_t GroundStation::tmReceivedSignal = cComponent::registerSignal("tmReceived");
simsignal_t GroundStation::tmLatencySignal = cComponent::registerSignal("tmLatency");
simsignal_t GroundStation::tmAgeSignal = cComponent::registerSignal("tmAge");

GroundStation::~GroundStation()
{
    cancelAndDelete(commandTimer);
    cancelAndDelete(updateTimer);
}

void GroundStation::initialize(int stage)
{
    cSimpleModule::initialize(stage);
    if (stage == INITSTAGE_LOCAL) {
        commandInterval = par("commandInterval");
        commandsOnlyDuringPass = par("commandsOnlyDuringPass");
        signCommands = par("signCommands");
        authKey = par("authKey").stdstringValue();
        proposeUpdates = par("proposeUpdates");
        twinValidation = par("twinValidation");
        updateKey = par("updateKey").stdstringValue();
        updateInterval = par("updateInterval");
        retryInterval = par("updateRetryInterval");
        updateValue = par("updateValue");
    }
    else if (stage == INITSTAGE_SINGLE_MOBILITY) {
        access = check_and_cast<AccessModel *>(getModuleByPath(par("accessModule")));
        cModule *col = getModuleByPath("^.collector");
        if (col != nullptr)
            collector = check_and_cast<Collector *>(col);
        const char *twinPath = par("twinModule");
        if (*twinPath)
            twin = check_and_cast<Twin *>(getModuleByPath(twinPath));
        const char *flowPath = par("flowDetectorModule");
        if (*flowPath)
            flow = check_and_cast<FlowDetector *>(getModuleByPath(flowPath));
        const char *randPath = par("randomDetectorModule");
        if (*randPath)
            randomDet = check_and_cast<RandomDetector *>(getModuleByPath(randPath));
        commandTimer = new cMessage("commandTick");
        scheduleAt(simTime() + commandInterval, commandTimer);
        if (proposeUpdates) {
            updateTimer = new cMessage("updateTick");
            scheduleAt(simTime() + updateInterval, updateTimer);
        }
    }
}

void GroundStation::handleMessage(cMessage *msg)
{
    if (msg == commandTimer) {
        generateTelecommand();
        scheduleAt(simTime() + commandInterval, commandTimer);
        return;
    }
    if (msg == updateTimer) {
        // a candidate waiting for contact stays queued rather than dropped. coverage
        // is 1.4%, so the timer almost never lands inside a pass and dropping would
        // make the pre-uplink validation experiment unrunnable. operators wait for the
        // next window too.
        bool sent = proposeConfigurationUpdate();
        scheduleAt(simTime() + (sent ? updateInterval : retryInterval), updateTimer);
        return;
    }
    if (auto *tm = dynamic_cast<Telemetry *>(msg)) {
        handleTelemetry(tm);
        return;
    }
    throw cRuntimeError("GroundStation: unexpected message '%s'", msg->getName());
}

void GroundStation::generateTelecommand()
{
    // no contact means no command is issued; a real operator does not uplink outside
    // a window. an unissued command is counted separately, not as a loss.
    if (commandsOnlyDuringPass && !access->isVisible()) {
        tcSuppressedNoAccess++;
        return;
    }

    auto *tc = new Telecommand("TC");
    tc->setCommandId(++commandId);
    tc->setSequence(++sequence);
    tc->setIssuedAt(simTime());
    tc->setCommandType(CMD_SET_PARAM);
    tc->setParamKey("gain");
    tc->setParamValue(1.0 + 0.1 * (commandId % 5));
    if (signCommands) {
        std::string body = authenticatedBody(tc);
        tc->setPayloadDigest(Sha256::hex(body).substr(0, 16).c_str());
        tc->setAuthTag(hmacSha256Hex(authKey, body).c_str());
    }
    tc->setByteLength(signCommands ? 64 : 32);   // the tag takes space

    tcGenerated++; tcSent++;
    emit(tcGeneratedSignal, 1L);
    emit(tcSentSignal, 1L);
    if (collector)
        collector->logEvent("tc.send", {{"cmdId", std::to_string(commandId)},
                                        {"seq", std::to_string(sequence)}});
    // operator gate: every sent command is written to the twin's logical channel
    if (twin)
        twin->noteApprovedCommand(tc);
    send(tc, "radioOut");
}

bool GroundStation::proposeConfigurationUpdate()
{
    // no contact means no uplink; the candidate waits for the next window
    if (commandsOnlyDuringPass && !access->isVisible())
        return false;
    updatesProposed++;

    // gate: try on the twin first
    // not a repeat of D1. D1 answers who sent the command; this gate answers whether
    // the value leaves the mission safe even when the sender is authorised. the
    // candidate is validly signed, so D1 passes it by definition.
    if (twinValidation && twin != nullptr) {
        std::string reason;
        Twin::UpdateVerdict verdict =
            twin->validateUpdate(updateKey, updateValue, reason);
        if (verdict != Twin::UPDATE_APPROVED) {
            // fail-closed: only APPROVED passes. UNSUPPORTED does not mean "no
            // problem seen"; it means the gate cannot say anything about that
            // parameter, and uplinking an unevaluated update equals having no gate.
            updatesBlocked++;
            if (verdict == Twin::UPDATE_UNSUPPORTED)
                updatesUnsupported++;
            if (collector)
                collector->logEvent(
                    verdict == Twin::UPDATE_UNSUPPORTED ? "update.unsupported"
                                                        : "update.blocked",
                    {{"paramKey", updateKey},
                     {"paramValue", std::to_string(updateValue)},
                     {"verdict", verdict == Twin::UPDATE_UNSUPPORTED
                                     ? "unsupported" : "rejected"},
                     {"reason", reason}});
            // never sent to the satellite: this is prevention, not detection. the
            // candidate is not retried either, since the verdict was not positive.
            return true;
        }
    }

    auto *tc = new Telecommand("TC-update");
    tc->setCommandId(++commandId);
    tc->setSequence(++sequence);
    tc->setIssuedAt(simTime());
    tc->setCommandType(CMD_UPDATE);
    tc->setParamKey(updateKey.c_str());
    tc->setParamValue(updateValue);
    if (signCommands) {
        std::string body = authenticatedBody(tc);
        tc->setPayloadDigest(Sha256::hex(body).substr(0, 16).c_str());
        tc->setAuthTag(hmacSha256Hex(authKey, body).c_str());
    }
    tc->setByteLength(signCommands ? 64 : 32);

    updatesUplinked++;
    tcGenerated++; tcSent++;
    emit(tcGeneratedSignal, 1L);
    emit(tcSentSignal, 1L);
    if (collector)
        collector->logEvent("update.uplink", {{"cmdId", std::to_string(commandId)},
                                              {"paramKey", updateKey},
                                              {"paramValue", std::to_string(updateValue)}});
    if (twin)
        twin->noteApprovedCommand(tc);
    send(tc, "radioOut");
    return true;
}

void GroundStation::handleTelemetry(Telemetry *tm)
{
    tmReceived++;
    emit(tmReceivedSignal, 1L);

    simtime_t age = simTime() - tm->getSourceTime();
    emit(tmAgeSignal, age);
    emit(tmLatencySignal, age);   // identical in phase 1; they diverge once A4 adds delay

    if (collector)
        collector->logEvent("tm.recv", {{"seq", std::to_string(tm->getTelemetrySeq())},
                                        {"ageS", age.str()},
                                        {"vbat", std::to_string(tm->getBatteryVoltage())},
                                        {"mode", std::to_string(tm->getMode())},
                                        {"rej", std::to_string(tm->getRejectedCmdCount())}});
    // all three detectors see telemetry only -- no labels, no answer key
    if (flow)
        flow->observePacket(tm->getBitLength());
    if (randomDet)
        randomDet->observe();
    if (twin)
        twin->observeTelemetry(tm);
    delete tm;
}

void GroundStation::finish()
{
    recordScalar("tcGenerated", tcGenerated);
    recordScalar("tcSent", tcSent);
    recordScalar("tcSuppressedNoAccess", tcSuppressedNoAccess);
    recordScalar("tmReceived", tmReceived);
    recordScalar("updatesProposed", updatesProposed);
    recordScalar("updatesBlocked", updatesBlocked);
    recordScalar("updatesUplinked", updatesUplinked);
    recordScalar("updatesUnsupported", updatesUnsupported);
}

} // namespace lifesat
