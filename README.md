# Selection Fitness → Home Assistant

Eine Custom-Integration, die deine Körperdaten und Trainingsdaten aus der
**Selection Fitness** App (Netpulse / eGym White-Label,
`com.netpulse.mobile.selectionfitness`) direkt als Entities in Home Assistant
abbildet – ohne MQTT, mit Config-Flow (Login in der UI).

Die Integration ruft dieselbe Backend-API auf, die auch die App nutzt
(„App-Impersonation"): Sie meldet sich mit deinen Zugangsdaten an und liest
**deine eigenen** Daten. Es werden keine Schutzmechanismen umgangen.

[![Open your Home Assistant instance and open this repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Blogshot&repository=homeassistant-selection-fitness&category=integration)

> Ein Klick auf den Button oben öffnet dieses Repository direkt in HACS auf
> deiner Home-Assistant-Instanz.

---

## Screenshots

> ⚠️ **Beispielansichten (Mockups) mit illustrativen Werten** – keine echten
> Messdaten und kein Funktionsnachweis. Sie zeigen nur, wie die Integration in
> der Home-Assistant-Oberfläche aussieht.

| Login-Dialog | Geräteseite mit Entities |
|---|---|
| ![Config-Flow (Beispiel)](images/config_flow.png) | ![Geräteseite (Beispiel)](images/device.png) |

---

## 1. Installation

### Variante A – über HACS (empfohlen)

1. Auf den **„Open in HACS"-Button** oben klicken (oder in HACS →
   *Benutzerdefinierte Repositories* → `https://github.com/Blogshot/homeassistant-selection-fitness`
   als Kategorie *Integration* hinzufügen).
2. *Selection Fitness* in HACS herunterladen.
3. Home Assistant **neu starten**.
4. Weiter mit Schritt 3 der manuellen Variante (Integration hinzufügen).

### Variante B – manuell

1. Kopiere den Ordner `custom_components/selection_fitness/` in dein
   Home-Assistant-Konfigurationsverzeichnis, sodass folgender Pfad existiert:

   ```
   <config>/custom_components/selection_fitness/__init__.py
   ```

   (z. B. per Samba/SSH-Add-on, oder als ZIP entpacken.)

2. Home Assistant **neu starten**.

3. **Einstellungen → Geräte & Dienste → Integration hinzufügen** →
   nach *„Selection Fitness"* suchen.

4. **E-Mail** und **Passwort** deines Selection-Fitness-Accounts eingeben.
   Die beiden URL-Felder kannst du in der Regel auf den Vorgaben lassen
   (siehe Abschnitt 4 zur Mobile-API-URL).

Danach erscheint ein Gerät **„Selection Fitness"** mit allen verfügbaren
Sensoren. Es werden nur die Sensoren angelegt, für die dein Account auch
Daten liefert.

---

## 2. Entities

| Entity | Quelle |
|---|---|
| `sensor.selection_fitness_gewicht` | Körpermessung (Gewicht) |
| `sensor.selection_fitness_korperfett` | Körpermessung (Körperfett %) |
| `sensor.selection_fitness_bmi` | Körpermessung (BMI) |
| `sensor.selection_fitness_muskelmasse` | Körpermessung |
| `sensor.selection_fitness_magermasse` | Körpermessung |
| `sensor.selection_fitness_viszeralfett` | Körpermessung |
| `sensor.selection_fitness_grundumsatz` | Körpermessung (kcal) |
| `sensor.selection_fitness_korpergrosse` | Körpermessung |
| `sensor.selection_fitness_taillenumfang` | Körpermessung |
| `sensor.selection_fitness_huftumfang` | Körpermessung |
| `sensor.selection_fitness_vo2max` | Cardio-Messung |
| `sensor.selection_fitness_ruhepuls` | Cardio-Messung |
| `sensor.selection_fitness_blutdruck_systolisch` | Cardio-Messung |
| `sensor.selection_fitness_blutdruck_diastolisch` | Cardio-Messung |
| `sensor.selection_fitness_anzahl_workouts` | Workout-Historie |
| `sensor.selection_fitness_anzahl_check_ins` | Check-in-Historie |
| `sensor.selection_fitness_letzter_check_in` | letzter Studio-Besuch (Zeitstempel) |
| `sensor.selection_fitness_letztes_studio` | Studioname des letzten Check-ins |
| `sensor.selection_fitness_mitgliedschaft` | Mitgliedschaftstyp |
| `sensor.selection_fitness_heimatstudio` | Heimatstudio |

Körpermesswerte tragen zusätzlich die Attribute `measured_at` (Messzeitpunkt)
und `source` (Messgerät/Quelle, z. B. eine InBody-Waage).

Aktualisierung: alle **30 Minuten** (die App-Daten ändern sich selten
häufiger; der Wert ist in `const.py` → `DEFAULT_SCAN_INTERVAL` anpassbar).

---

## 3. Wie es funktioniert (Reverse Engineering)

Ergebnis der Analyse der APK (Version 1.7, Build 119):

### Auth
- **Login:** `POST https://selectionfitness.netpulse.com/np/exerciser/login`
  mit JSON-Body `{"login": "<email>", "password": "<passwort>"}`.
- Antwort: JSON mit u. a. `uuid`, `verified`, `homeClubChainName`,
  `homeClubUuid`, `membershipType`, `barcode` – und setzt einen
  `Set-Cookie: JSESSIONID=…`.
- **Autorisierung** aller weiteren Requests = genau dieser
  `Cookie: JSESSIONID=…`. **Kein** API-Key, kein Client-Secret, kein
  Basic-Auth, keine Play-Integrity-Prüfung auf den Datenendpunkten.

### Pflicht-Header (aus `HeadersInterceptor`)
```
X-NP-User-Agent: clientType=MOBILE_DEVICE; devicePlatform=ANDROID; deviceUid=<uuid>; applicationName=SelectionFitness; applicationVersion=1.7; applicationVersionCode=119
X-NP-API-Version: 1.5
X-NP-APP-Version: 119
Accept: application/json
```

### Endpunkte
Auf dem Haupt-Backend `https://selectionfitness.netpulse.com`:
- `GET /np/exerciser/{uuid}/profile` – vollständiges Profil
- `GET /np/exercisers/{uuid}/latest-check-in` – letzter Besuch
  (`{checkInDate, gymLocationName, gymLocationAddress, …}`)
- `GET /np/exercisers/{uuid}/check-ins/history?endDate=YYYY-MM-DD` – Liste der Besuche
- `GET /np/exerciser/{uuid}/workouts` – Trainings-Historie

Auf dem eGym-Mobile-API-Host (für Körpermesswerte):
- `GET /measurements/api/v1.1/exercisers/{uuid}/body/latest-metrics?types=weight,bodyFat,BMI,…`
- `GET /measurements/api/v1.1/exercisers/{uuid}/cardio/latest-metrics?types=vo2Max,restingHeartRate,systolic,diastolic`
- Response je Metrik: `{type, value, createdAt, source, sourceLabel, valueInterpretation}`

Der `{uuid}`-Pfadbaustein wird mit der beim Login erhaltenen User-UUID gefüllt.

---

## 4. Wichtiger Hinweis zur Mobile-API-URL (Körpermesswerte)

Profil, Check-ins und Workouts liegen auf `selectionfitness.netpulse.com` –
dieser Host ist aus den App-Ressourcen **gesichert** korrekt.

Die **Körpermesswerte** (Gewicht, KFA, BMI …) laufen über einen separaten
eGym-Host. Die App-Ressource nennt dafür einen Integrations-/Staging-Host
(`mobile-api.int.api.egym.com`); die App ermittelt den echten Produktionshost
zur Laufzeit aus einer Branding-Konfiguration. Als Default ist deshalb
`https://mobile-api.api.egym.com` hinterlegt – das ist eine fundierte
Annahme, aber nicht 100 % sicher.

**Wenn die Körpermesswert-Sensoren nicht erscheinen**, der Rest aber
funktioniert, stimmt vermutlich nur dieser eine Host nicht. So findest du den
richtigen Wert:

- Mit einem HTTPS-Proxy (z. B. **HTTP Toolkit** oder **mitmproxy**) auf dem
  Handy einmal in der App auf den Analyse-/Messwerte-Bildschirm gehen und den
  Host der `…/measurements/api/…`-Anfrage ablesen, **oder**
- den Wert aus der Branding-Config lesen.

Dann die Integration entfernen und mit der korrigierten *Mobile-API-URL* neu
hinzufügen (das Feld steht direkt im Login-Dialog).

Schlägt dieser Host fehl, bricht die Integration **nicht** ab – alle übrigen
Sensoren bleiben verfügbar.

---

## 5. Hinweise

- Rein lesend: Die Integration schreibt nichts zurück ins Selection-Konto.
- Bei falschen Zugangsdaten meldet der Dialog „E-Mail oder Passwort ungültig".
- Session-Cookies laufen serverseitig ab; die Integration meldet sich bei
  einem `401` automatisch neu an.
- Nur für deinen eigenen Account gedacht.
