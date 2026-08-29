#!/usr/bin/env python3
"""
LIFESAT -- phase 0 gate: independent verification of the contact windows (rule R2).

OMNeT++/INET propagates the TLE with its own embedded SGP4. This script
propagates the same TLE at the same epoch with an independent implementation
(python sgp4, the official port of Vallado's reference C++ code) and compares the
contact windows from the same ground station.

If they do not overlap, the gate does not open.

Usage:
    python verify_access.py --results <directory> [--tolerance 5]
"""

import argparse
import csv
import math
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from sgp4.api import Satrec, jday, WGS72, WGS84
except ImportError:
    sys.exit("ERROR: the python package 'sgp4' is required.  Use the LIFESAT_PY interpreter.")

WGS84_A = 6378137.0
WGS84_F = 1.0 / 298.257223563
WGS84_E2 = WGS84_F * (2 - WGS84_F)


def gmst(julian_date):
    """Vallado gstime(), the same formula as in INET's Wgs84.cc."""
    tut1 = (julian_date - 2451545.0) / 36525.0
    temp = (-6.2e-6 * tut1 ** 3
            + 0.093104 * tut1 ** 2
            + (876600.0 * 3600.0 + 8640184.812866) * tut1
            + 67310.54841)
    temp = math.fmod(temp * (math.pi / 180.0 / 240.0), 2.0 * math.pi)
    return temp + 2.0 * math.pi if temp < 0 else temp


def teme_to_ecef(teme_km, gmst_rad):
    c, s = math.cos(gmst_rad), math.sin(gmst_rad)
    x, y, z = (v * 1000.0 for v in teme_km)          # km -> m
    return (c * x + s * y, -s * x + c * y, z)


def geodetic_to_ecef(lat_deg, lon_deg, alt_m):
    lat, lon = math.radians(lat_deg), math.radians(lon_deg)
    n = WGS84_A / math.sqrt(1 - WGS84_E2 * math.sin(lat) ** 2)
    return ((n + alt_m) * math.cos(lat) * math.cos(lon),
            (n + alt_m) * math.cos(lat) * math.sin(lon),
            (n * (1 - WGS84_E2) + alt_m) * math.sin(lat))


def elevation_deg(sat_ecef, gs_ecef, lat_deg, lon_deg):
    lat, lon = math.radians(lat_deg), math.radians(lon_deg)
    up = (math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat))
    los = tuple(s - g for s, g in zip(sat_ecef, gs_ecef))
    rng = math.sqrt(sum(v * v for v in los))
    if rng <= 0:
        return 90.0, 0.0
    sin_el = sum(u * l for u, l in zip(up, los)) / rng
    return math.degrees(math.asin(max(-1.0, min(1.0, sin_el)))), rng


def load_tle(path, name):
    lines = [l.rstrip("\n") for l in Path(path).read_text().splitlines() if l.strip()]
    for i, line in enumerate(lines):
        if line.strip() == name and i + 2 < len(lines) + 1:
            return lines[i + 1], lines[i + 2]
    raise SystemExit(f"ERROR: '{name}' not found in the TLE ({path})")


def independent_passes(tle1, tle2, epoch_iso, lat, lon, alt, mask_deg, duration_s, step_s,
                       gravity="wgs84"):
    # INET's SatelliteMobility calls SGP4 with wgs84 constants while python sgp4
    # defaults to wgs72. without matching constants the two diverge despite running
    # the same algorithm -- the first thing this gate caught.
    sat = Satrec.twoline2rv(tle1, tle2, WGS84 if gravity == "wgs84" else WGS72)
    t0 = datetime.fromisoformat(epoch_iso.replace("Z", "+00:00")).astimezone(timezone.utc)
    jd0, fr0 = jday(t0.year, t0.month, t0.day, t0.hour, t0.minute, t0.second)
    gs = geodetic_to_ecef(lat, lon, alt)

    passes, in_pass, start = [], False, None
    for t in range(0, duration_s + 1, step_s):
        fr = fr0 + t / 86400.0
        err, teme, _ = sat.sgp4(jd0, fr)
        if err != 0:
            raise SystemExit(f"ERROR: SGP4 returned error {err} for t={t}s")
        ecef = teme_to_ecef(teme, gmst(jd0 + fr))
        el, _ = elevation_deg(ecef, gs, lat, lon)
        visible = el >= mask_deg
        if visible and not in_pass:
            in_pass, start = True, t
        elif not visible and in_pass:
            in_pass = False
            passes.append((start, t))
    if in_pass:
        passes.append((start, duration_s))
    return passes


def omnet_passes(results_dir, scavetool):
    vec = sorted(Path(results_dir).glob("*.vec"))
    if not vec:
        raise SystemExit(f"ERROR: no .vec under {results_dir} -- run the simulation first")
    out = Path(results_dir) / "_passes.csv"
    subprocess.run([scavetool, "export", "-T", "v", "-o", str(out), "-F", "CSV-R",
                    "-f", "name =~ pass*", str(vec[-1])],
                   check=True, capture_output=True)
    # elevation:vector carries 86401 samples; the CSV field limit must be raised
    csv.field_size_limit(sys.maxsize)
    starts, ends = [], []
    with open(out) as f:
        for row in csv.DictReader(f):
            if row.get("type") != "vector":
                continue
            target = starts if row["name"] == "passStart:vector" else ends if row["name"] == "passEnd:vector" else None
            if target is None:
                continue
            target.extend(float(v) for v in row["vectime"].split() if v)
    return list(zip(sorted(starts), sorted(ends)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="simulations/results")
    ap.add_argument("--ini", default="simulations/access.ini")
    ap.add_argument("--scavetool", default="opp_scavetool")
    ap.add_argument("--tolerance", type=float, default=5.0, help="saniye")
    ap.add_argument("--step", type=int, default=1)
    ap.add_argument("--gravity", choices=["wgs72", "wgs84"], default="wgs84",
                    help="INET SatelliteMobility uses wgs84")
    args = ap.parse_args()

    ini = Path(args.ini).read_text()

    def param(pattern, cast=str):
        m = re.search(pattern, ini)
        if not m:
            raise SystemExit(f"ERROR: not found in the ini: {pattern}")
        return cast(m.group(1))

    tle_file = param(r'tleFile\s*=\s*absFilePath\("([^"]+)"\)')
    tle_path = (Path(args.ini).parent / tle_file).resolve()
    sat_name = param(r'satelliteName\s*=\s*"([^"]+)"')
    epoch = param(r'epoch\s*=\s*"([^"]+)"')
    lat = param(r'groundStationLatitude\s*=\s*([-\d.]+)deg', float)
    lon = param(r'groundStationLongitude\s*=\s*([-\d.]+)deg', float)
    alt = param(r'groundStationAltitude\s*=\s*([-\d.]+)m', float)
    mask = param(r'elevationMask\s*=\s*([-\d.]+)deg', float)
    limit_h = param(r'sim-time-limit\s*=\s*(\d+)h', int)

    print(f"TLE      : {tle_path.name}  ({sat_name})")
    print(f"epok     : {epoch}")
    print(f"yer ist. : {lat}°N {lon}°E {alt} m, maske {mask}°")
    print(f"span     : {limit_h} h, step {args.step} s")
    print(f"gravity  : {args.gravity} (same as INET SatelliteMobility.cc:46)\n")

    tle1, tle2 = load_tle(tle_path, sat_name)
    ref = independent_passes(tle1, tle2, epoch, lat, lon, alt, mask, limit_h * 3600,
                             args.step, args.gravity)
    got = omnet_passes(args.results, args.scavetool)

    print(f"independent SGP4 : {len(ref)} passes")
    print(f"OMNeT++/INET     : {len(got)} passes\n")

    ok = len(ref) == len(got)
    if not ok:
        print("[FAIL] PASS COUNT MISMATCH")
    print(f"{'#':>2} {'independent start':>18} {'omnet start':>13} {'delta':>7} "
          f"{'independent end':>17} {'omnet end':>11} {'delta':>7} {'length':>7}")
    for i, (r, g) in enumerate(zip(ref, got), 1):
        d_start, d_end = g[0] - r[0], g[1] - r[1]
        bad = abs(d_start) > args.tolerance or abs(d_end) > args.tolerance
        ok &= not bad
        print(f"{i:>2} {r[0]:>15.0f} {g[0]:>13.0f} {d_start:>+7.1f} "
              f"{r[1]:>14.0f} {g[1]:>11.0f} {d_end:>+7.1f} {g[1]-g[0]:>7.0f}"
              f"{'   [FAIL]' if bad else ''}")

    print()
    if ok:
        print(f"[OK] GATE OPEN -- every pass overlaps within +/-{args.tolerance:g} s.")
        print("   The contact schedule was verified against an independent SGP4 implementation (R2).")
        return 0
    print(f"[FAIL] GATE CLOSED -- the +/-{args.tolerance:g} s tolerance was exceeded.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
