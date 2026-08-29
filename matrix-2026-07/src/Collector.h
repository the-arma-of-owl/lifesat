//
// LIFESAT collector and forensic log
//
#ifndef __LIFESAT_COLLECTOR_H
#define __LIFESAT_COLLECTOR_H

#include <fstream>
#include <map>
#include <string>
#include <vector>

#include "inet/common/INETDefs.h"

#include "HashChain.h"

namespace lifesat {

using namespace inet;

/**
 * Run-wide event sink and tamper-evident forensic log.
 *
 * Two kinds of record go in, from opposite directions:
 *
 *   logEvent()          - what an observer at the ground station could see
 *                         (packet sent/received/dropped, detector decision,
 *                         pass start/end).  This is the forensic record.
 *
 *   recordGroundTruth() - what the attacker actually did.  This is the answer
 *                         key.  Only the attacker calls it, and nothing reads
 *                         it back during the run; it is written to a separate
 *                         file and joined offline during scoring.
 *
 * Keeping the two apart is rule R1: a detector cannot consult the answer key,
 * because no code path leads from the answer key to a detector.
 */
class Collector : public cSimpleModule
{
  public:
    typedef std::vector<std::pair<std::string, std::string>> Fields;

  protected:
    std::string runLabel;
    std::string outputDir;
    bool writeEventLog = true;

    HashChain chain;
    std::ofstream eventLog;    // forensic record, hash-chained
    std::ofstream truthLog;    // ground truth, never read during the run

    uint64_t eventIndex = 0;
    uint64_t truthIndex = 0;
    std::map<std::string, long> counters;

  protected:
    virtual void initialize() override;
    virtual void handleMessage(cMessage *msg) override;
    virtual void finish() override;

    /** Serialises fields as a stable CSV cell string used as the chain input. */
    static std::string serialise(const Fields& fields);

  public:
    /**
     * Appends one observable event to the forensic log and extends the chain.
     * Returns the new chain head.
     */
    virtual std::string logEvent(const char *category, const Fields& fields);

    /**
     * Records what the attacker did.   Answer key -- must never be consulted
     * by a detector, a defence or the twin.
     */
    virtual void recordGroundTruth(const Fields& fields);

    /** Increments a named counter; all counters are written as scalars. */
    virtual void count(const char *name, long by = 1) { counters[name] += by; }

    virtual long getCount(const char *name) const;

    virtual const std::string& getChainHead() const { return chain.getHead(); }
    virtual uint64_t getChainLength() const { return chain.getCount(); }
};

} // namespace lifesat

#endif
