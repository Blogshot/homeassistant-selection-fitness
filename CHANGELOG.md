# Changelog

Alle nennenswerten Änderungen an der Integration. Versionen entsprechen dem
Feld `version` in `custom_components/selection_fitness/manifest.json`.

## [1.6.2] – 2026-10-14

### Geändert
- `add_body_measurement` lehnt Körperwerte ab, die älter als die neueste
  bekannte Messung sind. Der Server übernimmt jedes gesendete Gewicht als
  aktuelles Profilgewicht – auch rückwirkend datierte. Mit
  `force_backdate: true` werden sie trotzdem gesendet; danach erscheint eine
  Benachrichtigung, dass das aktuelle Gewicht neu eingetragen werden muss.

## [1.6.1] – 2026-10-14

### Behoben
- Statistik-Import setzt `unit_class` (ab HA 2026.11 Pflicht, sonst wird der
  Import abgelehnt) – betrifft auch Geräte-, Kraft- und BioAge-Historie.
- Wasser-Sensoren nutzen `volume_storage`; `volume` erlaubt kein
  `state_class: measurement`.

## [1.6.0] – 2026-10-14

### Neu
- Services `selection_fitness.add_body_measurement` (Gewicht, Körperfett,
  Größe) und `selection_fitness.add_cardio_measurement` (Ruhepuls, Blutdruck,
  VO2max) schreiben Messwerte mit Messzeitpunkt ins Konto – über denselben
  Endpunkt wie der Health-Connect-Sync der App.
- Sensoren für die Körperanalyse-Waage im Studio (InBody / fithub):
  Fettmasse, viszerale Fettfläche, Körperwasser (gesamt, intra-/extrazellulär),
  ECW/TBW-Verhältnis, Phasenwinkel sowie zehn Segmentwerte (standardmäßig
  deaktiviert). Normbereiche als Attribute `normal_low`/`normal_high`,
  rückwirkende Historie als Langzeitstatistik.

### Behoben
- Muskelmasse, Magermasse, viszerales Fett und Grundumsatz liefern wieder
  Werte (kommen jetzt aus dem Messungs-Log statt aus dem defekten
  `latest-metrics`-Endpunkt).
- Fehlender `timedelta`-Import: ein in den Optionen gesetztes Abruf-Intervall
  ließ das Setup scheitern.

## [1.5.2] – 2026-10-12

### Behoben
- `StatisticMeanType` wird robust über mehrere Modulpfade aufgelöst.

## [1.5.1] – 2026-10-12

### Behoben
- `mean_type` in den Statistik-Metadaten gesetzt (zukunftssicher für HA 2026.11).

## [1.5.0] – 2026-10-12

### Neu
- Fitness-Alter- und Geräte-Historie werden jahresweise bis zur ersten
  Messung importiert.

## [1.4.4] – 2026-10-12

### Neu
- Anzahl Workouts wird als kumulativer Verlauf rückwirkend importiert.

## [1.4.3] – 2026-10-12

### Behoben
- Kraftmess-Historie nutzt das `createdAt` der obersten Ebene als Datum.

### Dokumentation
- Import der Kraftmess-Historie im README beschrieben.

## [1.4.2] – 2026-10-12

### Intern
- Antwort der Kraftmess-Historie einmalig geloggt, um ihre Struktur zu ermitteln.

## [1.4.1] – 2026-10-12

### Geändert
- Nach dem Setup wird sofort neu abgerufen, damit der Statistik-Import nicht
  erst beim nächsten Intervall läuft.

## [1.4.0] – 2026-10-12

### Neu
- Kraftmess-Historie als eigene Sensoren mit Langzeitstatistik.

## [1.3.3] – 2026-10-12

### Geändert
- Diagnose-Abfragen entfernt, Kraftmessung dokumentiert.

## [1.3.2] – 2026-10-12

### Behoben
- Kraftmessungen korrekt geparst (`strengthMeasurements`, Zuordnung über den Gerätenamen).

## [1.3.1] – 2026-10-12

### Intern
- Antwort der Kraftmessung einmalig geloggt, um ihre Struktur zu ermitteln.

## [1.3.0] – 2026-10-12

### Neu
- Kraftmessung (eGym-Testwert) je Gerät.

## [1.2.4] – 2026-10-12

### Behoben
- Schlüssel des Flexibilitäts-Abschnitts korrigiert (`flexibilityDetails`).

## [1.2.3] – 2026-10-12

### Geändert
- Mehr BioAge-Typen abgefragt, gelieferte Abschnitte werden geloggt.

## [1.2.2] – 2026-10-12

### Geändert
- Erwartete 404-Antworten beim Check-in nur noch im Debug-Log.

### Dokumentation
- Ausführliches README.

## [1.2.1] – 2026-10-12

### Neu
- Historie je Gerät wird als Langzeitstatistik importiert.

## [1.2.0] – 2026-10-11

### Neu
- Flexibles Datenmodell für Geräte, mehrere Personen (je Konto ein Eintrag).

## [1.1.1] – 2026-10-11

### Neu
- Gerätebilder sowie Trend und Prognose für das Gewicht.

### Geändert
- `via_device` entfernt.

## [1.1.0] – 2026-10-11

### Neu
- Sensoren je eGym-Gerät aus der Trainingshistorie.

## [1.0.11] – 2026-10-11

### Intern
- Attribute der obersten Ebene einer Übung geloggt (tatsächlich erfasste Werte).

## [1.0.10] – 2026-10-11

### Intern
- Eine Beispiel-Übung geloggt, um die Attribute je Gerät zu ermitteln.

## [1.0.9] – 2026-10-11

### Geändert
- Redundante Messwert-Abfragen entfernt, Diagnose-Ausgaben reduziert.

## [1.0.8] – 2026-10-11

### Behoben
- Richtiger Mobile-API-Host wird erzwungen; Workout-Datum ohne Offset.

## [1.0.7] – 2026-10-11

### Behoben
- Workout-Datumsformat (`+00:00`-Offset); Verbindungsfehler werden geloggt.

## [1.0.6] – 2026-10-11

### Neu
- Muskel-Unterwerte und Dysbalancen aus der BioAge-Übersicht.

## [1.0.5] – 2026-10-11

### Neu
- eGym BioAge (Körper-, Muskel-, Cardio-, Flexibilitäts-, Stoffwechselalter).

### Behoben
- Mobile-API-Host korrigiert.

## [1.0.4] – 2026-10-11

### Geändert
- Körperdaten aus dem Profil, echte Trainingshistorie.

## [1.0.3] – 2026-10-11

### Behoben
- Workouts korrekt geparst; Diagnose-Logging ergänzt.

## [1.0.2] – 2026-10-11

### Behoben
- Login-Feldname `username` statt `login`.

## [1.0.1] – 2026-10-11

### Behoben
- Login sendet die Zugangsdaten form-urlencoded statt als JSON.

## [1.0.0] – 2026-10-11

### Neu
- Erste Version der Selection-Fitness-Integration (Netpulse/eGym) für Home Assistant.

[1.6.2]: https://github.com/Blogshot/homeassistant-selection-fitness/compare/v1.6.1...v1.6.2
[1.6.1]: https://github.com/Blogshot/homeassistant-selection-fitness/compare/v1.6.0...v1.6.1
[1.6.0]: https://github.com/Blogshot/homeassistant-selection-fitness/compare/v1.5.2...v1.6.0
[1.5.2]: https://github.com/Blogshot/homeassistant-selection-fitness/compare/v1.5.1...v1.5.2
[1.5.1]: https://github.com/Blogshot/homeassistant-selection-fitness/compare/v1.5.0...v1.5.1
[1.5.0]: https://github.com/Blogshot/homeassistant-selection-fitness/compare/v1.4.4...v1.5.0
[1.4.4]: https://github.com/Blogshot/homeassistant-selection-fitness/compare/v1.4.3...v1.4.4
[1.4.3]: https://github.com/Blogshot/homeassistant-selection-fitness/compare/v1.4.2...v1.4.3
[1.4.2]: https://github.com/Blogshot/homeassistant-selection-fitness/compare/v1.4.1...v1.4.2
[1.4.1]: https://github.com/Blogshot/homeassistant-selection-fitness/compare/v1.4.0...v1.4.1
[1.4.0]: https://github.com/Blogshot/homeassistant-selection-fitness/compare/v1.3.3...v1.4.0
[1.3.3]: https://github.com/Blogshot/homeassistant-selection-fitness/compare/v1.3.2...v1.3.3
[1.3.2]: https://github.com/Blogshot/homeassistant-selection-fitness/compare/v1.3.1...v1.3.2
[1.3.1]: https://github.com/Blogshot/homeassistant-selection-fitness/compare/v1.3.0...v1.3.1
[1.3.0]: https://github.com/Blogshot/homeassistant-selection-fitness/compare/v1.2.4...v1.3.0
[1.2.4]: https://github.com/Blogshot/homeassistant-selection-fitness/compare/v1.2.3...v1.2.4
[1.2.3]: https://github.com/Blogshot/homeassistant-selection-fitness/compare/v1.2.2...v1.2.3
[1.2.2]: https://github.com/Blogshot/homeassistant-selection-fitness/compare/v1.2.1...v1.2.2
[1.2.1]: https://github.com/Blogshot/homeassistant-selection-fitness/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/Blogshot/homeassistant-selection-fitness/compare/v1.1.1...v1.2.0
[1.1.1]: https://github.com/Blogshot/homeassistant-selection-fitness/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/Blogshot/homeassistant-selection-fitness/compare/v1.0.11...v1.1.0
[1.0.11]: https://github.com/Blogshot/homeassistant-selection-fitness/compare/v1.0.10...v1.0.11
[1.0.10]: https://github.com/Blogshot/homeassistant-selection-fitness/compare/v1.0.9...v1.0.10
[1.0.9]: https://github.com/Blogshot/homeassistant-selection-fitness/compare/v1.0.8...v1.0.9
[1.0.8]: https://github.com/Blogshot/homeassistant-selection-fitness/compare/v1.0.7...v1.0.8
[1.0.7]: https://github.com/Blogshot/homeassistant-selection-fitness/compare/v1.0.6...v1.0.7
[1.0.6]: https://github.com/Blogshot/homeassistant-selection-fitness/compare/v1.0.5...v1.0.6
[1.0.5]: https://github.com/Blogshot/homeassistant-selection-fitness/compare/v1.0.4...v1.0.5
[1.0.4]: https://github.com/Blogshot/homeassistant-selection-fitness/compare/v1.0.3...v1.0.4
[1.0.3]: https://github.com/Blogshot/homeassistant-selection-fitness/compare/v1.0.2...v1.0.3
[1.0.2]: https://github.com/Blogshot/homeassistant-selection-fitness/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/Blogshot/homeassistant-selection-fitness/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/Blogshot/homeassistant-selection-fitness/releases/tag/v1.0.0
