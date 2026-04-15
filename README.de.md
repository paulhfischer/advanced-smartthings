# Advanced SmartThings

[English](README.md) | Deutsch

`Advanced SmartThings` ist eine Home-Assistant-Custom-Integration für einen bewusst kleinen, expliziten Teilbereich von Samsung-/SmartThings-Haushaltsgeräten.

Dieses Repository liefert kein Home-Assistant-Add-on mehr aus. Das Produkt ist jetzt eine native Custom-Integration unter `custom_components/advanced_smartthings/`.

## Unterstützter Umfang in v1

Bewusst unterstützt werden nur diese Geräteklassen und Funktionen:

- Backofen
  - Fernsteuerung aktiviert als nur lesbares `binary_sensor`
  - Modus/Programm als schreibbares `select`
  - Timer-Dauer als schreibbares `number`
  - Temperatur-Sollwert als schreibbares `number`
  - explizite Buttons `Programm starten` und `Programm stoppen`
  - Beleuchtung als schreibbares `switch`
- Kühlschrank
  - Kühlschranktür offen als nur lesbares `binary_sensor`
  - Gefrierschranktür offen als nur lesbares `binary_sensor`
  - Kühlschrank-Temperatur-Sollwert als schreibbares `number`
  - Gefrierschrank-Temperatur-Sollwert als schreibbares `number`
  - Aktuelle Leistungsaufnahme als nur lesbares `sensor`
  - Wasserfilterverbrauch als nur lesbares `sensor`
- Kochfeld
  - Aktiv-Zustand als nur lesbares `binary_sensor`

Alles andere wird in v1 absichtlich ignoriert.

## Explizit nicht unterstützt

- Generische SmartThings-Capability-Durchleitung
- Rohausführung beliebiger SmartThings-Kommandos aus Home Assistant
- Dunstabzug, einzelne Kochzonen-Steuerung und schreibbare Kochfeld-Steuerung
- Kühlschrankkamera, Eiswürfelbereiter, Vacation Mode, Power Cool/Freeze und weitere Samsung-spezifische Zusatzfunktionen
- Andere Gerätekategorien außerhalb von Backofen, Kühlschrank und Kochfeld

## Sprachunterstützung

Home-Assistant-Benutzeroberflächen-Texte sind vorbereitet für:

- Englisch
- Deutsch

Das umfasst Konfigurationsdialoge, Fehler-/Abbruchtexte, Optionen und Entitätsnamen.

Backofen-Modi werden anhand der Home-Assistant-Systemsprache auf Englisch oder Deutsch dargestellt, sofern eine bekannte Zuordnung existiert. Unbekannte SmartThings-Modi werden als lesbare Fallback-Bezeichnung angezeigt.

## Installation

### HACS als benutzerdefiniertes Repository

1. HACS öffnen.
2. Dieses Repository als benutzerdefiniertes Repository vom Typ `Integration` hinzufügen.
3. Nach `Advanced SmartThings` suchen.
4. Integration installieren.
5. Home Assistant neu starten.

### Manuelle Installation

1. `custom_components/advanced_smartthings` in dein Home-Assistant-Konfigurationsverzeichnis kopieren:

   `config/custom_components/advanced_smartthings`

2. Home Assistant neu starten.

## SmartThings-OAuth einrichten

Erstelle eine SmartThings-OAuth-In-App und verwende die externe Home-Assistant-URL als Redirect-URI.

Erforderliche SmartThings-Einstellungen:

- Redirect-URI:
  - `https://DEINE_HOME_ASSISTANT_EXTERNAL_URL/auth/external/callback`
- Scopes:
  - `r:devices:*`
  - `x:devices:*`
  - `r:locations:*`

Hinweise:

- Die externe Home-Assistant-URL muss im Browser erreichbar sein.
- Die Redirect-URI muss exakt mit dem in SmartThings registrierten Wert übereinstimmen.
- Der Einrichtungsdialog der Integration zeigt die exakte Callback-URL dieser Home-Assistant-Instanz an.
- Client-ID und Client-Geheimnis werden im Home-Assistant-Konfigurationsdialog eingegeben.

## Einrichtung in Home Assistant

1. In Home Assistant `Einstellungen > Geräte & Dienste > Integration hinzufügen` öffnen.
2. `Advanced SmartThings` hinzufügen.
3. SmartThings-Client-ID und Client-Geheimnis eingeben.
4. Die SmartThings-Autorisierung im Browser abschließen.
5. Die unterstützten Geräte auswählen, die Home Assistant einbinden soll.
6. Den Dialog abschließen.

## Mapping-Hinweise

- Backofen-Modi verwenden `samsungce.ovenMode`.
- Der Backofen-Timer verwendet `samsungce.ovenOperatingState.setOperationTime` und wird als Dauer-`number` in Minuten dargestellt.
- Die Backofen-Temperatur verwendet `ovenSetpoint`.
- Starten/Stoppen des Backofens verwendet `samsungce.ovenOperatingState.start` bzw. `stop`.
- Die Fernsteuerbarkeit des Backofens verwendet `remoteControlStatus.remoteControlEnabled`.
- Die Backofen-Beleuchtung verwendet `samsungce.lamp` und wird als Schalter über unterstützte Helligkeitsstufen abgebildet.
- Backofen-Modus, Timer und Temperatur dienen als vorbereitete Programmeinstellungen. Mit `Programm starten` sendet die Integration Modus plus aktuelle Temperatur/Timer als zusammengehörige Start-Sequenz an SmartThings.
- `Programm starten` verweigert `Aus` / `NoOperation` und verwendet den von SmartThings gelieferten Standard-Temperaturwert des gewählten Modus, falls noch kein Temperaturwert gesetzt ist.
- Schreiben auf Backofen-Modus, Timer, Temperatur sowie Start-/Stop-Buttons wird blockiert, wenn SmartThings die Fernsteuerung als deaktiviert meldet. Die Beleuchtung bleibt trotzdem steuerbar.
- Kühlschrank-Temperaturen verwenden `thermostatCoolingSetpoint` auf den Komponenten `cooler` und `freezer`.
- Kühlschrank-Türen verwenden `contactSensor` auf den Komponenten `cooler` und `freezer`.
- Die Leistungsaufnahme des Kühlschranks verwendet `powerConsumptionReport.powerConsumption.value.power`.
- Der Wasserfilterverbrauch verwendet `custom.waterFilter.waterFilterUsage`.
- Der Kochfeld-Zustand verwendet den nur lesbaren `switch`-Status und wird als `binary_sensor` dargestellt, nicht als schreibbarer `switch`.

## Entwicklung

Empfohlene lokale Entwicklung:

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q tests
pre-commit run --all-files
```

## Logo-/Branding-Hinweis

Dieses Repository enthält jetzt offizielle SmartThings-Branding-Assets für das Home-Assistant-Integrationsbranding unter [custom_components/advanced_smartthings/brand](/Users/fischerp/Workspace/smartthings-oven-bridge/custom_components/advanced_smartthings/brand).

Quelle:

- SmartThings Brand Guidelines: [partners.smartthings.com/brand-guidelines](https://partners.smartthings.com/brand-guidelines)

Diese Assets werden für das Branding der Home-Assistant-Custom-Integration verwendet und sollten weiterhin im Rahmen der SmartThings-Brand-Guidelines genutzt werden.
