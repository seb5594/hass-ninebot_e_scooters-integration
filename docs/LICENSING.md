# Lizenz

Das Projekt steht unter der [MIT-Lizenz](../LICENSE): Jede Person darf den
Code frei nutzen, verändern und weitergeben, auch kommerziell.

## Sitzungsverschlüsselung

Bis Version 1.0.0b5 ging `protocols/ninebot/crypto.py` laut Ausgangsprojekt auf
ScooterHacking/NinebotCrypto (AGPL-3.0) zurück. Seit 2026.11.11.1 ist das Modul neu
geschrieben, und zwar nach der öffentlichen Beschreibung des Verfahrens
([Encryption](https://nootnooot.codeberg.page/segway-ninebot-ble/encryption/),
[Authentication](https://nootnooot.codeberg.page/segway-ninebot-ble/authentication/)):
eigener Aufbau, eigene Namen, kein übernommener Code. Dass es sich auf der Leitung gleich
verhält, belegen aufgezeichnete Sitzungen der Vorversion
(`.github/tests/fixtures/released_crypto_sessions.json`).

Zwei Dinge gehören zur Einordnung dazu:

- Es war keine Reinraum-Entwicklung. Die Vorversion war beim Schreiben bekannt. Ob die
  Neufassung rechtlich als eigenständiges Werk gilt, kann dieses Dokument nicht zusichern.
- Die 16 Byte `FIRMWARE_SEED` sind ein Wert aus der Scooter-Firmware. Ohne ihn spricht kein
  Programm mit diesen Scootern; er steht in jeder öffentlichen Implementierung.

[THIRD_PARTY.md](THIRD_PARTY.md) dokumentiert die Herkunft der übrigen Teile.
