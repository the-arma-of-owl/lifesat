//
// LIFESAT collector and forensic log
//
#include "Collector.h"

#include <sys/stat.h>
#include <sstream>

namespace lifesat {

Define_Module(Collector);

void Collector::initialize()
{
    runLabel = par("runLabel").stdstringValue();
    outputDir = par("outputDir").stdstringValue();
    writeEventLog = par("writeEventLog");

    if (runLabel.empty())
        runLabel = "run";

    ::mkdir(outputDir.c_str(), 0755);

    std::ostringstream base;
    base << outputDir << "/" << runLabel
         << "-r" << getEnvir()->getConfigEx()->getActiveRunNumber();

    if (writeEventLog) {
        eventLog.open(base.str() + "-events.csv");
        if (!eventLog)
            throw cRuntimeError("cannot open event log '%s-events.csv'", base.str().c_str());
        // 'chain' is the running hash; 'prev' lets a verifier recompute it
        eventLog << "idx,time,category,fields,prev,chain\n";
    }

    truthLog.open(base.str() + "-truth.csv");
    if (!truthLog)
        throw cRuntimeError("cannot open truth log '%s-truth.csv'", base.str().c_str());
    truthLog << "idx,time,fields\n";

    EV_INFO << "collector: run '" << runLabel << "', genesis chain head "
            << chain.getHead().substr(0, 16) << "...\n";
}

void Collector::handleMessage(cMessage *msg)
{
    throw cRuntimeError("Collector does not receive messages");
}

std::string Collector::serialise(const Fields& fields)
{
    std::ostringstream out;
    bool first = true;
    for (const auto& f : fields) {
        if (!first) out << ';';
        out << f.first << '=' << f.second;
        first = false;
    }
    return out.str();
}

std::string Collector::logEvent(const char *category, const Fields& fields)
{
    std::string payload = serialise(fields);

    // The chained record is exactly what is written, so a verifier reading the
    // CSV can recompute the chain without knowing anything about this code.
    std::ostringstream rec;
    rec << eventIndex << ',' << simTime().str() << ',' << category << ',' << payload;
    std::string record = rec.str();

    std::string prev = chain.getHead();
    std::string head = chain.append(record);

    if (writeEventLog)
        eventLog << record << ',' << prev << ',' << head << '\n';

    eventIndex++;
    counters[std::string("event.") + category]++;
    return head;
}

void Collector::recordGroundTruth(const Fields& fields)
{
    truthLog << truthIndex << ',' << simTime().str() << ',' << serialise(fields) << '\n';
    truthIndex++;
    counters["groundTruthRecords"]++;
}

long Collector::getCount(const char *name) const
{
    auto it = counters.find(name);
    return it == counters.end() ? 0 : it->second;
}

void Collector::finish()
{
    if (eventLog.is_open()) eventLog.close();
    if (truthLog.is_open()) truthLog.close();

    for (const auto& c : counters)
        recordScalar(c.first.c_str(), c.second);

    recordScalar("chainLength", (double)chain.getCount());

    // The final chain head is the run's integrity anchor (§3.5, A7).  It is a
    // string, so it goes to its own file rather than to the scalar result file;
    // the verifier recomputes the chain from the event CSV and compares.
    std::ostringstream anchorPath;
    anchorPath << outputDir << "/" << runLabel
               << "-r" << getEnvir()->getConfigEx()->getActiveRunNumber() << "-anchor.txt";
    std::ofstream anchor(anchorPath.str());
    anchor << "genesisInput=" << HashChain::GENESIS_INPUT << "\n"
           << "chainLength=" << chain.getCount() << "\n"
           << "chainHead=" << chain.getHead() << "\n";
    anchor.close();

    EV_INFO << "collector: " << chain.getCount() << " chained events, head "
            << chain.getHead() << "\n";
}

} // namespace lifesat
