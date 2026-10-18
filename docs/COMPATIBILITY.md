# Deinen Scooter prüfen

Ein Testbericht bezieht sich auf ein konkretes Modell, seine Region und Firmware.
Die Modellliste nennt verfügbare Profile; „experimentell“ bedeutet, dass ihre
Hardware-Abnahme noch fehlt. Für einen ersten Bericht ist kein Programmieren nötig.

1. **Vorbereiten:** HA-Sicherung anlegen. Modell/Region, BLE-, DRV- und BMS-Version
   in der Hersteller-App ablesen. Adapter oder ESPHome-Proxy und HA-Version notieren.
   Den Scooter sicher abstellen und die Hersteller-App anschließend trennen.
2. **Einrichten:** Das passende Profil wählen. Keine ähnlich benannte Serie
   erzwingen: F ist nicht F2, G30 ist nicht G2. Den Power-Button nur beim Hinweis drücken.
3. **Werte vergleichen:** Akkustand, Spannung, Stromrichtung, Temperatur und
   Kilometerstand nacheinander mit der Hersteller-App vergleichen. Fehlende Werte
   ausdrücklich als fehlend melden; ein unbekannter Wert ist nicht null.
4. **Verbindung prüfen:** 15–30 Minuten eingeschaltet beobachten. Danach HA neu
   starten, Scooter aus-/einschalten und kurz aus der Reichweite bewegen.
   Wiederherstellung, Wartezeit, Signaltöne und erneute Pairing-Hinweise notieren.
5. **Bericht senden:** Im Integrationsmenü die Diagnose herunterladen und über
   [Modell-Kompatibilität](https://github.com/seb5594/hass-ninebot_e_scooters-integration/issues/new?template=model-support.yml)
   berichten. Vor dem Upload auf MAC-Adressen, Seriennummern und Schlüssel prüfen.
   Debug-Logs können zusätzliche persönliche Angaben enthalten und brauchen eine
   eigene Bereinigung; niemals `app_key` veröffentlichen.

Ninebot-Profile lesen derzeit nur. Für Kompatibilitätstests sind keine Änderungen
an Firmware, Region oder Fahrparametern erforderlich. Bei einem nicht unterstützten
Rahmen reichen Modell, Firmware, Diagnose und ein Ablaufbericht zunächst aus.

Kopierbare Kurzvorlage:

```text
Modell / Region:
BLE / DRV / BMS:
HA / Integration:
Bluetooth-Adapter oder Proxy:
Gewähltes Profil:
Erstes Pairing / Neustart / Reichweitenverlust:
Verglichene Werte und Abweichungen:
Verbindungsabbrüche / Signaltöne / fehlende Werte:
Beobachtungsdauer:
Bereinigte Diagnose:
```

Fortgeschrittene können bereinigte Paket-Fixtures und ihre dokumentierte Quelle
beisteuern. Erst vollständige Rahmen, Host-/Geräteadresse, Opcode, Index und
Firmwarekontext erlauben eine zuverlässige Zuordnung. Siehe
[CONTRIBUTING.md](CONTRIBUTING.md) für Register- und Modellvorlagen.
