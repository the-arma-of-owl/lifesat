#include "RandomDetector.h"

namespace lifesat {

Define_Module(RandomDetector);

simsignal_t RandomDetector::randomAlarmSignal = cComponent::registerSignal("randomAlarm");

void RandomDetector::initialize()
{
    enabled = par("enabled");
    alarmProbability = par("alarmProbability");
    cModule *col = getModuleByPath("^.collector");
    if (col != nullptr)
        collector = check_and_cast<Collector *>(col);
}

void RandomDetector::observe()
{
    if (!enabled) return;
    observations++;
    if (uniform(0, 1) < alarmProbability) {
        alarms++;
        emit(randomAlarmSignal, 1L);
        // scoring runs the random detector through the same path as D2 and D3
        if (collector)
            collector->logEvent("rnd.alarm", {{"n", std::to_string(observations)}});
    }
}

void RandomDetector::finish()
{
    recordScalar("randomAlarms", alarms);
    recordScalar("randomObservations", observations);
}

} // namespace lifesat
