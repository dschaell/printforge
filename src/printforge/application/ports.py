from pathlib import Path
from typing import Protocol

from printforge.domain.planning import PrintSpec


class Upscaler(Protocol):
    def upscale(self, source: Path, destination: Path) -> None: ...


class ImageProcessor(Protocol):
    def inspect(self, source: Path, max_pixels: int = 30_000_000) -> dict[str, object]: ...
    def normalize(self, source: Path, destination: Path) -> None: ...
    def export(self, source: Path, destination: Path, spec: "PrintSpec", fmt: str) -> None: ...
