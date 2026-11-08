import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from printforge.domain.planning import PrintError


@dataclass(frozen=True)
class Upscayl:
    binary: Path
    models: Path
    model: str = "high-fidelity-4x"

    @classmethod
    def from_environment(cls) -> "Upscayl":
        base = Path("/Applications/Upscayl.app/Contents/Resources")
        return cls(
            Path(os.getenv("UPSCAYL_BIN", str(base / "bin/upscayl-bin"))),
            Path(os.getenv("UPSCAYL_MODELS", str(base / "models"))),
            os.getenv("UPSCAYL_MODEL", "high-fidelity-4x"),
        )

    @property
    def available(self) -> bool:
        return (
            self.binary.is_absolute()
            and self.binary.is_file()
            and os.access(self.binary, os.X_OK)
            and all((self.models / f"{self.model}.{ext}").is_file() for ext in ("bin", "param"))
        )

    def upscale(self, source: Path, destination: Path) -> None:
        if not self.available:
            raise PrintError("Upscayl fehlt. Lokales Binary und 4×-Modell konfigurieren.")
        try:
            # Paths/model are operator configuration, never supplied by HTTP clients. No shell.
            subprocess.run(  # noqa: S603
                [
                    str(self.binary),
                    "-i",
                    str(source),
                    "-o",
                    str(destination),
                    "-m",
                    str(self.models),
                    "-n",
                    self.model,
                    "-s",
                    "4",
                    "-z",
                    "4",
                    "-t",
                    "256",
                    "-f",
                    "png",
                ],
                check=True,
                timeout=600,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            raise PrintError(
                "Upscayl fehlgeschlagen oder Zeitlimit erreicht. GPU/Modell prüfen."
            ) from exc
