//
// LIFESAT telecommand and telemetry packets
//
// No ground-truth field appears here and none may. A packet carries no more than a
// real ground station would see on the wire. What the attacker did is recorded only
// through Collector::recordGroundTruth(), on a path separate from the packet.
// tests/check_label_isolation.py scans this file for isAttack, attackLabel,
// groundTruth, isMalicious and tampered, and closes the phase gate on a hit.
//
// A detector therefore has no field to consult, so the shortcut is structurally
// unavailable rather than merely disclaimed.
//
cplusplus {{
#include "inet/common/INETDefs.h"
}}

namespace lifesat;

//
// Satellite operating mode, a component of the logical state channel
//
enum SatMode
{
    MODE_NOMINAL = 0;
    MODE_SAFE    = 1;   // autonomous fallback mode (§4.4: both a mitigation and an attack surface)
    MODE_PAYLOAD = 2;
}

//
// Telecommand classes. A2 (unauthorised command) and A6 (unauthorised update) are
// drawn from this set; only nominal ones flow under B0.
//
enum CommandType
{
    CMD_NOOP      = 0;
    CMD_SET_PARAM = 1;
    CMD_SET_MODE  = 2;
    CMD_UPDATE    = 3;   // software/configuration update (A6, L1)
}

//
// Ground to satellite telecommand.
//
// sequence and issuedAt carry freshness and D1 checks them: command payloads need a
// count or nonce against replay and spoofing. authTag is produced in phase 1 but not
// verified under D0.
//
packet Telecommand
{
    long commandId;
    long sequence;
    simtime_t issuedAt;
    int commandType @enum(CommandType) = CMD_NOOP;

    string paramKey = "";
    double paramValue = 0;
    int targetMode @enum(SatMode) = MODE_NOMINAL;

    string authTag = "";        // the signature D1 will verify
    string payloadDigest = "";  // body digest for the integrity check
}

//
// Satellite to ground telemetry, carrying the three state channels (section 5.1).
//
// These are declared behaviour models, not a validated power or thermal model of a
// platform; the limit is stated in L6.
//
packet Telemetry
{
    long telemetrySeq;
    simtime_t sourceTime;       // instant of generation onboard -- the twin's delay measurement rests on this

    // physical channel
    double batteryVoltage;      // V
    bool illuminated;           // in sunlight or in eclipse

    // logical channel
    int mode @enum(SatMode) = MODE_NOMINAL;
    string paramDigest = "";    // digest of the parameter store

    // Id of the accepted command that last changed the logical state.
    //
    // Not a ground-truth label: it is read from the satellite's own command ledger and
    // the ground already sees the same id in tc.accept rows. It says nothing about
    // attack versus fault, only which command wrote the state.
    long modeWriteCmdId = -1;
    long modeWriteSeq = -1;
    // per-key lineage of the parameter store: "key:cmdId:seq;..." with one entry per
    // prevailing write. a single last-writer pointer was not enough: an unrelated
    // routine command overwrote it and the responsible command was lost.
    string paramWriteProvenance = "";

    // security channel
    long rejectedCmdCount;      // number of commands D1 rejected (the target of A7c)
    long acceptedCmdCount;

    string integrityTag = "";
}
