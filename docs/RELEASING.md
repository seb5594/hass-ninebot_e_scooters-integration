# Release veröffentlichen

Ein neues Release entsteht, sobald die Manifest-Version
(`custom_components/ninebot_e_scooters/manifest.json`) auf `main` neu ist. Tag und Titel
lauten `v<Version>`; Versionen mit `a`, `b` oder `rc` erscheinen unter ihrer Stufe
(zum Beispiel `Beta 4`). Die Prüfsumme der ZIP-Datei steht als letzte Zeile in den
Release-Hinweisen.

1. Manifest-Version erhöhen, die Cache-Version des Pairing-Moduls in `__init__.py`
   (`pairing_dialog.js?v=…`) angleichen und `CHANGELOG.md` ergänzen.
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
