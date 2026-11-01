# OpenCCU Gartenfeuchtemesser - Raspberry Pi Pico 2 W / Pico W (MicroPython)
#
# Misst die Bodenfeuchte mit einem "Capacitive Soil Moisture Sensor v1.2" und meldet sie
# an die OpenCCU. Dort dient sie als Anzeiger fuer die bestehende Gartenbewaesserung:
#   - Systemvariable "Gartenfeuchte"        (Zahl, 0-100 %)
#   - Systemvariable "Garten_feucht"        (Logikwert: wahr = Boden feucht genug)
#   - Systemvariable "Gartenfeuchte_Stand"  (Zeichenkette: Uhrzeit der letzten Meldung)
#   - optional "Gartenfeuchte_Akku"         (Zahl, % Powerbank)
# Das Bewaesserungsprogramm bekommt die Bedingung "Garten_feucht = nein" dazu - ist der
# Boden feucht genug, faellt die Bewaesserung aus. Siehe README.md.
#
# SICHER BEI STOERUNGEN: Im Zweifel meldet der Messer "nicht feucht" (= es wird gegossen),
# z. B. bei Sensorfehler. Faellt der Messer ganz aus, setzt das Waechter-Programm in der
# OpenCCU "Garten_feucht" nach 2 h ohne Meldung zurueck (openccu/waechter.hms).
#
# Auf den Pico kopieren: diese Datei als main.py, dazu ccu.py, seite.html, akku.py, akku.html.
#   - Bedienung im Browser: http://gartenfeuchte.local (Heim-WLAN)
#   - Kalibrieren auf der Seite: Sensor an der Luft -> "trocken", im Wasserglas -> "nass"
#   - Siri: Kurzbefehl ruft http://gartenfeuchte.local/feuchte auf -> Antwort zum Vorlesen
#   - Akku: http://gartenfeuchte.local/akku (Akku-Waechter mit Push, wie beim Rolltor)
#
# SPARMODUS fuer Akkubetrieb (wie bei der LED-Uhr): das WLAN ist nur in einem Fenster zu jeder
# vollen Stunde an (hh:00 bis hh:05, und nach dem Einschalten) - dann ist die Webseite
# erreichbar, die Uhr wird gestellt und eine wartende Push-Nachricht geht raus. Auf der
# Seite laesst sich das Fenster per Knopf um 30 min verlaengern (z. B. zum Kalibrieren).
# Ausserhalb der Fenster misst der Pico alle 15 min, schaltet das WLAN nur fuer die Meldung
# an die OpenCCU kurz ein (wenige Sekunden) und schlaeft dazwischen (machine.lightsleep).

import json
import os
import select
import socket
import time
import machine
from machine import ADC, Pin

import ccu

try:
    import akku                  # Akku-Waechter (Push "Akku laden"), siehe akku.py
except ImportError:
    akku = None

try:
    import network
except ImportError:          # Pico ohne W: keine Verbindung zur OpenCCU moeglich
    network = None

# ============================================================================
# KONFIGURATION
# ============================================================================

# Sensor. AOUT an GP26 (ADC0, Pin 31). VCC an SENSOR_STROM_PIN: der Pico schaltet den Sensor
# nur zum Messen ein (spart Strom, der Sensor altert langsamer). None = VCC fest an 3V3 (Pin 36).
SENSOR_ADC_PIN = 26
SENSOR_STROM_PIN = 22        # GP22 = Pin 29
AUFWAERMEN_MS = 2000         # so lange nach dem Einschalten warten (Ausgang muss sich einpendeln)
PROBEN = 15                  # je Messung so viele Proben, davon der Median
MESSEN_ALLE_S = 300          # alle 5 min messen und an die OpenCCU melden (ohne Sparmodus)

# Kalibrierung (Spannung in mV). Hoehere Spannung = trockener. Diese Werte sind nur der
# Anfang - auf der Seite mit "Jetzt trocken" / "Jetzt nass" einmessen, das wird gespeichert.
TROCKEN_MV = 2600            # Sensor an der Luft
NASS_MV = 1200               # Sensor bis zur Linie im Wasser
# Schaltschwellen mit Hysterese (verhindert Flattern um eine Grenze):
FEUCHT_AB = 45               # ab so viel % gilt der Boden als feucht  -> Garten_feucht = wahr
TROCKEN_UNTER = 35           # unter so viel % wieder trocken          -> Garten_feucht = falsch
# Messwerte ausserhalb dieses Bereichs = Sensor ab / Kabel kaputt -> Sensorfehler
FEHLER_UNTER_MV = 150
FEHLER_UEBER_MV = 3200

# OpenCCU
CCU_IP = "192.168.1.10"           # Beispiel - Adresse deiner OpenCCU eintragen
CCU_PORT = 8181              # 8181 = Remote Homematic-Script API (48181 mit CCU_HTTPS = True)
CCU_HTTPS = False
CCU_BENUTZER = ""            # nur noetig, wenn in der OpenCCU die Authentifizierung an ist
CCU_PASSWORT = ""
CCU_VAR_FEUCHTE = "Gartenfeuchte"
CCU_VAR_FEUCHT = "Garten_feucht"
CCU_VAR_STAND = "Gartenfeuchte_Stand"
CCU_VAR_AKKU = "Gartenfeuchte_Akku"     # "" = Akkustand nicht melden
CCU_NEUVERSUCH_S = 60        # Meldung nicht angekommen? Nach 1 min nochmal

# WLAN
HEIM_WLAN_NAME = ""
HEIM_WLAN_PASSWORT = ""
HOSTNAME = "gartenfeuchte"           # -> http://gartenfeuchte.local
# Feste IP-Adresse im Heim-WLAN (empfohlen, dann kann die OpenCCU-Firewall genau diese
# Adresse freigeben). None = Router vergibt sie. Beispiel: HEIM_FESTE_IP = "192.168.1.60"
HEIM_FESTE_IP = None
HEIM_NETZMASKE = "255.255.255.0"
HEIM_GATEWAY = None                  # None = .1 im selben Netz (meist der Router)
HEIM_DNS = None                      # None = wie HEIM_GATEWAY
# Ist das Heim-WLAN beim Start nicht erreichbar, macht der Pico ein eigenes auf (zum
# Kalibrieren): Handy mit "Gartenfeuchte" verbinden, http://192.168.4.1 - dann keine OpenCCU.
EIGENES_WLAN_NAME = "Gartenfeuchte"
EIGENES_WLAN_PASSWORT = "gartenfeuchte"   # mindestens 8 Zeichen
WLAN_PRUEFEN_ALLE_S = 60             # Heim-WLAN weg? Dann neu verbinden
WEB_PORT = 80
WEB_PIN = None                       # Zahl = Einstellungen auf der Seite brauchen die PIN

# Sparmodus fuer Akkubetrieb (siehe oben). False = WLAN und Webseite immer an (Netzteil).
SPARMODUS = True
SPAR_MESSEN_ALLE_S = 900     # im Sparmodus alle 15 min messen und melden
WLAN_FENSTER_MIN = 5         # WLAN an von hh:00 bis hh:05 (und nach dem Einschalten)
WLAN_VERLAENGERN_MIN = 30    # Knopf auf der Seite: WLAN so lange anlassen
WLAN_KURZ_TIMEOUT_S = 15     # Verbindungsaufbau fuer eine Meldung hoechstens so lange
LEICHTSCHLAF = True          # zwischen den Messungen machine.lightsleep (spart am meisten)

DATEI = "feuchte.json"
SEITE_DATEI = "seite.html"
VERLAUF_PUNKTE = 288                 # Messpunkte fuer die Kurve (24 h bei 5 min, 72 h bei 15 min)

# Akku-Waechter. Bei Netzteil: AKKU_BENUTZEN = False.
# Laufzeit einmessen: Akkuseite -> Testlauf (siehe akku.py). Ohne Sparmodus braucht der
# Pico W mit WLAN etwa 40-50 mA, mit Sparmodus nur einen Bruchteil davon.
AKKU_BENUTZEN = True
AKKU_LAUFZEIT_H = 200        # Platzhalter - per Testlauf einmessen!
AKKU_WARNEN_BEI_H = 24
NTFY_THEMA = ""              # z. B. "garten-7k3q9" - leer = keine Push-Nachricht
AKKU = None                  # wird in main() angelegt

# ============================================================================
# SENSOR UND AUSWERTUNG
# ============================================================================


class Sensor:
    def __init__(self):
        self.adc = ADC(Pin(SENSOR_ADC_PIN))
        self.strom = None
        if SENSOR_STROM_PIN is not None:
            try:                                     # kraeftiger Ausgang (Sensor braucht ~5 mA)
                self.strom = Pin(SENSOR_STROM_PIN, Pin.OUT, value=0, drive=Pin.DRIVE_3)
            except (AttributeError, TypeError, ValueError):
                self.strom = Pin(SENSOR_STROM_PIN, Pin.OUT, value=0)

    def messen(self):
        """Spannung am Sensorausgang in mV (Median aus PROBEN Proben)."""
        if self.strom:
            self.strom.value(1)
            time.sleep_ms(AUFWAERMEN_MS)
        proben = []
        for _ in range(PROBEN):
            proben.append(self.adc.read_u16())
            time.sleep_ms(20)
        if self.strom:
            self.strom.value(0)
        proben.sort()
        return proben[len(proben) // 2] * 3300 // 65535


class Feuchte:
    """Kalibrierung, Prozentwert und Schaltzustand mit Hysterese."""

    def __init__(self):
        self.trocken_mv = TROCKEN_MV
        self.nass_mv = NASS_MV
        self.feucht_ab = FEUCHT_AB
        self.trocken_unter = TROCKEN_UNTER
        self.mv = None
        self.prozent = None
        self.feucht = False                  # Start: "nicht feucht" (= im Zweifel giessen)
        self.fehler = None
        self.gemessen_ms = None
        self.verlauf = []
        self._laden()

    def prozent_aus(self, mv):
        spanne = self.trocken_mv - self.nass_mv
        if spanne <= 0:
            return None
        p = (self.trocken_mv - mv) * 100 / spanne
        return max(0.0, min(100.0, p))

    def neuer_wert(self, mv):
        self.mv = mv
        self.gemessen_ms = time.ticks_ms()
        if mv < FEHLER_UNTER_MV or mv > FEHLER_UEBER_MV:
            self.fehler = "Sensorfehler (%d mV) - Kabel/Sensor pruefen" % mv
            self.prozent = None
            self.feucht = False
            print("Feuchte:", self.fehler)
            return
        p = self.prozent_aus(mv)
        if p is None:
            self.fehler = "Kalibrierung ungueltig (trocken muss hoeher sein als nass)"
            self.prozent = None
            self.feucht = False
            return
        self.fehler = None
        self.prozent = p
        if p >= self.feucht_ab:
            self.feucht = True
        elif p < self.trocken_unter:
            self.feucht = False
        self.verlauf.append(int(p + 0.5))
        if len(self.verlauf) > VERLAUF_PUNKTE:
            self.verlauf.pop(0)
        print("Feuchte: %d mV = %.0f %% -> %s" % (mv, p, "feucht" if self.feucht else "trocken"))

    def text(self):
        """Fuer Siri und die Konsole."""
        if self.fehler:
            return "Gartenfeuchte: " + self.fehler + "."
        if self.prozent is None:
            return "Gartenfeuchte: noch nicht gemessen."
        return "Gartenfeuchte %d Prozent, %s." % (
            int(self.prozent + 0.5),
            "feucht genug, die Bewässerung kann ausfallen" if self.feucht else "trocken, es wird gegossen")

    def status(self):
        alter = None
        if self.gemessen_ms is not None:
            alter = time.ticks_diff(time.ticks_ms(), self.gemessen_ms) // 1000
        return {"mv": self.mv, "prozent": None if self.prozent is None else round(self.prozent, 1),
                "feucht": self.feucht, "fehler": self.fehler, "alter_s": alter,
                "trocken_mv": self.trocken_mv, "nass_mv": self.nass_mv,
                "feucht_ab": self.feucht_ab, "trocken_unter": self.trocken_unter,
                "verlauf": self.verlauf, "messen_alle_s": MESSEN_ALLE_S}

    def einstellen(self, d):
        neu = {}
        for k in ("trocken_mv", "nass_mv", "feucht_ab", "trocken_unter"):
            neu[k] = int(float(d[k])) if d.get(k) is not None else getattr(self, k)
        if neu["trocken_mv"] <= neu["nass_mv"]:
            raise ValueError("Trocken-Wert muss hoeher sein als der Nass-Wert")
        if not 0 <= neu["trocken_unter"] <= neu["feucht_ab"] <= 100:
            raise ValueError("Es muss gelten: 0 <= trocken unter <= feucht ab <= 100")
        for k in neu:
            setattr(self, k, neu[k])
        self.speichern()
        if self.mv is not None:
            self.neuer_wert(self.mv)             # mit den neuen Werten neu bewerten

    # ------------------------------------------------------------- Speichern
    def speichern(self):
        daten = {"trocken_mv": self.trocken_mv, "nass_mv": self.nass_mv,
                 "feucht_ab": self.feucht_ab, "trocken_unter": self.trocken_unter}
        try:
            with open(DATEI + ".neu", "w") as f:
                json.dump(daten, f)
            try:
                os.remove(DATEI)
            except OSError:
                pass
            os.rename(DATEI + ".neu", DATEI)
        except OSError as fehler:
            print("Speichern fehlgeschlagen:", fehler)

    def _laden(self):
        for name in (DATEI, DATEI + ".neu"):
            try:
                with open(name) as f:
                    d = json.load(f)
            except (OSError, ValueError):
                continue
            self.trocken_mv = int(d.get("trocken_mv", self.trocken_mv))
            self.nass_mv = int(d.get("nass_mv", self.nass_mv))
            self.feucht_ab = int(d.get("feucht_ab", self.feucht_ab))
            self.trocken_unter = int(d.get("trocken_unter", self.trocken_unter))
            print("Kalibrierung geladen: trocken %d mV, nass %d mV" % (self.trocken_mv, self.nass_mv))
            return
        print("Noch keine Kalibrierung gespeichert - Startwerte aus main.py.")


# ============================================================================
# OPENCCU
# ============================================================================


class Melder:
    """Schickt die Werte an die OpenCCU und merkt sich das Ergebnis fuer die Seite."""

    def __init__(self):
        self.ok = None
        self.info = "noch nichts gesendet"
        self.fehlend = []
        self.gesendet_ms = None
        self.offen = False
        self.naechster_versuch = time.ticks_ms()

    def werte(self, feuchte):
        w = []
        if feuchte.prozent is not None:
            w.append((CCU_VAR_FEUCHTE, round(feuchte.prozent, 1)))
        w.append((CCU_VAR_FEUCHT, feuchte.feucht))
        w.append((CCU_VAR_STAND, ccu.ZEIT, "Sensorfehler " if feuchte.fehler else ""))
        if AKKU and CCU_VAR_AKKU:
            w.append((CCU_VAR_AKKU, AKKU.prozent()))
        return w

    def melden(self, feuchte):
        self.offen = True
        self.naechster_versuch = time.ticks_ms()
        return self.schritt(feuchte)

    def schritt(self, feuchte):
        if not self.offen or time.ticks_diff(time.ticks_ms(), self.naechster_versuch) < 0:
            return None
        if not wlan_ok():
            self.ok, self.info = False, "kein Heim-WLAN"
        else:
            self.ok, self.info, self.fehlend = ccu.senden(
                CCU_IP, self.werte(feuchte), CCU_PORT, CCU_BENUTZER, CCU_PASSWORT, CCU_HTTPS)
            if not self.ok and self.fehlend == [CCU_VAR_AKKU]:
                # Nur die (freiwillige) Akku-Variable fehlt - der Rest ist angekommen.
                self.ok = True
                self.info = "ok (ohne Akkustand: %s fehlt in der OpenCCU)" % CCU_VAR_AKKU
        if self.ok:
            self.offen = False
            self.gesendet_ms = time.ticks_ms()
            print("OpenCCU: gemeldet")
        else:
            self.naechster_versuch = time.ticks_add(time.ticks_ms(), CCU_NEUVERSUCH_S * 1000)
            print("OpenCCU:", self.info, "- neuer Versuch in", CCU_NEUVERSUCH_S, "s")
        return self.ok

    def status(self):
        alter = None
        if self.gesendet_ms is not None:
            alter = time.ticks_diff(time.ticks_ms(), self.gesendet_ms) // 1000
        return {"ip": CCU_IP, "ok": self.ok, "info": self.info, "fehlend": self.fehlend,
                "alter_s": alter, "wartet": self.offen,
                "variablen": [CCU_VAR_FEUCHTE, CCU_VAR_FEUCHT, CCU_VAR_STAND]
                + ([CCU_VAR_AKKU] if AKKU and CCU_VAR_AKKU else [])}


# ============================================================================
# WLAN UND WEBSEITE (inkl. Siri-Adressen)
# ============================================================================

STA = None


def wlan_ok():
    return STA is not None and STA.isconnected()


def feste_ip_setzen(sta):
    """HEIM_FESTE_IP vor dem Verbinden setzen (dann fragt der Pico den Router nicht)."""
    if not HEIM_FESTE_IP:
        return
    teile = HEIM_FESTE_IP.split(".")
    gw = HEIM_GATEWAY or ".".join(teile[:3] + ["1"])
    try:
        sta.ifconfig((HEIM_FESTE_IP, HEIM_NETZMASKE, gw, HEIM_DNS or gw))
        print("Feste IP im Heim-WLAN: " + HEIM_FESTE_IP + " (Gateway " + gw + ")")
    except Exception as e:
        print("Feste IP nicht gesetzt (" + str(e) + ") - nehme DHCP.")
    # Neueres MicroPython (ab ca. 1.24): DNS-Server ueber network.ipconfig setzen,
    # sonst ist z. B. ntfy.sh nicht aufloesbar (siehe Rolltor/Startampel).
    if hasattr(network, "ipconfig"):
        try:
            network.ipconfig(dns=HEIM_DNS or gw)
        except Exception as e:
            print("DNS-Server nicht gesetzt (" + str(e) + ")")


def wlan_starten():
    """Heim-WLAN, sonst eigenes. Gibt (ip, modus) zurueck."""
    global STA
    if network is None:
        return None, None
    try:
        if hasattr(network, "hostname"):
            network.hostname(HOSTNAME)
    except Exception:
        pass
    if HEIM_WLAN_NAME:
        sta = network.WLAN(network.STA_IF)
        sta.active(True)
        feste_ip_setzen(sta)
        sta.connect(HEIM_WLAN_NAME, HEIM_WLAN_PASSWORT)
        bis = time.ticks_add(time.ticks_ms(), 20000)
        while not sta.isconnected() and time.ticks_diff(bis, time.ticks_ms()) > 0:
            time.sleep_ms(200)
        if sta.isconnected():
            STA = sta
            ip = sta.ifconfig()[0]
            print("Heim-WLAN verbunden: http://" + HOSTNAME + ".local  oder  http://" + ip)
            return ip, "heim"
        print("Heim-WLAN nicht erreichbar - mache eigenes WLAN auf.")
        sta.active(False)
    else:
        print("Kein HEIM_WLAN_NAME eingetragen - mache eigenes WLAN auf.")
    ap = network.WLAN(network.AP_IF)
    ap.config(essid=EIGENES_WLAN_NAME, password=EIGENES_WLAN_PASSWORT)
    ap.active(True)
    ip = ap.ifconfig()[0]
    print("Eigenes WLAN \"" + EIGENES_WLAN_NAME + "\" (Passwort: " + EIGENES_WLAN_PASSWORT
          + "): http://" + ip)
    return ip, "eigenes"


def wlan_an(timeout_s=WLAN_KURZ_TIMEOUT_S):
    """Sparmodus: Heim-WLAN einschalten und verbinden. True = verbunden."""
    if STA is None:
        return False
    if STA.isconnected():
        return True
    STA.active(True)
    feste_ip_setzen(STA)
    STA.connect(HEIM_WLAN_NAME, HEIM_WLAN_PASSWORT)
    bis = time.ticks_add(time.ticks_ms(), timeout_s * 1000)
    while not STA.isconnected() and time.ticks_diff(bis, time.ticks_ms()) > 0:
        time.sleep_ms(100)
    return STA.isconnected()


def wlan_aus():
    """Sparmodus: WLAN-Chip ganz abschalten (spart etwa 30-40 mA)."""
    if STA is None:
        return
    try:
        STA.disconnect()
    except Exception:
        pass
    STA.active(False)


def uhr_stellen():
    """Uhr per NTP stellen (fuer das Fenster zur vollen Stunde). Klappt es nicht, laeuft
    das Fenster einfach jede Stunde ab dem Einschalten."""
    try:
        import ntptime
        ntptime.settime()
        return True
    except Exception as e:
        print("Uhr nicht gestellt:", e)
        return False


def wlan_pruefen():
    """Im Garten reisst das WLAN schon mal ab - dann neu verbinden (blockiert nicht)."""
    if STA is None or STA.isconnected():
        return
    print("Heim-WLAN weg - verbinde neu.")
    try:
        STA.disconnect()
    except Exception:
        pass
    try:
        STA.connect(HEIM_WLAN_NAME, HEIM_WLAN_PASSWORT)
    except Exception as e:
        print("Neu verbinden fehlgeschlagen:", e)


def abfrage_werte(pfad):
    """'/messen?pin=12' -> ('/messen', {'pin': '12'})"""
    pfad, _, rest = pfad.partition("?")
    werte = {}
    for teil in rest.split("&"):
        k, _, v = teil.partition("=")
        if k:
            werte[k] = v
    return pfad, werte


class Webseite:
    """Kleiner Webserver ohne Faeden: die Hauptschleife fragt per poll(0), ob jemand anklopft,
    und beantwortet eine Anfrage am Stueck (Zeitlimit 1 s)."""

    def __init__(self, sensor, feuchte, melder, modus, port=WEB_PORT, adresse="0.0.0.0"):
        self.sensor = sensor
        self.feuchte = feuchte
        self.melder = melder
        self.modus = modus
        self.jetzt_messen = False
        self.server = socket.socket()
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(socket.getaddrinfo(adresse, port)[0][-1])
        self.server.listen(3)
        self.server.setblocking(False)
        self.poll = select.poll()
        self.poll.register(self.server, select.POLLIN)

    def schliessen(self):
        try:
            self.poll.unregister(self.server)
        except Exception:
            pass
        self.server.close()

    def schritt(self):
        for _ in self.poll.poll(0):
            try:
                kunde, _adr = self.server.accept()
            except OSError:
                return
            try:
                kunde.settimeout(1.0)
                self._anfrage(kunde)
            except Exception as fehler:
                print("Webseite:", fehler)
            finally:
                kunde.close()

    # ------------------------------------------------------------- HTTP
    def _lesen(self, kunde):
        daten = b""
        while b"\r\n\r\n" not in daten and len(daten) < 4096:
            stueck = kunde.recv(512)
            if not stueck:
                break
            daten += stueck
        kopf, _, rumpf = daten.partition(b"\r\n\r\n")
        zeilen = kopf.decode().split("\r\n")
        teile = zeilen[0].split(" ")
        methode = teile[0] if teile else ""
        pfad = teile[1] if len(teile) > 1 else "/"
        felder = {}
        for z in zeilen[1:]:
            k, _, v = z.partition(":")
            felder[k.strip().lower()] = v.strip()
        laenge = min(int(felder.get("content-length", "0") or 0), 2048)
        while len(rumpf) < laenge:
            stueck = kunde.recv(512)
            if not stueck:
                break
            rumpf += stueck
        return methode, pfad, felder, rumpf

    def _senden(self, kunde, code, inhalt, art="application/json"):
        if isinstance(inhalt, str):
            inhalt = inhalt.encode()
        text = {200: "OK", 400: "Bad Request", 401: "Unauthorized", 404: "Not Found",
                409: "Conflict"}.get(code, "OK")
        kopf = ("HTTP/1.0 %d %s\r\nContent-Type: %s; charset=utf-8\r\nCache-Control: no-store\r\n"
                "Content-Length: %d\r\nConnection: close\r\n\r\n") % (code, text, art, len(inhalt))
        senden = kunde.sendall if hasattr(kunde, "sendall") else kunde.write
        senden(kopf.encode())
        senden(inhalt)

    def _datei(self, kunde, name, art):
        try:
            groesse = os.stat(name)[6]
        except OSError:
            return self._senden(kunde, 404, name + " fehlt auf dem Pico - bitte mitkopieren.", "text/plain")
        senden = kunde.sendall if hasattr(kunde, "sendall") else kunde.write
        senden((("HTTP/1.0 200 OK\r\nContent-Type: %s; charset=utf-8\r\nCache-Control: no-store\r\n"
                 "Content-Length: %d\r\nConnection: close\r\n\r\n") % (art, groesse)).encode())
        puffer = bytearray(512)
        with open(name, "rb") as f:
            while True:
                n = f.readinto(puffer)
                if not n:
                    break
                senden(puffer[:n])

    def _status(self):
        return json.dumps({"feuchte": self.feuchte.status(), "ccu": self.melder.status(),
                           "wlan": self.modus, "host": HOSTNAME,
                           "sparmodus": spar_aktiv(self.modus), "verlaengern_min": WLAN_VERLAENGERN_MIN,
                           "wlan_rest_min": fenster_rest_min(),
                           "akku_h": round(AKKU.rest_h(), 1) if AKKU else None,
                           "akku_stufe": AKKU.stufe if AKKU else 0})

    # ------------------------------------------------------------- Routen
    def _anfrage(self, kunde):
        methode, voll, felder, rumpf = self._lesen(kunde)
        pfad, werte = abfrage_werte(voll)
        if methode == "GET" and pfad in ("/", "/index.html"):
            return self._datei(kunde, SEITE_DATEI, "text/html")
        if methode == "GET" and pfad == "/akku" and AKKU:
            return self._datei(kunde, akku.SEITE_DATEI, "text/html")
        # Nur lesen geht ohne PIN: Status und Siri-Abfrage
        if methode == "GET" and pfad == "/status":
            return self._senden(kunde, 200, self._status())
        if methode == "GET" and pfad == "/feuchte":                 # Siri: "Wie feucht ist der Garten?"
            return self._senden(kunde, 200, self.feuchte.text(), "text/plain")
        if WEB_PIN is not None and felder.get("x-pin", werte.get("pin", "")) != str(WEB_PIN):
            return self._senden(kunde, 401, "PIN falsch", "text/plain")

        # Akku: /akku/geladen, /akku/rest, /akku/test, /akku/status (siehe akku.py)
        antwort = AKKU.anfrage(methode, pfad, werte, rumpf) if AKKU else None
        if antwort:
            return self._senden(kunde, *antwort)

        if methode == "GET" and pfad == "/messen":                  # jetzt messen + melden
            self.feuchte.neuer_wert(self.sensor.messen())
            self.melder.melden(self.feuchte)
            return self._senden(kunde, 200, self._status())
        if methode == "GET" and pfad == "/wlan/verlaengern":
            if not spar_aktiv(self.modus):
                return self._senden(kunde, 200, "Sparmodus ist aus - WLAN bleibt ohnehin an.", "text/plain")
            fenster_verlaengern(WLAN_VERLAENGERN_MIN)
            return self._senden(kunde, 200, "WLAN bleibt noch %d Minuten an." % WLAN_VERLAENGERN_MIN,
                                "text/plain")
        if methode == "GET" and pfad == "/ccu/senden":
            ok = self.melder.melden(self.feuchte)
            return self._senden(kunde, 200 if ok else 409,
                                "An die OpenCCU gemeldet." if ok else self.melder.info, "text/plain")

        if methode == "POST":
            try:
                d = json.loads(rumpf or b"{}")
            except ValueError:
                return self._senden(kunde, 400, "kein JSON", "text/plain")
            if pfad == "/kalibrieren":
                was = d.get("was")
                if was not in ("trocken", "nass"):
                    return self._senden(kunde, 400, "trocken oder nass?", "text/plain")
                mv = self.sensor.messen()
                if mv < FEHLER_UNTER_MV or mv > FEHLER_UEBER_MV:
                    return self._senden(kunde, 409, "Sensor liefert %d mV - angeschlossen?" % mv,
                                        "text/plain")
                try:
                    self.feuchte.einstellen({was + "_mv": mv})
                except ValueError as e:
                    # Ersten Punkt trotzdem merken, wenn der andere noch nicht passt
                    setattr(self.feuchte, was + "_mv", mv)
                    self.feuchte.speichern()
                    return self._senden(kunde, 409, "%s gespeichert (%d mV). Hinweis: %s"
                                        % (was.capitalize(), mv, e), "text/plain")
                print("Kalibrierung:", was, mv, "mV")
                self.feuchte.neuer_wert(mv)
                return self._senden(kunde, 200, self._status())
            if pfad == "/einstellen":
                try:
                    self.feuchte.einstellen(d)
                except (ValueError, TypeError) as e:
                    return self._senden(kunde, 400, str(e), "text/plain")
                self.melder.melden(self.feuchte)
                return self._senden(kunde, 200, self._status())
        self._senden(kunde, 404, "nicht gefunden", "text/plain")


# ============================================================================
# HAUPTSCHLEIFE
# ============================================================================


# Sparmodus: bis wann das WLAN-Fenster offen ist (ticks_ms) - None = zu
FENSTER = {"bis": None}


def spar_aktiv(modus):
    return SPARMODUS and modus == "heim"


def fenster_verlaengern(minuten):
    """WLAN mindestens noch so viele Minuten anlassen."""
    neu = time.ticks_add(time.ticks_ms(), minuten * 60000)
    alt = FENSTER["bis"]
    if alt is None or time.ticks_diff(neu, alt) > 0:
        FENSTER["bis"] = neu


def fenster_rest_min():
    if FENSTER["bis"] is None:
        return None
    return max(0, time.ticks_diff(FENSTER["bis"], time.ticks_ms())) // 60000 + 1


def schlafen(ms):
    """Sparmodus: so lange schlafen (lightsleep, sonst normales Warten)."""
    global LEICHTSCHLAF
    if ms <= 0:
        return
    if LEICHTSCHLAF:
        try:
            machine.lightsleep(ms)
            return
        except Exception as e:                 # aeltere Firmware: dann eben normal warten
            print("lightsleep nicht moeglich (" + str(e) + ") - warte normal.")
            LEICHTSCHLAF = False
    time.sleep_ms(ms)


def main():
    global AKKU
    if akku and AKKU_BENUTZEN:
        AKKU = akku.Akku("Gartenfeuchte", AKKU_LAUFZEIT_H, AKKU_WARNEN_BEI_H, NTFY_THEMA,
                         testlauf_text="Normalbetrieb: " + (
                             "Sparmodus, alle %d min messen und melden, WLAN-Fenster zur vollen "
                             "Stunde." % (SPAR_MESSEN_ALLE_S // 60) if SPARMODUS else
                             "alle %d min messen und an die OpenCCU melden, WLAN bleibt an."
                             % (MESSEN_ALLE_S // 60)))
    sensor = Sensor()
    feuchte = Feuchte()
    melder = Melder()

    led = Pin("LED", Pin.OUT)
    ip, modus = wlan_starten()
    seite = None
    if ip:
        try:
            seite = Webseite(sensor, feuchte, melder, modus)
        except Exception as fehler:
            print("Webseite nicht moeglich:", fehler)

    if spar_aktiv(modus):
        sparbetrieb(sensor, feuchte, melder, seite, led)
        return

    naechste_messung = time.ticks_ms()               # gleich nach dem Start messen
    naechste_wlan_pruefung = time.ticks_add(time.ticks_ms(), WLAN_PRUEFEN_ALLE_S * 1000)
    while True:
        jetzt = time.ticks_ms()
        if seite:
            seite.schritt()
        if time.ticks_diff(jetzt, naechste_messung) >= 0:
            naechste_messung = time.ticks_add(jetzt, MESSEN_ALLE_S * 1000)
            led.off()
            feuchte.neuer_wert(sensor.messen())
            if modus == "heim":
                melder.melden(feuchte)
        else:
            melder.schritt(feuchte)                  # Neuversuch, falls die CCU nicht erreichbar war
        if modus == "heim" and time.ticks_diff(jetzt, naechste_wlan_pruefung) >= 0:
            naechste_wlan_pruefung = time.ticks_add(jetzt, WLAN_PRUEFEN_ALLE_S * 1000)
            wlan_pruefen()
        if AKKU:
            AKKU.schritt()
        # Onboard-LED: an = Heim-WLAN verbunden, blinkt = eigenes WLAN, aus = kein WLAN
        if modus == "heim":
            led.value(1 if wlan_ok() else (time.ticks_ms() // 150) % 2)
        elif modus == "eigenes":
            led.value((time.ticks_ms() // 500) % 2)
        time.sleep_ms(20)


def sparbetrieb(sensor, feuchte, melder, seite, led):
    """Akkubetrieb: WLAN nur im Fenster zur vollen Stunde, sonst kurz zum Melden."""
    uhr_ok = uhr_stellen()
    fenster_verlaengern(WLAN_FENSTER_MIN)            # erstes Fenster direkt nach dem Einschalten
    fenster_stunde = time.gmtime()[3]
    start_ms = time.ticks_ms()
    naechste_messung = start_ms                      # gleich messen
    print("Sparmodus: WLAN-Fenster %d min zu jeder vollen Stunde, Messung alle %d min."
          % (WLAN_FENSTER_MIN, SPAR_MESSEN_ALLE_S // 60))

    while True:
        jetzt = time.ticks_ms()
        offen = FENSTER["bis"] is not None

        # Fenster zur vollen Stunde oeffnen (ohne gestellte Uhr: stuendlich ab dem Start)
        if not offen:
            if uhr_ok:
                t = time.gmtime()
                stunde_voll = t[4] < WLAN_FENSTER_MIN and t[3] != fenster_stunde
                if stunde_voll:
                    fenster_stunde = t[3]
            else:
                stunde = time.ticks_diff(jetzt, start_ms) // 3600000
                stunde_voll = stunde != fenster_stunde
                if stunde_voll:
                    fenster_stunde = stunde
            if stunde_voll:
                print("WLAN-Fenster auf.")
                if wlan_an():
                    fenster_verlaengern(WLAN_FENSTER_MIN)
                    uhr_ok = uhr_stellen() or uhr_ok
                    if seite is None:
                        try:
                            seite = Webseite(sensor, feuchte, melder, "heim")
                        except Exception as fehler:
                            print("Webseite nicht moeglich:", fehler)
                    if AKKU and getattr(AKKU, "offen", None):
                        AKKU.naechster_versuch = time.ticks_ms()   # wartende Push gleich senden
                    offen = True
                else:
                    print("Heim-WLAN nicht erreichbar - naechstes Fenster in einer Stunde.")
                    wlan_aus()

        # Messen und melden
        if time.ticks_diff(jetzt, naechste_messung) >= 0:
            naechste_messung = time.ticks_add(jetzt, SPAR_MESSEN_ALLE_S * 1000)
            feuchte.neuer_wert(sensor.messen())
            if offen or wlan_an():
                melder.melden(feuchte)
                if AKKU and getattr(AKKU, "offen", None):
                    AKKU._senden_offen()             # wartende Push-Nachricht mitnehmen
                if not offen:
                    wlan_aus()
            else:
                melder.ok, melder.info = False, "Heim-WLAN nicht erreichbar"
                print("Meldung nicht moeglich: Heim-WLAN nicht erreichbar.")
                wlan_aus()

        if offen:
            # Fenster offen: Webseite bedienen, normal weiterlaufen
            led.value(1 if wlan_ok() else 0)
            if seite:
                seite.schritt()
            melder.schritt(feuchte)
            if AKKU:
                AKKU.schritt(darf_senden=wlan_ok())
            if time.ticks_diff(time.ticks_ms(), FENSTER["bis"]) >= 0:
                FENSTER["bis"] = None
                if seite:
                    seite.schliessen()
                    seite = None
                wlan_aus()
                led.off()
                print("WLAN-Fenster zu, Sparbetrieb.")
            time.sleep_ms(20)
        else:
            # Fenster zu: schlafen bis zur naechsten Messung (hoechstens 60 s am Stueck,
            # damit die volle Stunde nicht verpasst wird)
            if AKKU:
                AKKU.schritt(darf_senden=False)
            rest = time.ticks_diff(naechste_messung, time.ticks_ms())
            schlafen(min(max(rest, 0), 60000))


if __name__ == "__main__":
    main()
