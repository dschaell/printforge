"""Pure print geometry. No framework, image library or filesystem dependencies."""

from dataclasses import asdict, dataclass
from math import ceil, isfinite
from typing import Literal

Fit = Literal["contain", "cover"]
MAX_PIXELS = 120_000_000
PRESETS = {
    "A0": (84.1, 118.9),
    "A1": (59.4, 84.1),
    "A2": (42.0, 59.4),
    "A3": (29.7, 42.0),
    "A4": (21.0, 29.7),
    "A5": (14.8, 21.0),
}


class PrintError(ValueError):
    """Expected, safe-to-display application error."""


@dataclass(frozen=True)
class PrintSpec:
    width_cm: float = 21
    height_cm: float = 29.7
    ppi: int = 300
    fit: Fit = "contain"

    def __post_init__(self) -> None:
        if not all(isfinite(x) and 1 <= x <= 200 for x in (self.width_cm, self.height_cm)):
            raise PrintError("Druckmaße müssen zwischen 1 und 200 cm liegen.")
        if not 72 <= self.ppi <= 600 or self.fit not in ("contain", "cover"):
            raise PrintError("Ungültige PPI oder Einpassung.")
        if self.width_px * self.height_px > MAX_PIXELS:
            raise PrintError("Ausgabe überschreitet das Limit von 120 Megapixeln.")

    @property
    def width_px(self) -> int:
        return ceil(self.width_cm / 2.54 * self.ppi)

    @property
    def height_px(self) -> int:
        return ceil(self.height_cm / 2.54 * self.ppi)


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

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def plan_print(width: int, height: int, spec: PrintSpec) -> Plan:
    if width <= 0 or height <= 0:
        raise PrintError("Ungültige Bildabmessungen.")
    ratios = (spec.width_px / width, spec.height_px / height)
    scale = min(ratios) if spec.fit == "contain" else max(ratios)
    crop = (1 - (spec.width_px * spec.height_px) / (width * height * scale**2)) * 100
    crop = max(0.0, crop) if spec.fit == "cover" else 0.0
    ppi = spec.ppi / scale
    warnings = []
    if scale > 1:
        warnings.append("Upscaling ergänzt geschätzte Details; echte Schärfe ist nicht garantiert.")
    if ppi < 150:
        warnings.append("Sehr wenig Originaldetails für dieses Druckmaß: Probedruck empfohlen.")
    if scale > 4:
        warnings.append(
            "Mehr als 4× nötig. MVP blockiert Export statt mehrfach KI hochzuskalieren."
        )
    if spec.fit == "cover" and crop > 0.1:
        warnings.append("Mittiger Beschnitt entfernt Bildinhalt. Vorschau prüfen.")
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
    )
