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
    delete lastAcceptedCopy;
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
        eclipseSecondsPerOrbit = par("eclipseSecondsPerOrbit").doubleValue();
    }
    else if (stage == INITSTAGE_SINGLE_MOBILITY) {
        access = check_and_cast<AccessModel *>(getModuleByPath(par("accessModule")));
        cModule *cs = getModuleByPath(par("causalModule"));
        if (cs != nullptr)
            causal = check_and_cast<CausalScenario *>(cs);
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
        // The episode window is a function of the declared schedule, so it is
        // advanced on the clock rather than on whatever happened to occur.
        if (causal != nullptr) {
            causal->tickEpisode();
            // SP-6 selects on the downlink, so considerCausalTarget never runs for that
            // pair and the third cause was not applied there: two of the twelve
            // RB-third-cause runs came out with truth other than third_cause.
            if (causal->isEpisodeOpen() && !causal->hasThirdCause())
                applyCausalThirdCause();
        }
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

    bool wasIlluminated = illuminatedNow;
    illuminatedNow = PowerModel::isIlluminated(eci, PowerModel::sunDirectionEci(jd));
    // The start of the current eclipse segment, sampled from the same geometry
    // the physical channel already runs on. SP-2's window condition is read
    // from it; nothing here looks the orbit up in a table.
    if (!illuminatedNow && (wasIlluminated || eclipseSince < SIMTIME_ZERO))
        eclipseSince = simTime();
    if (illuminatedNow)
        eclipseSince = -1;

    power.step(illuminatedNow, telemetryInterval.dbl());

    emit(batteryVoltageSignal, power.getVoltage());
    emit(illuminatedSignal, (long)(illuminatedNow ? 1 : 0));
}

bool CubeSat::eclipseWindowClear(int steps) const
{
    // common_target.illumination_rule: "the orbit affords 1786.0 s of eclipse,
    // or 178 steps, against the 100 steps this target needs". The window is
    // clear when the remainder of THIS eclipse still holds the whole window.
    if (eclipseSince < SIMTIME_ZERO)
        return false;
    double elapsed = (simTime() - eclipseSince).dbl();
    double needed = steps * telemetryInterval.dbl();
    return elapsed + needed <= eclipseSecondsPerOrbit;
}

std::string CubeSat::paramProvenanceString() const
{
    // std::map for deterministic order; one entry per prevailing write
    std::ostringstream s;
    for (const auto& kv : paramProvenance)
        s << kv.first << ':' << kv.second.first << ':' << kv.second.second << ';';
    return s.str();
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

    // phase 3: target selection, before the packet is written
    // the rule picks the first tm.send at or after contact start + X; tm.send is logged
    // only while in view, so a candidate is offered only then. the selection sets up the
    // arm's onboard mechanism.
    if (causal != nullptr && causal->isActive() && access->isVisible())
        considerCausalTarget(telemetrySeq);

    // measurement noise: the twin sees the noisy measurement, not the true value. both
    // are recorded separately, and the width of D3's tolerance is calibrated from their
    // difference (calibrated, not learned).
    //
    // noise is drawn on every arm; sensor bias is added on top.
    double measured = power.getVoltage() + normal(0, voltageNoiseSigma);
    if (sensorBiasObservations > 0) {
        measured += sensorBias;
        sensorBiasObservations--;
    }
    if (causal != nullptr)
        measured += causal->sensorErrorOffset();
    tm->setBatteryVoltage(measured);
    emit(batteryVoltageMeasuredSignal, measured);
    tm->setIlluminated(illuminatedNow);
    tm->setMode(mode);
    tm->setParamDigest(paramStoreDigest().c_str());
    tm->setRejectedCmdCount(rejectedCmdCount);
    tm->setAcceptedCmdCount(acceptedCmdCount);
    tm->setModeWriteCmdId(modeWriteCmdId);
    tm->setModeWriteSeq(modeWriteSeq);
    tm->setParamWriteProvenance(paramProvenanceString().c_str());
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

// Phase 3 onboard causal injectors
//
// All fire on a single rule: has the target observation been selected. No random draw
// anywhere, and no branch reads which arm it is in and changes the observation. The arm
// selects which mechanism is attached, not what the mechanism sees.

void CubeSat::considerCausalTarget(long seq)
{
    if (!causal->offerTelemetryTarget(seq, illuminatedNow,
                                      eclipseWindowClear(causal->getEclipseSteps())))
        return;

    // the episode window opens before the intervention row. even written at the same
    // instant, a begin appearing after the intervention would tell the reader the wrong
    // order.
    causal->tickEpisode();

    const double deviation = causal->getTargetDeviationV();
    char magnitude[64];

    switch (causal->getPair()) {
        case CausalScenario::SP1:
            std::snprintf(magnitude, sizeof(magnitude), "%+.3f V", deviation);
            if (causal->isFault()) {
                sensorBias = deviation;
                sensorBiasObservations = 1;      // "the same single observation"
                causal->recordIntervention(
                    "fault", "sensor_bias",
                    "onboard voltage sensor bias term, applied before the packet is written",
                    magnitude, "volt", seq, simTime());
            }
            else {
                causal->recordIntervention(
                    "attack", "telemetry_modification",
                    "downlink telemetry payload field batteryVoltage, in transit",
                    magnitude, "volt", seq, simTime());
            }
            break;

        case CausalScenario::SP2:
            // Amendment v5: the manipulated coefficient is chargeRate (sunlit
            // branch).  The headroom gate is evaluated BEFORE the write, on the
            // onboard true voltage, and a run without headroom raises the
            // run-blocking DESIGN_TARGET_UNREACHABLE -- never an abstention.
            std::snprintf(magnitude, sizeof(magnitude), "%.5f V/s",
                          causal->getPerturbedChargeRate());
            if (!hasVoltageHeadroom()) {
                if (collector)
                    collector->logEvent("causal.blocked",
                        {{"outcome", "DESIGN_TARGET_UNREACHABLE"},
                         {"unit", "paired_seed"},
                         {"voltage", std::to_string(power.getVoltage())},
                         {"seq", std::to_string(seq)}});
                break;
            }
            if (causal->isFault()) {
                applyCausalChargeDegradation();
                causal->recordIntervention(
                    "fault", "degradation",
                    "PowerModel chargeRate, lowered by benign degradation with NO causing command",
                    magnitude, "volt_per_second", seq, simTime());
            }
            // on the attack arm the intervention is written when the hostile CMD_UPDATE
            // is accepted; the contract says the row's time equals the accepted command's
            // time, which is after uplink rather than at this observation.
            break;

        case CausalScenario::SP3:
            if (causal->isFault()) {
                applyCausalStoreCorruption();
                causal->recordIntervention(
                    "fault", "store_corruption",
                    "onboard parameter store, corrupted with NO causing command",
                    "exact identifier equality", "identifier", seq, simTime());
            }
            // attack arm: same reasoning, the row is written on acceptance
            break;

        case CausalScenario::SP4:
            std::snprintf(magnitude, sizeof(magnitude), "%+.3f s",
                          causal->getDelayTarget().dbl());
            causal->recordIntervention(
                causal->isAttack() ? "attack" : "fault",
                causal->isAttack() ? "telemetry_withholding" : "coverage_buffering",
                causal->isAttack()
                    ? "downlink delivery time of a selected telemetry observation, withheld on-path"
                    : "ground-side store-and-forward buffering of the same received observation",
                magnitude, "second", seq, simTime());
            break;

        case CausalScenario::SP5:
            std::snprintf(magnitude, sizeof(magnitude), "%+d count",
                          causal->getCounterTargetDelta());
            if (causal->isFault()) {
                applyCausalLedgerFault();
                causal->recordIntervention(
                    "fault", "ledger_loss",
                    "ground-side rejected-command ledger, which loses the records of genuine rejections",
                    magnitude, "count", seq, simTime());
            }
            else {
                causal->recordIntervention(
                    "attack", "counter_tampering",
                    "downlink telemetry payload field rej, in transit",
                    magnitude, "count", seq, simTime());
            }
            break;

        default:
            break;                          // SP-6 is composed on the downlink
    }

    applyCausalThirdCause();
}

void CubeSat::applyCausalDegradation()
{
    // uncommanded. this call raises the discharge rate without passing through an
    // accepted command. the contract requires it: through the command path the fault arm
    // would carry the attack arm's decisive evidence.
    power.setDischargeRate(causal->getPerturbedDischargeRate());
    // the corrupted rate is part of the onboard state and is reported; its divergence
    // from the digest the twin expects is the precondition for publishing the logical
    // alarm with an explicit null link.
    paramStore["dischargeRate"] = causal->getPerturbedDischargeRate();
    paramProvenance["dischargeRate"] = {-1, -1};   // no command: EXPLICIT null
}

void CubeSat::applyCausalChargeDegradation()
{
    // KOMUTSUZ.  Amendment v5: the manipulated coefficient is chargeRate,
    // the SUNLIT branch -- the only one active during a ground contact.
    // dischargeRate is multiplied by nothing while `illuminated` is true, which
    // is why the accepted SP-2 could never produce its observable.
    const double before = power.getChargeRate();
    power.setChargeRate(causal->getPerturbedChargeRate());
    paramStore["chargeRate"] = causal->getPerturbedChargeRate();
    paramProvenance["chargeRate"] = {-1, -1};   // no command: EXPLICIT null
    recordActivation("fault", "chargeRate", before, power.getChargeRate());
}

void CubeSat::recordActivation(const char *arm, const char *coefficient,
                               double before, double after)
{
    // Amendment v5 recording obligation.  first_affected_power_step_time is
    // RECORDED, not inferred: handleMessage runs updatePhysicalState() (the
    // step) BEFORE generateTelemetry() (where the fault write lands), so a
    // write at a grid instant first bites at the NEXT step.  The anchor is the
    // PAIRED target grid instant, never a grid derived from this timestamp.
    if (collector == nullptr || causal == nullptr)
        return;
    const simtime_t t0 = causal->getTargetSendTime() >= SIMTIME_ZERO
                       ? causal->getTargetSendTime() : simTime();
    const simtime_t interval = telemetryInterval;
    const double sinceAnchor = (simTime() - t0).dbl();
    const long steps = (long)std::floor(sinceAnchor / interval.dbl()) + 1;
    const simtime_t firstAffected = t0 + interval * steps;
    const simtime_t tNext = t0 + interval;
    collector->logEvent("causal.activation",
        {{"arm", arm},
         {"coefficient", coefficient},
         {"coefficientBefore", std::to_string(before)},
         {"coefficientAfter", std::to_string(after)},
         {"activationTime", simTime().str()},
         {"targetGridInstant", t0.str()},
         {"firstAffectedPowerStepTime", firstAffected.str()},
         {"activationMarginS", std::to_string((tNext - simTime()).dbl())},
         {"illuminated", illuminatedNow ? "1" : "0"},
         {"eclipseSince", eclipseSince.str()}});
}

bool CubeSat::hasVoltageHeadroom() const
{
    // Amendment v5 clipping closure.  Reads the ONBOARD TRUE voltage, not the
    // noisy telemetry, and is evaluated BEFORE the intervention -- a state both
    // arms share, so the gate stays arm-blind.
    if (causal == nullptr)
        return true;
    const double drop = std::fabs(causal->getPerturbedChargeRate())
                      * causal->getSp2Window().dbl();
    return power.getVoltage()
         > causal->getMinVoltageV() + drop + causal->getClippingMarginV();
}

void CubeSat::applyCausalStoreCorruption()
{
    // uncommanded onboard state corruption: the mode shifts by exactly +1 ordinal. what
    // is observed matches the attack arm exactly; the only separator is that no command
    // wrote it.
    mode = (SatMode)((int)mode + causal->getModeOrdinalDelta());
    modeWriteCmdId = -1;
    modeWriteSeq = -1;
}

void CubeSat::applyCausalLedgerFault()
{
    // real rejections. the contract's hook for this arm is already here: a telecommand
    // whose sequence is not greater than lastAcceptedSequence fails the freshness check
    // (reason 2, rejFresh) and increments the onboard counters. the only thing missing
    // is the corresponding rows in the ground ledger.
    if (!commandAuthEnabled)
        throw cRuntimeError("SP-5 fault arm needs the freshness check enabled; "
                            "without D1 there is no genuine rejection to lose");
    if (lastAcceptedCopy == nullptr)
        throw cRuntimeError("SP-5 fault arm reached its onset with no previously "
                            "accepted command to re-deliver; the run cannot "
                            "produce genuine rejections and is a design failure, "
                            "not an abstention");
    const int delta = causal->getCounterTargetDelta();
    // ledger loss
    // the ground ledger records none of these rejections. the counter rose and the rows
    // are absent, so from the ground the jump looks unexplained, exactly as on the attack
    // arm. the only separator is that the onboard copy moves with it.
    suppressRejectLedger += delta;
    // benign fault: a corrupted command buffer redelivers an already accepted command
    // delta times. each delivery produces a real freshness rejection, so the counter is
    // not fabricated.
    for (int i = 0; i < delta; i++)
        handleTelecommand(lastAcceptedCopy->dup());
}

void CubeSat::recordHostileConfigIntervention(const Telecommand *tc)
{
    char magnitude[64];
    if (causal->getPair() == CausalScenario::SP2) {
        std::snprintf(magnitude, sizeof(magnitude), "%.5f V/s",
                      causal->getPerturbedChargeRate());
        causal->recordIntervention(
            "attack", "hostile_config",
            "PowerModel chargeRate, via an accepted CMD_UPDATE carrying paramKey 'chargeRate'",
            magnitude, "volt_per_second", causal->getTargetSeq(), simTime());
    }
    else if (causal->getPair() == CausalScenario::SP3) {
        causal->recordIntervention(
            "attack", "hostile_config",
            "onboard parameter store, via an accepted hostile configuration command",
            "exact identifier equality", "identifier",
            causal->getTargetSeq(), simTime());
    }
}

void CubeSat::applyCausalThirdCause()
{
    if (causal->getRobustnessArm() != CausalScenario::RB_THIRD_CAUSE)
        return;
    // an unmodelled third cause, concurrent with the arm's intervention: a state jump
    // the twin knows nothing about. its prediction drifts, which is the point -- the arm
    // probes the decision rule outside its support.
    double magnitude = causal->getRobustnessMagnitude();
    if (magnitude == 0.0)
        magnitude = 0.10;      // robustness_spec declares no magnitude for this arm
    power.setVoltage(power.getVoltage() - magnitude);
    char text[64];
    std::snprintf(text, sizeof(text), "%+.3f V", -magnitude);
    causal->recordThirdCause("PowerModel voltage, unmodelled concurrent state jump",
                             text, "volt");
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
        // the id of the command that wrote the logical state is kept onboard and
        // reported in telemetry; the twin binds its logical alarm to it. lineage attaches
        // to the component written, so a routine gain write does not overwrite the mode
        // component's lineage.
        if (tc->getCommandType() == CMD_SET_MODE) {
            modeWriteCmdId = tc->getCommandId();
            modeWriteSeq = tc->getSequence();
        }
        else if (tc->getCommandType() == CMD_SET_PARAM
                 || tc->getCommandType() == CMD_UPDATE) {
            paramProvenance[tc->getParamKey()] =
                {tc->getCommandId(), tc->getSequence()};
        }
        // the command SP-5's benign buffer fault will redeliver
        delete lastAcceptedCopy;
        lastAcceptedCopy = tc->dup();
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
                // Amendment v5: the SP-2 attack arm reaches the SAME sunlit
                // coefficient the fault arm reaches, but through an accepted
                // command -- which is precisely its decisive evidence.
                if (std::string(tc->getParamKey()) == "chargeRate") {
                    const double before = power.getChargeRate();
                    power.setChargeRate(tc->getParamValue());
                    recordActivation("attack", "chargeRate", before,
                                     power.getChargeRate());
                }
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
        // phase 3, SP-2/SP-3 attack arm: the row time is the accepted command's time,
        // which is exactly here.
        if (causal != nullptr && causal->isHostileCommand(tc->getCommandId()))
            recordHostileConfigIntervention(tc);
    }
    else {
        rejectedCmdCount++;
        emit(tcRejectedSignal, 1L);
        emit(tcRejectReasonSignal, reason);
        // SP-5 fault: ground ledger loss
        // the rejection happened and the onboard counter rose; only the ground's record
        // is missing. suppressing the row is exactly what "the ledger lost these
        // rejections" means.
        bool suppressed = false;
        if (suppressRejectLedger > 0) {
            suppressRejectLedger--;
            suppressed = true;
        }
        if (collector && !suppressed)
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
