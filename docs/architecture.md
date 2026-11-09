# Vorgehen und Architektur

## 1. Anforderungen und überprüfbare Kriterien

Vor Implementierung: Druckgeometrie, Schutzgrenzen, unterstützte Formate und Qualitätsversprechen festlegen. Erfolg bedeutet: bekannter A1-Input ergibt 7016 × 9934 px bei 300 PPI; Cover beschneidet mittig ohne Verzerrung; Contain erhält das Motiv; ungültige oder zu große Dateien scheitern vor GPU-Verarbeitung; Export enthält sRGB und korrekte PPI ohne GPS; ohne Vergrößerung kein Upscayl; GPU-Fehler werden sichtbar.

## 2. Modularer Monolith mit vier Schichten

Browser → Presentation/FastAPI → Application/Use Cases → Domain/Druckgeometrie.
Infrastructure implementiert die Ports `ImageProcessor` und `Upscaler`; nur der Composition Root in Presentation verdrahtet konkrete Adapter. Domain und Application importieren keine Infrastruktur/Frameworks. Tests erzwingen diese Abhängigkeitsrichtung.

- **Presentation:** lokale statische Oberfläche, HTTP-Validierung, Uploadstream, Fehlervertrag, temporärer Request-Lebenszyklus und Single-User-Zugangsschutz.
- **Application:** Analyse-/Export-Use-Cases; Koordination der Ports, Entscheidung über KI-Verarbeitung und Größenlimits.
- **Domain:** Zentimeter → Zielpixel, PPI, Skalierungsfaktor, Anschnitt, Zuschnitt, Qualitätsstufe und Warnungen. Keine I/O.
- **Infrastructure:** Pillow für Dekodierung/Farbmanagement/Export; Upscayl als CLI-Prozess ohne Shell.

N-Tier bezeichnet hier logische Schichten; Browser und Server sind die zwei physischen Tiers. Microservices, DB und Redis sind im lokalen MVP nicht notwendig. Die Request-Verarbeitung läuft synchron in einem Threadpool; das API nimmt keine zweite Verarbeitung an. Zukunft: persistente Jobzustände und separat begrenzter GPU-Worker hinter einem Queue-Port, ohne Druckgeometrie zu verändern.

## 3. Druckmodell

`target_px = ceil(cm / 2.54 × ppi)`. Rundung nach oben unterschreitet die Zielauflösung nicht. Contain verwendet den kleineren, Cover den größeren Achsenfaktor. `source_ppi = target_ppi / scale` berücksichtigt den Bildbereich nach gewählter Einpassung. Metadaten-PPI der Vorlage bestimmen nicht die tatsächlich verfügbaren Details.

Ein 4×-KI-Pass nur bei `scale > 1`; anschließend exakte Geometrie durch Lanczos. Mehr als 4× wird blockiert. Maximal `PRINTFORGE_MAX_MEGAPIXELS` (Standard 800) auch für das Zwischenbild, damit eine scheinbar kleine Zielvergrößerung nicht unbemerkt ein riesiges 4×-Bild produziert. Kein automatisches Nachgenerieren. sRGB-Ausgabe statt unkontrollierter CMYK-Konvertierung. Keine Druckqualität aus PPI allein ableiten.

## 4. Qualität als Pipeline

Kleine PR pro Issue, Akzeptanzkriterien vor Code, Architekturentscheidungen als ADR. Ruff, striktes Mypy, fachliche Unit-Tests, echte Pillow-/API-Integration, Browser-Smoke. SAST mit Semgrep und eigenen Regeln, SCA mit pip-audit, DAST mit ZAP gegen Wegwerfinstanz. Keine Produktivdaten im Scan. Kein `continue-on-error` für Gates. Dependency-Lock regelmäßig erneuern und nach Änderung komplett prüfen.

## 5. Betriebsweg

Erst lokal und Single-User. Öffentliche GitHub-Quellen bedeuten keinen öffentlichen Bildservice. Vor Hosting: Auth, Quoten, zuverlässige Jobs, Upload-Timeout/Proxy-Limits, Worker-Isolation mit CPU/RAM/GPU-Grenzen, Speicherung mit TTL, Telemetrie ohne Bildinhalte, Löschung, Backup-/Recovery-Modell und gehärteter DAST. Siehe Roadmap.
