"""
Synthetic sensor frame generator and threat detector.

Simulates what a multi-spectral imager might return as the satellite passes
over terrain. When the satellite is over the target area, a threat signature
(a bright, spatially-coherent emitter cluster) is injected into the frame.

Detection uses a matched filter — correlates the frame against a reference
emitter template and reports confidence as the normalized peak response.
"""

import io
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageDraw, ImageFont

# Frame dimensions (pixels) — keeps memory and CPU trivial
FRAME_H, FRAME_W = 128, 128

# Detection fires when CFAR confidence exceeds this (0–1 scale, ~SNR 7.2)
DETECTION_THRESHOLD = 0.72

# AOI: Persian Gulf / Arabian Peninsula corridor — 18–32°N, 42–75°E.
# Geopolitically relevant for USSF scenarios; well within the 51.6° inclination
# ground track. Narrow enough that the satellite spends most of its time in
# transit, creating clear scanning/idle state transitions during the demo.
TARGET_LAT_MIN, TARGET_LAT_MAX = 18.0, 32.0
TARGET_LON_MIN, TARGET_LON_MAX = 42.0, 75.0

# ── Thermal colormap (iron) ───────────────────────────────────────────────────
# Maps 0→1 intensity to black→blue→red→orange→yellow→white.
# Standard for space-based IR/FLIR imagery; bright emitters read immediately.

def _build_thermal_lut() -> np.ndarray:
    lut = np.zeros((256, 3), dtype=np.uint8)
    for i in range(256):
        t = i / 255.0
        if t < 0.25:
            s = t / 0.25
            lut[i] = [0, 0, int(s * 180)]
        elif t < 0.50:
            s = (t - 0.25) / 0.25
            lut[i] = [int(s * 210), 0, int(180 * (1 - s))]
        elif t < 0.75:
            s = (t - 0.50) / 0.25
            lut[i] = [210 + int(s * 45), int(s * 160), 0]
        else:
            s = (t - 0.75) / 0.25
            lut[i] = [255, 160 + int(s * 95), int(s * 255)]
    return lut

_THERMAL_LUT = _build_thermal_lut()


def frame_to_png(
    frame: NDArray,
    frame_id: int = 0,
    lat: float = 0.0,
    lon: float = 0.0,
    timestamp: str = "",
) -> bytes:
    """Render a float32 IR frame as a thermal PNG with targeting reticle.

    Output: 256×274px PNG (256×256 image + 18px metadata strip).
    Reticle drawn at the peak-intensity pixel — the detected emitter location.
    """
    SCALE = 2
    H, W = frame.shape

    # Locate the emitter (brightest pixel)
    peak_y, peak_x = divmod(int(np.argmax(frame)), W)

    # Apply iron colormap
    idx = (frame * 255).clip(0, 255).astype(np.uint8)
    rgb = _THERMAL_LUT[idx]                     # H×W×3
    img = Image.fromarray(rgb, "RGB")
    img = img.resize((W * SCALE, H * SCALE), Image.NEAREST)

    draw = ImageDraw.Draw(img)

    # Corner-bracket reticle in targeting green (#00FF41)
    rx, ry = peak_x * SCALE, peak_y * SCALE
    arm, gap = 14, 7
    green = (0, 255, 65)
    for dx, dy in [(-1, -1), (1, -1), (-1, 1), (1, 1)]:
        bx, by = rx + dx * gap, ry + dy * gap
        draw.line([(bx, by), (bx + dx * arm, by)], fill=green, width=1)
        draw.line([(bx, by), (bx, by + dy * arm)], fill=green, width=1)
    draw.ellipse([rx - 2, ry - 2, rx + 2, ry + 2], fill=green)

    # Metadata strip
    META_H = 18
    canvas = Image.new("RGB", (W * SCALE, H * SCALE + META_H), (0, 0, 0))
    canvas.paste(img, (0, 0))
    dmeta = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.load_default(size=11)
    except TypeError:
        font = ImageFont.load_default()
    ts = timestamp[11:19] if len(timestamp) >= 19 else timestamp
    lat_s = f"{abs(lat):.3f}°{'N' if lat >= 0 else 'S'}"
    lon_s = f"{abs(lon):.3f}°{'E' if lon >= 0 else 'W'}"
    dmeta.text((4, H * SCALE + 3), f"IR FR#{frame_id:04d}  {ts}Z  {lat_s} {lon_s}",
               fill=(160, 160, 160), font=font)

    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    return buf.getvalue()


# Emitter signature: tight cluster of 3–5 bright pixels (hot emitter profile)
_TEMPLATE_SIZE = 9
_EMITTER_TEMPLATE: NDArray = np.zeros((_TEMPLATE_SIZE, _TEMPLATE_SIZE), dtype=np.float32)
_cx, _cy = _TEMPLATE_SIZE // 2, _TEMPLATE_SIZE // 2
for _r in range(_TEMPLATE_SIZE):
    for _c in range(_TEMPLATE_SIZE):
        dist = (((_r - _cx) ** 2 + (_c - _cy) ** 2) ** 0.5)
        _EMITTER_TEMPLATE[_r, _c] = np.exp(-0.8 * dist)


@dataclass
class DetectionResult:
    alert_id: str
    timestamp: str
    confidence: float
    lat: float
    lon: float
    alt_km: float
    frame_id: int
    classification: str = "UNKNOWN_EMITTER"
    routed: bool = False


def _over_target(lat: float, lon: float) -> bool:
    return (
        TARGET_LAT_MIN <= lat <= TARGET_LAT_MAX
        and TARGET_LON_MIN <= lon <= TARGET_LON_MAX
    )


def generate_frame(lat: float, lon: float, rng: np.random.Generator, force_emitter: bool = False) -> NDArray:
    """Return a synthetic 128×128 grayscale sensor frame (float32, 0–1).

    Models a thermal/IR sensor band. Terrain varies slowly in temperature
    (smooth background). Active emitters (radar, engine plumes) appear as
    sharp, high-intensity point sources — the physical basis for detection.
    """
    from PIL import Image

    # Very smooth background — only coarse octaves, no fine texture.
    # Simulates slow terrain temperature variation in the thermal IR band.
    frame = np.zeros((FRAME_H, FRAME_W), dtype=np.float32)
    for scale, weight in [(16, 0.6), (8, 0.3), (4, 0.1)]:
        small = rng.random((max(FRAME_H // scale, 2), max(FRAME_W // scale, 2))).astype(np.float32)
        resized = np.array(
            Image.fromarray(small).resize((FRAME_W, FRAME_H), Image.BILINEAR)
        )
        frame += resized * weight

    # Rescale terrain to 0.1–0.5 (cool, slowly varying background)
    frame = (frame - frame.min()) / (frame.max() - frame.min() + 1e-6)
    frame = frame * 0.4 + 0.1

    # Sensor speckle noise
    frame += rng.normal(0, 0.008, frame.shape).astype(np.float32)
    frame = np.clip(frame, 0, 1)

    # Inject a point-source emitter when over the target area.
    # Emitter peaks well above terrain (0.88–0.96) in a tight 5×5 pixel core —
    # this is how a high-power radar or rocket plume appears in thermal IR from LEO.
    if _over_target(lat, lon) or force_emitter:
        cx = rng.integers(15, FRAME_W - 15)
        cy = rng.integers(15, FRAME_H - 15)
        intensity = rng.uniform(0.88, 0.96)
        for dr in range(-2, 3):
            for dc in range(-2, 3):
                dist = (dr ** 2 + dc ** 2) ** 0.5
                frame[cy + dr, cx + dc] = max(
                    frame[cy + dr, cx + dc],
                    intensity * np.exp(-0.5 * dist),
                )
        frame = np.clip(frame, 0, 1)

    return frame


def detect(frame: NDArray, lat: float, lon: float, alt_km: float, frame_id: int) -> DetectionResult | None:
    """
    Point-source anomaly detector.

    Compares the peak pixel value to the 90th-percentile background level.
    This contrast ratio is naturally high for bright emitters against smooth
    terrain and low for clutter-only scenes — no tuning needed as background
    brightness varies with terrain type or illumination.
    """
    peak = float(frame.max())
    background_p90 = float(np.percentile(frame, 90))
    noise_floor = float(frame.std()) + 1e-6

    # Contrast: how far the peak sits above the 90th-percentile background
    contrast_snr = (peak - background_p90) / noise_floor

    # Map to 0–1 confidence (SNR 5 → 0.5, SNR 10 → 1.0)
    confidence = min(contrast_snr / 10.0, 1.0)

    if confidence < DETECTION_THRESHOLD:
        return None

    return DetectionResult(
        alert_id=str(uuid.uuid4())[:8],
        timestamp=datetime.now(timezone.utc).isoformat(),
        confidence=round(confidence, 3),
        lat=lat,
        lon=lon,
        alt_km=alt_km,
        frame_id=frame_id,
    )
