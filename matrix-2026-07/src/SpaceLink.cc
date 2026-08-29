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
    }
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
