#include "FlowDetector.h"

#include <cmath>
#include <fstream>
#include <sstream>

namespace lifesat {

Define_Module(FlowDetector);

simsignal_t FlowDetector::windowPpsSignal = cComponent::registerSignal("windowPps");
simsignal_t FlowDetector::windowBpsSignal = cComponent::registerSignal("windowBps");
simsignal_t FlowDetector::d2AlarmSignal = cComponent::registerSignal("d2Alarm");

FlowDetector::~FlowDetector() { cancelAndDelete(windowTimer); }

void FlowDetector::initialize()
{
    enabled = par("enabled");
    calibrationMode = par("calibrationMode");
    thresholdFile = par("thresholdFile").stdstringValue();
    windowSize = par("windowSize");
    sigmaFactor = par("sigmaFactor");
    sigmaFloorFraction = par("sigmaFloorFraction");

    cModule *col = getModuleByPath("^.collector");
    if (col != nullptr)
        collector = check_and_cast<Collector *>(col);

    if (enabled && !calibrationMode)
        loadThresholds();

    if (enabled) {
        windowTimer = new cMessage("flowWindow");
        scheduleAt(simTime() + windowSize, windowTimer);
    }
}

void FlowDetector::loadThresholds()
{
    if (thresholdFile.empty())
        throw cRuntimeError("D2 is on but no thresholdFile was given -- detection is "
                            "impossible without a threshold derived from B0 (K-59, data leakage)");
    std::ifstream in(thresholdFile);
    if (!in)
        throw cRuntimeError("could not read threshold file: '%s'.  Run the calibration "
                            "pass first (analysis/calibrate_d2.py)",
                            thresholdFile.c_str());
    std::string line;
    while (std::getline(in, line)) {
        std::istringstream s(line);
        std::string key; double val;
        if (std::getline(s, key, '=') && (s >> val)) {
            if (key == "muPps") muPps = val;
            else if (key == "sigmaPps") sigmaPps = val;
            else if (key == "muBps") muBps = val;
            else if (key == "sigmaBps") sigmaBps = val;
            else if (key == "muIat") muIat = val;
            else if (key == "sigmaIat") sigmaIat = val;
        }
    }
    thresholdsLoaded = true;
    EV_INFO << "D2 thresholds loaded: pps " << muPps << "+/-"
            << sigmaFactor * effectiveSigma(sigmaPps, muPps)
            << ", bps " << muBps << "±" << sigmaFactor * effectiveSigma(sigmaBps, muBps)
            << ", iat " << muIat << "±" << sigmaFactor * effectiveSigma(sigmaIat, muIat) << "\n";
}

void FlowDetector::observePacket(long bits)
{
    if (!enabled) return;
    windowPackets++;
    windowBits += bits;

    // inter-arrival time is meaningful only between consecutive packets in the same
    // pass; the gap between passes runs to hours and destroys the statistic. gaps
    // longer than five nominal intervals are treated as pass boundaries and skipped.
    if (lastArrival >= SIMTIME_ZERO) {
        double gap = (simTime() - lastArrival).dbl();
        if (gap <= 5 * windowSize.dbl()) {
            windowIatSum += gap;
            windowIatCount++;
        }
    }
    lastArrival = simTime();
}

void FlowDetector::closeWindow()
{
    double pps = windowPackets / windowSize.dbl();
    double bps = windowBits / windowSize.dbl();
    emit(windowPpsSignal, pps);
    emit(windowBpsSignal, bps);

    if (calibrationMode) {
        // only windows with traffic are accumulated: 98% of LEO windows are empty and
        // including them drives mu to zero and makes sigma meaningless.
        if (windowPackets > 0) {
            nWindows++;
            sumPps += pps; sumSqPps += pps * pps;
            sumBps += bps; sumSqBps += bps * bps;
        }
        if (windowIatCount > 0) {
            double iat = windowIatSum / windowIatCount;
            nIatWindows++;
            sumIat += iat; sumSqIat += iat * iat;
        }
    }
    else if (thresholdsLoaded && windowPackets > 0) {
        double iat = windowIatCount > 0 ? windowIatSum / windowIatCount : muIat;
        bool breachPps = std::fabs(pps - muPps) > sigmaFactor * effectiveSigma(sigmaPps, muPps);
        bool breachBps = std::fabs(bps - muBps) > sigmaFactor * effectiveSigma(sigmaBps, muBps);
        bool breachIat = windowIatCount > 0
                      && std::fabs(iat - muIat) > sigmaFactor * effectiveSigma(sigmaIat, muIat);
        if (breachPps || breachBps || breachIat) {
            alarms++;
            emit(d2AlarmSignal, 1L);
            if (collector)
                collector->logEvent("d2.alarm",
                    {{"pps", std::to_string(pps)}, {"bps", std::to_string(bps)},
                     {"iat", std::to_string(iat)},
                     {"which", breachIat ? "iat" : (breachPps ? "pps" : "bps")}});
        }
    }
    windowPackets = 0; windowBits = 0;
    windowIatSum = 0; windowIatCount = 0;
}

void FlowDetector::handleMessage(cMessage *msg)
{
    if (msg != windowTimer)
        throw cRuntimeError("FlowDetector: unexpected message");
    closeWindow();
    scheduleAt(simTime() + windowSize, windowTimer);
}

void FlowDetector::finish()
{
    recordScalar("d2Alarms", alarms);
    if (calibrationMode && nWindows > 1) {
        double mp = sumPps / nWindows;
        double mb = sumBps / nWindows;
        double vp = std::max(0.0, sumSqPps / nWindows - mp * mp);
        double vb = std::max(0.0, sumSqBps / nWindows - mb * mb);
        recordScalar("calibWindows", nWindows);
        recordScalar("calibMuPps", mp);
        recordScalar("calibSigmaPps", std::sqrt(vp));
        recordScalar("calibMuBps", mb);
        recordScalar("calibSigmaBps", std::sqrt(vb));
    }
    if (calibrationMode && nIatWindows > 1) {
        double mi = sumIat / nIatWindows;
        double vi = std::max(0.0, sumSqIat / nIatWindows - mi * mi);
        recordScalar("calibIatWindows", nIatWindows);
        recordScalar("calibMuIat", mi);
        recordScalar("calibSigmaIat", std::sqrt(vi));
    }
}

} // namespace lifesat
