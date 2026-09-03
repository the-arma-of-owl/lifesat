//
// LIFESAT twin and deviation detector (D3)
//
#include "Twin.h"

#include <sstream>

#include "HashChain.h"
#include "inet/common/geometry/common/Wgs84.h"

namespace lifesat {

Define_Module(Twin);

simsignal_t Twin::voltageDeviationSignal = cComponent::registerSignal("voltageDeviation");
simsignal_t Twin::voltageBoundSignal = cComponent::registerSignal("voltageBound");
simsignal_t Twin::temporalLagSignal = cComponent::registerSignal("temporalLag");
simsignal_t Twin::d3AlarmSignal = cComponent::registerSignal("d3Alarm");
simsignal_t Twin::d3AlarmChannelSignal = cComponent::registerSignal("d3AlarmChannel");

Twin::~Twin() { cancelAndDelete(stepTimer); }

void Twin::initialize(int stage)
{
    cSimpleModule::initialize(stage);

    if (stage == INITSTAGE_LOCAL) {
        enabled = par("enabled");
        updateInterval = par("updateInterval");
        rateUncertainty = par("rateUncertainty");
        noiseSigma = par("noiseSigma");
        sigmaFactor = par("sigmaFactor");
        maxTemporalBound = par("maxTemporalBound");
        resyncOnMatch = par("resyncOnMatch");
        uplinkDelayBound = par("uplinkDelayBound");
        validationHorizon = par("validationHorizon");
        orbitalPeriod = par("orbitalPeriod").doubleValue();
        illuminationDuty = par("illuminationDuty");
        safetyFloorVoltage = par("safetyFloorVoltage");

        // twin rates differ from the satellite by rateBias; the twin knows only
        // the rateUncertainty bound, not the actual offset
        double bias = 1.0 + par("rateBias").doubleValue();
        nominalDischargeRate = par("dischargeRate").doubleValue();
        model.configure(par("nominalVoltage").doubleValue(),
                        par("minVoltage").doubleValue(),
                        par("maxVoltage").doubleValue(),
                        par("chargeRate").doubleValue() * bias,
                        nominalDischargeRate * bias);
    }
    else if (stage == INITSTAGE_SINGLE_MOBILITY) {
        access = check_and_cast<AccessModel *>(getModuleByPath(par("accessModule")));
        mobility = check_and_cast<SatelliteMobility *>(
                       getModuleByPath(par("satelliteMobilityModule")));
        cModule *c = getModuleByPath("^.collector");
        if (c != nullptr)
            collector = check_and_cast<Collector *>(c);

        const char *epoch = mobility->par("epoch");
        int y, mo, d, h, mi; double s;
        if (!*epoch || sscanf(epoch, "%d-%d-%dT%d:%d:%lf", &y, &mo, &d, &h, &mi, &s) != 6)
            throw cRuntimeError("Twin needs an explicit mobility epoch");
        epochJulianDate = wgs84::julianDateFromUtc(y, mo, d, h, mi, s);

        stepTimer = new cMessage("twinStep");
        scheduleAt(simTime() + updateInterval, stepTimer);
    }
}

void Twin::handleMessage(cMessage *msg)
{
    if (msg != stepTimer)
        throw cRuntimeError("Twin received an unexpected message");
    stepModel();
    scheduleAt(simTime() + updateInterval, stepTimer);
}

void Twin::stepModel()
{
    // runs regardless of visibility: the ground side predicts across the gap
    double jd = epochJulianDate + simTime().dbl() / 86400.0;
    Coord ecef = mobility->getCurrentPosition();
    double g = wgs84::gmst(jd);
    Coord eci(std::cos(g) * ecef.x - std::sin(g) * ecef.y,
              std::sin(g) * ecef.x + std::cos(g) * ecef.y,
              ecef.z);
    bool illuminated = PowerModel::isIlluminated(eci, PowerModel::sunDirectionEci(jd));
    model.step(illuminated, updateInterval.dbl());
}

double Twin::physicalStateBound(simtime_t dt) const
{
    // measurement term: realigning to the observed value makes the next
    // comparison carry two independent noise draws, so the bound scales by
    // sqrt(2) -- variance accounting, not threshold tuning
    double effectiveSigma = resyncOnMatch ? noiseSigma * M_SQRT2 : noiseSigma;
    double measurementTerm = sigmaFactor * effectiveSigma;

    // model term: rate error accumulates over dt, so the bound widens with the
    // contact gap
    double modelTerm = rateUncertainty * nominalDischargeRate * dt.dbl();
    return measurementTerm + modelTerm;
}

std::string Twin::paramDigestAfter(size_t n) const
{
    std::map<std::string, double> store;
    for (size_t i = 0; i < n && i < approved.size(); i++)
        if (approved[i].type == CMD_SET_PARAM || approved[i].type == CMD_UPDATE)
            store[approved[i].paramKey] = approved[i].paramValue;
    std::ostringstream s;
    for (const auto& kv : store)
        s << kv.first << '=' << kv.second << ';';
    return Sha256::hex(s.str()).substr(0, 16);
}

SatMode Twin::modeAfter(size_t n) const
{
    SatMode m = MODE_NOMINAL;
    for (size_t i = 0; i < n && i < approved.size(); i++)
        if (approved[i].type == CMD_SET_MODE)
            m = (SatMode)approved[i].targetMode;
    return m;
}

size_t Twin::sentByTime(simtime_t ts) const
{
    size_t n = 0;
    for (const auto& a : approved)
        if (a.sentAt <= ts)
            n++;
    return n;
}

Twin::UpdateVerdict Twin::validateUpdate(const std::string& key, double value,
                                         std::string& reason)
{
    if (!enabled) {
        // no twin means no validation gate (A6s control arm); reaching here is a
        // configuration error -- do not approve silently
        reason = "twin disabled; no pre-uplink validation performed";
        return UPDATE_UNSUPPORTED;
    }
    updatesValidated++;

    // candidate is applied to a copy: a failed validation must not corrupt the
    // twin state estimate
    PowerModel candidate = model;
    if (key == "dischargeRate")
        candidate.setDischargeRate(value);
    else {
        // parameter with no declared physical effect: the gate cannot decide, so
        // it fails closed and records a separate verdict for the operator
        reason = "parameter has no declared physical effect; outside this envelope";
        updatesUnsupported++;
        // twin-prefixed: this is the twin's internal verdict; the ground station
        // writes the final one (update.unsupported). Sharing a name would double
        // count a single semantic event
        if (collector)
            collector->logEvent("twin.updateUnsupported",
                {{"paramKey", key}, {"paramValue", std::to_string(value)},
                 {"reason", reason}});
        return UPDATE_UNSUPPORTED;
    }

    // forward pass: illumination comes from the orbital period and the measured
    // illuminated fraction; the question is the energy balance over the horizon,
    // not the instantaneous position
    const double dt = 60.0;
    double worst = candidate.getVoltage();
    for (double t = 0; t < validationHorizon.dbl(); t += dt) {
        bool illuminated = std::fmod(t, orbitalPeriod) < illuminationDuty * orbitalPeriod;
        candidate.step(illuminated, dt);
        if (candidate.getVoltage() < worst)
            worst = candidate.getVoltage();
    }

    if (worst <= safetyFloorVoltage) {
        std::ostringstream s;
        s << "projected battery voltage " << worst << " V reaches the declared floor "
          << safetyFloorVoltage << " V within " << validationHorizon.dbl() / 3600.0 << " h";
        reason = s.str();
        updatesRejected++;
        if (collector)
            collector->logEvent("twin.updateRejected",
                {{"paramKey", key}, {"paramValue", std::to_string(value)},
                 {"worstVoltage", std::to_string(worst)},
                 {"floorV", std::to_string(safetyFloorVoltage)}});
        return UPDATE_REJECTED;
    }

    if (collector)
        collector->logEvent("twin.updateApproved",
            {{"paramKey", key}, {"paramValue", std::to_string(value)},
             {"worstVoltage", std::to_string(worst)}});
    reason = "within envelope";
    return UPDATE_APPROVED;
}

void Twin::applyConfirmedPhysicalEffects(size_t from, size_t to)
{
    // half-open [from, to): confirmedPrefix never moves backwards, so a command
    // cannot be applied twice
    for (size_t i = from; i < to && i < approved.size(); i++) {
        if (approved[i].type != CMD_UPDATE)
            continue;
        if (approved[i].paramKey == "dischargeRate") {
            model.setDischargeRate(approved[i].paramValue);
            nominalDischargeRate = approved[i].paramValue;   // the tolerance term shifts with it
            updatesAppliedToModel++;
            if (collector)
                collector->logEvent("twin.modelUpdated",
                    {{"paramKey", approved[i].paramKey},
                     {"paramValue", std::to_string(approved[i].paramValue)},
                     {"trigger", "confirmed-by-telemetry"}});
        }
    }
}

void Twin::noteApprovedCommand(const Telecommand *tc)
{
    // released commands are recorded with their send time; delayed telemetry
    // cannot be interpreted without it
    approved.push_back({simTime(), tc->getCommandType(),
                        tc->getParamKey(), tc->getParamValue(), tc->getTargetMode(),
                        tc->getCommandId(), tc->getSequence()});
}

bool Twin::wasApproved(long commandId, long sequence) const
{
    for (const auto& a : approved)
        if (a.commandId == commandId && a.sequence == sequence)
            return true;
    return false;
}

void Twin::emitAlarm(const Telemetry *tm, const char *channel,
                     double deviation, double bound, simtime_t dt,
                     bool withCommandLink, bool modeExplained,
                     bool digestExplained)
{
    if (collector == nullptr)
        return;
    Collector::Fields fields = {
        {"channel", channel},
        {"deviationV", std::to_string(deviation)},
        {"boundV", std::to_string(bound)},
        {"dtS", dt.str()},
        {"tmSeq", std::to_string(tm->getTelemetrySeq())}};

    if (withCommandLink) {
        // explicit null, not an absent field
        //
        // the fault signature tests is_null(); a missing field is MISSING, and every
        // comparison against MISSING is FALSE, which would make the fault arm
        // undecidable. the literal "null" string means the ground
        // is itself the statement "there was NO command that wrote this state".
        //
        // value comes from the satellite's own last state-writing command id; the
        // ground sees the same id in tc.accept. temporal adjacency is never a
        // substitute
        // the link is the command that made the state inadmissible, not merely the
        // last one that wrote it
        //
        // first locate the deviating component (mode or parameter store), then look
        // for an unapproved command in its lineage; none gives explicit null
        //
        // a single last-writer pointer lost the responsible command on any routine
        // write, and could point at an approved one, firing the attack signature
        // against the fault arm
        long linkCmd = -1, linkSeq = -1;
        if (!modeExplained && tm->getModeWriteCmdId() >= 0
                && !wasApproved(tm->getModeWriteCmdId(), tm->getModeWriteSeq())) {
            linkCmd = tm->getModeWriteCmdId();
            linkSeq = tm->getModeWriteSeq();
        }
        else if (!digestExplained) {
            // one "key:cmdId:seq;" entry per prevailing write
            std::istringstream stream(tm->getParamWriteProvenance());
            std::string entry;
            while (std::getline(stream, entry, ';')) {
                if (entry.empty())
                    continue;
                size_t second = entry.rfind(':');
                if (second == std::string::npos || second == 0)
                    continue;
                size_t first = entry.rfind(':', second - 1);
                if (first == std::string::npos)
                    continue;
                long cmdId = std::stol(entry.substr(first + 1, second - first - 1));
                long seq = std::stol(entry.substr(second + 1));
                if (cmdId >= 0 && !wasApproved(cmdId, seq)) {
                    linkCmd = cmdId;
                    linkSeq = seq;
                    break;
                }
            }
        }
        if (linkCmd < 0) {
            // explicit null: is_null() is tested, and MISSING would compare FALSE
            // everywhere, leaving the fault arm undecidable
            fields.push_back({"linkCmdId", "null"});
            fields.push_back({"linkSeq", "null"});
        }
        else {
            fields.push_back({"linkCmdId", std::to_string(linkCmd)});
            fields.push_back({"linkSeq", std::to_string(linkSeq)});
        }
    }
    collector->logEvent("d3.alarm", fields);
}

void Twin::observeTelemetry(const Telemetry *tm)
{
    if (!enabled)
        return;
    observations++;

    // temporal bound: age of the telemetry at source time. dt is read here; it is
    // not an alarm criterion
    simtime_t lag = simTime() - tm->getSourceTime();
    simtime_t sinceLastObservation =
        (lastObservation < SIMTIME_ZERO) ? simTime() : simTime() - lastObservation;
    simtime_t dt = std::min(sinceLastObservation, maxTemporalBound);
    emit(temporalLagSignal, lag);

    // physical channel
    double expectedV = model.getVoltage();
    double observedV = tm->getBatteryVoltage();
    double deviation = std::fabs(expectedV - observedV);
    double bound = physicalStateBound(dt);
    emit(voltageDeviationSignal, deviation);
    emit(voltageBoundSignal, bound);
    bool physicalBreach = deviation > bound;

    // logical channel: which commands had landed at sourceTime is generally
    // uncertain, so the twin expands every admissible prefix and alarms only if the
    // observation matches none. uncertainty itself is not an alarm
    size_t possible = sentByTime(tm->getSourceTime());
    bool logicalBreach = true;
    size_t matched = confirmedPrefix;
    // components are tested separately: a whole-state mismatch does not say which
    // one deviated, and the link needs that component's command
    bool modeExplained = false, digestExplained = false;
    for (size_t n = confirmedPrefix; n <= possible; n++) {
        bool modeOk = modeAfter(n) == (SatMode)tm->getMode();
        bool digestOk = paramDigestAfter(n) == std::string(tm->getParamDigest());
        if (modeOk) modeExplained = true;
        if (digestOk) digestExplained = true;
        if (modeOk && digestOk && logicalBreach) {
            logicalBreach = false;
            matched = n;
        }
    }
    // on a match the twin pins to that state; on a mismatch it does not advance, so
    // an attacker cannot walk it forward
    //
    // physical effects are applied when the prefix advances, not at send time: a
    // sent command may never have arrived
    if (!logicalBreach) {
        if (matched > confirmedPrefix)
            applyConfirmedPhysicalEffects(confirmedPrefix, matched);
        confirmedPrefix = matched;
    }

    // security channel: the ground sends only valid commands, so the expected
    // rejection count is constant. an increase is evidence that D1 rejected
    // something the ground never sent. A7c falsifies this counter
    //
    // alarm on the transition, not the level: the counter stays raised, and
    // re-alarming on every telemetry would turn one event into hundreds. the twin
    // adopts the new baseline afterwards
    bool securityBreach = (tm->getRejectedCmdCount() != expectedRejectedCount);

    if (physicalBreach || logicalBreach || securityBreach) {
        alarms++;
        int channel = physicalBreach ? 0 : (logicalBreach ? 1 : 2);
        if (physicalBreach) alarmPhysical++;
        if (logicalBreach)  alarmLogical++;
        if (securityBreach) alarmSecurity++;
        emit(d3AlarmSignal, 1L);
        emit(d3AlarmChannelSignal, (long)channel);
        if (securityBreach) {
            // evidence consumed: the new count is the known baseline
            unexplainedRejections += tm->getRejectedCmdCount() - expectedRejectedCount;
            expectedRejectedCount = tm->getRejectedCmdCount();
        }
        // one row per channel
        //
        // a single winning-channel row let a physical violation mask a logical one;
        // scoring splits d3.alarm by channel, and SP-2 context evidence lives on the
        // logical side
        //
        // the alarm criterion is unchanged; both violated channels are now reported
        if (physicalBreach)
            emitAlarm(tm, "physical", deviation, bound, dt, false);
        if (logicalBreach)
            emitAlarm(tm, "logical", deviation, bound, dt, true,
                      modeExplained, digestExplained);
        if (securityBreach)
            emitAlarm(tm, "security", deviation, bound, dt, false);
    }
    else if (resyncOnMatch) {
        // realign only inside the bound; otherwise an attacker could drag the twin
        model.setVoltage(observedV);
    }

    lastObservation = simTime();
}

void Twin::finish()
{
    recordScalar("observations", observations);
    recordScalar("d3Alarms", alarms);
    recordScalar("d3AlarmsPhysical", alarmPhysical);
    recordScalar("d3AlarmsLogical", alarmLogical);
    recordScalar("d3AlarmsSecurity", alarmSecurity);
    recordScalar("unexplainedRejections", unexplainedRejections);
    recordScalar("updatesValidated", updatesValidated);
    recordScalar("updatesRejected", updatesRejected);
    recordScalar("updatesUnsupported", updatesUnsupported);
    recordScalar("updatesAppliedToModel", updatesAppliedToModel);
    recordScalar("d3AlarmRate", observations ? (double)alarms / observations : 0.0);
}

} // namespace lifesat
