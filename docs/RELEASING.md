# Beta veröffentlichen

**Vorbereitet:** Anzeigename v1.0.0 Beta 1, Manifest-Version `1.0.0b1`, Git-Tag
`v1.0.0b1`. Diese Schreibweise ist für Home Assistant und Python eindeutig.

1. Änderungen auf `main` übernehmen und den grünen **CI**-Lauf prüfen.
2. Die Lizenz-/Rechtefrage klären. Das private Repository erst danach öffentlich stellen.
3. Unter **Settings → Secrets and variables → Actions** `ORCHESTRATION_PAT` setzen:
   ein Token mit Leserechten für das private Repository `seb5594/hass-workflows`.
   Alternativ für Tests genügt der lokale CI-Pfad ohne dieses Secret.
4. **Actions → Release → Run workflow** auf `main` starten. `draft: true` belassen.
   Der Workflow prüft erneut und erstellt einen Release-Entwurf mit ZIPs und Prüfsummen.
5. Unter **Releases** den Entwurf öffnen, kurze Änderungen ergänzen und die Dateien
   prüfen. **Pre-release** für Beta-Versionen aktiviert lassen, dann veröffentlichen.

Die ZIP-Veröffentlichung verwendet `GITHUB_TOKEN`; dafür reicht die im Release-Job
gesetzte Berechtigung `contents: write`. Der Engine-Pin verwendet den geprüften Commit
`c5bbbd6` aus `hass-workflows`. Der lokale Adapter `.github/engine-beta.patch`
ergänzt Beta-Versionen, pytest und Release-Entwürfe. Ein neuer Engine-Pin braucht
eine erneute Prüfung dieses Patches; das zentrale Repository bleibt unverändert.

| Datei | Zweck |
| --- | --- |
| `ninebot_e_scooters.zip` | HACS, Integration direkt im ZIP-Wurzelordner |
| `ninebot_e_scooters-1.0.0b1-manual.zip` | Manuelle Installation mit `custom_components/…` |
| `ninebot_e_scooters_1.0.0b1_source.zip` | Quellcode, Tests und Dokumentation |
| `SHA256SUMS.txt` | Prüfsummen der ZIP-Dateien |

**Nächste Beta:** Manifest auf `1.0.0b2` setzen, Cache-Version des Pairing-Moduls in
`__init__.py` und Changelog aktualisieren, prüfen, erneut einen Entwurf erstellen.
Ein vorhandenes Release wird nicht überschrieben. Für die stabile Version `1.0.0`
verwenden und den Pre-release-Status deaktivieren. Ein Tag markiert eine feste
Codeversion; ein Release ergänzt Titel, Hinweise und herunterladbare Dateien.
