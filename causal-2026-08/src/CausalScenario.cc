//
// LIFESAT -- phase 3 causal scenario controller
//
#include "CausalScenario.h"

#include <sstream>

namespace lifesat {

Define_Module(CausalScenario);

CausalScenario::Pair CausalScenario::parsePair(const std::string& id)
{
    if (id == "SP-1") return SP1;
    if (id == "SP-2") return SP2;
    if (id == "SP-3") return SP3;
    if (id == "SP-4") return SP4;
    if (id == "SP-5") return SP5;
    if (id == "SP-6") return SP6;
    if (id.empty())   return PAIR_NONE;
    throw cRuntimeError("CausalScenario: unknown pairId '%s'", id.c_str());
}

CausalScenario::Arm CausalScenario::parseArm(const std::string& id)
{
    if (id == "attack") return ATTACK;
    if (id == "fault")  return FAULT;
    if (id.empty())     return ARM_NONE;
    throw cRuntimeError("CausalScenario: unknown arm '%s'", id.c_str());
}

CausalScenario::RbArm CausalScenario::parseRbArm(const std::string& id)
{
    if (id == "RB-model-mismatch") return RB_MODEL_MISMATCH;
    if (id == "RB-sensor-error")   return RB_SENSOR_ERROR;
    if (id == "RB-third-cause")    return RB_THIRD_CAUSE;
    if (id.empty())                return RB_NONE;
    throw cRuntimeError("CausalScenario: unknown robustnessArm '%s'", id.c_str());
}

void CausalScenario::initialize(int stage)
{
    cSimpleModule::initialize(stage);

    if (stage == INITSTAGE_LOCAL) {
        pairIdStr = par("pairId").stdstringValue();
        armStr = par("arm").stdstringValue();
        robustnessArmStr = par("robustnessArm").stdstringValue();
        runIdStr = par("runId").stdstringValue();
        runSeedIndex = par("runSeedIndex").intValue();
        pair = parsePair(pairIdStr);
        arm = parseArm(armStr);
        rbArm = parseRbArm(robustnessArmStr);
        if (pair != PAIR_NONE && arm == ARM_NONE)
            throw cRuntimeError("CausalScenario: pairId '%s' without an arm",
                                pairIdStr.c_str());
        if (pair != PAIR_NONE && runIdStr.empty())
            throw cRuntimeError("CausalScenario: a causal run needs an explicit "
                                "runId; an unnamed run cannot be reconciled");

        onsetOffset = par("onsetOffsetS");
        durationObservations = par("durationObservations").intValue();
        targetDeviationV = par("targetDeviationV");
        perturbedDischargeRate = par("perturbedDischargeRate");
        perturbedChargeRate = par("perturbedChargeRate");
        sp2MinContactDuration = par("sp2MinContactDurationS");
        sp2Window = par("sp2WindowS");
        activationGuard = par("activationGuardS");
        minVoltageV = par("minVoltageV");
        clippingMarginV = par("clippingMarginV");
        eclipseSteps = par("eclipseSteps").intValue();
        modeOrdinalDelta = par("modeOrdinalDelta").intValue();
        delayTarget = par("delayTargetS");
        counterTargetDelta = par("counterTargetDelta").intValue();
        replayWindowObservations = par("replayWindowObservations").intValue();
        robustnessMagnitude = par("robustnessMagnitude");
        telemetryInterval = par("telemetryIntervalS");
    }
    else if (stage == INITSTAGE_SINGLE_MOBILITY) {
        cModule *col = getModuleByPath(par("collectorModule"));
        if (col != nullptr)
            collector = check_and_cast<Collector *>(col);
        cModule *acc = getModuleByPath(par("accessModule"));
        if (acc != nullptr)
            access = check_and_cast<AccessModel *>(acc);
        if (isActive() && collector == nullptr)
            throw cRuntimeError("CausalScenario: a causal run needs a collector; "
                                "without one there is no truth authority");
    }
}

void CausalScenario::handleMessage(cMessage *msg)
{
    throw cRuntimeError("CausalScenario receives no messages");
}

void CausalScenario::truth(const Collector::Fields& extra)
{
    truthAt(extra, simTime());
}

void CausalScenario::truthAt(const Collector::Fields& extra, simtime_t at)
{
    // Every truth row carries the full run identity, so a row can never be
    // read as belonging to a run it did not come from.  truth_reference_spec
    // requires begin, intervention(s) and end to share run_id, seed_index and
    // pair_id; that is enforced HERE, at the point of writing.
    //
    // The field NAMES are the ones truth_reference_spec and the accepted
    // validator bind against (run_id, pair_id, seed_index, episode_ref, arm,
    // cause, intervention_class, variable, magnitude, units).  Writing them in
    // any other spelling would mean translating at the far end, and a
    // translation layer is somewhere a mismatch can hide.
    Collector::Fields fields;
    fields.push_back({"run_id", runIdStr});
    fields.push_back({"pair_id", pairIdStr});
    fields.push_back({"arm", armStr});
    fields.push_back({"seed_index", std::to_string(runSeedIndex)});
    fields.push_back({"episode_ref", runIdStr});
    if (!robustnessArmStr.empty())
        fields.push_back({"robustness_arm", robustnessArmStr});
    for (const auto& item : extra)
        fields.push_back(item);
    collector->recordGroundTruthAt(fields, at);
}

bool CausalScenario::offerTelemetryTarget(long seq, bool illuminated,
                                          bool eclipseWindowClear)
{
    if (!isActive())
        return false;

    // The clock for every onset rule is the FIRST contact of the run.  A pass
    // lasts a few hundred seconds and every declared offset except SP-6's is
    // larger than that, so "contact start + X" lands in the gap between passes
    // and the rule's own words -- the first tm.send AT OR AFTER that instant -- // select the first observation of a later contact.  The rule is total
    // either way; reading it as "inside the same pass" would make five of the
    // six pairs unsatisfiable by construction.
    if (firstPassStart < SIMTIME_ZERO) {
        if (pair == SP2) {
            // Amendment v5 selection rule
            // "the FIRST ground contact of the run whose duration is at least
            // sp2MinContactDurationS".  Evaluated against the PRECOMPUTED pass
            // schedule, which is a function of the TLE and the epoch alone -- // identical in both arms, blind to the seed and to every outcome.
            // Anchoring on the run's first pass instead (the accepted rule for
            // the other pairs) would place the window in a contact too short
            // to hold it.
            simtime_t qualifyingStart = -1, qualifyingEnd = -1;
            if (access == nullptr
                || !access->firstPassAtLeast(sp2MinContactDuration,
                                             qualifyingStart, qualifyingEnd))
                return false;                // no eligible contact: fail closed
            sp2SelectedContactStart = qualifyingStart;
            sp2SelectedContactEnd = qualifyingEnd;
            firstPassStart = qualifyingStart;
            onsetTime = qualifyingStart + onsetOffset;
        }
        else {
            simtime_t start = access ? access->getCurrentPassStart() : simtime_t(-1);
            if (start < SIMTIME_ZERO)
                return false;                // no contact has opened yet
            firstPassStart = start;
            onsetTime = firstPassStart + onsetOffset;
        }
    }
    if (targetSeq >= 0)
        return false;
    offersSeen++;
    if (simTime() < onsetTime) {
        offersBeforeOnset++;
        return false;
    }

    if (pair == SP6) {
        // SP-6 does not pick its target here.
        //
        // The repeated or reordered frame is known only on the downlink, so the target
        // is named there (setTarget). Filling targetSeq here would stop noteContactFrame
        // from building its own contact ledger.
        return false;
    }

    if (pair == SP5) {
        // "the second tm.send of the target observation pair": the schedule
        // selects the pair's first observation, the intervention lands on the
        // next one, and the two are consecutive observations of one contact.
        if (anchorSeq < 0) {
            anchorSeq = seq;
            return false;
        }
    }

    if (pair == SP2) {
        // SP-2 illumination precondition cannot hold in this geometry: the satellite
        // is never in eclipse while in ground-station view. the rule is applied
        // literally (first tm.send in contact view) and whether the eclipse condition
        // held is recorded in two counters and in the run scalars. stopping the run
        // here would turn a contract design constraint into missing data.
        if (illuminated)
            offersRejectedIlluminated++;
        else if (!eclipseWindowClear)
            offersRejectedWindow++;
        targetInEclipse = !illuminated;
        targetEclipseWindowClear = eclipseWindowClear;
    }

    targetSeq = seq;
    targetSendTime = simTime();
    targetContactStart = access ? access->getCurrentPassStart() : simtime_t(-1);
    return true;
}

void CausalScenario::tickEpisode()
{
    if (!isActive())
        return;

    if (!episodeOpen && !interventionEmitted && targetSeq < 0
            && targetContactStart < SIMTIME_ZERO)
        return;                                  // nothing scheduled yet

    if (!episodeOpen && episodeEndTime < SIMTIME_ZERO) {
        // The window OPENS at the start of the contact that carries the target,
        // so the pair's first observation (SP-5) and the first three deliveries
        // (SP-6) are inside it by construction rather than by luck.
        episodeStartContact = targetContactStart >= SIMTIME_ZERO
                                  ? targetContactStart
                                  : (access ? access->getCurrentPassStart()
                                            : simtime_t(-1));
        if (episodeStartContact < SIMTIME_ZERO)
            return;
        plannedEnd = declaredEnd();
        openEpisode(episodeStartContact);
        return;
    }

    if (episodeOpen && plannedEnd >= SIMTIME_ZERO && simTime() >= plannedEnd)
        closeEpisode(simTime());
}

simtime_t CausalScenario::declaredEnd() const
{
    // pair_intervention_registry end_rule, per pair, in the registry's own
    // terms.  Nothing is rounded to a contact boundary: a window that stopped
    // when the contact stopped would silently shorten SP-2 and SP-3.
    simtime_t anchor = targetSendTime >= SIMTIME_ZERO ? targetSendTime : simTime();
    switch (pair) {
        case SP1:                                  // "the same single observation"
        case SP5:                                  // "same observation"
            return anchor + telemetryInterval;
        case SP2:                                  // "onset + 100 telemetry steps"
            return anchor + telemetryInterval * eclipseSteps;
        case SP3:                                  // "onset + 3600 s"
            return anchor + SimTime(3600, SIMTIME_S);
        case SP4:                                  // "the arrival of that same observation"
            return anchor + delayTarget + telemetryInterval;
        case SP6:                                  // "first 3 observations"
            return anchor + telemetryInterval * replayWindowObservations;
        default:
            return anchor + telemetryInterval;
    }
}

int CausalScenario::noteContactFrame(simtime_t passStart)
{
    if (!isActive() || pair != SP6)
        return -1;
    if (firstPassStart < SIMTIME_ZERO) {
        // SP-6 is the one pair whose window is a CONTACT rather than a single
        // observation: "the first three received observations after contact
        // start", at an onset offset of 10 s.  A contact lasts hundreds of
        // seconds, so the first tm.send at or after (first pass start + 10 s)
        // lies inside the FIRST contact, and that contact is the window.
        firstPassStart = passStart;
        onsetTime = firstPassStart + onsetOffset;
    }
    // the counter starts at the first delivery of a contact, not at a 10 s offset.
    // SP-6's window is the first three received observations after contact start and
    // position is counted from there; starting at an offset would shift the window.
    if (contactFrameIndex < 0) {
        targetContactStart = passStart;
        contactFrameIndex = 0;
        // the window opens with the first counted frame; an episode row appearing after
        // the intervention would tell the reader the wrong order.
        tickEpisode();
    }
    if (passStart != targetContactStart)
        return -1;
    return contactFrameIndex++;
}

void CausalScenario::setTarget(long seq, simtime_t sendTime)
{
    // SP-6 does not choose its target when the packet is generated: the frame
    // that is replayed or reordered is only known on the downlink, at the
    // moment the third delivery is composed.  The truth row still has to name
    // it, so it is recorded here rather than inferred later.
    if (targetSeq < 0) {
        targetSeq = seq;
        targetSendTime = sendTime;
    }
}

void CausalScenario::openEpisode(simtime_t at)
{
    if (!isActive() || episodeOpen)
        return;
    episodeOpen = true;
    episodeBeginTime = at;
    // The window opens with the CONTACT, not with the tick that noticed it.
    truthAt({{"kind", "episode.begin"}}, at);
}

void CausalScenario::recordIntervention(const std::string& cause,
                                        const std::string& interventionClass,
                                        const std::string& variable,
                                        const std::string& magnitude,
                                        const std::string& units,
                                        long targetSequence,
                                        simtime_t targetTime)
{
    if (!isActive())
        return;
    if (interventionEmitted)
        throw cRuntimeError("CausalScenario: a second intervention row for run "
                            "'%s'; one episode carries exactly one pair "
                            "intervention", runIdStr.c_str());
    interventionEmitted = true;
    std::ostringstream sendTime;
    sendTime << targetTime;
    truth({{"kind", "intervention"},
           {"cause", cause},
           {"intervention_class", interventionClass},
           {"variable", variable},
           {"magnitude", magnitude},
           {"units", units},
           {"target_seq", std::to_string(targetSequence)},
           {"target_send_time", sendTime.str()},
           {"schedule_onset_offset_s", onsetOffset.str()},
           {"schedule_duration", std::to_string(durationObservations)}});
}

void CausalScenario::recordThirdCause(const std::string& variable,
                                      const std::string& magnitude,
                                      const std::string& units)
{
    if (!isActive() || rbArm != RB_THIRD_CAUSE || thirdCauseEmitted)
        return;
    thirdCauseEmitted = true;
    // truth_causes.third_cause_classes is a closed set with exactly one member;
    // an unregistered class fails D-TRUTH-INTERVENTION-01 at the accepting end.
    // The row still carries the run's own arm: a third-cause perturbation is
    // outside the matched design but it is not outside the run.
    truth({{"kind", "intervention"},
           {"cause", "third_cause"},
           {"intervention_class", "third_cause_model_error"},
           {"variable", variable},
           {"magnitude", magnitude},
           {"units", units},
           {"target_seq", std::to_string(targetSeq)},
           {"target_send_time", targetSendTime.str()},
           {"schedule_onset_offset_s", onsetOffset.str()},
           {"schedule_duration", std::to_string(durationObservations)}});
}

void CausalScenario::closeEpisode(simtime_t at)
{
    if (!isActive() || !episodeOpen)
        return;
    episodeOpen = false;
    episodeEndTime = at;
    truth({{"kind", "episode.end"}});
}

void CausalScenario::finish()
{
    if (!isActive())
        return;
    // A causal run that produced no intervention is a FAILED run and says so.
    // Reporting it as an ordinary quiet run would let a missing injector look
    // like an uneventful experiment.
    if (!interventionEmitted)
        throw cRuntimeError(
            "CausalScenario: run '%s' finished without ever applying its "
            "declared intervention. Candidate observations offered: %ld; "
            "before onset: %ld; rejected because the satellite was sunlit: "
            "%ld; rejected because the eclipse window was too short: %ld. "
            "The onset rule selected nothing, which is a DESIGN failure of "
            "this run and is reported as one, never as an abstention.",
            runIdStr.c_str(), offersSeen, offersBeforeOnset,
            offersRejectedIlluminated, offersRejectedWindow);
    if (episodeOpen)
        throw cRuntimeError("CausalScenario: run '%s' finished with its episode "
                            "still open", runIdStr.c_str());
    recordScalar("causalTargetSeq", targetSeq);
    // the realised measurement of SP-2's eclipse condition. the numbers reach the
    // report from here; saying a constraint was not met beats passing over it.
    recordScalar("causalOffersSeen", offersSeen);
    recordScalar("causalOffersBeforeOnset", offersBeforeOnset);
    recordScalar("causalOffersSunlit", offersRejectedIlluminated);
    recordScalar("causalOffersEclipseWindowShort", offersRejectedWindow);
    recordScalar("causalTargetInEclipse", targetInEclipse ? 1 : 0);
    recordScalar("causalTargetEclipseWindowClear", targetEclipseWindowClear ? 1 : 0);
    recordScalar("causalOnsetTime", onsetTime.dbl());
    recordScalar("causalEpisodeBegin", episodeBeginTime.dbl());
    recordScalar("causalEpisodeEnd", episodeEndTime.dbl());
}

} // namespace lifesat
