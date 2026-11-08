"""Opt-in integration with the real operator-configured Upscayl binary and GPU."""

import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from printforge.application.service import render
from printforge.domain.planning import PrintSpec
from printforge.infrastructure.images import PillowImages
from printforge.infrastructure.upscayl import Upscayl

with tempfile.TemporaryDirectory(prefix="printforge-gpu-") as directory:
    work = Path(directory)
    source = work / "source.png"
    image = Image.new("RGB", (64, 64), "#687c51")
    draw = ImageDraw.Draw(image)
    draw.ellipse((8, 8, 56, 56), fill="#eccf89")
    draw.line((0, 0, 64, 64), fill="black", width=2)
    image.save(source)
    result = render(
        source, work, PrintSpec(2.54, 2.54, 128), "png", Upscayl.from_environment(), PillowImages()
    )
    with Image.open(result) as output:
        if output.size != (128, 128):
            raise RuntimeError(f"Unexpected output dimensions: {output.size}")
        if not output.info.get("icc_profile"):
            raise RuntimeError("Missing sRGB profile")
    print("Real Upscayl GPU smoke passed: 64×64 → 256×256 → 128×128 PNG + sRGB + 128 PPI")
