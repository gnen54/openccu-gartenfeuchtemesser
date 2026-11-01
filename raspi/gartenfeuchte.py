#!/usr/bin/env python3
# OpenCCU Gartenfeuchtemesser - Variante fuer Raspberry Pi 3 (Python 3, Raspberry Pi OS)
#
# Der Raspberry Pi hat keinen Analogeingang. Darum sitzt ein ADS1115 (16-Bit-A/D-Wandler,
# I2C) dazwischen: Sensor AOUT -> ADS1115 A0. Sonst macht das Programm dasselbe wie die
# Pico-Version: alle 5 min messen, Prozent mit Hysterese bewerten, an die OpenCCU melden.
# Die OpenCCU-Anbindung kommt aus ../pico/ccu.py (gemeinsam fuer beide Varianten).
#
# Aufruf:
#   python3 gartenfeuchte.py                      Dauerbetrieb (als Dienst, siehe README)
#   python3 gartenfeuchte.py --messen             einmal messen und anzeigen (nichts senden)
#   python3 gartenfeuchte.py --kalibrieren trocken   Sensor an der Luft
#   python3 gartenfeuchte.py --kalibrieren nass      Sensor bis zur Linie im Wasser
#   python3 gartenfeuchte.py --senden             einmal messen und an die OpenCCU melden
#
# Status im Browser: http://<raspi>:8080/ (JSON), Siri-Text: http://<raspi>:8080/feuchte

import argparse
import json
import os
import statistics
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HIER, "..", "pico"))
import ccu  # noqa: E402

# ============================================================================
# KONFIGURATION (wie in pico/main.py)
# ============================================================================

I2C_BUS = 1                  # Pins 3 (SDA) und 5 (SCL)
ADS_ADRESSE = 0x48           # ADDR an GND
ADS_KANAL = 0                # A0
MESSEN_ALLE_S = 300
PROBEN = 15

TROCKEN_MV = 2600
NASS_MV = 1200
FEUCHT_AB = 45
TROCKEN_UNTER = 35
FEHLER_UNTER_MV = 150
FEHLER_UEBER_MV = 3200

CCU_IP = "192.168.1.10"           # Beispiel - Adresse deiner OpenCCU eintragen
CCU_PORT = 8181
CCU_HTTPS = False
CCU_BENUTZER = ""
CCU_PASSWORT = ""
CCU_VAR_FEUCHTE = "Gartenfeuchte"
CCU_VAR_FEUCHT = "Garten_feucht"
CCU_VAR_STAND = "Gartenfeuchte_Stand"
CCU_NEUVERSUCH_S = 60

WEB_PORT = 8080              # 0 = keine Statusseite
DATEI = os.path.join(HIER, "feuchte.json")

# ============================================================================
# ADS1115
# ============================================================================


class ADS1115:
    """Einzelmessung an einem Eingang gegen GND, Bereich +-4,096 V (reicht fuer 3,3 V)."""

    def __init__(self, bus=I2C_BUS, adresse=ADS_ADRESSE):
        from smbus2 import SMBus             # sudo apt install python3-smbus2
        self.bus = SMBus(bus)
        self.adresse = adresse

    def lesen_mv(self, kanal=ADS_KANAL):
        konfig = (0x8000                     # Einzelmessung starten
                  | ((0x4 + kanal) << 12)    # MUX: AINx gegen GND
                  | 0x0200                   # PGA +-4,096 V
                  | 0x0100                   # Einzelmessung
                  | 0x0080                   # 128 Messungen/s
                  | 0x0003)                  # Komparator aus
        self.bus.write_i2c_block_data(self.adresse, 0x01, [konfig >> 8, konfig & 0xFF])
        time.sleep(0.01)
        hoch, tief = self.bus.read_i2c_block_data(self.adresse, 0x00, 2)
        roh = (hoch << 8) | tief
        if roh & 0x8000:
            roh -= 0x10000
        return roh * 4096 // 32768

    def messen(self):
        proben = []
        for _ in range(PROBEN):
            proben.append(self.lesen_mv())
            time.sleep(0.02)
        return int(statistics.median(proben))


# ============================================================================
# AUSWERTUNG
# ============================================================================


class Feuchte:
    def __init__(self):
        self.trocken_mv, self.nass_mv = TROCKEN_MV, NASS_MV
        self.feucht_ab, self.trocken_unter = FEUCHT_AB, TROCKEN_UNTER
        self.mv = self.prozent = self.fehler = None
        self.feucht = False                  # Start: im Zweifel giessen
        self.zeit = None
        self.laden()

    def laden(self):
        try:
            with open(DATEI) as f:
                d = json.load(f)
        except (OSError, ValueError):
            return
        for k in ("trocken_mv", "nass_mv", "feucht_ab", "trocken_unter"):
            if k in d:
                setattr(self, k, int(d[k]))

    def speichern(self):
        d = {k: getattr(self, k) for k in ("trocken_mv", "nass_mv", "feucht_ab", "trocken_unter")}
        neu = DATEI + ".neu"
        with open(neu, "w") as f:
            json.dump(d, f, indent=1)
        os.replace(neu, DATEI)

    def neuer_wert(self, mv):
        self.mv, self.zeit = mv, time.time()
        if mv < FEHLER_UNTER_MV or mv > FEHLER_UEBER_MV:
            self.fehler = "Sensorfehler (%d mV)" % mv
            self.prozent, self.feucht = None, False
            return
        spanne = self.trocken_mv - self.nass_mv
        if spanne <= 0:
            self.fehler = "Kalibrierung ungueltig"
            self.prozent, self.feucht = None, False
            return
        self.fehler = None
        self.prozent = max(0.0, min(100.0, (self.trocken_mv - mv) * 100 / spanne))
        if self.prozent >= self.feucht_ab:
            self.feucht = True
        elif self.prozent < self.trocken_unter:
            self.feucht = False

    def text(self):
        if self.fehler:
            return "Gartenfeuchte: %s." % self.fehler
        if self.prozent is None:
            return "Gartenfeuchte: noch nicht gemessen."
        return "Gartenfeuchte %d Prozent, %s." % (
            round(self.prozent),
            "feucht genug, die Bewässerung kann ausfallen" if self.feucht else "trocken, es wird gegossen")

    def werte(self):
        w = []
        if self.prozent is not None:
            w.append((CCU_VAR_FEUCHTE, round(self.prozent, 1)))
        w.append((CCU_VAR_FEUCHT, self.feucht))
        w.append((CCU_VAR_STAND, ccu.ZEIT, "Sensorfehler " if self.fehler else ""))
        return w

    def status(self):
        return {"mv": self.mv, "prozent": None if self.prozent is None else round(self.prozent, 1),
                "feucht": self.feucht, "fehler": self.fehler, "zeit": self.zeit,
                "trocken_mv": self.trocken_mv, "nass_mv": self.nass_mv,
                "feucht_ab": self.feucht_ab, "trocken_unter": self.trocken_unter}


def melden(feuchte):
    ok, info, _ = ccu.senden(CCU_IP, feuchte.werte(), CCU_PORT, CCU_BENUTZER, CCU_PASSWORT, CCU_HTTPS)
    print("OpenCCU:", "gemeldet" if ok else info, flush=True)
    return ok, info


# ============================================================================
# STATUSSEITE
# ============================================================================


def statusseite(feuchte, ccu_stand):
    class Seite(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/feuchte"):
                inhalt, art = feuchte.text().encode(), "text/plain; charset=utf-8"
            elif self.path in ("/", "/status"):
                inhalt = json.dumps({"feuchte": feuchte.status(), "ccu": ccu_stand},
                                    ensure_ascii=False, indent=1).encode()
                art = "application/json; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", art)
            self.send_header("Content-Length", str(len(inhalt)))
            self.end_headers()
            self.wfile.write(inhalt)

        def log_message(self, *a):
            pass

    server = ThreadingHTTPServer(("", WEB_PORT), Seite)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print("Statusseite: http://<raspi>:%d/" % WEB_PORT, flush=True)


# ============================================================================
# START
# ============================================================================


def main():
    p = argparse.ArgumentParser(description="OpenCCU Gartenfeuchtemesser (Raspberry Pi)")
    p.add_argument("--messen", action="store_true", help="einmal messen und anzeigen")
    p.add_argument("--senden", action="store_true", help="einmal messen und an die OpenCCU melden")
    p.add_argument("--kalibrieren", choices=("trocken", "nass"), help="Kalibrierpunkt speichern")
    a = p.parse_args()

    sensor = ADS1115()
    feuchte = Feuchte()

    if a.kalibrieren:
        mv = sensor.messen()
        if mv < FEHLER_UNTER_MV or mv > FEHLER_UEBER_MV:
            sys.exit("Sensor liefert %d mV - angeschlossen?" % mv)
        setattr(feuchte, a.kalibrieren + "_mv", mv)
        feuchte.speichern()
        print("%s gespeichert: %d mV (trocken %d / nass %d)"
              % (a.kalibrieren.capitalize(), mv, feuchte.trocken_mv, feuchte.nass_mv))
        if feuchte.trocken_mv <= feuchte.nass_mv:
            print("Achtung: trocken muss hoeher sein als nass - bitte beide Punkte einmessen.")
        return
    if a.messen or a.senden:
        feuchte.neuer_wert(sensor.messen())
        print(feuchte.text(), "(%d mV)" % feuchte.mv)
        if a.senden:
            sys.exit(0 if melden(feuchte)[0] else 1)
        return

    ccu_stand = {"ok": None, "info": "noch nichts gemeldet", "zeit": None}
    if WEB_PORT:
        statusseite(feuchte, ccu_stand)
    while True:
        try:
            feuchte.neuer_wert(sensor.messen())
            print(feuchte.text(), "(%d mV)" % feuchte.mv, flush=True)
        except OSError as e:                     # I2C gestoert
            feuchte.fehler, feuchte.prozent, feuchte.feucht = "ADS1115 nicht lesbar (%s)" % e, None, False
            print(feuchte.fehler, flush=True)
        ende = time.time() + MESSEN_ALLE_S
        while True:
            ok, info = melden(feuchte)
            ccu_stand.update(ok=ok, info=info, zeit=time.time() if ok else ccu_stand["zeit"])
            if ok or time.time() + CCU_NEUVERSUCH_S >= ende:
                break
            time.sleep(CCU_NEUVERSUCH_S)
        time.sleep(max(1, ende - time.time()))


if __name__ == "__main__":
    main()
