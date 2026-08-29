//
// LIFESAT physical state channel: illumination and battery
//
#ifndef __LIFESAT_POWERMODEL_H
#define __LIFESAT_POWERMODEL_H

#include <cmath>

#include "inet/common/geometry/common/Coord.h"

namespace lifesat {

using inet::Coord;

/**
 * Illumination geometry and a two-state battery model.
 *
 *  Design assumption: this is not a validated power budget for a platform.
 * The sun direction comes from real astronomy (a low-precision almanac formula,
 * about 0.01 deg) and the shadow test is cylindrical.
 *
 * §7 L6: "declared behavioural models rather than validated representations of
 * a flown power, thermal or attitude subsystem".
 */
class PowerModel
{
  public:
    void configure(double nominalV, double minV, double maxV,
                   double chargeRateVps, double dischargeRateVps)
    {
        voltage = nominalV;
        minVoltage = minV;
        maxVoltage = maxV;
        chargeRate = chargeRateVps;
        dischargeRate = dischargeRateVps;
    }

    /** Unit direction vector of the sun in ECI (TEME); low-precision almanac. */
    static Coord sunDirectionEci(double julianDate)
    {
        double n = julianDate - 2451545.0;
        double L = std::fmod(280.460 + 0.9856474 * n, 360.0);            // mean longitude, deg
        double g = std::fmod(357.528 + 0.9856003 * n, 360.0) * M_PI / 180.0;  // mean anomaly
        double lambda = (L + 1.915 * std::sin(g) + 0.020 * std::sin(2 * g)) * M_PI / 180.0;
        double eps = (23.439 - 0.0000004 * n) * M_PI / 180.0;            // obliquity
        return Coord(std::cos(lambda),
                     std::cos(eps) * std::sin(lambda),
                     std::sin(eps) * std::sin(lambda));
    }

    /**
     * Cylindrical shadow test: the satellite is in eclipse if it is on the far
     * side of the Earth from the sun and inside the shadow cylinder.
     */
    static bool isIlluminated(const Coord& satEci, const Coord& sunUnitEci,
                              double earthRadiusM = 6378137.0)
    {
        double along = satEci * sunUnitEci;   // component along the sun direction
        if (along >= 0)
            return true;                      // on the sunlit side
        Coord perp = satEci - sunUnitEci * along;
        return perp.length() > earthRadiusM;  // outside the cylinder
    }

    /** Advances one step and returns the voltage. */
    double step(bool illuminated, double dtSeconds)
    {
        voltage += (illuminated ? chargeRate : -dischargeRate) * dtSeconds;
        if (voltage > maxVoltage) voltage = maxVoltage;
        if (voltage < minVoltage) voltage = minVoltage;
        return voltage;
    }

    double getVoltage() const { return voltage; }
    void setVoltage(double v) { voltage = v; }

    /** A6: a configuration update may change the discharge rate. */
    void setDischargeRate(double r) { dischargeRate = r; }
    // Amendment v5: chargeRate is the coefficient active during a sunlit
    // contact, and is therefore the one SP-2 manipulates. dischargeRate is
    // multiplied by nothing while `illuminated` is true.
    void setChargeRate(double r) { chargeRate = r; }
    double getChargeRate() const { return chargeRate; }
    double getDischargeRate() const { return dischargeRate; }
    double getMinVoltage() const { return minVoltage; }

  private:
    double voltage = 7.4;
    double minVoltage = 6.0;
    double maxVoltage = 8.4;
    double chargeRate = 0.0;
    double dischargeRate = 0.0;
};

} // namespace lifesat

#endif
