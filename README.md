# Ninebot E-Scooters

<!-- badges:begin (generated from project metadata) -->
[![version](https://img.shields.io/static/v1?label=version&message=1.0.0b1&color=1877A5&style=flat)](https://github.com/seb5594/hass-ninebot_e_scooters-integration/releases) [![released](https://img.shields.io/github/release-date-pre/seb5594/hass-ninebot_e_scooters-integration?label=released&style=flat)](https://github.com/seb5594/hass-ninebot_e_scooters-integration/releases) [![checks](https://img.shields.io/github/actions/workflow/status/seb5594/hass-ninebot_e_scooters-integration/ci.yml?branch=main&label=checks&style=flat)](https://github.com/seb5594/hass-ninebot_e_scooters-integration/actions/workflows/ci.yml)<br>
[![stars](https://img.shields.io/github/stars/seb5594/hass-ninebot_e_scooters-integration?label=stars&style=flat)](https://github.com/seb5594/hass-ninebot_e_scooters-integration/stargazers) [![issues](https://img.shields.io/github/issues/seb5594/hass-ninebot_e_scooters-integration?label=issues&style=flat)](https://github.com/seb5594/hass-ninebot_e_scooters-integration/issues) [![updated](https://img.shields.io/github/last-commit/seb5594/hass-ninebot_e_scooters-integration?label=updated&style=flat)](https://github.com/seb5594/hass-ninebot_e_scooters-integration/commits/main)<br>
[![downloads](https://img.shields.io/github/downloads/seb5594/hass-ninebot_e_scooters-integration/total?label=downloads&style=flat)](https://github.com/seb5594/hass-ninebot_e_scooters-integration/releases) [![latest release](https://img.shields.io/github/downloads/seb5594/hass-ninebot_e_scooters-integration/latest/total?label=latest%20release&style=flat)](https://github.com/seb5594/hass-ninebot_e_scooters-integration/releases/latest)<br>
![home assistant](https://img.shields.io/static/v1?label=home%20assistant&message=%E2%89%A5%202026.9.0&color=1877A5&style=flat) ![stage](https://img.shields.io/static/v1?label=stage&message=beta&color=C27C0E&style=flat) ![type](https://img.shields.io/static/v1?label=type&message=device&color=5B6770&style=flat) ![iot class](https://img.shields.io/static/v1?label=iot%20class&message=local%20polling&color=5B6770&style=flat) ![setup](https://img.shields.io/static/v1?label=setup&message=UI%20config%20flow&color=157F71&style=flat) ![discovery](https://img.shields.io/static/v1?label=discovery&message=bluetooth&color=157F71&style=flat) ![requirements](https://img.shields.io/static/v1?label=requirements&message=0&color=1877A5&style=flat)<br>
![tests](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fseb5594%2Fhass-ninebot_e_scooters-integration%2Fbadges%2Ftests.json&style=flat) ![HACS zip](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fseb5594%2Fhass-ninebot_e_scooters-integration%2Fbadges%2Fzip-size.json&style=flat) ![last build](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fseb5594%2Fhass-ninebot_e_scooters-integration%2Fbadges%2Flast-build.json&style=flat)<br>
[![HACS](https://img.shields.io/static/v1?label=HACS&message=Add%20integration&color=41BDF5&style=flat&logo=homeassistantcommunitystore&logoColor=white)](https://my.home-assistant.io/redirect/hacs_repository/?owner=seb5594&repository=hass-ninebot_e_scooters-integration&category=integration)<br>
[![Buy Me a Coffee](https://img.shields.io/static/v1?label=Support&message=Buy%20Me%20a%20Coffee&color=FFDD00&logo=buy-me-a-coffee&logoColor=black&style=flat)](https://buymeacoffee.com/seb5594) [![PayPal](https://img.shields.io/static/v1?label=Support&message=PayPal&color=0070BA&logo=paypal&logoColor=white&style=flat)](https://www.paypal.com/donate/?hosted_button_id=QMQPNRENXDN26)
<!-- badges:end -->

**v1.0.0 Beta 1** · Lokale Home-Assistant-Integration für Ninebot/Segway E-Scooter
und kompatible Xiaomi-Modelle. Kein Cloud-Konto erforderlich.

Die Referenz ist ein Xiaomi 1S mit BLE 1.29 und DRV 1.28. Weitere Profile sind
experimentell und benötigen Hardware-Rückmeldungen. Die Integration behält eine
funktionierende Bluetooth-Sitzung und nutzt gespeicherte Schlüssel erneut.

## Modelle und Firmware

| Modell/Familie | Protokoll/Firmware | Funktionen | Prüfstatus |
| --- | --- | --- | --- |
| Xiaomi 1S | 5A A5, BLE129 / DRV1.28 | Telemetrie und abgesicherte Steuerung | Referenzgerät der Basis |
| Xiaomi Pro 2 / Essential | 5A A5, BLE129 | Telemetrie | Hardwaretest ausstehend |
| Xiaomi M365, Vier-Punkte-Anzeige | Unverschlüsseltes 55 AA | Telemetrie | Hardwaretest ausstehend |
| Xiaomi M365 Pro | 5A A5, BLE110/122 | Telemetrie | Hardwaretest ausstehend |
| Ninebot ES1 / ES2 / ES3 / ES4 | 5A A5, BLE109/110 | Lesende Wortregister | Experimentell |
| Ninebot Max G30 / G30P / G30D / G30E / G30LP / G30LE / G30LD | 5A A5, BLE110/113/114 | Lesende Wortregister | Experimentell |
| Ninebot E22 / E25 / E45 | 5A A5, BLE209/213 | Lesende Wortregister | Experimentell |
| Ninebot F20 / F25 / F30 / F40 | 5A A5, BLE307, PC-Adresse | Lesende Wortregister | Experimentell |

Diese BLE-Versionen stammen aus öffentlichen Implementierungen. Sie garantieren keine
Kompatibilität mit jeder Regions-, Dashboard- oder Firmwarevariante. Xiaomi BLE132 mit
5A AB, Xiaomi 3/4 sowie Ninebot G2, F2, ZT und GT sind nicht freigegeben.
Modellhinweise im Recherchekatalog bedeuten keine Unterstützung.

Ninebot liest Akkustand, Strom, Spannung, Batterietemperaturen und Statuswort.
Kilometerstand, Firmware, Fehler und Batteriegesundheit werden schrittweise abgefragt.
Die aktuelle Geschwindigkeit, externe ES-Batterien und schreibende Ninebot-Steuerung
sind noch nicht implementiert. Fehlende Werte bleiben unbekannt.

## Installation

Voraussetzungen: **Home Assistant 2026.9 oder neuer**, Bluetooth-Adapter oder aktiver
ESPHome-Bluetooth-Proxy. Andere Scooter-Apps vor der Einrichtung trennen.

1. Per HACS installieren (siehe unten) oder manuell im Terminal von Home Assistant
   (SSH-/Terminal-App) die gewünschte Version aus den
   [Releases](https://github.com/seb5594/hass-ninebot_e_scooters-integration/releases) laden:

   ```bash
   cd /config
   mkdir -p custom_components/ninebot_e_scooters
   wget -O /tmp/ninebot_e_scooters.zip \
     https://github.com/seb5594/hass-ninebot_e_scooters-integration/releases/download/v1.0.0b1/ninebot_e_scooters.zip
   unzip -o /tmp/ninebot_e_scooters.zip -d custom_components/ninebot_e_scooters
   rm /tmp/ninebot_e_scooters.zip
   ```

   `v1.0.0b1` durch die gewünschte Version ersetzen. Danach Home Assistant neu starten.
2. Unter **Einstellungen → Geräte & Dienste → Integration hinzufügen** nach
   **Ninebot E-Scooters** suchen. Scooter einschalten und passendes Modell auswählen.
3. Erst beim zentrierten Pairing-Hinweis einmal kurz die Einschalttaste drücken.

Für HACS nach einer öffentlichen Veröffentlichung: dieses Repository als
**Benutzerdefiniertes Repository → Integration** hinzufügen; Beta-Versionen aktivieren.
Die Datei `ninebot_e_scooters.zip` enthält die Integration direkt im ZIP-Wurzelordner und
dient HACS wie der manuellen Installation.

**Umstieg von `xiaomi_scooter`:** Die neue technische Domain ist `ninebot_e_scooters`.
Dies ist kein automatisches Update des alten Config Entries. Zuerst eine HA-Sicherung
anlegen, bisherige Entity-IDs notieren und die alte Integration entfernen. Den alten
Komponentenordner entfernen, den neuen installieren und den Scooter neu einrichten.
Pairing wird dabei neu bestätigt. Anschließend Entity-IDs und Automationen prüfen.
Die beiden Integrationen dürfen nicht gleichzeitig denselben Scooter verbinden.
Keine Dateien unter `.storage` von Hand bearbeiten.

Wenn kein Gerät gefunden wird: erneut suchen oder Bluetooth-Adresse und den exakten
ausgesendeten Bluetooth-Namen eingeben. Der Name ist Teil der Verschlüsselung und
kann von deiner frei gewählten Gerätebezeichnung abweichen.

## Verbindung und Werte

Der Standard-Leseabstand beträgt zehn Sekunden; in den Optionen sind fünf bis 120
Sekunden möglich. Für einen geparkten Scooter sind 20–30 Sekunden oft ausreichend.

Eine funktionierende Sitzung bleibt bestehen. Nach einem Abbruch braucht der nächste
Versuch eine neue, aktuelle Bluetooth-Sichtung. Zuerst wird eine gespeicherte Sitzung
mit einem verschlüsselten Lesezugriff geprüft. Timeouts ersetzen den App-Key nicht.
Wiederholte Fehler verlängern die Pause; ein nicht bestätigtes Pairing wird frühestens
nach einer Minute erneut versucht. Das soll unnötige Verbindungswechsel reduzieren.
Firmwaregesteuerte Verbindungstöne können trotzdem auftreten.

„Verbindung“, „Telemetrie veraltet“ und „Letzte Telemetrie“ zeigen den Verbindungs- und
Datenstatus. Messwerte besitzen `last_live_telemetry` und `value_is_cached`. Nach mehr
als zehn Minuten werden alte Messwerte nicht mehr als verfügbar markiert. Die
1S-Referenzreichweite ist eine einfache Akkuprozent-Schätzung.

Schloss, Rücklicht, Rekuperation, Fahrmodus und Tempomat bleiben auf das bestätigte
Xiaomi-1S-Profil begrenzt. Steuerungen benötigen aktuelle Stillstandstelemetrie und
bestätigte Rücklesung. Bei Ninebot bleiben diese Steuerentitäten nicht verfügbar.

## Wenn die Verbindung hakt

- Andere Bluetooth-Apps trennen, Scooter eingeschaltet und beim Pairing nahe am Adapter lassen.
- Exakten Bluetooth-Namen, Modell und Firmware prüfen.
- Den Tastendruck erst nach dem Hinweis ausführen und die Wiederholungspause abwarten.
- Nicht wiederholt neu laden oder den gespeicherten Schlüssel löschen.
- Diagnose im Integrationsmenü herunterladen und Modell, BLE/DRV, Adapter/Proxy und Ablauf angeben.

Bei Bedarf Debug-Logging aktivieren:

```yaml
logger:
  logs:
    custom_components.ninebot_e_scooters: debug
```

## Kompatibilität prüfen und mithelfen

1. Modell, Region und BLE-/DRV-/BMS-Version in der Hersteller-App notieren.
2. Passendes Profil wählen und zuerst nur Telemetrie prüfen. Akkustand, Spannung,
   Temperatur und Kilometerstand mit der Hersteller-App vergleichen; Apps nacheinander nutzen.
3. HA-Neustart, Scooter-Neustart und eine kurze Reichweitenunterbrechung testen.
4. [Modellbericht erstellen](https://github.com/seb5594/hass-ninebot_e_scooters-integration/issues/new?template=model-support.yml):
   Ergebnis, Firmware, Adapter/Proxy und bereinigte Diagnose anhängen.

Ein gleicher Bluetooth-Name oder eine erfolgreiche GATT-Verbindung beweist noch
keine Protokollkompatibilität. Fehlende Werte, wiederholte Pairing-Aufforderungen oder
ein abweichender Rahmen sind ebenfalls hilfreiche Rückmeldungen.

[Ausführlicher Testablauf](docs/COMPATIBILITY.md) ·
[Entwicklung und Modellvorlagen](docs/CONTRIBUTING.md) ·
[Architektur](docs/ARCHITECTURE.md) · [Release-Anleitung](docs/RELEASING.md) ·
[Änderungen](CHANGELOG.md)

## Danksagung

Ein ausdrückliches Dankeschön an **ScooterHacking** für das Reverse Engineering,
das [Wiki](https://wiki.scooterhacking.org/doku.php?id=nbdocs) und das ausführliche
[Ninebot ES Scooter Protocol PDF](https://wiki.scooterhacking.org/lib/exe/fetch.php?media=ninebot_es_scooter_protocol_918.pdf).
Diese Dokumentation bildet die wichtigste Protokollgrundlage des Projekts.

## Lizenz

Die Projektlizenz ist noch nicht festgelegt. Die Veröffentlichung ist bis zur
Klärung der Rechte vorbereitet; daraus entsteht keine allgemeine Nutzungserlaubnis.
Vorhandene Drittanbieterrechte bleiben bestehen. Siehe
[Lizenzentscheidung](docs/LICENSING.md) und [Herkunftshinweise](THIRD_PARTY.md).

Öffentliche Statistik-Badges funktionieren erst, wenn das Repository öffentlich und
ein Release veröffentlicht ist; bis dahin können sie „not found“ anzeigen.
