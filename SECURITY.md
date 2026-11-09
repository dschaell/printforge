# Security

MVP nur mit `--host 127.0.0.1` betreiben. Kein Auth-System; keine Freigabe für Internet/LAN. Host-Allowlist gegen DNS-Rebinding, Prüfung fremder POST-Origins, keine CORS-Freigabe, strikte CSP ohne externe Assets. Zugriff anderer lokaler Prozesse bleibt möglich.

Uploads werden gestreamt (Standard 100 MiB, einstellbar), anhand dekodierter Inhalte geprüft (keine SVG/PDF/Animationen), unter zufälligen privaten OS-Tempverzeichnissen gespeichert und nach Request bereinigt. Keine nutzergesteuerten Pfade, Modellnamen oder Shellbefehle. Upscayl hat einen festen Timeout und feste 4×-/Tile-Parameter. Kein Logging von Bildinhalten, Originalnamen oder EXIF. ICC-Konvertierung scheitert geschlossen bei ungültigen Profilen.

Restrisiken: native Bilddecoder/GPU-Binary, Ressourcenverbrauch bis zu mehreren GB, langsame Uploads und lokale Prozesse. Keine harte Container-Sandbox, persistente Queue oder Crash-sichere Löschung. Vor Mehrbenutzerbetrieb separate Worker, OS-Limits und Auth umsetzen. `UPSCAYL_*` ist vertrauenswürdige Betreiberkonfiguration.

## Prüfungen

- Semgrep: `p/python`, `p/security-audit` und eigene `.semgrep.yml` (Shell-Verbot). SAST ist kein Vollständigkeitsbeweis.
- `pip-audit` gegen Runtime-Lock; GitHub Dependabot wöchentlich.
- ZAP passive Baseline gegen ausschließlich lokalen Wegwerfserver in CI. Kein aktiver Pentest, keine authentifizierte Coverage. HTML-Report als Artefakt; Warnungen benötigen explizite Bearbeitung. `security/zap-baseline.conf` führt ausschließlich den Cache-Inventarhinweis 10049 als INFO weiter: Diese von ZAP als Informational bewertete Regel meldet sowohl no-store als auch cachebare Inhalte. Der Befund bleibt im Report sichtbar; API-/Download-no-store wird unabhängig getestet. Alle anderen und neue Regeln bleiben blockierend. Siehe [ZAP 10049](https://www.zaproxy.org/docs/alerts/10049/) und [Baseline-Konfiguration](https://www.zaproxy.org/docs/docker/baseline-scan/).
- API-Tests für Fremd-Origin, DNS-Rebinding, falschen Inhalt, Größenlimits, Timeout-Fehler und sensible Metadaten.

Schwachstellen bitte nicht mit privaten Fotos/Secrets in öffentliche Issues einstellen. Nutze GitHub Private Vulnerability Reporting, sofern vom Repository-Betreiber aktiviert, sonst vor Veröffentlichung einen privaten Kontaktweg vereinbaren.
