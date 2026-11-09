"""Use cases depend on the Upscaler port; Pillow is isolated in the image adapter."""

from pathlib import Path

from printforge.application.ports import ImageProcessor, Upscaler
from printforge.domain.planning import (
    MAX_PIXELS,
    Plan,
    PrintError,
    PrintSpec,
    plan_print,
    sample_window,
)


def analyze(
    source: Path, spec: PrintSpec, images: ImageProcessor
) -> tuple[Plan, dict[str, object]]:
    info = images.inspect(source)
    plan = plan_print(int(str(info["width"])), int(str(info["height"])), spec)
    return plan, info


def _enlarge(source: Path, destination: Path, upscaler: Upscaler, images: ImageProcessor) -> None:
    before = images.inspect(source)
    upscaler.upscale(source, destination)
    actual = images.inspect(destination, max_pixels=MAX_PIXELS)
    expected = (int(str(before["width"])) * 4, int(str(before["height"])) * 4)
    if (actual["width"], actual["height"]) != expected:
        raise PrintError("Upscayl lieferte unerwartete Abmessungen. Export abgebrochen.")


def sample(
    source: Path,
    work: Path,
    spec: PrintSpec,
    method: str,
    upscaler: Upscaler,
    images: ImageProcessor,
) -> Path:
    """100 % detail crop of the print result: plain Lanczos or one Upscayl pass on the crop."""
    if method not in ("plain", "ai"):
        raise PrintError("Unbekannte Vergleichsmethode.")
    plan, _ = analyze(source, spec, images)
    if method == "ai" and plan.required_scale > 4:
        raise PrintError("Mehr als 4× Vergrößerung nötig. Druckmaß oder PPI reduzieren.")
    normalized = work / "normalized.png"
    images.normalize(source, normalized)
    box, size = sample_window(plan.source_width, plan.source_height, spec, plan.required_scale)
    cropped = work / "crop.png"
    images.crop(normalized, cropped, box)
    base = cropped
    if method == "ai" and plan.ai_passes:
        base = work / "crop-enlarged.png"
        _enlarge(cropped, base, upscaler, images)
    result = work / "sample.png"
    images.resize(base, result, size)
    return result


def render(
    source: Path,
    work: Path,
    spec: PrintSpec,
    output_format: str,
    upscaler: Upscaler,
    images: ImageProcessor,
) -> Path:
    if output_format not in ("png", "jpeg", "tiff"):
        raise PrintError("Unbekanntes Ausgabeformat.")
    plan, _ = analyze(source, spec, images)
    normalized = work / "normalized.png"
    images.normalize(source, normalized)
    if plan.required_scale > 4:
        raise PrintError("Mehr als 4× Vergrößerung nötig. Druckmaß oder PPI reduzieren.")
    if plan.ai_passes:
        if plan.source_width * plan.source_height * 16 > MAX_PIXELS:
            raise PrintError(
                "4×-Zwischenbild überschreitet 120 Megapixel. Kleineren Ausschnitt verwenden."
            )
        enlarged = work / "enlarged.png"
        upscaler.upscale(normalized, enlarged)
        actual = images.inspect(enlarged, max_pixels=MAX_PIXELS)
        if (actual["width"], actual["height"]) != (plan.source_width * 4, plan.source_height * 4):
            raise PrintError("Upscayl lieferte unerwartete Abmessungen. Export abgebrochen.")
        normalized = enlarged
    result = work / f"printforge.{output_format}"
    images.export(normalized, result, spec, output_format)
    return result
