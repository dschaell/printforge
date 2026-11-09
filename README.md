# PrintForge

Lokaler Druckhelfer: Bild hochladen, Druckmaß wählen, echte Original-PPI beurteilen und bei Bedarf mit **lokalem Upscayl** vergrößern. PNG, JPEG oder TIFF mit exakten Zielpixeln und PPI-Metadaten herunterladen.

## Start (Python 3.12–3.14)

```sh
python3.14 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.lock
pip install --no-deps -e .
uvicorn printforge.presentation.api:app --host 127.0.0.1 --port 8787
```

Öffne http://127.0.0.1:8787. Keine Cloud-Konten, keine API-Schlüssel. Auf macOS wird eine Installation unter `/Applications/Upscayl.app` erkannt. Auf Linux/Windows die lokale CLI und ein **4×-NCNN-Modell** konfigurieren:

```sh
export UPSCAYL_BIN=/absolute/path/to/upscayl-bin
export UPSCAYL_MODELS=/absolute/path/to/models
export UPSCAYL_MODEL=high-fidelity-4x
```

Binary muss ausführbar sein. Modellname ohne `.bin`/`.param`. Auf Windows PowerShell `$env:UPSCAYL_BIN = "C:\...\upscayl-bin.exe"` verwenden. Upscayl benötigt eine kompatible Vulkan-GPU. Keine Binaries oder Modelle werden mitgeliefert; Modell-Lizenz und Herkunft selbst prüfen. Aktuelle CLI-Verwendung: [Upscayl NCNN](https://github.com/upscayl/upscayl-ncnn), lokal mit `upscayl-bin -h` getestet.

## Was die erste Version kann

- JPEG/PNG/WebP/TIFF anhand tatsächlicher Datei dekodieren, EXIF-Ausrichtung berücksichtigen.
- A6–A0, B1–B4, Poster-Standards (30×40 bis 70×100) oder freie Maße 1–200 cm, 72–600 PPI. Papier dreht sich automatisch passend zum Bild; ⇄ dreht zurück.
- „Weiße Ränder entfernen“ schneidet fast-weiße Kanten vor dem Skalieren ab (Transparenz zählt als Weiß). Danach schlägt die Analyse das größte Papiermaß mit Bildseitenverhältnis innerhalb des gewählten Formats vor, ohne Zoom und ohne neue Ränder.
- Optionaler Druckerei-Anschnitt 0–10 mm je Seite. „Fläche füllen“ läuft in den Anschnitt, „Ganzes Bild“ lässt ihn weiß.
- Ganze Bilder mit weißen Rändern oder mittigem Zuschnitt; Vorschau im Browser (TIFF browserabhängig).
- Original-PPI am gewählten Druckmaß, erforderlicher Faktor, abgeschnittener Bildanteil und eine Qualitätseinstufung (gut / ausreichend / grenzwertig / kritisch) anzeigen.
- Bei Überschreitung der Megapixel- oder 4×-Grenze die höchste mögliche PPI nennen und per Klick übernehmen.
- Detailvergleich: 100-%-Ausschnitt des Ergebnisses als Interpolation und als Upscayl-Durchlauf (nur auf dem Ausschnitt, daher schnell). Kein Ersatz für einen Probedruck.
- Bei Vergrößerung genau ein 4×-Upscayl-Durchlauf, anschließend Lanczos auf exakte Zielpixel. Ohne Vergrößerung kein KI-Aufruf.
- ICC-Eingaben nach sRGB konvertieren; Transparenz auf Weiß; frische Ausgabe ohne EXIF/GPS, eingebettetes sRGB. CMYK ohne gültiges Profil ablehnen.
- PNG und TIFF verlustfrei, JPEG mit Qualität 95 und ohne Farbunterabtastung.

**Qualitätsgrenze:** 300 PPI beschreiben die Pixeldichte, nicht die Menge echter Fotodetails. KI-Upscaling schätzt Details und kann Artefakte erzeugen. Keine Auflösungsgarantie für unscharfe Vorlagen. Prüfe einen 100-%-Ausschnitt und einen Probedruck. Im Druckdialog „tatsächliche Größe“ einstellen; Druckdienstleister können PPI-Metadaten ignorieren. Kein CMYK-Softproof, PDF/X oder druckerspezifisches ICC-Proofing.

## Betrieb und Grenzen

Single-User-MVP auf Loopback, **nicht öffentlich exponieren**. Ein Vorgang gleichzeitig, sonst HTTP 429; kein persistenter Jobserver. 40 MiB Upload, 30 MP Eingang, 400 MP Ziel und 4×-Zwischenbild (einstellbar, s. u.), 600 Sekunden Upscayl-Timeout. Das Limit ist auf lokalen Rechnern anhebbar: `export PRINTFORGE_MAX_MEGAPIXELS=600` vor dem Start (1–2000, Standard 400). Rechne mit grob 10 Byte RAM pro Ausgabepixel (400 MP ≈ 4 GB Spitze); ein 4×-Zwischenbild belegt zusätzlich Speicher. Bei Überschreitung nennt die App die höchste mögliche PPI. Kein stiller Wechsel auf reine Interpolation bei fehlendem Upscayl. Konfigurierte Modelle müssen tatsächlich 4× liefern; Abmessungen werden geprüft.

Temporärdateien werden nach Analyse/Fehler bzw. abgeschlossener Downloadantwort entfernt. Ein Prozessabbruch kann OS-Tempdateien hinterlassen; keine Garantie sicherer physischer Löschung. Bilder werden weder ins Repository geschrieben noch an externe Dienste geschickt. Der Browser lädt die Datei bei Analyse und Export jeweils an den lokalen Server. GPU-/RAM-Last kann erheblich sein; Pixelgrenzen ersetzen kein Betriebssystem-Ressourcenlimit.

## Entwicklung

```sh
ruff check .
ruff format --check .
mypy
pytest -q
pip-audit -r requirements.lock
# Browser-End-to-End nach einmaligem `playwright install chromium`:
python scripts/browser_smoke.py
# Optional: echter lokaler GPU-Lauf mit synthetischem Bild
python scripts/gpu_smoke.py
```

[Architektur und Vorgehen](docs/architecture.md) · [Security](SECURITY.md) · [Roadmap](docs/roadmap.md) · [Mitwirken](CONTRIBUTING.md)

GitHub Actions: Tests, Ruff, Mypy, Dependency-Audit, Semgrep-SAST und ZAP-Baseline-DAST. Scannerbefunde führen nicht automatisch zu einer sicheren Anwendung; Ergebnisse prüfen. Echte GPU-Integration separat und optional testen, da GitHub-Standardrunner keine passende Vulkan-GPU garantieren.

Lizenz: AGPL-3.0-or-later. Upscayl/Modelle bleiben eigenständige externe Komponenten mit ihren jeweiligen Lizenzen.
