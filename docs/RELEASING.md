# Beta veröffentlichen

**Vorbereitet:** Anzeigename Beta 2, Manifest-Version `1.0.0b2`, Git-Tag
`v1.0.0b2`. Diese Schreibweise ist für Home Assistant und Python eindeutig; Versionen
mit `a`, `b` oder `rc` werden automatisch als Pre-release veröffentlicht.

1. Änderungen auf `main` übernehmen und den grünen **CI**-Lauf prüfen.
2. Die Lizenz-/Rechtefrage klären. Das private Repository erst danach öffentlich stellen.
3. Unter **Settings → Secrets and variables → Actions** `ORCHESTRATION_PAT` setzen:
   ein Token mit Leserechten für das private Repository `seb5594/hass-workflows`.
4. Ein neues Release entsteht, sobald die Manifest-Version auf `main` neu ist. Für eine
   Prüfung vorab **Actions → Validate and release integration → Run workflow** auf `main`
   starten und `draft` aktiviert lassen: Es entsteht ein Release-Entwurf mit ZIPs und
   Prüfsummen.
5. Unter **Releases** den Entwurf öffnen, kurze Änderungen ergänzen und die Dateien
   prüfen, dann veröffentlichen. Den Titel setzt die Engine aus Name und Manifest-Version
   (`Ninebot E-Scooters 1.0.0b2`); der Anzeigename aus dem Changelog lässt sich hier ergänzen.

Die gesamte Pipeline kommt aus `seb5594/hass-workflows`; `.github/workflows/ci.yml`
ruft sie mit einem festen Commit auf und darf nicht lokal angepasst werden. Ein neuer
Pin wird durch Kopieren der Vorlage `.templates/integration/ci.yml.tpl` übernommen.
Die Veröffentlichung verwendet `GITHUB_TOKEN` mit `contents: write`.

| Datei | Zweck |
| --- | --- |
| `ninebot_e_scooters.zip` | HACS und manuelle Installation (`wget`), Integration direkt im ZIP-Wurzelordner |
| `SHA256SUMS.txt` | Prüfsummen der ZIP-Dateien |

**Nächste Beta:** Manifest auf `1.0.0b3` setzen, Cache-Version des Pairing-Moduls in
`__init__.py` und Changelog aktualisieren, prüfen. Ein vorhandenes Release wird nicht
überschrieben. Für die stabile Version `1.0.0` verwenden. Ein Tag markiert eine feste
Codeversion; ein Release ergänzt Titel, Hinweise und herunterladbare Dateien.
