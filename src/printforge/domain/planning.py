"""Pure print geometry. No framework, image library or filesystem dependencies."""

import os
from dataclasses import asdict, dataclass
from math import ceil, isfinite
from typing import Literal

Fit = Literal["contain", "cover"]
Quality = Literal["gut", "ausreichend", "grenzwertig", "kritisch"]
DEFAULT_MAX_MEGAPIXELS = 800
ENV_MAX_MEGAPIXELS = "PRINTFORGE_MAX_MEGAPIXELS"
DEFAULT_MAX_INPUT_MEGAPIXELS = 100
ENV_MAX_INPUT_MEGAPIXELS = "PRINTFORGE_MAX_INPUT_MEGAPIXELS"
DEFAULT_MAX_UPLOAD_MIB = 100
ENV_MAX_UPLOAD_MIB = "PRINTFORGE_MAX_UPLOAD_MIB"


def _configured(name: str, default: float, high: float, raw: str | None) -> float:
    """Operator setting from the environment; invalid or implausible values use the default."""
    text = os.environ.get(name) if raw is None else raw
    try:
        value = float(text) if text else default
    except ValueError:
        value = default
    return value if isfinite(value) and 1 <= value <= high else default


def configured_max_pixels(raw: str | None = None) -> int:
    """Output pixel budget in pixels."""
    value = _configured(ENV_MAX_MEGAPIXELS, DEFAULT_MAX_MEGAPIXELS, 2000, raw)
    return int(value * 1_000_000)


def configured_max_input_pixels(raw: str | None = None) -> int:
    value = _configured(ENV_MAX_INPUT_MEGAPIXELS, DEFAULT_MAX_INPUT_MEGAPIXELS, 1000, raw)
    return int(value * 1_000_000)


def configured_max_upload_bytes(raw: str | None = None) -> int:
    value = _configured(ENV_MAX_UPLOAD_MIB, DEFAULT_MAX_UPLOAD_MIB, 1000, raw)
    return int(value * 1024 * 1024)


MAX_PIXELS = configured_max_pixels()
MAX_INPUT_PIXELS = configured_max_input_pixels()
MAX_UPLOAD_BYTES = configured_max_upload_bytes()
MIN_PPI = 72
MAX_PPI = 600
MAX_BLEED_MM = 10.0
# Single source of truth for the UI (served via /api/health), ordered small to large.
PRESETS = {
    "A6": (10.5, 14.8),
    "A5": (14.8, 21.0),
    "A4": (21.0, 29.7),
    "A3": (29.7, 42.0),
    "A2": (42.0, 59.4),
    "A1": (59.4, 84.1),
    "A0": (84.1, 118.9),
    "B4": (25.0, 35.3),
    "B3": (35.3, 50.0),
    "B2": (50.0, 70.7),
    "B1": (70.7, 100.0),
    "30×40": (30.0, 40.0),
    "40×50": (40.0, 50.0),
    "50×70": (50.0, 70.0),
    "60×90": (60.0, 90.0),
    "70×100": (70.0, 100.0),
}


class PrintError(ValueError):
    """Expected, safe-to-display application error."""

    def __init__(self, message: str, suggested_ppi: int | None = None) -> None:
        super().__init__(message)
        self.suggested_ppi = suggested_ppi


def _pixels(size_cm: float, ppi: int) -> int:
    return ceil(size_cm / 2.54 * ppi)


def max_ppi(width_cm: float, height_cm: float, bleed_mm: float = 0) -> int:
    """Highest PPI whose full output (incl. bleed) stays within MAX_PIXELS."""
    full_w = width_cm + 2 * bleed_mm / 10
    full_h = height_cm + 2 * bleed_mm / 10
    low, high = MIN_PPI, MAX_PPI
    while low < high:
        mid = (low + high + 1) // 2
        if _pixels(full_w, mid) * _pixels(full_h, mid) <= MAX_PIXELS:
            low = mid
        else:
            high = mid - 1
    return low


@dataclass(frozen=True)
class PrintSpec:
    width_cm: float = 21
    height_cm: float = 29.7
    ppi: int = 300
    fit: Fit = "contain"
    bleed_mm: float = 0

    def __post_init__(self) -> None:
        if not all(isfinite(x) and 1 <= x <= 200 for x in (self.width_cm, self.height_cm)):
            raise PrintError("Druckmaße müssen zwischen 1 und 200 cm liegen.")
        if not MIN_PPI <= self.ppi <= MAX_PPI or self.fit not in ("contain", "cover"):
            raise PrintError("Ungültige PPI oder Einpassung.")
        if not (isfinite(self.bleed_mm) and 0 <= self.bleed_mm <= MAX_BLEED_MM):
            raise PrintError(f"Anschnitt muss zwischen 0 und {MAX_BLEED_MM:g} mm liegen.")
        if self.width_px * self.height_px > MAX_PIXELS:
            possible = max_ppi(self.width_cm, self.height_cm, self.bleed_mm)
            raise PrintError(
                f"Ausgabe überschreitet das Limit von {MAX_PIXELS // 1_000_000} Megapixeln. "
                f"Bei diesem Maß sind höchstens {possible} PPI möglich.",
                suggested_ppi=possible,
            )

    @property
    def full_width_cm(self) -> float:
        return self.width_cm + 2 * self.bleed_mm / 10

    @property
    def full_height_cm(self) -> float:
        return self.height_cm + 2 * self.bleed_mm / 10

    @property
    def width_px(self) -> int:
        """Output width including bleed."""
        return _pixels(self.full_width_cm, self.ppi)

    @property
    def height_px(self) -> int:
        return _pixels(self.full_height_cm, self.ppi)

    @property
    def trim_width_px(self) -> int:
        return _pixels(self.width_cm, self.ppi)

    @property
    def trim_height_px(self) -> int:
        return _pixels(self.height_cm, self.ppi)


@dataclass(frozen=True)
class Plan:
    source_width: int
    source_height: int
    target_width: int
    target_height: int
    source_ppi: float
    required_scale: float
    ai_passes: int
    crop_percent: float
    warnings: list[str]
    quality: Quality = "kritisch"
    quality_text: str = ""
    suggested_ppi: int | None = None
    fitted_paper_cm: tuple[float, float] | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


QUALITY_TEXT: dict[Quality, str] = {
    "gut": "Ausreichend Originaldetails für dieses Druckmaß.",
    "ausreichend": "Für normale Betrachtungsabstände ausreichend; Details ggf. weich.",
    "grenzwertig": "Nur aus größerem Abstand überzeugend. Probedruck empfohlen.",
    "kritisch": "Sehr wenig Originaldetails. Nur mit Probedruck und kleinerem Maß sinnvoll.",
}


def rate_quality(source_ppi: float) -> Quality:
    if source_ppi >= 200:
        return "gut"
    if source_ppi >= 150:
        return "ausreichend"
    if source_ppi >= 100:
        return "grenzwertig"
    return "kritisch"


def fit_paper(aspect: float, width_cm: float, height_cm: float) -> tuple[float, float] | None:
    """Largest paper with the image aspect that fits inside the chosen size; None if equal."""
    if abs(aspect / (width_cm / height_cm) - 1) <= 0.01:
        return None
    if aspect >= width_cm / height_cm:
        return width_cm, round(width_cm / aspect, 1)
    return round(height_cm * aspect, 1), height_cm


def plan_print(width: int, height: int, spec: PrintSpec) -> Plan:
    if width <= 0 or height <= 0:
        raise PrintError("Ungültige Bildabmessungen.")
    if spec.fit == "contain":
        # The whole image sits inside the trim box; bleed stays white.
        scale = min(spec.trim_width_px / width, spec.trim_height_px / height)
    else:
        # The image fills the full sheet including bleed.
        scale = max(spec.width_px / width, spec.height_px / height)
    crop = (1 - (spec.width_px * spec.height_px) / (width * height * scale**2)) * 100
    crop = max(0.0, crop) if spec.fit == "cover" else 0.0
    ppi = spec.ppi / scale
    quality = rate_quality(ppi)
    suggested = None
    warnings = []
    if scale > 1:
        warnings.append("Upscaling ergänzt geschätzte Details; echte Schärfe ist nicht garantiert.")
    if ppi < 150:
        warnings.append("Sehr wenig Originaldetails für dieses Druckmaß: Probedruck empfohlen.")
    if 1 < scale <= 4 and width * height * 16 > MAX_PIXELS:
        # The 4x intermediate image would exceed the budget although the final size is fine.
        possible = int(spec.ppi / scale)
        warning = (
            f"Das 4×-Zwischenbild ({round(width * height * 16 / 1_000_000)} MP) überschreitet "
            f"das Limit von {MAX_PIXELS // 1_000_000} MP."
        )
        if possible >= MIN_PPI:
            suggested = possible
            warning += f" Bis {possible} PPI braucht dieses Bild keine KI-Vergrößerung."
        warnings.append(warning)
    if scale > 4:
        possible = int(spec.ppi * 4 / scale)
        warning = "Mehr als 4× nötig. Export wird blockiert statt mehrfach KI hochzuskalieren."
        if possible >= MIN_PPI:
            suggested = possible
            warning += f" Bei diesem Bild und Maß sind höchstens {possible} PPI möglich."
        else:
            warning += (
                " Bei diesem Maß reicht das Bild auch bei 72 PPI nicht; kleineres Maß wählen."
            )
        warnings.append(warning)
    if spec.fit == "cover" and crop > 0.1:
        warnings.append("Mittig abgeschnittener Bildanteil entfernt Inhalt. Vorschau prüfen.")
    if spec.fit == "contain":
        warnings.append("Das vollständige Bild wird mit weißen Rändern eingepasst.")
    return Plan(
        width,
        height,
        spec.width_px,
        spec.height_px,
        round(ppi, 1),
        scale,
        int(scale > 1),
        round(crop, 1),
        warnings,
        quality,
        QUALITY_TEXT[quality],
        suggested,
        fit_paper(width / height, spec.width_cm, spec.height_cm),
    )


SAMPLE_WIDTH_PX = 900
SAMPLE_HEIGHT_PX = 600


def sample_window(
    width: int, height: int, spec: PrintSpec, scale: float
) -> tuple[tuple[int, int, int, int], tuple[int, int]]:
    """Centered source box whose result is a ~100 % detail crop of the printed output.

    Returns the box (left, top, right, bottom) in source pixels and the output size in
    target pixels. The box never leaves the part of the image that is actually printed.
    """
    visible_w = max(1, min(width, int(spec.width_px / scale)))
    visible_h = max(1, min(height, int(spec.height_px / scale)))
    box_w = max(1, min(visible_w, ceil(SAMPLE_WIDTH_PX / scale)))
    box_h = max(1, min(visible_h, ceil(SAMPLE_HEIGHT_PX / scale)))
    left = (width - box_w) // 2
    top = (height - box_h) // 2
    size = (max(1, round(box_w * scale)), max(1, round(box_h * scale)))
    return (left, top, left + box_w, top + box_h), size
