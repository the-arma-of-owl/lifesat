#include "SpaceLink.h"

namespace lifesat {

Define_Module(SpaceLink);

simsignal_t SpaceLink::deliveredUpSignal = cComponent::registerSignal("deliveredUp");
simsignal_t SpaceLink::deliveredDownSignal = cComponent::registerSignal("deliveredDown");
simsignal_t SpaceLink::droppedNoAccessSignal = cComponent::registerSignal("droppedNoAccess");
simsignal_t SpaceLink::propagationDelaySignal = cComponent::registerSignal("propagationDelay");

void SpaceLink::initialize(int stage)
{
    cSimpleModule::initialize(stage);
    if (stage == INITSTAGE_LOCAL) {
        bitrateUp = par("bitrateUp").doubleValue();
        bitrateDown = par("bitrateDown").doubleValue();
        c = par("propagationSpeed").doubleValue();
    }
    else if (stage == INITSTAGE_SINGLE_MOBILITY) {
        access = check_and_cast<AccessModel *>(getModuleByPath(par("accessModule")));
        cModule *col = getModuleByPath("^.collector");
        if (col != nullptr)
            collector = check_and_cast<Collector *>(col);
        cModule *cs = getModuleByPath(par("causalModule"));
        if (cs != nullptr)
            causal = check_and_cast<CausalScenario *>(cs);
    }
}

SpaceLink::~SpaceLink()
{
    if (reorderHeld != nullptr)
        delete reorderHeld;
}

bool SpaceLink::causalCoverageGap(cMessage *msg, simtime_t transferDelay)
{
    auto *tm = dynamic_cast<Telemetry *>(msg);
    if (tm == nullptr)
        return false;

    // the outage interval is closed: [t0, t0+delay]. using >= left a frame produced
    // exactly at t0+delay outside the outage, and that frame arrived a few hundred
    // microseconds before the held one, so another delivery happened during the outage.
    if (coverageGapOpen && simTime() > coverageGapEnd)
        coverageGapOpen = false;

    if (!coverageGapOpen && causal->isTarget(tm->getTelemetrySeq())) {
        // the outage opens exactly at the target observation and lasts the declared
        // interval. the held frame takes that interval on top of its base age;
        // propagation and transmission are already accounted for here, so the reported
        // age is the same number on both arms.
        coverageGapOpen = true;
        coverageGapEnd = simTime() + causal->getDelayTarget();
        collector->logEvent("link.drop", {{"dir", "down"}, {"reason", "coverage"}});
        sendDelayed(msg, transferDelay + causal->getDelayTarget(), "groundOut");
        deliveredDown++;
        emit(deliveredDownSignal, 1L);
        return true;
    }

    if (coverageGapOpen) {
        // no other delivery happens while the outage lasts. these are genuinely lost and
        // the reason is recorded.
        droppedNoAccess++;
        droppedDown++;
        emit(droppedNoAccessSignal, 1L);
        collector->count("link.droppedNoAccess");
        collector->logEvent("link.drop", {{"dir", "down"}, {"reason", "coverage"}});
        delete msg;
        return true;
    }
    return false;
}

bool SpaceLink::causalReorder(cMessage *msg, simtime_t transferDelay)
{
    auto *tm = dynamic_cast<Telemetry *>(msg);
    if (tm == nullptr)
        return false;

    int index = causal->noteContactFrame(access->getCurrentPassStart());
    if (index < 0)
        return false;

    if (index == 0) {
        // the first frame is held. the contract gives this arm's row time as the delayed
        // frame's send time, which is exactly this moment: when the frame reaches the
        // link, in the same second as its send.
        reorderHeld = msg;
        reorderHeldDelay = transferDelay;
        causal->setTarget(tm->getTelemetrySeq(), tm->getSourceTime());
        causal->recordIntervention(
            "fault", "delivery_reordering",
            "downlink delivery order, by a benign reordering of two in-flight frames",
            "exact identifier equality", "identifier",
            tm->getTelemetrySeq(), tm->getSourceTime());
        return true;
    }

    if (index == reorderReleaseAfter && reorderHeld != nullptr) {
        // after the third frame passes, the held frame is delivered for the first time.
        // its sequence number regresses but its source time was never seen before: a
        // reordering, not a replay.
        //
        // sent directly rather than through forward(), which would re-apply the outage.
        sendDelayed(msg, transferDelay, "groundOut");
        deliveredDown++;
        emit(deliveredDownSignal, 1L);
        cMessage *held = reorderHeld;
        reorderHeld = nullptr;
        // the held frame must arrive strictly after the third: arriving together would
        // make "third delivery" follow from the tie key rather than the delivery order.
        sendDelayed(held, transferDelay + SimTime(1, SIMTIME_MS), "groundOut");
        deliveredDown++;
        emit(deliveredDownSignal, 1L);
        return true;
    }
    return false;
}

void SpaceLink::forward(cMessage *msg, const char *gate, double bitrate, const char *dir)
{
    if (!access->isVisible()) {
        droppedNoAccess++;
        if (strcmp(dir, "up") == 0) droppedUp++; else droppedDown++;
        emit(droppedNoAccessSignal, 1L);
        if (collector) {
            collector->count("link.droppedNoAccess");
            collector->logEvent("link.drop", {{"dir", dir}, {"reason", "coverage"}});
        }
        delete msg;
        return;
    }

    // delay from geometry: slant range from the SGP4 position, divided by c
    double range = access->getSlantRangeM();
    simtime_t prop = range / c;
    simtime_t tx = SIMTIME_ZERO;
    if (auto *pk = dynamic_cast<cPacket *>(msg))
        tx = pk->getBitLength() / bitrate;

    emit(propagationDelaySignal, prop);

    // phase 3: benign link faults, downlink only
    // propagation and transmission times are already computed and kept as they are; a
    // benign fault shifts only the delivery time. recomputing the frame later would
    // change its reported age.
    if (causal != nullptr && causal->isActive() && causal->isFault()
            && strcmp(dir, "down") == 0) {
        if (causal->getPair() == CausalScenario::SP4
                && causalCoverageGap(msg, prop + tx))
            return;
        if (causal->getPair() == CausalScenario::SP6
                && causalReorder(msg, prop + tx))
            return;
    }

    if (strcmp(dir, "up") == 0) { deliveredUp++; emit(deliveredUpSignal, 1L); }
    else                        { deliveredDown++; emit(deliveredDownSignal, 1L); }

    sendDelayed(msg, prop + tx, gate);
}

void SpaceLink::handleMessage(cMessage *msg)
{
    if (msg->arrivedOn("groundIn"))
        forward(msg, "satOut", bitrateUp, "up");
    else if (msg->arrivedOn("satIn"))
        forward(msg, "groundOut", bitrateDown, "down");
    else
        throw cRuntimeError("SpaceLink: unexpected gate");
}

void SpaceLink::finish()
{
    recordScalar("deliveredUp", deliveredUp);
    recordScalar("deliveredDown", deliveredDown);
    recordScalar("droppedNoAccess", droppedNoAccess);
    recordScalar("droppedUp", droppedUp);
    recordScalar("droppedDown", droppedDown);
}

} // namespace lifesat
