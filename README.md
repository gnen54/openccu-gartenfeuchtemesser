# OpenCCU Gartenfeuchtemesser

Misst die **Bodenfeuchte im Garten** mit einem **Capacitive Soil Moisture Sensor v1.2** und
meldet sie an die **OpenCCU**. Dort dient sie als **Anzeiger für die bestehende automatische
Gartenbewässerung**: Ist der Boden feucht genug, fällt das Gießen aus. Alle Werte
erscheinen auch in **Pocket Control HM** (iOS).

- **Raspberry Pi Pico 2 W / Pico W** (empfohlen) – MicroPython, mit Webseite zum
  Kalibrieren, Siri-Abfrage und Akku-Wächter für den Betrieb an einer Powerbank.
- **Raspberry Pi 3** (Alternative) – Python 3, mit A/D-Wandler ADS1115.
- **Keine Zusatzsoftware in der OpenCCU** (keine XML-API, kein CUxD): Der Messer setzt die
  Systemvariablen direkt über die „Remote Homematic-Script API“.
- **Sicher bei Störungen:** Im Zweifel meldet der Messer „nicht feucht“, und ein
  Wächter-Programm in der OpenCCU setzt die Freigabe zurück, wenn der Messer schweigt.
  Es wird dann gegossen wie ohne Messer – vertrocknen kann nichts.

Das Programm für den Pico baut auf `main.py` und `akku.py` der Projekte
[Rolltor](https://github.com/gnen54/rolltor) und Startampel auf (gleicher Webserver,
gleiche WLAN-Logik, gleicher Akku-Wächter).

## So funktioniert's

```
Sensor ──► Pico W ──WLAN──► OpenCCU
              │                 │
              │  alle 5 min     ├─ Gartenfeuchte        42.0 %
              │                 ├─ Garten_feucht        nein
              │                 ├─ Gartenfeuchte_Stand  01.11. 05:10
              │                 └─ Gartenfeuchte_Akku   87 %
              │                          │
   http://gartenfeuchte.local            ▼
   (Kalibrieren, Verlauf)       Bewässerungsprogramm:
                                „… UND Garten_feucht = nein“
```

| Systemvariable | Typ | Bedeutung |
|---|---|---|
| `Gartenfeuchte` | Zahl, 0–100 % | Bodenfeuchte (0 = Sensor an der Luft, 100 = im Wasser) |
| `Garten_feucht` | Logikwert | **ja** = Boden feucht genug → Bewässerung aussetzen |
| `Gartenfeuchte_Stand` | Zeichenkette | Uhrzeit der letzten Meldung (aus der Uhr der OpenCCU) |
| `Gartenfeuchte_Akku` | Zahl, 0–100 % | Powerbank des Pico (optional) |

`Garten_feucht` schaltet mit **Hysterese**: Es wird **ja** ab 45 % und erst unter 35 %
wieder **nein** (beides auf der Webseite einstellbar). So springt der Wert nicht bei jeder
Messung hin und her, wenn die Feuchte gerade um eine Grenze schwankt.

## Teile

- **Raspberry Pi Pico 2 WH** (oder Pico 2 W, Pico W/WH). Wichtig ist das **W** (WLAN).
- **Capacitive Soil Moisture Sensor v1.2** mit 3-poligem Kabel (VCC, GND, AOUT)
- Stromversorgung: USB-Netzteil **oder** Powerbank (Akku-Wächter zählt mit)
- Wetterfestes Gehäuse: **zum Selberdrucken im Ordner [`gehaeuse/`](gehaeuse/)** – mit
  Akkuschacht für 4 × AA, Dichtnut für eine 3-mm-Rundschnur, Befestigungslaschen und
  Kabelverschraubung PG7 (Einkaufsliste und Druckhinweise dort). Alternativ eine
  Abzweigdose IP65 mit Kabelverschraubung.

Für die **Raspberry-Pi-3-Variante** stattdessen: Raspberry Pi 3 + **ADS1115**-Modul (I2C).

## Verdrahtung Pico

| Sensor | Pico GPIO | Pico Pin |
|---|---|---|
| VCC  | **GP22** (schaltet den Sensor nur zum Messen ein) | 29 |
| GND  | GND | 38 |
| AOUT | **GP26** (ADC0) | 31 |

Der Pico schaltet den Sensor nur für die Messung ein (2 s Aufwärmen, dann 15 Proben).
Das spart Strom und schont den Sensor. Soll er dauernd an sein, VCC an **3V3 (Pin 36)**
und in `main.py` `SENSOR_STROM_PIN = None` setzen.

## Den Sensor vorbereiten (wichtig!)

1. **Chip prüfen:** Auf dem Sensor sitzt ein kleiner 8-beiniger Chip. Steht **TLC555**
   (oder „555C“) drauf, ist alles gut. Bei manchen billigen v1.2-Sensoren sitzt ein
   **NE555** – der braucht 5 V und **schwingt bei 3,3 V nicht**: Der Messwert ändert sich
   dann nicht, egal ob trocken oder nass. Abhilfe: anderen Sensor nehmen oder VCC an
   **VBUS (5 V, Pin 40)** und AOUT über einen Spannungsteiler (10 kΩ / 20 kΩ) an GP26,
   damit nie mehr als 3,3 V am Pico ankommen. Dann neu kalibrieren.
2. **Elektronik abdichten:** Die obere Hälfte (Bauteile) und vor allem die **Schnittkanten
   der Platine** saugen sonst Wasser. Mit Schrumpfschlauch, Nagellack oder Gießharz
   versiegeln. In den Boden nur **bis zur weißen Linie** stecken.
3. **Kabel kurz halten:** Das Signal ist analog. Bis ca. 2 m Kabel geht gut – lieber den
   Pico im Gehäuse nahe ans Beet setzen.

## OpenCCU einrichten

### 1. Remote Homematic-Script API freigeben

**Einstellungen → Systemsteuerung → Firewall konfigurieren**

- „Remote Homematic-Script API“ auf **Eingeschränkt** stellen,
- bei „IP-Adressen für den eingeschränkten Zugriff“ die Adresse des Messers eintragen
  (am besten eine feste IP, siehe unten) – oder das ganze Heimnetz, z. B. `192.168.1.0/24`.

Ist unter **Einstellungen → Systemsteuerung → Sicherheit** die **Authentifizierung**
eingeschaltet, einen eigenen Benutzer anlegen und in `main.py` bei `CCU_BENUTZER` /
`CCU_PASSWORT` eintragen.

### 2. Systemvariablen anlegen

**Automatisch:** **Programme und Verknüpfungen → Programme & Zentralenverknüpfung →
Skript testen**, den Inhalt von [`openccu/variablen_anlegen.hms`](openccu/variablen_anlegen.hms)
einfügen, **Ausführen**. Ausgabe: „Angelegt: Gartenfeuchte Garten_feucht …“.

**Von Hand:** **Einstellungen → Systemvariablen → Neu**

| Name | Variablentyp | Werte |
|---|---|---|
| `Gartenfeuchte` | Zahl | Min 0, Max 100, Maßeinheit `%` |
| `Garten_feucht` | Logikwert | wahr = `ja`, falsch = `nein` |
| `Gartenfeuchte_Stand` | Zeichenkette | – |
| `Gartenfeuchte_Akku` | Zahl | Min 0, Max 100, Maßeinheit `%` (nur mit Powerbank) |

Die Namen müssen **genau** so lauten (oder in `main.py` bei `CCU_VAR_…` anpassen).
Fehlt eine Variable, zeigt die Webseite des Messers „Systemvariable fehlt in der OpenCCU: …“.

### 3. Wächter-Programm (Sicherheitsnetz)

Fällt der Messer aus, bliebe `Garten_feucht` auf dem letzten Wert stehen. Darum:

**Programme → Neu**, Name „Gartenfeuchte Wächter“

- **Bedingung: Wenn…** → *Systemzustand* → `CCU_im_Reboot` → **bei ist falsch** →
  **nur prüfen** (sonst wirkt der Zeitstempel direkt nach einem Neustart veraltet)
- **UND** → *Zeitsteuerung* → Zeitmodul: Zeitspanne **ganztägig**, Haken bei
  **Zeitintervall** mit 0 Stunden 30 Minuten, Serienmuster **täglich, jeden Tag**,
  kein Enddatum
- **Aktivität: Dann…** → *Skript* → Inhalt von [`openccu/waechter.hms`](openccu/waechter.hms)

Kommt 2 Stunden lang keine Meldung, setzt es `Garten_feucht` auf **nein** und schreibt
„keine Meldung seit … min“ in `Gartenfeuchte_Stand`.

### 4. In die bestehende Bewässerung einbauen

Im vorhandenen Bewässerungsprogramm (z. B. „Wenn Zeitsteuerung 6:00 Uhr … Dann Ventil
an für 20 min“) eine Bedingung **mit UND** ergänzen:

- **UND** → *Systemzustand* → `Garten_feucht` → **bei nein** → **nur prüfen**

Bedeutung: Um 6:00 Uhr wird geprüft, ob der Boden zu trocken ist – nur dann läuft die
Bewässerung. Die Zeitsteuerung bleibt der Auslöser („bei Erreichen“/„auslösen“), die
Feuchte wird nur geprüft. Ansonsten bleibt das Programm, wie es ist.

**Mehrere Bereiche:** Gibt es getrennte Programme je Bereich (z. B. ein Multiprogramm,
das die Uhrzeiten prüft und Trigger-Variablen setzt, und je ein Programm für Garten und
Vorgarten), gehört die Bedingung nur in das Programm des Bereichs, in dem der Sensor
steckt. Beispiel:

| Programm | Rolle | Feuchte-Bedingung |
|---|---|---|
| `BewässerungMulti` | prüft jede Minute Freigabe, Regenmenge und Uhrzeiten | – |
| `BewässerungGA` (Garten, Ventil 1) | gießt, wenn „Ventil 1 Trigger“ = bewässern | **UND `Garten_feucht` bei nein, nur prüfen** |
| `BewässerungVG` (Vorgarten) | gießt den Vorgarten | – (erst mit eigenem Sensor) |

Für einen zweiten Bereich einfach einen zweiten Pico mit Sensor aufbauen und in dessen
`main.py` andere Variablennamen eintragen (z. B. `Vorgarten_feucht`).

Tipp: Mit `Gartenfeuchte` lassen sich auch feinere Regeln bauen, z. B. zwei Programme –
unter 20 % 30 min gießen, zwischen 20 % und 35 % nur 10 min.

### 5. Anzeige in Pocket Control HM (iOS)

Pocket Control HM liest die Systemvariablen direkt aus der OpenCCU, im Messer ist dafür
nichts einzustellen. Nach dem Anlegen der Variablen:

1. In der App die **Konfiguration der Zentrale neu laden** (bzw. neu synchronisieren),
   damit die neuen Variablen erscheinen.
2. Eine **eigene Ansicht „Garten“** anlegen und dort zusammenstellen:
   `Gartenfeuchte`, `Garten_feucht`, `Gartenfeuchte_Stand`, `Gartenfeuchte_Akku`,
   dazu das Bewässerungsventil und das Bewässerungsprogramm.
3. Unterwegs geht das wie gewohnt über die VPN-Verbindung der App. Der Messer selbst
   spricht nur im Heimnetz mit der OpenCCU, für den Fernzugriff ändert sich nichts.

Gut zu wissen:

- `Garten_feucht` lässt sich in der App zwar von Hand umschalten, der Messer überschreibt
  den Wert aber bei der nächsten Meldung (spätestens nach 5 min). Um die Bewässerung von
  Hand auszusetzen (z. B. nach Rasendüngen), besser das Bewässerungsprogramm in der App
  vorübergehend **deaktivieren**.
- Zeigt `Gartenfeuchte_Stand` „keine Meldung seit … min“ oder „Sensorfehler …“, sieht man
  das in der App sofort, ohne die Webseite des Messers aufzurufen.

## Pico einrichten

1. **MicroPython** aufspielen: auf micropython.org die `.uf2` für **genau dein Modell**
   („Raspberry Pi Pico 2 W“ bzw. „Raspberry Pi Pico W“). BOOTSEL halten, Pico per USB
   anstecken (Datenkabel!), die Datei auf das neue Laufwerk ziehen.
2. In `pico/main.py` oben eintragen:
   ```python
   HEIM_WLAN_NAME = "MeinWLAN"
   HEIM_WLAN_PASSWORT = "geheim"
   HEIM_FESTE_IP = "192.168.1.60"     # eine freie Adresse, für die Firewall der OpenCCU
   CCU_IP = "192.168.1.10"         # Adresse deiner OpenCCU
   ```
   Die Adressen sind Beispiele – trag die aus deinem Heimnetz ein.
3. Mit **Thonny** diese Dateien aus `pico/` auf den Pico speichern:
   `main.py`, `ccu.py`, `seite.html`, `akku.py`, `akku.html`.
   Ohne Powerbank: `AKKU_BENUTZEN = False` (die beiden Akku-Dateien können dann weg).

   **Beim Herunterladen von GitHub:** In der Dateiansicht auf **„Raw“** gehen (oder den
   Download-Knopf daneben) und erst dann speichern – sonst landet die ganze GitHub-Webseite
   in der Datei, und der Pico startet nicht.
4. Pico neu starten. Die **Onboard-LED leuchtet**, wenn das Heim-WLAN verbunden ist
   (blinkt schnell = WLAN gerade weg, blinkt langsam = eigenes WLAN). In Thonny steht
   alle 5 min eine Zeile wie `Feuchte: 1830 mV = 55 % -> feucht` und `OpenCCU: gemeldet`.
5. Im Browser **http://gartenfeuchte.local** öffnen (oder die Zahlen-Adresse).

Ist das Heim-WLAN beim Start nicht erreichbar, macht der Pico ein **eigenes WLAN
„Gartenfeuchte“** auf (Passwort `gartenfeuchte`, Seite unter http://192.168.4.1) –
praktisch zum Kalibrieren, aber dann ohne OpenCCU.

## Kalibrieren

Auf der Seite unter **Kalibrieren**:

1. Sensor abtrocknen, an die Luft halten → **Jetzt trocken** (typisch 2400–2800 mV).
2. **Nass:** Den Sensor in einen Blumentopf mit Erde stecken, **kräftig durchgießen**,
   ein, zwei Minuten warten → **Jetzt nass**. Das passt besser zum Garten als ein Glas
   Wasser: Bei manchen Sensoren liegt der Wert im Wasserglas kaum unter dem Trockenwert
   (beim Erstaufbau z. B. 2836 mV trocken, 2302 mV im Glas, 1780 mV in nasser Erde). Dann
   landet schon leicht feuchte Erde fast bei 100 %.

Danach in den Boden stecken. Ein paar Tage beobachten und bei Bedarf die
**Schaltschwellen** anpassen: Wie viel % zeigt der Messer direkt nach dem Gießen, wie viel
wenn die Pflanzen schlapp werden? Die Schwellen liegen sinnvoll dazwischen.

Die Kurve zeigt die letzten 24 Stunden (seit dem letzten Neustart).

## Siri (iPhone, Kurzbefehle-App)

1. **Kurzbefehle** → **+** → Aktion **„Inhalte von URL abrufen“**:
   `http://gartenfeuchte.local/feuchte`
2. Aktion **„Text sprechen“** dahinter.
3. Benennen: **„Wie feucht ist der Garten“**.

Antwort z. B.: „Gartenfeuchte 42 Prozent, trocken, es wird gegossen.“

| Adresse | Wirkung |
|---|---|
| `/feuchte` | Text zum Vorlesen |
| `/status` | alle Werte als JSON |
| `/messen` | sofort messen und an die OpenCCU melden |
| `/ccu/senden` | letzten Wert sofort an die OpenCCU melden |
| `/akku`, `/akku/rest`, `/akku/geladen` | Akku-Wächter (wie beim Rolltor) |

Ist in `main.py` eine `WEB_PIN` gesetzt, brauchen Einstellungen und `/messen` die PIN
(`?pin=1234` anhängen); `/feuchte` und `/status` gehen ohne.

## Akku / Powerbank

Wie beim Rolltor: **http://gartenfeuchte.local/akku** zeigt die geschätzte Restlaufzeit,
schickt per **ntfy** eine Push-Nachricht „Akku laden“ und hat einen **Testlauf** zum
Einmessen der Powerbank. Der Pico W braucht mit dauerhaft verbundenem WLAN etwa
40–50 mA, eine 10 000-mAh-Powerbank hält damit grob eine Woche. Zusätzlich landet der
Akkustand in der OpenCCU (`Gartenfeuchte_Akku`) – damit kann auch die OpenCCU warnen.

Für den Dauerbetrieb im Garten ist ein **USB-Netzteil** (z. B. über eine Außensteckdose)
bequemer; dann `AKKU_BENUTZEN = False`.

## Variante Raspberry Pi 3

Der Pi hat keinen Analogeingang, darum der **ADS1115**:

| ADS1115 | Raspberry Pi 3 |
|---|---|
| VDD  | 3,3 V (Pin 1) |
| GND  | GND (Pin 6) |
| SDA  | GPIO 2 / SDA (Pin 3) |
| SCL  | GPIO 3 / SCL (Pin 5) |
| ADDR | GND (→ Adresse 0x48) |
| A0   | Sensor AOUT |

Sensor VCC an 3,3 V (Pin 17), GND an GND (Pin 9).

```bash
sudo raspi-config                      # Interface Options → I2C → aktivieren
sudo apt install python3-smbus2 i2c-tools git
i2cdetect -y 1                         # muss 48 zeigen
git clone https://github.com/gnen54/openccu-gartenfeuchtemesser.git
cd openccu-gartenfeuchtemesser/raspi
nano gartenfeuchte.py                  # CCU_IP usw. prüfen
python3 gartenfeuchte.py --kalibrieren trocken   # Sensor an der Luft
python3 gartenfeuchte.py --kalibrieren nass      # Sensor im Wasser
python3 gartenfeuchte.py --senden                # Probe: einmal an die OpenCCU
sudo cp gartenfeuchte.service /etc/systemd/system/
sudo systemctl enable --now gartenfeuchte
```

Status: `http://<raspi>:8080/` (JSON), Siri-Text: `http://<raspi>:8080/feuchte`.
Ausgaben: `journalctl -u gartenfeuchte -f`.

## Fehlersuche

| Anzeige | Ursache / Abhilfe |
|---|---|
| „OpenCCU nicht erreichbar“ | IP falsch, OpenCCU aus, oder Firewall blockt Port 8181 → Schritt 1 |
| „OpenCCU lehnt ab“ / HTTP 403 | Messer-IP nicht bei „eingeschränkter Zugriff“ eingetragen |
| „OpenCCU verlangt Anmeldung“ | Authentifizierung an → `CCU_BENUTZER` / `CCU_PASSWORT` |
| „Systemvariable fehlt …“ | Variable nicht (oder anders geschrieben) angelegt → Schritt 2 |
| „Sensorfehler (… mV)“ | Kabel ab, Kurzschluss oder falscher Pin |
| Wert ändert sich nie | NE555 auf dem Sensor (siehe „Den Sensor vorbereiten“) |
| Werte springen stark | Kabel zu lang, Elektronik nass geworden, Sensor zu locker im Boden |

## Dateien

```
pico/main.py        Hauptprogramm Pico W (Messen, Webseite, OpenCCU)
pico/ccu.py         OpenCCU-Anbindung (auch von der Raspi-Variante benutzt)
pico/seite.html     Webseite: Anzeige, Verlauf, Kalibrieren, Schwellen
pico/akku.py        Akku-Wächter (gleich wie Rolltor/Startampel)
pico/akku.html      Akkuseite
raspi/gartenfeuchte.py        Variante Raspberry Pi 3 + ADS1115
raspi/gartenfeuchte.service   systemd-Dienst
openccu/variablen_anlegen.hms Systemvariablen per Skript anlegen
openccu/waechter.hms          Wächter-Programm (Sicherheitsnetz)
gehaeuse/                     3D-Druck-Gehäuse (STL, OpenSCAD, Einkaufsliste)
```

## Lizenz

MIT – siehe [LICENSE](LICENSE). Nachbauen ausdrücklich erwünscht.
