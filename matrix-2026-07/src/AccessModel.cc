//
// LIFESAT -- contact window model
//
#include "AccessModel.h"

#include "inet/common/ModuleAccess.h"
#include "inet/common/geometry/common/Wgs84.h"

namespace lifesat {

Define_Module(AccessModel);

simsignal_t AccessModel::elevationSignal = cComponent::registerSignal("elevation");
simsignal_t AccessModel::slantRangeSignal = cComponent::registerSignal("slantRange");
simsignal_t AccessModel::accessStateSignal = cComponent::registerSignal("accessState");
simsignal_t AccessModel::passStartSignal = cComponent::registerSignal("passStart");
simsignal_t AccessModel::passEndSignal = cComponent::registerSignal("passEnd");

AccessModel::~AccessModel()
{
    cancelAndDelete(sampleTimer);
}

void AccessModel::initialize(int stage)
{
    cSimpleModule::initialize(stage);

    if (stage == INITSTAGE_LOCAL) {
        elevationMaskDeg = par("elevationMask").doubleValue();
        updateInterval = par("updateInterval");
    }
    else if (stage == INITSTAGE_SINGLE_MOBILITY) {
        const char *path = par("satelliteMobilityModule");
        cModule *mobilityModule = getModuleByPath(path);
        if (mobilityModule == nullptr)
            throw cRuntimeError("satelliteMobilityModule '%s' not found", path);
        satelliteMobility = check_and_cast<SatelliteMobility *>(mobilityModule);

        // note: 'm' here is INET's metre unit type and must not be shadowed, or the
        // GeoCoord constructor will not compile.
        GeoCoord gsGeo(deg(par("groundStationLatitude").doubleValue()),
                       deg(par("groundStationLongitude").doubleValue()),
                       m(par("groundStationAltitude").doubleValue()));
        gsEcef = wgs84::geodeticToEcef(gsGeo);

        double latRad = M_PI / 180.0 * gsGeo.latitude.get();
        double lonRad = M_PI / 180.0 * gsGeo.longitude.get();
        gsUp = Coord(std::cos(latRad) * std::cos(lonRad),
                     std::cos(latRad) * std::sin(lonRad),
                     std::sin(latRad));

        cModule *collectorModule = getModuleByPath("^.collector");
        if (collectorModule != nullptr)
            collector = check_and_cast<Collector *>(collectorModule);

        // emit the initial state at t=0. without it timeavg covers only the period
        // after the first transition and the visibility fraction comes out too high
        // (1.650% instead of 1.583%).
        emit(accessStateSignal, 0L);

        sampleTimer = new cMessage("accessSample");
        scheduleAt(simTime(), sampleTimer);
    }
}

void AccessModel::handleMessage(cMessage *msg)
{
    if (msg != sampleTimer)
        throw cRuntimeError("AccessModel received an unexpected message");
    sample();
    scheduleAt(simTime() + updateInterval, sampleTimer);
}

double AccessModel::computeElevationDeg(const Coord& satEcef, double& rangeOut) const
{
    Coord los = satEcef - gsEcef;
    double range = los.length();
    rangeOut = range;
    if (range <= 0)
        return 90;
    double sinEl = (gsUp * los) / range;   // Coord::operator* is the dot product
    sinEl = std::max(-1.0, std::min(1.0, sinEl));
    return 180.0 / M_PI * std::asin(sinEl);
}

void AccessModel::sample()
{
    // SatelliteMobility with coordinateSystemModule="" reports raw ECEF metres.
    Coord satEcef = satelliteMobility->getCurrentPosition();

    double range = NaN;
    double elDeg = computeElevationDeg(satEcef, range);
    lastElevationDeg = elDeg;
    lastRangeM = range;

    emit(elevationSignal, elDeg);
    emit(slantRangeSignal, range);

    bool nowVisible = (elDeg >= elevationMaskDeg);
    if (nowVisible != visible) {
        visible = nowVisible;
        emit(accessStateSignal, (long)(visible ? 1 : 0));
        if (visible) {
            currentPassStart = simTime();
            passCount++;
            emit(passStartSignal, simTime());
            if (collector)
                collector->logEvent("pass.start", {{"pass", std::to_string(passCount)},
                                                   {"elevationDeg", std::to_string(elDeg)}});
            EV_INFO << "pass " << passCount << " start, elevation " << elDeg << " deg\n";
        }
        else {
            lastPassEnd = simTime();
            currentPassStart = -1;
            emit(passEndSignal, simTime());
            if (collector)
                collector->logEvent("pass.end", {{"pass", std::to_string(passCount)},
                                                 {"durationS", (simTime() - passStartOfCurrent).str()}});
            EV_INFO << "pass " << passCount << " end\n";
        }
        if (visible)
            passStartOfCurrent = simTime();
    }
    if (visible)
        lastVisibleTime = simTime();
}

simtime_t AccessModel::getTimeSinceLastAccess() const
{
    if (visible)
        return SIMTIME_ZERO;
    if (lastVisibleTime < SIMTIME_ZERO)
        return simTime();   // no contact yet at all
    return simTime() - lastVisibleTime;
}

void AccessModel::finish()
{
    recordScalar("passCount", passCount);
}

} // namespace lifesat
