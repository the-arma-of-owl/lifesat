//
// LIFESAT on-path attacker
//
#include "OnPathAttacker.h"

// A2v re-signs with a compromised key, so it needs the same body serialisation and
// HMAC the satellite verifies with.
#include "CubeSat.h"
#include "Hmac.h"

namespace lifesat {

Define_Module(OnPathAttacker);

simsignal_t OnPathAttacker::observedSignal = cComponent::registerSignal("observed");
simsignal_t OnPathAttacker::tamperedSignal = cComponent::registerSignal("tampered");
simsignal_t OnPathAttacker::injectedSignal = cComponent::registerSignal("injected");
simsignal_t OnPathAttacker::replayedSignal = cComponent::registerSignal("replayed");
simsignal_t OnPathAttacker::droppedSignal = cComponent::registerSignal("dropped");
simsignal_t OnPathAttacker::episodeActiveSignal = cComponent::registerSignal("episodeActive");

OnPathAttacker::~OnPathAttacker()
{
    cancelAndDelete(episodeStart);
    cancelAndDelete(episodeEnd);
    cancelAndDelete(injectTimer);
    delete captured;
    delete lastSeen;
    delete capturedFrame;
}

void OnPathAttacker::applySeverityProfile()
{
    // all three profiles were fixed before the runs. the literature gives no single
    // validated value for this configuration, so each is a design assumption and
    // enters the sensitivity sweep.
    // separate rates for TC and TM: telemetry is produced every 10 s and commands
    // every 30 s. a single rate would make the same severity three times denser on
    // the downlink and miss the realistic anomaly density criterion.
    const std::string s = par("severity").stdstringValue();
    if (s == "low")         { affectedFractionTc = 0.15; affectedFractionTm = 0.06; addedDelay = 5;   injectionInterval = 180; paramDelta = 0.20; voltageDelta = 0.05; }
    else if (s == "medium") { affectedFractionTc = 0.30; affectedFractionTm = 0.15; addedDelay = 30;  injectionInterval = 90;  paramDelta = 0.50; voltageDelta = 0.15; }
    else if (s == "high")   { affectedFractionTc = 0.60; affectedFractionTm = 0.25; addedDelay = 120; injectionInterval = 45;  paramDelta = 1.00; voltageDelta = 0.40; }
    else throw cRuntimeError("unknown severity '%s' (low|medium|high)", s.c_str());
}

void OnPathAttacker::initialize(int stage)
{
    cSimpleModule::initialize(stage);
    if (stage == INITSTAGE_LOCAL) {
        scenario = par("scenario").stdstringValue();
        compromisedKey = par("compromisedKey").stdstringValue();
        if (scenario == "A2v" && compromisedKey.empty())
            throw cRuntimeError("A2v requires a compromised key "
                                "(attacker.compromisedKey); the crypto is not broken, it is stolen");
        attackedPassFraction = par("attackedPassFraction");
        episodeStartFraction = par("episodeStartFraction");
        episodeSpanFraction = par("episodeSpanFraction");
        applySeverityProfile();
        episodeStart = new cMessage("episodeStart");
        episodeEnd = new cMessage("episodeEnd");
        injectTimer = new cMessage("inject");
    }
    else if (stage == INITSTAGE_SINGLE_MOBILITY) {
        access = check_and_cast<AccessModel *>(getModuleByPath(par("accessModule")));
        cModule *col = getModuleByPath("^.collector");
        if (col != nullptr)
            collector = check_and_cast<Collector *>(col);
        cModule *cs = getModuleByPath(par("causalModule"));
        if (cs != nullptr)
            causal = check_and_cast<CausalScenario *>(cs);

        // in causal mode the old scenario machine is never set up. subscribing to
        // passStart alone means a uniform() draw, and that draw breaks the two arms
        // consuming the same stream on the same seed.
        if (causal != nullptr && causal->isActive()) {
            emit(episodeActiveSignal, 0L);
            return;
        }

        if (scenario != "B0") {
            // episodes sit inside passes: the attacker knows when traffic occurs from
            // the schedule, since contact timing is public.
            access->subscribe("passStart", this);
            truth({{"event", "attacker.armed"}, {"scenario", scenario},
                   {"severity", par("severity").stdstringValue()}});
        }
        emit(episodeActiveSignal, 0L);
    }
}

void OnPathAttacker::receiveSignal(cComponent *, simsignal_t, const SimTime&, cObject *)
{
    // new pass. will this one be attacked?
    if (episodeActive || uniform(0, 1) >= attackedPassFraction)
        return;
    // pass duration is not known in advance; start and duration are drawn uniformly
    // and scaled by the typical pass length.
    simtime_t typicalPass = 330;
    simtime_t offset = uniform(0, 2 * episodeStartFraction) * typicalPass;
    simtime_t span = uniform(0.5, 1.5) * episodeSpanFraction * typicalPass;
    cancelEvent(episodeStart);
    cancelEvent(episodeEnd);
    scheduleAt(simTime() + offset, episodeStart);
    scheduleAt(simTime() + offset + span, episodeEnd);
}

void OnPathAttacker::beginEpisode()
{
    episodeActive = true;
    episodeCount++;
    emit(episodeActiveSignal, 1L);
    truth({{"event", "episode.begin"}, {"scenario", scenario},
           {"episode", std::to_string(episodeCount)}});
    if (scenario == "A2" || scenario == "A3" || scenario == "A6" || scenario == "A7c")
        scheduleAt(simTime() + injectionInterval, injectTimer);
    if (scenario == "A8")
        spoofResync();
}

void OnPathAttacker::endEpisode()
{
    episodeActive = false;
    emit(episodeActiveSignal, 0L);
    cancelEvent(injectTimer);
    frozenRejectedCount = -1;   // A7c: let the next episode capture a new baseline
    truth({{"event", "episode.end"}, {"episode", std::to_string(episodeCount)}});
}

void OnPathAttacker::injectForgedCommand()
{
    auto *tc = new Telecommand("TC-forged");
    tc->setCommandId(++forgedId);
    tc->setSequence(forgedId);
    tc->setIssuedAt(simTime());
    tc->setCommandType(CMD_SET_PARAM);
    tc->setParamKey("gain");
    tc->setParamValue(9.99);           // a value the ground never approved
    tc->setByteLength(32);

    injected++;
    emit(injectedSignal, 1L);
    // A7c reuses the A2 injection mechanism for a different purpose: produce a
    // command D1 will reject, then erase its trace (rejectedCmdCount) on the
    // downlink.
    truth({{"event", "inject"}, {"scenario", scenario},
           {"cmdId", std::to_string(forgedId)},
           {"paramKey", "gain"}, {"paramValue", "9.99"}});
    send(tc, "linkOut");
}

void OnPathAttacker::injectMaliciousUpdate()
{
    // A6 -- CMD_UPDATE with no valid tag. accepted under D0, where it perturbs the
    // twin's logical channel; rejected under D1. the validly signed variant needs key
    // compromise and is out of scope (L7).
    auto *tc = new Telecommand("TC-update");
    tc->setCommandId(++forgedId);
    tc->setSequence(forgedId);
    tc->setIssuedAt(simTime());
    tc->setCommandType(CMD_UPDATE);
    tc->setParamKey("fw_version");
    tc->setParamValue(9.9);            // a version stamp the operator never approved

    injected++;
    emit(injectedSignal, 1L);
    truth({{"event", "inject"}, {"scenario", "A6"},
           {"cmdId", std::to_string(forgedId)}, {"commandType", "CMD_UPDATE"},
           {"paramKey", "fw_version"}, {"paramValue", "9.9"}});
    send(tc, "linkOut");
}

void OnPathAttacker::spoofResync()
{
    // A8 -- spoofed telemetry injected at pass start, where dt is largest and the
    // physical bound widest. material derives only from telemetry the attacker
    // already saw on the wire; no access to satellite internals.
    if (lastSeen == nullptr)
        return;             // no telemetry was seen before this pass
    auto *tm = lastSeen->dup();
    tm->setName("TM-spoofed");
    tm->setTelemetrySeq(lastSeen->getTelemetrySeq() + 1);
    tm->setSourceTime(simTime());
    double before = tm->getBatteryVoltage();
    tm->setBatteryVoltage(before + voltageDelta);

    tampered++;
    emit(tamperedSignal, 1L);
    truth({{"event", "spoof"}, {"scenario", "A8"},
           {"tmSeq", std::to_string(tm->getTelemetrySeq())},
           {"field", "batteryVoltage"},
           {"before", std::to_string(before)},
           {"after", std::to_string(tm->getBatteryVoltage())}});
    send(tm, "groundOut");
}

void OnPathAttacker::replayCapturedCommand()
{
    if (captured == nullptr)
        return;
    auto *copy = captured->dup();
    replayed++;
    emit(replayedSignal, 1L);
    truth({{"event", "replay"}, {"scenario", "A3"},
           {"cmdId", std::to_string(captured->getCommandId())},
           {"seq", std::to_string(captured->getSequence())}});
    send(copy, "linkOut");
}

// Phase 3 deterministic causal injectors

void OnPathAttacker::causalDownlink(Telemetry *tm, bool& consumed)
{
    consumed = false;

    // The attacker is the instrument of the attack arm and of nothing else.
    //
    // Fault-arm mechanisms live onboard (CubeSat) or in the link layer (SpaceLink). An
    // armless branch here would apply the attack-arm intervention on the fault arm too,
    // and the matched pair would then run the same intervention twice.
    if (!causal->isAttack())
        return;

    const long seq = tm->getTelemetrySeq();

    switch (causal->getPair()) {
        case CausalScenario::SP1:
            // target observation only, batteryVoltage only, once. no drop branch, no
            // delay branch, no rate gate: the contract specifies a deterministic
            // tamper-only injector keyed to the target.
            if (causal->isTarget(seq)) {
                double before = tm->getBatteryVoltage();
                tm->setBatteryVoltage(before + causal->getTargetDeviationV());
                tampered++;
                emit(tamperedSignal, 1L);
            }
            break;

        case CausalScenario::SP2:
        case CausalScenario::SP3:
            // the downlink is untouched. seeing the target observation is the cue to
            // send the hostile configuration command upward.
            //
            // attack arm only: injecting a command on the fault arm would give that arm
            // the attack arm's own decisive evidence.
            if (causal->isAttack() && causal->isTarget(seq) && !hostileConfigSent)
                injectHostileConfig();
            break;

        case CausalScenario::SP4:
            // delay only. the link layer already applied propagation and transmission
            // time; the 30 s added here sits on exactly the same base age on both arms,
            // so the reported delay matches.
            if (causal->isTarget(seq)) {
                sendDelayed(tm, causal->getDelayTarget(), "groundOut");
                consumed = true;
            }
            break;

        case CausalScenario::SP5:
            // the same on-path tamper, this time on the rej field. the onboard copy is
            // untouched, which is precisely the separating evidence.
            if (causal->isTarget(seq)) {
                tm->setRejectedCmdCount(tm->getRejectedCmdCount()
                                        + causal->getCounterTargetDelta());
                tampered++;
                emit(tamperedSignal, 1L);
            }
            break;

        case CausalScenario::SP6: {
            // the target is the first three deliveries of a contact. the first frame
            // is captured verbatim, the second passes normally, and the third delivery
            // is that verbatim copy. not a telecommand replay: the accepted contract
            // treats a freshness-rejected replay as a telemetry sequence regression.
            if (!causal->isAttack())
                break;
            simtime_t passStart = access->getCurrentPassStart();
            int index = causal->noteContactFrame(passStart);
            if (index == 0) {
                // the first frame of the contact is captured. its copy is emitted on
                // the third delivery; the first frame is chosen so its sequence number
                // stays below the largest one in flight.
                delete capturedFrame;
                capturedFrame = tm->dup();
            }
            else if (index == 1) {
                // re-emit after the second frame has passed
                causalFrameIndex = 1;
            }
            break;
        }

        default:
            break;
    }
}

void OnPathAttacker::injectHostileConfig()
{
    hostileConfigSent = true;
    auto *tc = new Telecommand("TC-hostile");
    tc->setCommandId(++forgedId);
    tc->setSequence(forgedId);
    tc->setIssuedAt(simTime());
    if (causal->getPair() == CausalScenario::SP2) {
        // Amendment v5: the SP-2 attack arm manipulates the SUNLIT-branch
        // coefficient, the same one the fault arm reaches command-free.  The
        // Twin has no chargeRate branch in evaluateUpdate or
        // applyConfirmedPhysicalEffects, so this update cannot enter the twin's
        // approved list or shift its model or tolerance term -- which is what
        // keeps the two arms' expectations identical.
        tc->setCommandType(CMD_UPDATE);
        tc->setParamKey("chargeRate");
        tc->setParamValue(causal->getPerturbedChargeRate());
    }
    else {
        tc->setCommandType(CMD_SET_MODE);
        tc->setTargetMode(causal->getModeOrdinalDelta());
    }
    tc->setByteLength(32);

    injected++;
    emit(injectedSignal, 1L);
    // the satellite writes the real row when it accepts this command; the contract
    // defines that arm's row time as the accepted command's time.
    causal->noteHostileCommand(tc->getCommandId());
    send(tc, "linkOut");
}

void OnPathAttacker::replayCapturedTelemetry()
{
    // the captured telemetry frame, verbatim. telemetrySeq and sourceTime are unchanged,
    // so the ground sees a second copy of a frame it already received, which is SP-6's
    // attack signature.
    if (capturedFrame == nullptr)
        return;
    auto *copy = capturedFrame->dup();
    replayed++;
    emit(replayedSignal, 1L);
    causal->setTarget(copy->getTelemetrySeq(), copy->getSourceTime());
    causal->recordIntervention(
        "attack", "telemetry_replay",
        "downlink telemetry stream order, by re-injecting a previously captured telemetry frame",
        "exact identifier equality", "identifier",
        copy->getTelemetrySeq(), copy->getSourceTime());
    // the copy must arrive strictly after the second delivery: arriving at the same
    // instant would make ordering fall to the tie key, and "third delivery" would follow
    // from the sequence number rather than the delivery order.
    sendDelayed(copy, SimTime(1, SIMTIME_MS), "groundOut");
}

bool OnPathAttacker::handleUplink(cMessage *msg)
{
    auto *tc = dynamic_cast<Telecommand *>(msg);
    if (tc == nullptr || !episodeActive)
        return false;

    if (scenario == "A1" && uniform(0, 1) < affectedFractionTc) {
        double before = tc->getParamValue();
        tc->setParamValue(before + paramDelta);
        tampered++;
        emit(tamperedSignal, 1L);
        truth({{"event", "tamper"}, {"scenario", "A1"},
               {"cmdId", std::to_string(tc->getCommandId())},
               {"field", "paramValue"},
               {"before", std::to_string(before)},
               {"after", std::to_string(tc->getParamValue())}});
        sendDelayed(tc, addedDelay, "linkOut");
        return true;
    }
    if (scenario == "A2v" && uniform(0, 1) < affectedFractionTc) {
        // A2v: credentials are valid, trust is misplaced. the attacker edits a
        // legitimate command and re-signs with a compromised key, so tag, digest and
        // sequence all check out and D1 passes it. only behavioural defence remains:
        // the ground never approved this value, so the logical channel must see it.
        double before = tc->getParamValue();
        tc->setParamValue(before + paramDelta);
        std::string body = authenticatedBody(tc);
        tc->setPayloadDigest(Sha256::hex(body).substr(0, 16).c_str());
        tc->setAuthTag(hmacSha256Hex(compromisedKey, body).c_str());
        tampered++;
        emit(tamperedSignal, 1L);
        truth({{"event", "tamper"}, {"scenario", "A2v"},
               {"cmdId", std::to_string(tc->getCommandId())},
               {"field", "paramValue"}, {"resigned", "1"},
               {"before", std::to_string(before)},
               {"after", std::to_string(tc->getParamValue())}});
        send(tc, "linkOut");
        return true;
    }
    if (scenario == "A3" && captured == nullptr) {
        captured = tc->dup();          // capture it for a later replay
        truth({{"event", "capture"}, {"scenario", "A3"},
               {"cmdId", std::to_string(tc->getCommandId())},
               {"seq", std::to_string(tc->getSequence())}});
    }
    return false;
}

bool OnPathAttacker::handleDownlink(cMessage *msg)
{
    auto *tm = dynamic_cast<Telemetry *>(msg);
    if (tm == nullptr)
        return false;

    // causal mode replaces all of the old paths. A4's rate gate and three-way random
    // pick are never evaluated here, so no run is won by one branch.
    if (causal != nullptr && causal->isActive()) {
        bool consumed = false;
        causalDownlink(tm, consumed);
        if (!consumed)
            send(tm, "groundOut");
        if (causal->getPair() == CausalScenario::SP6 && causalFrameIndex == 1) {
            causalFrameIndex = -1;
            replayCapturedTelemetry();
        }
        return true;
    }

    if (scenario == "A8") {
        // keep the last real telemetry as material for the spoofed resync packet
        delete lastSeen;
        lastSeen = tm->dup();
    }

    if (scenario == "A7c" && episodeActive) {
        // baseline to hide behind: the first counter value seen in this episode.
        // every command D1 rejects during the episode adds to it; freezing the field
        // at the baseline erases the trace.
        if (frozenRejectedCount < 0)
            frozenRejectedCount = tm->getRejectedCmdCount();
        else if (tm->getRejectedCmdCount() != frozenRejectedCount) {
            long before = tm->getRejectedCmdCount();
            tm->setRejectedCmdCount(frozenRejectedCount);
            tampered++;
            emit(tamperedSignal, 1L);
            truth({{"event", "tamper"}, {"scenario", "A7c"},
                   {"tmSeq", std::to_string(tm->getTelemetrySeq())},
                   {"field", "rejectedCmdCount"},
                   {"before", std::to_string(before)},
                   {"after", std::to_string(frozenRejectedCount)}});
        }
    }

    if (scenario != "A4" || !episodeActive)
        return false;
    if (uniform(0, 1) >= affectedFractionTm)
        return false;

    double r = uniform(0, 1);
    if (r < 0.34) {                     // drop
        dropped++;
        emit(droppedSignal, 1L);
        truth({{"event", "drop"}, {"scenario", "A4"},
               {"tmSeq", std::to_string(tm->getTelemetrySeq())}});
        delete tm;
        return true;
    }
    if (r < 0.67) {                     // delay
        truth({{"event", "delay"}, {"scenario", "A4"},
               {"tmSeq", std::to_string(tm->getTelemetrySeq())},
               {"addedDelayS", addedDelay.str()}});
        sendDelayed(tm, addedDelay, "groundOut");
        return true;
    }
    double before = tm->getBatteryVoltage();   // alter its field
    tm->setBatteryVoltage(before + voltageDelta);
    tampered++;
    emit(tamperedSignal, 1L);
    truth({{"event", "tamper"}, {"scenario", "A4"},
           {"tmSeq", std::to_string(tm->getTelemetrySeq())},
           {"field", "batteryVoltage"},
           {"before", std::to_string(before)},
           {"after", std::to_string(tm->getBatteryVoltage())}});
    send(tm, "groundOut");
    return true;
}

void OnPathAttacker::handleMessage(cMessage *msg)
{
    if (msg == episodeStart)  { beginEpisode(); return; }
    if (msg == episodeEnd)    { endEpisode(); return; }
    if (msg == injectTimer) {
        if (episodeActive) {
            if (scenario == "A2" || scenario == "A7c") injectForgedCommand();
            else if (scenario == "A3") replayCapturedCommand();
            else if (scenario == "A6") injectMaliciousUpdate();
            scheduleAt(simTime() + injectionInterval, injectTimer);
        }
        return;
    }

    observed++;
    emit(observedSignal, 1L);

    if (msg->arrivedOn("groundIn")) {
        if (!handleUplink(msg))
            send(msg, "linkOut");
    }
    else if (msg->arrivedOn("linkIn")) {
        if (!handleDownlink(msg))
            send(msg, "groundOut");
    }
    else
        throw cRuntimeError("OnPathAttacker: unexpected gate");
}

void OnPathAttacker::finish()
{
    recordScalar("observed", observed);
    recordScalar("episodes", episodeCount);
    recordScalar("tampered", tampered);
    recordScalar("injected", injected);
    recordScalar("replayed", replayed);
    recordScalar("dropped", dropped);
    recordScalar("attackEvents", tampered + injected + replayed + dropped);
}

} // namespace lifesat
