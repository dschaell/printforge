"""Use cases depend on the Upscaler port; Pillow is isolated in the image adapter."""

from pathlib import Path

from printforge.application.ports import ImageProcessor, Upscaler
from printforge.domain.planning import MAX_PIXELS, Plan, PrintError, PrintSpec, plan_print


def analyze(
    source: Path, spec: PrintSpec, images: ImageProcessor
) -> tuple[Plan, dict[str, object]]:
    info = images.inspect(source)
    plan = plan_print(int(str(info["width"])), int(str(info["height"])), spec)
    return plan, info


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
