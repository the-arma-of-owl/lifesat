//
// LIFESAT -- phase 3 causal scenario controller
//
#ifndef __LIFESAT_CAUSALSCENARIO_H
#define __LIFESAT_CAUSALSCENARIO_H

#include <string>
#include <vector>

#include "inet/common/INETDefs.h"

#include "AccessModel.h"
#include "Collector.h"

namespace lifesat {

using namespace inet;

/**
 * The deterministic schedule of ONE causal pilot run.
 *
 * The producer modules (CubeSat, OnPathAttacker, SpaceLink, Twin) ask this
 * object narrow, mechanical questions -- "is this sequence the target", "is the
 * coverage gap open" -- and it answers from state that only the run identity and
 * the simulation clock determine.  There is no random draw anywhere in this
 * class and no branch that depends on a value the ground could not also see;
 * the arm selects WHICH mechanism is wired, never WHAT a mechanism observes.
 *
 * Target selection is a single rule, shared by every pair:
 *
 *     the first tm.send at or after (first pass.start + onsetOffsetS)
 *
 * SP-2 adds the contract's own eclipse condition and SP-6 works on the target
 * CONTACT rather than a single observation; both are stated below where they
 * are implemented, not in an ini file.
 */
class CausalScenario : public cSimpleModule
{
  public:
    enum Pair { PAIR_NONE, SP1, SP2, SP3, SP4, SP5, SP6 };
    enum Arm { ARM_NONE, ATTACK, FAULT };
    enum RbArm { RB_NONE, RB_MODEL_MISMATCH, RB_SENSOR_ERROR, RB_THIRD_CAUSE };

  protected:
    Collector *collector = nullptr;
    AccessModel *access = nullptr;

    std::string pairIdStr, armStr, robustnessArmStr, runIdStr;
    Pair pair = PAIR_NONE;
    Arm arm = ARM_NONE;
    RbArm rbArm = RB_NONE;
    long runSeedIndex = 0;

    simtime_t onsetOffset;
    int durationObservations = 1;
    double targetDeviationV = 0.15;
    double perturbedDischargeRate = 0.00048;
    // Amendment v5: the SUNLIT-branch coefficient SP-2 now manipulates.
    double perturbedChargeRate = -0.00043;
    simtime_t sp2MinContactDuration;
    simtime_t sp2Window;
    simtime_t activationGuard;
    double minVoltageV = 6.0;
    double clippingMarginV = 0.05;
    simtime_t sp2SelectedContactStart = -1;
    simtime_t sp2SelectedContactEnd = -1;
    int eclipseSteps = 100;
    int modeOrdinalDelta = 1;
    simtime_t delayTarget;
    int counterTargetDelta = 3;
    int replayWindowObservations = 3;
    double robustnessMagnitude = 0.0;

    // --- schedule state ----------------------------------------------------
    simtime_t firstPassStart = -1;
    simtime_t onsetTime = -1;        // (firstPassStart + onsetOffset)
    long targetSeq = -1;             // the single targeted observation
    simtime_t targetSendTime = -1;
    // SP-5's onset rule names "the second tm.send of the target observation
    // pair": the schedule selects the pair's FIRST observation and the
    // intervention lands on the one after it, which is what makes the ground
    // counter move BETWEEN two consecutive observations of the same contact.
    long anchorSeq = -1;
    simtime_t episodeStartContact = -1;
    simtime_t plannedEnd = -1;
    simtime_t telemetryInterval;
    bool episodeOpen = false;
    bool interventionEmitted = false;
    bool thirdCauseEmitted = false;
    simtime_t episodeBeginTime = -1;
    simtime_t episodeEndTime = -1;

    // SP-6 works on the target CONTACT: its pass start and the frame index
    // inside it.
    simtime_t targetContactStart = -1;
    int contactFrameIndex = -1;
    long hostileCmdId = -1;
    // candidate counters. when a run never selects its target, we must say which
    // condition left it open: "no observation selected" is an outcome, not a diagnosis.
    long offersSeen = 0;
    long offersBeforeOnset = 0;
    long offersRejectedIlluminated = 0;
    long offersRejectedWindow = 0;
    // SP-2: whether the eclipse condition held at the target instant. does not stop the
    // run, but appears by name in the pilot report.
    bool targetInEclipse = false;
    bool targetEclipseWindowClear = false;

  protected:
    virtual void initialize(int stage) override;
    virtual int numInitStages() const override { return NUM_INIT_STAGES; }
    virtual void handleMessage(cMessage *msg) override;

    void truth(const Collector::Fields& extra);
    void truthAt(const Collector::Fields& extra, simtime_t at);
    simtime_t declaredEnd() const;
    static Pair parsePair(const std::string& id);
    static Arm parseArm(const std::string& id);
    static RbArm parseRbArm(const std::string& id);

  public:
    bool isActive() const { return pair != PAIR_NONE; }
    bool isAttack() const { return arm == ATTACK; }
    bool isFault() const { return arm == FAULT; }
    Pair getPair() const { return pair; }
    RbArm getRobustnessArm() const { return rbArm; }
    double getRobustnessMagnitude() const { return robustnessMagnitude; }
    long getTargetSeq() const { return targetSeq; }
    simtime_t getTargetSendTime() const { return targetSendTime; }
    simtime_t getDelayTarget() const { return delayTarget; }
    int getCounterTargetDelta() const { return counterTargetDelta; }
    double getTargetDeviationV() const { return targetDeviationV; }
    double getPerturbedDischargeRate() const { return perturbedDischargeRate; }
    double getPerturbedChargeRate() const { return perturbedChargeRate; }
    simtime_t getSp2Window() const { return sp2Window; }
    simtime_t getActivationGuard() const { return activationGuard; }
    double getMinVoltageV() const { return minVoltageV; }
    double getClippingMarginV() const { return clippingMarginV; }
    simtime_t getSelectedContactStart() const { return sp2SelectedContactStart; }
    simtime_t getSelectedContactEnd() const { return sp2SelectedContactEnd; }
    int getModeOrdinalDelta() const { return modeOrdinalDelta; }
    int getEclipseSteps() const { return eclipseSteps; }

    /** The deterministic sensor offset the RB-sensor-error arm adds to BOTH
     *  copies of the reported value.  Zero in every other arm. */
    double sensorErrorOffset() const
    { return rbArm == RB_SENSOR_ERROR ? robustnessMagnitude : 0.0; }

    /**
     * Offered every telemetry generation, BEFORE the packet is written.
     * Returns true exactly once per run, on the observation the contract's
     * onset rule selects.  `eclipseWindowClear` is the caller's answer to the
     * SP-2 condition "the intervention window lies wholly inside eclipse".
     */
    bool offerTelemetryTarget(long seq, bool illuminated, bool eclipseWindowClear);

    /** True once the target has been selected and this is it. */
    bool isTarget(long seq) const { return targetSeq >= 0 && seq == targetSeq; }

    /** The pair's first observation, for the SP-5 pair. */
    long getAnchorSeq() const { return anchorSeq; }

    /**
     * Called on every telemetry tick.  Opens the episode at the target
     * contact's start and closes it at the pair's declared end rule, so the
     * episode window is a function of the schedule and not of what happened
     * inside it.
     */
    void tickEpisode();

    /** SP-6: frame bookkeeping inside the target contact. */
    int noteContactFrame(simtime_t passStart);

    /** Names the targeted observation when it is only known downlink-side. */
    void setTarget(long seq, simtime_t sendTime);

    /**
     * SP-2/SP-3 attack: the on-path attacker registers the hostile command it
     * uplinked, so the satellite can write the truth row at the instant that
     * command is ACCEPTED -- which is what the contract's onset rule names.
     */
    void noteHostileCommand(long cmdId) { hostileCmdId = cmdId; }
    bool isHostileCommand(long cmdId) const
    { return hostileCmdId >= 0 && cmdId == hostileCmdId; }
    bool inTargetContact(simtime_t passStart) const
    { return targetContactStart >= SIMTIME_ZERO && passStart == targetContactStart; }

    /** Truth authority. Written to the truth log only; never observable. */
    void openEpisode(simtime_t at);
    void recordIntervention(const std::string& cause,
                            const std::string& interventionClass,
                            const std::string& variable,
                            const std::string& magnitude,
                            const std::string& units,
                            long targetSequence,
                            simtime_t targetTime);
    void recordThirdCause(const std::string& variable, const std::string& magnitude,
                          const std::string& units);
    void closeEpisode(simtime_t at);
    bool isEpisodeOpen() const { return episodeOpen; }
    bool hasIntervention() const { return interventionEmitted; }
    bool hasThirdCause() const { return thirdCauseEmitted; }
    bool wasTargetInEclipse() const { return targetInEclipse; }

    virtual void finish() override;
};

} // namespace lifesat

#endif
