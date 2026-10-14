# Changelog

All notable changes to this integration. Versions match the `version` field in
`custom_components/selection_fitness/manifest.json`.

## [1.7.0] – 2026-10-14

### Added
- UI translations for 18 languages: English, German, Spanish, French, Italian,
  Dutch, Polish, Portuguese (Portugal and Brazil), Russian, Ukrainian, Turkish,
  Chinese (Simplified and Traditional), Japanese, Korean, Arabic and Hindi.
- Machine and strength test sensors, the machines device, the primary metric
  selection in the options, units such as "points"/"reps" and the trend
  attribute values (`rising`/`falling`/`stable`) are now translated.
- Service errors and the backdating notification are translated.

### Changed
- Machine and exercise names are requested from the eGym API in the language of
  the Home Assistant instance (previously always German).
- The `trend` attribute of machine sensors now uses the values
  `rising`/`falling`/`stable` instead of `steigend`/`fallend`/`stabil`.
- README and changelog are now in English.
- Minimum Home Assistant version raised to 2024.11.

## [1.6.2] – 2026-10-14

### Changed
- `add_body_measurement` rejects body values older than the newest known
  measurement. The server takes every weight it receives as the current
  profile weight – including backdated ones. With `force_backdate: true` they
  are sent anyway; a notification then reminds you to enter the current weight
  again.

## [1.6.1] – 2026-10-14

### Fixed
- Statistics import sets `unit_class` (required from HA 2026.11, otherwise the
  import is rejected) – also affects machine, strength and BioAge history.
- Water sensors use `volume_storage`; `volume` does not allow
  `state_class: measurement`.

## [1.6.0] – 2026-10-14

### Added
- Services `selection_fitness.add_body_measurement` (weight, body fat, height)
  and `selection_fitness.add_cardio_measurement` (resting heart rate, blood
  pressure, VO2max) write measurements with their measurement time to the
  account – using the same endpoint as the app's Health Connect sync.
- Sensors for the body composition scale at the gym (InBody / fithub): body fat
  mass, visceral fat area, body water (total, intra-/extracellular), ECW/TBW
  ratio, phase angle and ten segment values (disabled by default). Normal
  ranges as `normal_low`/`normal_high` attributes, backfilled history as
  long-term statistics.

### Fixed
- Muscle mass, lean body mass, visceral fat and basal metabolic rate report
  values again (now taken from the measurement log instead of the broken
  `latest-metrics` endpoint).
- Missing `timedelta` import: an update interval set in the options made the
  setup fail.

## [1.5.2] – 2026-10-12

### Fixed
- `StatisticMeanType` is resolved robustly across several module paths.

## [1.5.1] – 2026-10-12

### Fixed
- `mean_type` set in the statistics metadata (future-proof for HA 2026.11).

## [1.5.0] – 2026-10-12

### Added
- Fitness age and machine history are imported year by year back to the first
  measurement.

## [1.4.4] – 2026-10-12

### Added
- Workout count is backfilled as cumulative history.

## [1.4.3] – 2026-10-12

### Fixed
- Strength history uses the top-level `createdAt` as its date.

### Documentation
- Backfill of the strength test history described in the README.

## [1.4.2] – 2026-10-12

### Internal
- Strength history response logged once to map its structure.

## [1.4.1] – 2026-10-12

### Changed
- Data is refreshed right after setup, so the statistics backfill runs
  immediately instead of at the next interval.

## [1.4.0] – 2026-10-12

### Added
- Strength test history as separate sensors with long-term statistics.

## [1.3.3] – 2026-10-12

### Changed
- Diagnostic requests removed, strength test documented.

## [1.3.2] – 2026-10-12

### Fixed
- Strength tests parsed correctly (`strengthMeasurements`, matched by machine name).

## [1.3.1] – 2026-10-12

### Internal
- Strength test response logged once to map its structure.

## [1.3.0] – 2026-10-12

### Added
- Strength test (eGym test value) per machine.

## [1.2.4] – 2026-10-12

### Fixed
- Key of the flexibility section corrected (`flexibilityDetails`).

## [1.2.3] – 2026-10-12

### Changed
- More BioAge types requested, returned sections are logged.

## [1.2.2] – 2026-10-12

### Changed
- Expected 404 responses for check-ins only in the debug log.

### Documentation
- Comprehensive README.

## [1.2.1] – 2026-10-11

### Added
- History per machine is imported as long-term statistics.

## [1.2.0] – 2026-10-11

### Added
- Flexible data model for machines, multiple people (one entry per account).

## [1.1.1] – 2026-10-11

### Added
- Machine images as well as trend and forecast for the weight.

### Changed
- `via_device` removed.

## [1.1.0] – 2026-10-11

### Added
- Sensors per eGym machine from the training history.

## [1.0.11] – 2026-10-11

### Internal
- Top-level attributes of an exercise logged (actually recorded values).

## [1.0.10] – 2026-10-11

### Internal
- One sample exercise logged to map the per-machine attributes.

## [1.0.9] – 2026-10-11

### Changed
- Redundant measurement requests removed, diagnostic output reduced.

## [1.0.8] – 2026-10-11

### Fixed
- Correct mobile API host enforced; workout date without offset.

## [1.0.7] – 2026-10-11

### Fixed
- Workout date format (`+00:00` offset); connection errors are logged.

## [1.0.6] – 2026-10-11

### Added
- Muscle sub-values and imbalances from the BioAge summary.

## [1.0.5] – 2026-10-11

### Added
- eGym BioAge (body, muscle, cardio, flexibility, metabolic age).

### Fixed
- Mobile API host corrected.

## [1.0.4] – 2026-10-11

### Changed
- Body data from the profile, real training history.

## [1.0.3] – 2026-10-11

### Fixed
- Workouts parsed correctly; diagnostic logging added.

## [1.0.2] – 2026-10-11

### Fixed
- Login field name `username` instead of `login`.

## [1.0.1] – 2026-10-11

### Fixed
- Login sends the credentials form-urlencoded instead of JSON.

## [1.0.0] – 2026-10-11

### Added
- First version of the Selection Fitness integration (Netpulse/eGym) for Home Assistant.

[1.7.0]: https://github.com/Blogshot/homeassistant-selection-fitness/compare/v1.6.2...v1.7.0
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
