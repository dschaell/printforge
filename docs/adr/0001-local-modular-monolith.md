# ADR 0001 — Lokaler modularer Monolith

Status: akzeptiert, 2026-11-08.

Ein Browser kann lokal installierte GPU-Binaries nicht direkt ausführen. Wir betreiben deshalb einen Loopback-Server mit expliziten Ports für Bildverarbeitung und Upscaling. Fachlogik bleibt frei von FastAPI/Pillow. Kein Datenbank-Tier ohne Persistenzanforderung. Vorteil: überschaubarer Betrieb und austauschbarer Upscaler; Nachteil: lange HTTP-Requests und keine dauerhaften Jobs. Öffentlicher Mehrbenutzerbetrieb erfordert separate Architekturarbeit.
