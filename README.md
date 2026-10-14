# Selection Fitness → Home Assistant

A custom integration that brings your body, fitness and training data from the
**Selection Fitness** app (Netpulse / eGym white label,
`com.netpulse.mobile.selectionfitness`) into Home Assistant as entities – no
MQTT, login directly in the UI.

The integration talks to the same backend API as the app ("app impersonation"):
it signs in with your credentials and reads **your own** data. No protection
mechanisms are bypassed.

[![Open your Home Assistant instance and open this repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Blogshot&repository=homeassistant-selection-fitness&category=integration)

> Clicking the button opens the repository directly in HACS on your Home
> Assistant instance.

---

## Features

- **Body data** from the profile: weight, height, gender, unit system, home club
- **eGym BioAge / fitness age**: body age, muscle age, cardio age, flexibility
  age, metabolic age – including upper body / core / lower body age and the
  muscle balance states
- **Values behind BioAge**: body fat, BMI, VO2max, resting heart rate, blood
  pressure, waist-hip ratio
- **Body composition scale at the gym** (InBody / fithub): muscle, lean and fat
  mass, visceral fat, basal metabolic rate, body water (intra-/extracellular,
  ECW/TBW), phase angle and segment values for arms, legs and trunk – with the
  normal range as attributes and backfilled history
- **Training**: workout count, last workout, workout plan, exercises in the last workout
- **Per machine** (eGym machines): one sensor per machine with the selected
  primary metric, **machine image**, trend & forecast, and all other values as
  attributes
- **Strength test per machine**: the fixed eGym test value (independent of the
  weight set on the machine) including progress/change – as attribute and as a
  selectable primary metric
- **Backfilled history**: machine values are imported as HA long-term
  statistics → full history graphs, also for the time before installation
- **Multiple people**: each account is its own entry with its own device set;
  device and entity names are prefixed per person
- **Write measurements back**: send weight, body fat, resting heart rate, blood
  pressure and VO2max to the account via services – with the real measurement
  time, e.g. from a scale in Home Assistant
- **Translated UI** in 18 languages (see below)

Only sensors for which your account actually provides data are created.
Updates every **30 minutes** (configurable in the options).

---

## Screenshots

> ⚠️ **Example views (mockups) with illustrative values** – not real
> measurements. They only show what the integration looks like in the UI.

| Login dialog | Device page with entities |
|---|---|
| ![Config flow (example)](images/config_flow.png) | ![Device page (example)](images/device.png) |

---

## Installation

### Via HACS (recommended)

1. Click the **"Open in HACS" button** above (or in HACS → *Custom
   repositories* → `Blogshot/homeassistant-selection-fitness`, category
   *Integration*).
2. Download *Selection Fitness* and **restart** Home Assistant.
3. **Settings → Devices & services → Add integration** → *Selection Fitness*.
4. Enter your **email** and **password**. The URL fields can usually stay at
   their defaults.

For a **second person**, simply add the integration again with the other
credentials – a separate device set is created.

### Manual

Copy the folder `custom_components/selection_fitness/` into your HA config
directory (`<config>/custom_components/selection_fitness/__init__.py`), restart,
then add it as above.

---

## Configuration: primary metric per machine

Under **Settings → Devices & services → Selection Fitness → Configure** you can
choose which metric the machine sensor shows as its **state**:

- **Weight lifted** (default)
- **Strength test** (fixed eGym test value, independent of the set weight)
- **Calories**
- **Activity points**
- **Repetitions**

The other values stay available as **attributes** on the sensor (`weight_kg`,
`reps`, `sets`, `calories`, `activity_points`, `strength_value`,
`strength_progress`, `strength_change_pct`, `strength_measured_at`, `trend`,
`trend_per_month`, `projected_next`, `last_trained`, `session_count`,
`training_method`, `source`, `exercise_code`). This way everyone can use the
value that matters to them as the main value – the weight lifted, the strength
test or the calories.

---

## Entities (selection)

Entity names follow the language of your Home Assistant instance. The examples
use English entity IDs.

**Body & BioAge:** `…_weight`, `…_height`, `…_gender`, `…_body_age`,
`…_muscle_age`, `…_cardio_age`, `…_flexibility_age`, `…_metabolic_age`,
`…_upper_body_age`, `…_core_age`, `…_lower_body_age`, `…_upper_body_balance`,
`…_body_fat`, `…_bmi`, `…_vo2max`, `…_resting_heart_rate`,
`…_blood_pressure_systolic`, …

**Body composition (scale):** `…_muscle_mass`, `…_body_fat_mass`,
`…_body_water`, `…_phase_angle`, `…_basal_metabolic_rate`, … – each with
`measured_at`, `source` and, if the scale provides it,
`normal_low`/`normal_high`. The ten segment values (fat/lean mass per arm, leg
and trunk) are created but disabled by default.

**Training:** `…_workout_count`, `…_last_workout`, `…_last_workout_plan`,
`…_exercises_in_last_workout`

**Per machine:** `…_<machine name>` (e.g. `…_egym_leg_press`) with the primary
metric, image, trend/forecast and all values as attributes, plus
`…_<machine name>_strength_test`.

Names are prefixed with the person's first name, so nothing collides with
multiple accounts.

---

## History, trend & forecast

- **History:** Home Assistant records every sensor from installation onward.
  In addition, **machine values are backfilled** as long-term statistics – the
  weight lifted from the workout history **and** the **strength test history**
  per machine (separate eGym endpoint). History graphs are filled right away.
- **Fitness age backfill:** body, muscle, cardio, metabolic and flexibility age
  are imported via the `bioage/history` endpoint back to the first measurement
  (often several years).
- **Body composition backfill:** all values from the body measurement log
  (e.g. every scan of the scale at the gym) are imported as long-term
  statistics.
- **Year-by-year queries:** the eGym server returns only one year per request
  (the app switches between years). The history is therefore fetched year by
  year and merged – stopping early after two empty years.
- **No duplicates:** statistics are unique per `(statistic_id, hour)`; the
  import is an upsert (it overwrites the same hourly bucket), so the 30-minute
  poll creates **no duplicates**.
- **Trend/forecast:** per machine, a linear regression over the latest sessions
  is computed (`trend`: rising/falling/stable, `trend_per_month` in unit/month,
  `projected_next` as a rough forecast of the next value).

---

## Sending measurements (services)

> ⚠️ Sent values are stored permanently in the Selection/eGym account and feed
> into the BioAge evaluation. The API offers **no way to delete measurements**
> – be especially careful with backdated values.

| Service | Fields |
|---|---|
| `selection_fitness.add_body_measurement` | `weight` (kg), `body_fat` (%), `height` (cm) |
| `selection_fitness.add_cardio_measurement` | `resting_heart_rate` (bpm), `systolic` + `diastolic` (mmHg), `vo2max` |

Both optionally accept `measured_at` (default: now) and `config_entry_id`
(only needed with several accounts). Without `height`, the height from the
profile is sent along; otherwise the server would add it on its own.

**Backdated body values:** the server takes every weight it receives as the
*current* profile weight – even if `measured_at` lies in the past.
`add_body_measurement` therefore rejects values older than the newest known
measurement. With `force_backdate: true` they are sent anyway; afterwards a
notification appears and the current weight has to be entered again. Cardio
values are not affected.
In the app, the values show up with the source "Home Assistant / HealthConnect".

Example automation for a scale:

```yaml
triggers:
  - trigger: state
    entity_id: sensor.scale_weight
conditions:
  - condition: template
    value_template: "{{ trigger.to_state.state | is_number }}"
actions:
  - action: selection_fitness.add_body_measurement
    data:
      weight: "{{ trigger.to_state.state | float }}"
      measured_at: "{{ trigger.to_state.last_changed }}"
```

---

## Languages

The UI (setup, options, entity and device names, units, services and error
messages) is translated into English, German, Spanish, French, Italian, Dutch,
Polish, Portuguese (Portugal and Brazil), Russian, Ukrainian, Turkish, Chinese
(Simplified and Traditional), Japanese, Korean, Arabic and Hindi. Home Assistant
uses the language of your instance; other languages fall back to English.

Machine and exercise names come from the eGym API, which is queried in the
language of your instance as well.

---

## How it works (reverse engineering)

Analysis of the APK (v1.7, build 119).

### Auth
- **Login:** `POST https://selectionfitness.netpulse.com/np/exerciser/login`,
  **form-urlencoded** with `username=<email>&password=<password>`.
  (The field name is `username`, not `login`; the body is form-encoded, not JSON.)
- The response contains the `uuid` and sets `Set-Cookie: JSESSIONID=…`.
- **Authorization** of all further requests = this `Cookie: JSESSIONID=…`.
  No API key, no secret, no Play Integrity check.

### Required headers
```
X-NP-User-Agent: clientType=MOBILE_DEVICE; devicePlatform=ANDROID; deviceUid=<uuid>; applicationName=SelectionFitness; applicationVersion=1.7; applicationVersionCode=119
X-NP-API-Version: 1.5
X-NP-APP-Version: 119
```

### Endpoints
Main host `https://selectionfitness.netpulse.com`:
- `GET /np/exerciser/{uuid}/profile` – profile (incl. weight, height, gender …)
- `GET /workouts/api/workouts/v2.3/exercisers/{uuid}/workouts?completedAfter=…&completedBefore=…&languageCode=en`
  – full training history (`{workouts:[{completedAt, workoutPlanLabel,
  exercises:[{name, exerciseCode, source, attributes:{calories, activity_points,
  sets_of_…:[{reps,weight}]}}]}]}`)

eGym mobile API host `https://mobile-api.int.api.egym.com`:
- `GET /analysis/api/v1.0/exercisers/{uuid}/bioage?types=strength,cardio,metabolic,flexibility&languageCode=en`
  – BioAge summary (`totalDetails`, `muscleDetails`, `cardioDetails`,
  `flexDetails`, `metabolicDetails`, each with `{value}` entries)
- `GET /measurements/api/v1.0/exercisers/{uuid}/body-measurements?startDate=…&endDate=…`
  – body measurement log (manual entries, gym scale, Health Connect), one year
  per request

App date format: `yyyy-MM-dd'T'HH:mm:ss.SSSZZZZZ` (numeric offset).

### Writing (the app's Health Connect sync)
- `POST {mobile}/connected-app-measurements/api/v1.0/exerciser/{uuid}/bmi`
  – JSON `{appName:"healthConnect", originalSource, timezone, completedAt,
  weight(kg), height(cm), bodyFat(%)}`, empty fields are omitted
- `POST {mobile}/connected-app-measurements/api/v1.0/exerciser/{uuid}/cardio`
  – likewise with `bpm`, `systolic`, `diastolic`, `vo2max`
- `completedAt` in the format `yyyy-MM-dd'T'HH:mm:ss.SSSSSS` without offset.
  The app formats it in UTC, but the server interprets it as **local time** of
  the time zone in `timezone` – so the integration sends local time.
- Response `200` with an empty body; measurements have no ID, and the app has
  no delete endpoint for measurements.

---

## Known limitations

- **Check-ins / gym visits:** return `Membership not found` if the account has
  no membership record on the server – the corresponding sensors are then not
  created. This is on the account/brand side and cannot be solved by the
  integration.
- **Positive/negative movement weight:** eGym training methods (`regular`,
  `negative`, `isokinetic`, `adaptive`, `explonic`) can mean different weights
  for the positive/negative phase per training week. The API provides one
  `weight` per set; the `training_method` field is passed along as an attribute
  if present. A separate positive/negative evaluation is planned.
- **Strength test vs. weight lifted:** the primary metric can be chosen freely
  (see above), as depending on the user the weight lifted, the calories or the
  strength test is more relevant.

---

## Notes

- Read-only except for the services above – data is only written when you call
  a service.
- Session cookies expire on the server; the integration signs in again
  automatically on `401`.
- Intended for your own account only.
