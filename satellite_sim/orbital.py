"""
Orbital mechanics wrapper around Skyfield.

Uses a real TLE to compute satellite position each tick. The TLE epoch and
RAAN are computed dynamically at startup so the ground track always passes
over the Persian Gulf AOI regardless of when the sim runs.  A TLE file at
/opt/satellite-sim/tle.txt overrides this behaviour if present.
"""

import logging
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

from skyfield.api import EarthSatellite, load, wgs84
from skyfield.earthlib import earth_rotation_angle

_DEFAULT_TLE_NAME = "DEMO-SAT"

_TLE_FILE = Path("/opt/satellite-sim/tle.txt")

# Geographic longitude of the ascending node that keeps the ground track
# crossing the Persian Gulf AOI (18–32°N, 42–75°E).  Calibrated empirically
# against a same-day epoch TLE.  The orbit crosses the AOI once per ~24 h so
# the warp search uses a 24-hour window to guarantee a hit.
_AN_LON_OFFSET = 57.0  # degrees E


def _tle_checksum(line68: str) -> int:
    """Return the TLE checksum digit for a 68-character line body."""
    return sum(int(c) if c.isdigit() else (1 if c == '-' else 0) for c in line68) % 10


def _generate_live_tle(ts) -> tuple[str, str, str]:
    """Build a TLE whose epoch is *now* and whose RAAN is derived from the
    current GMST so the satellite always crosses the AOI within one orbit."""
    now = ts.now()
    dt = now.utc_datetime()

    # Epoch string: YYDDD.DDDDDDDD
    year_2d = dt.year % 100
    doy = dt.timetuple().tm_yday
    frac_day = (dt.hour * 3600 + dt.minute * 60 + dt.second + dt.microsecond / 1e6) / 86400.0
    epoch_str = f"{year_2d:02d}{doy:03d}.{frac_day * 1e8:08.0f}"

    # GMST from ERA (earth_rotation_angle returns ERA in turns)
    gmst_deg = (earth_rotation_angle(now.ut1) * 360.0) % 360.0
    raan = (gmst_deg + _AN_LON_OFFSET) % 360.0

    line1_body = f"1 25544U 98067A   {epoch_str}  .00002182  00000+0  40768-4 0  999"
    line2_body = f"2 25544  51.6416 {raan:8.4f} 0006703 130.5360 325.0288 15.5037757942989"

    line1 = line1_body + str(_tle_checksum(line1_body))
    line2 = line2_body + str(_tle_checksum(line2_body))

    log.info("Generated live TLE: epoch=%s RAAN=%.4f (GMST=%.2f + offset=%.2f)",
             epoch_str, raan, gmst_deg, _AN_LON_OFFSET)
    return _DEFAULT_TLE_NAME, line1, line2


_AOI_LAT_MIN, _AOI_LAT_MAX = 18.0, 32.0
_AOI_LON_MIN, _AOI_LON_MAX = 42.0, 75.0
_APPROACH_BUFFER_S = 2 * 60  # sim starts this many seconds before AOI entry


def _compute_warp(ts, satellite) -> float:
    """Return seconds to offset real time so the satellite enters the AOI ~5 min after sim start.

    Searches up to 24 hours forward for the next AOI entry (the orbit only
    crosses the Persian Gulf corridor once per day on the ascending pass).
    If the satellite starts inside the AOI it waits for exit first, then finds
    the following entry.  Returns 0 if no crossing is found.
    """
    now = ts.now()
    was_in_aoi = None

    for i in range(0, 24 * 60 * 60, 10):
        t = ts.tt_jd(now.tt + i / 86400)
        sub = wgs84.subpoint(satellite.at(t))
        lat = float(sub.latitude.degrees)
        lon = float(sub.longitude.degrees)
        in_aoi = _AOI_LAT_MIN <= lat <= _AOI_LAT_MAX and _AOI_LON_MIN <= lon <= _AOI_LON_MAX

        if was_in_aoi is None:
            was_in_aoi = in_aoi

        if in_aoi and not was_in_aoi:
            warp = i - _APPROACH_BUFFER_S
            log.info("AOI entry in %.0f s — applying time warp of %.0f s", i, warp)
            return float(warp)

        was_in_aoi = in_aoi

    log.warning("No AOI crossing found in next 24 h — running with no time warp")
    return 0.0


def _load_tle(ts) -> tuple[str, str, str]:
    """Load TLE from file if present, otherwise generate a live one."""
    if _TLE_FILE.exists():
        lines = _TLE_FILE.read_text().strip().splitlines()
        if len(lines) >= 3:
            log.info("Loaded TLE from %s", _TLE_FILE)
            return lines[0].strip(), lines[1].strip(), lines[2].strip()
    return _generate_live_tle(ts)


@dataclass
class OrbitalState:
    timestamp: str
    lat: float
    lon: float
    alt_km: float
    velocity_kms: float
    subpoint_name: str


class SatelliteTracker:
    def __init__(self):
        self.ts = load.timescale()
        name, line1, line2 = _load_tle(self.ts)
        self.satellite = EarthSatellite(line1, line2, name, self.ts)
        self._warp_s = _compute_warp(self.ts, self.satellite)

    def current_state(self) -> OrbitalState:
        t = self.ts.tt_jd(self.ts.now().tt + self._warp_s / 86400)
        geocentric = self.satellite.at(t)
        subpoint = wgs84.subpoint(geocentric)

        # Velocity from position delta over 1 simulated second
        t1 = self.ts.tt_jd(t.tt + 1 / 86400)
        pos0 = geocentric.position.km
        pos1 = self.satellite.at(t1).position.km
        velocity_kms = float(sum((b - a) ** 2 for a, b in zip(pos0, pos1)) ** 0.5)

        return OrbitalState(
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            lat=round(float(subpoint.latitude.degrees), 4),
            lon=round(float(subpoint.longitude.degrees), 4),
            alt_km=round(float(subpoint.elevation.km), 2),
            velocity_kms=round(velocity_kms, 3),
            subpoint_name="",
        )
