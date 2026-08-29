//
// LIFESAT twin and deviation detector (D3)
//
#ifndef __LIFESAT_TWIN_H
#define __LIFESAT_TWIN_H

#include <map>
#include <string>

#include "inet/common/INETDefs.h"
#include "inet/mobility/single/SatelliteMobility.h"

#include "AccessModel.h"
#include "Collector.h"
#include "LifesatPackets_m.h"
#include "PowerModel.h"

namespace lifesat {

using namespace inet;

/**
 * The ground-side twin of the satellite.
 *
 * It advances the expected value of the three channels **continuously** (even while
 * the satellite is out of view), compares it with incoming telemetry and applies the
 * two-part tolerance of §3.2:
 *
 *   temporal bound  dt  = time since the last contact (from AccessModel)
 *   state bound         = the deviation the channel model allows over dt
 *
 * The alarm condition is **not delay** but exceeding the state bound accepted
 * for the current dt.
 *
 *  R1: no ground-truth label is or can be available here.  The inputs are:
 *    · the telemetry packet (what a real ground station would see)
 *    · the ground's own approved command history (from the operator gate)
 */
class Twin : public cSimpleModule
{
  public:
    /** The ground station hands every telemetry it receives to this. */
    virtual void observeTelemetry(const Telemetry *tm);

    /** The twin is notified whenever the operator approves and sends a command. */
    virtual void noteApprovedCommand(const Telecommand *tc);

    /** When D1 rejects a command the ground's own counter advances (safety channel). */
    virtual void noteRejectedCommand() { expectedRejectedCount++; }

    /**
     * Result of the pre-uplink validation.
     *
     *  A boolean is not enough: "not rejected" and "approved" are different
     * things. For a parameter outside the envelope the gate can say nothing, and
     * recording that as approval would be fail-open.
     * cannot count.
     */
    enum UpdateVerdict {
        UPDATE_APPROVED,     // inside the envelope -- may be uplinked
        UPDATE_REJECTED,     // violates the envelope -- not uplinked
        UPDATE_UNSUPPORTED   // parameter the twin cannot model -- NO verdict, not uplinked
    };

    /**
     *  PRE-UPLINK VALIDATION -- the core of the in-orbit phase of the abstract:
     * *"Security patches and configuration updates are first tested within the
     * DT.  Upon successful validation, verified updates are transmitted."*
     *
     * The candidate update is forward-simulated on a COPY of the twin's model and
     * checked against the declared safety envelope. On a negative verdict the command
     * is never sent, so this is prevention rather than detection.
     *
     *  A gate independent of the cryptographic check (D1): a validly signed but
     * behaviourally unsafe update passes D1 and fails here. This is the
     * authentication-versus-safety separation the paper describes.
     *
     *  FAIL-CLOSED: only UPDATE_APPROVED permits an uplink.  An update the gate
     * could not evaluate is not let through as "no problem seen".
     */
    virtual UpdateVerdict validateUpdate(const std::string& key, double value,
                                         std::string& reason);

  protected:
    AccessModel *access = nullptr;
    SatelliteMobility *mobility = nullptr;
    Collector *collector = nullptr;

    bool enabled = true;
    double epochJulianDate = 0;
    simtime_t updateInterval;
    cMessage *stepTimer = nullptr;

    // --- the twin's own state ---------------------------------------------
    PowerModel model;                       // off from the satellite's by rateBias
    long expectedRejectedCount = 0;
    long unexplainedRejections = 0;   // rejections the ground cannot account for

    /**
     * **Timestamped** history of approved commands.
     *
     *  This is a list, not one expected state, and the reason is the subject of
     * section 3.2. Incoming telemetry reports a past instant of the satellite; the
     * twin cannot know which commands had landed by then.
     */
    struct ApprovedCommand {
        simtime_t sentAt;
        int type;
        std::string paramKey;
        double paramValue;
        int targetMode;
    };
    std::vector<ApprovedCommand> approved;
    simtime_t uplinkDelayBound;

    /**
     * The last command prefix **confirmed** by telemetry.
     *
     *  The twin cannot assume a sent command reached the satellite. A command may
     * be dropped at the edge of a contact window, and the ground learns that only
     * from telemetry. Assuming otherwise creates a standing phantom deviation.
     *
     * This counter advances only when an observation MATCHES a prefix; when it does
     * not, an alarm is raised and the counter does not advance.  The twin is thereby
     * a state estimator.
     */
    size_t confirmedPrefix = 0;

    // --- tolerance parameters ----------------------------------------------
    double rateUncertainty = 0.10;
    double nominalDischargeRate = 0.00008;
    double noiseSigma = 0.01;
    double sigmaFactor = 3.0;
    simtime_t maxTemporalBound;
    bool resyncOnMatch = true;

    // --- pre-uplink validation envelope (A6s) -----------------------------
    // declared, not learned: orbital period and illuminated fraction come from
    // pre-flight geometry (SGP4 plus almanac), the safety floor from the mission.
    simtime_t validationHorizon;
    double orbitalPeriod = 5724.0;      // s -- FUNCUBE-1, 95,4 dk
    double illuminationDuty = 0.688;    // measured (analysis/select_tle.py), not assumed
    double safetyFloorVoltage = 7.0;
    long updatesValidated = 0, updatesRejected = 0, updatesUnsupported = 0;
    long updatesAppliedToModel = 0;

    // --- measurement -------------------------------------------------------
    simtime_t lastObservation = -1;
    long alarms = 0, observations = 0;
    long alarmPhysical = 0, alarmLogical = 0, alarmSecurity = 0;

    static simsignal_t voltageDeviationSignal, voltageBoundSignal;
    static simsignal_t temporalLagSignal, d3AlarmSignal, d3AlarmChannelSignal;

  protected:
    virtual void initialize(int stage) override;
    virtual int numInitStages() const override { return NUM_INIT_STAGES; }
    virtual void handleMessage(cMessage *msg) override;
    virtual void finish() override;

    /** Advances the twin's model one step (runs even while the satellite is out of view). */
    virtual void stepModel();

    /**
     * Physical state bound allowed for a given dt:
     *   sigmaFactor·sigma                  measurement noise
     * + rateUncertainty·nominalRate·dt     accumulated model error
     *
     * The second term grows with dt: the longer the contact gap, the more
     * naturally uncertain the twin's knowledge becomes.  Counting that
     * uncertainty as an alarm is what §3.2 rejects; bounding it is what it argues for.
     */
    virtual double physicalStateBound(simtime_t dt) const;

    /** Digest of the parameter store with the first `n` commands applied. */
    virtual std::string paramDigestAfter(size_t n) const;
    /** Operating mode with the first `n` commands applied. */
    virtual SatMode modeAfter(size_t n) const;

    /**
     * Acceptable command prefix interval for telemetry source time `ts`.
     *
     *   lower bound : confirmedPrefix -- the last state confirmed by telemetry.
     *                 Based on evidence, NOT on send time.
     *   upper bound : every command sent up to the instant `ts`.
     *
     * Any prefix in between is possible: the command may be in flight, may have been
     * dropped, or may have been applied.  The twin cannot count that uncertainty as an
     * alarm (§3.2).
     */
    virtual size_t sentByTime(simtime_t ts) const;

    /**
     * When `confirmedPrefix` advances, the PHYSICAL effects of the newly confirmed
     * commands are applied to the twin's working model.
     *
     *  Applied at confirmation rather than at send time: a sent command may never
     * arrive (it can drop at the contact edge). Applying at send time would let the
     * twin advance on something that never happened onboard.
     *
     *  Without this the twin drifted permanently after an update it had itself
     * approved: the satellite ran on the new discharge rate while the twin stayed on
     * the old one.
     */
    virtual void applyConfirmedPhysicalEffects(size_t from, size_t to);

  public:
    virtual ~Twin();
};

} // namespace lifesat
#endif
