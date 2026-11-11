# Release veröffentlichen

Ein neues Release entsteht, sobald die Manifest-Version
(`custom_components/ninebot_e_scooters/manifest.json`) auf `main` neu ist. Tag und Titel
lauten `v<Version>`. Die Prüfsumme der ZIP-Datei steht als letzte Zeile in den
Release-Hinweisen.

Versionen heißen seit November 2026 `JJJJ.MM.TT.BUILD`, zum Beispiel `2026.11.11.1`: das
Datum des Releases und eine laufende Nummer ab 1 für mehrere Releases am selben Tag. Monat
und Tag stehen ohne führende Null im Vergleich (`2026.11.11.1` ist neuer als `2026.9.30.2`
und als jede `1.0.0b…`).

1. Manifest-Version erhöhen und `CHANGELOG.md` ergänzen. Die Cache-Version des
   Pairing-Moduls folgt der Manifest-Version von selbst.
2. Änderungen auf `main` übernehmen und den grünen **CI**-Lauf abwarten.
3. Die Pipeline veröffentlicht das Release mit `ninebot_e_scooters.zip`. Ein vorhandenes
   Release wird nicht überschrieben.

Für eine Prüfung vorab **Actions → Home Assistant CI → Run workflow** auf `main` starten und
`draft` aktiviert lassen: Es entsteht ein Release-Entwurf, den du ergänzen und
veröffentlichen kannst.

Die gesamte Pipeline kommt aus `seb5594/hass-workflows`; `.github/workflows/ci.yml` ruft sie
mit einem festen Commit auf und darf nicht lokal angepasst werden. Neue Pins kommen über
`managed.py sync` der Engine. Für die Veröffentlichung wird `ORCHESTRATION_PAT` (Leserecht auf
das private Engine-Repository) benötigt.

| Datei | Zweck |
| --- | --- |
| `ninebot_e_scooters.zip` | HACS und manuelle Installation (`wget`), Integration direkt im ZIP-Wurzelordner |
