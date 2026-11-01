# Akku-Waechter - Laufzeitzaehler mit Push-Nachricht "Akku laden"
# fuer Raspberry Pi Pico W / Pico 2 W (MicroPython), gemeinsam fuer
# STARTAMPEL, ROLLTOR, CH BELEUCHTUNG und OPENCCU GARTENFEUCHTEMESSER.
#
# Eine Powerbank verraet nicht, wie voll sie ist. Darum zaehlt der Pico seine Betriebsstunden
# seit dem letzten Laden und schickt rechtzeitig eine Push-Nachricht aufs Handy:
#   1. Warnung, wenn nur noch WARNEN_BEI_H Stunden uebrig sind
#   2. "Dringend", wenn nur noch 1 Stunde uebrig ist
#
# Nach dem Laden auf der Seite http://<name>.local/akku auf "Akku geladen" tippen
# (oder per Siri die Adresse /akku/geladen aufrufen) - dann zaehlt er wieder von vorn.
#
# Push-Nachrichten kommen ueber ntfy (kostenlose App fuer iPhone und Android, ohne Anmeldung):
# In der App das gleiche Thema abonnieren, das hier bei ntfy_thema steht.
# Achtung: Themen auf ntfy.sh sind oeffentlich - einen schwer zu erratenden Namen waehlen,
# z. B. "omega-sim-7k3q9".
#
# Laufzeit einmessen: Laufzeit hoch einstellen (z. B. 200 h), Powerbank voll laden, laufen
# lassen bis sie leer ist, wieder laden und auf "Akku geladen" tippen. Die Seite zeigt dann
# "Letzte Laufzeit: 47 h" - etwas weniger davon als Laufzeit eintragen, fertig.
#
# Einbinden (siehe die Projekte):
#   import akku
#   AKKU = akku.Akku("Rolltor", laufzeit_h=40, warnen_bei_h=6, ntfy_thema="omega-sim-7k3q9")
#   in der Hauptschleife:          AKKU.schritt()
#   im Webserver, vor der PIN:     GET /akku          -> Datei akku.html senden
#   im Webserver, nach der PIN:    antwort = AKKU.anfrage(methode, pfad, werte, rumpf)
#
# TESTLAUF (Laufzeit der Powerbank messen): auf der Akkuseite "Testlauf starten". Eine Uhr
# zaehlt die Laufzeit des Tests und zeigt sie live an - zum Vergleich mit den LEDs der
# Powerbank. Sie wird jede Minute in den Flash geschrieben: geht die Powerbank waehrend des
# Tests aus, steht nach dem naechsten Einschalten "Letzter Testlauf: 7 h 42 min (bis leer)"
# auf der Seite, auf die Minute genau. Mit "Als Laufzeit uebernehmen" wird daraus die
# Laufzeit fuer die Warnung. Was waehrend des Tests passiert, bestimmt das Projekt: die
# Startampel simuliert z. B. Rennbetrieb (siehe main.py, AKKU.test_aktiv).

import gc
import json
import os
import time

DATEI = "akku.json"
SEITE_DATEI = "akku.html"    # Akkuseite, liegt als Datei neben akku.py (spart Arbeitsspeicher)
SPEICHERN_ALLE_S = 600       # Zaehler alle 10 min in den Flash schreiben
TEST_SPEICHERN_ALLE_S = 60   # im Testlauf jede Minute - so geht beim Leerlaufen kaum etwas verloren
# NEUSTART IM TESTLAUF: Ein Neustart ohne Stromausfall (Strg+D in Thonny, neues Programm
# aufgespielt) beendet den Test nicht. Erkennung ueber die Uhr des Pico: sie laeuft bei einem
# Neustart weiter, beginnt nach einem Stromausfall aber wieder bei ihrem Anfangswert. Liegt
# die letzte Speicherung hoechstens so viele Sekunden zurueck, laeuft der Test weiter.
TEST_WEITER_NACH_NEUSTART_S = 90
NEUVERSUCH_S = 300           # Nachricht nicht rausgegangen (kein Internet)? In 5 min nochmal


def _ascii(text):
    """HTTP-Kopfzeilen (Titel) vertragen keine Umlaute."""
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("Ä", "Ae"), ("Ö", "Oe"), ("Ü", "Ue"),
                 ("ß", "ss")):
        text = text.replace(a, b)
    return "".join(z if 32 <= ord(z) < 127 else "?" for z in text)


def dauer_text(s):
    """Sekunden -> '7 h 42 min' bzw. '12 min'."""
    m = int(s) // 60
    return ("%d h %02d min" % (m // 60, m % 60)) if m >= 60 else ("%d min" % m)


def _wlan_ok():
    try:
        import network
        return network.WLAN(network.STA_IF).isconnected()
    except Exception:
        return False


class Akku:

    def __init__(self, name, laufzeit_h=40, warnen_bei_h=6, ntfy_thema="",
                 ntfy_server="https://ntfy.sh", testlauf_text=""):
        self.name = name
        self.testlauf_text = testlauf_text   # was waehrend des Testlaufs passiert (fuer die Seite)
        self.test_aktiv = False
        self.test_s = 0.0
        self.letzter_test_s = None     # Dauer des letzten Testlaufs
        self.letzter_test_leer = False # True = endete, weil der Strom weg war
        self.test_info = ""            # vom Projekt gesetzt, z. B. "Runde 3 - Rennen"
        self._test_gemeldet_min = 0
        self.laufzeit_h = float(laufzeit_h)
        self.warnen_bei_h = float(warnen_bei_h)
        self.ntfy_thema = ntfy_thema
        self.ntfy_server = ntfy_server.rstrip("/")
        self.betrieb_s = 0.0
        self.stufe = 0                 # 0 = nichts gemeldet, 1 = gewarnt, 2 = dringend gemeldet
        self.letzte_laufzeit_h = None  # Betriebsstunden beim letzten "Akku geladen"
        self.offen = None              # (titel, text, prioritaet) wartet auf Versand
        self.letzte_meldung = None     # Text fuer die Seite
        jetzt = time.ticks_ms()
        self.letzter_ms = jetzt
        self.gespeichert_ms = jetzt
        self.naechster_versuch = jetzt
        self._laden()
        print("Akku:", self.name, "- %.1f h in Betrieb, noch ca. %.1f h" % (self.betrieb_h(), self.rest_h()))

    # ------------------------------------------------------------- Zahlen
    def betrieb_h(self):
        return self.betrieb_s / 3600

    def rest_h(self):
        return max(0.0, self.laufzeit_h - self.betrieb_h())

    def prozent(self):
        if self.laufzeit_h <= 0:
            return 0
        return max(0, min(100, int(self.rest_h() * 100 / self.laufzeit_h + 0.5)))

    def status(self):
        return {"name": self.name, "betrieb_h": round(self.betrieb_h(), 1),
                "rest_h": round(self.rest_h(), 1), "prozent": self.prozent(),
                "laufzeit_h": self.laufzeit_h, "warnen_bei_h": self.warnen_bei_h,
                "letzte_laufzeit_h": self.letzte_laufzeit_h, "stufe": self.stufe,
                "push": bool(self.ntfy_thema), "ntfy_thema": self.ntfy_thema,
                "wartet": self.offen is not None,
                "meldung": self.letzte_meldung,
                "test_aktiv": self.test_aktiv, "test_s": int(self.test_s),
                "letzter_test_s": self.letzter_test_s, "letzter_test_leer": self.letzter_test_leer,
                "test_text": self.testlauf_text, "test_info": self.test_info}

    # ------------------------------------------------------------- im Takt
    def schritt(self, darf_senden=True):
        """Aus der Hauptschleife aufrufen - kostet fast nichts. Gezaehlt wird immer;
        darf_senden=False haelt eine faellige Push-Nachricht zurueck (Senden dauert 1-2 s),
        z. B. waehrend ein Motor faehrt oder ein Start-Countdown laeuft."""
        jetzt = time.ticks_ms()
        d = time.ticks_diff(jetzt, self.letzter_ms)
        if d < 1000:
            return
        self.letzter_ms = jetzt
        self.betrieb_s += d / 1000
        if self.test_aktiv:
            self.test_s += d / 1000
            m = int(self.test_s) // 600
            if m > self._test_gemeldet_min:          # alle 10 min eine Zeile in Thonny
                self._test_gemeldet_min = m
                print("Akku: Testlauf", dauer_text(self.test_s))

        rest = self.rest_h()
        if self.stufe < 1 and rest <= self.warnen_bei_h:
            self.stufe = 1
            self._melden("Akku laden - " + self.name,
                         "%s: Akku bald leer, noch ca. %d h. Bitte Powerbank laden." % (self.name, int(rest + 0.5)),
                         "high")
        if self.stufe < 2 and rest <= 1:
            self.stufe = 2
            self._melden("DRINGEND Akku laden - " + self.name,
                         "%s: Akku gleich leer (unter 1 h)! Jetzt Powerbank laden." % self.name,
                         "urgent")

        if darf_senden and self.offen and time.ticks_diff(jetzt, self.naechster_versuch) >= 0:
            self._senden_offen()
        alle = TEST_SPEICHERN_ALLE_S if self.test_aktiv else SPEICHERN_ALLE_S
        if time.ticks_diff(jetzt, self.gespeichert_ms) >= alle * 1000:
            self.speichern()

    # ------------------------------------------------------------- Bedienung
    def geladen(self):
        if self.betrieb_h() >= 1:
            self.letzte_laufzeit_h = round(self.betrieb_h(), 1)
        self.betrieb_s = 0.0
        self.stufe = 0
        self.offen = None
        self.letzte_meldung = None
        self.speichern()
        print("Akku:", self.name, "- geladen, Zaehler zurueckgesetzt.")
        return "%s: Akku geladen, Zähler steht wieder auf null." % self.name

    # ------------------------------------------------------------- Testlauf
    def testlauf_start(self):
        if self.test_aktiv:
            return "Testlauf läuft schon (%s)." % dauer_text(self.test_s)
        self.test_aktiv = True
        self.test_s = 0.0
        self._test_gemeldet_min = 0
        self.speichern()
        print("Akku:", self.name, "- Testlauf gestartet.")
        return "Testlauf gestartet. Die Uhr läuft, bis du ihn beendest oder die Powerbank leer ist."

    def testlauf_stop(self, leer=False):
        if not self.test_aktiv:
            return "Es läuft kein Testlauf."
        self.test_aktiv = False
        self.letzter_test_s = int(self.test_s)
        self.letzter_test_leer = leer
        self.speichern()
        print("Akku:", self.name, "- Testlauf beendet nach", dauer_text(self.test_s))
        return "Testlauf beendet nach %s." % dauer_text(self.test_s)

    def testlauf_uebernehmen(self):
        if not self.letzter_test_s or self.letzter_test_s < 600:
            return False, "Noch kein Testlauf mit mindestens 10 min."
        h = round(self.letzter_test_s / 3600, 1)
        self.einstellen(laufzeit_h=h)
        return True, "Laufzeit auf %.1f h gesetzt (aus dem letzten Testlauf)." % h

    def einstellen(self, laufzeit_h=None, warnen_bei_h=None, ntfy_thema=None):
        if ntfy_thema is not None:
            # Auf der Akkuseite eintragbar - so muss niemand dafuer ins Programm.
            t = "".join(z for z in str(ntfy_thema).strip() if ord(z) < 128 and (z.isalpha() or z.isdigit() or z in "-_"))[:64]
            self.ntfy_thema = t
        if laufzeit_h is not None and float(laufzeit_h) > 0:
            self.laufzeit_h = float(laufzeit_h)
        if warnen_bei_h is not None and float(warnen_bei_h) >= 0:
            self.warnen_bei_h = float(warnen_bei_h)
        # Stufe neu bestimmen, damit nach dem Aendern richtig (nicht doppelt) gewarnt wird
        rest = self.rest_h()
        self.stufe = 2 if rest <= 1 else 1 if rest <= self.warnen_bei_h else 0
        self.speichern()

    def test(self):
        """Testnachricht sofort senden. Gibt Text fuer Seite/Siri zurueck."""
        if not self.ntfy_thema:
            return False, "Kein ntfy-Thema eingetragen - Push ist aus."
        ok, info = self._senden("Test - " + self.name,
                                "%s: Testnachricht. Akku noch ca. %d h." % (self.name, int(self.rest_h() + 0.5)),
                                "default")
        return ok, ("Testnachricht gesendet." if ok else "Senden fehlgeschlagen: " + info)

    # ------------------------------------------------------------- Push
    def _melden(self, titel, text, prio):
        print("Akku:", text)
        self.letzte_meldung = text
        if self.ntfy_thema:
            self.offen = (titel, text, prio)
            self.naechster_versuch = time.ticks_ms()

    def _senden_offen(self):
        titel, text, prio = self.offen
        ok, info = self._senden(titel, text, prio)
        if ok:
            self.offen = None
        else:
            print("Akku: Push nicht gesendet (" + info + ") - neuer Versuch in", NEUVERSUCH_S, "s")
            self.naechster_versuch = time.ticks_add(time.ticks_ms(), NEUVERSUCH_S * 1000)

    def _senden(self, titel, text, prio):
        if not _wlan_ok():
            return False, "kein Heim-WLAN/Internet"
        try:
            import requests
        except ImportError:
            import urequests as requests
        gc.collect()                               # TLS braucht ein Stueck freien Speicher
        kopf = {"Title": _ascii(titel), "Priority": prio, "Tags": "battery"}
        url = self.ntfy_server + "/" + self.ntfy_thema
        try:
            try:
                r = requests.post(url, data=text.encode(), headers=kopf, timeout=8)
            except TypeError:                      # aeltere Firmware ohne timeout
                r = requests.post(url, data=text.encode(), headers=kopf)
            code = r.status_code
            r.close()
        except MemoryError:
            gc.collect()
            return False, "zu wenig Arbeitsspeicher (ggf. ntfy_server=\"http://ntfy.sh\" probieren)"
        except Exception as fehler:
            return False, str(fehler)
        gc.collect()
        if 200 <= code < 300:
            print("Akku: Push gesendet:", titel)
            return True, "ok"
        return False, "HTTP %d" % code

    # ------------------------------------------------------------- Speichern
    def speichern(self):
        self.gespeichert_ms = time.ticks_ms()
        daten = {"betrieb_s": int(self.betrieb_s), "stufe": self.stufe,
                 "laufzeit_h": self.laufzeit_h, "warnen_bei_h": self.warnen_bei_h,
                 "letzte_laufzeit_h": self.letzte_laufzeit_h, "ntfy_thema": self.ntfy_thema,
                 "test_aktiv": self.test_aktiv, "test_s": int(self.test_s),
                 "letzter_test_s": self.letzter_test_s, "letzter_test_leer": self.letzter_test_leer,
                 "uhr": time.time()}
        try:
            with open(DATEI + ".neu", "w") as f:
                json.dump(daten, f)
            try:
                os.remove(DATEI)
            except OSError:
                pass
            os.rename(DATEI + ".neu", DATEI)
        except OSError as fehler:
            print("Akku: Speichern fehlgeschlagen:", fehler)

    def _laden(self):
        for name in (DATEI, DATEI + ".neu"):
            try:
                with open(name) as f:
                    d = json.load(f)
            except (OSError, ValueError):
                continue
            self.betrieb_s = float(d.get("betrieb_s", 0))
            self.stufe = int(d.get("stufe", 0))
            self.laufzeit_h = float(d.get("laufzeit_h", self.laufzeit_h))
            self.warnen_bei_h = float(d.get("warnen_bei_h", self.warnen_bei_h))
            self.letzte_laufzeit_h = d.get("letzte_laufzeit_h")
            if d.get("ntfy_thema") is not None:      # auf der Seite eingetragen: gilt vor main.py
                self.ntfy_thema = d["ntfy_thema"]
            self.letzter_test_s = d.get("letzter_test_s")
            self.letzter_test_leer = bool(d.get("letzter_test_leer", False))
            vorbei = None
            try:
                vorbei = time.time() - int(d.get("uhr"))
            except (TypeError, ValueError):
                pass
            if d.get("test_aktiv") and vorbei is not None and 0 <= vorbei <= TEST_WEITER_NACH_NEUSTART_S:
                # Nur neu gestartet, Strom war nicht weg: Test laeuft weiter.
                self.test_aktiv = True
                self.test_s = float(d.get("test_s", 0)) + vorbei
                self._test_gemeldet_min = int(self.test_s) // 600
                print("Akku: Testlauf laeuft nach dem Neustart weiter (%s)." % dauer_text(self.test_s))
            elif d.get("test_aktiv"):
                # Der Testlauf lief noch, als der Strom wegging: die Powerbank ist leer
                # gelaufen. Die zuletzt gespeicherte Dauer ist das Ergebnis (auf 1 min genau).
                self.letzter_test_s = int(d.get("test_s", 0))
                self.letzter_test_leer = True
                print("Akku: letzter Testlauf endete mit leerer Powerbank nach",
                      dauer_text(self.letzter_test_s))
                self.speichern()
            return

    # ------------------------------------------------------------- Webseite
    def anfrage(self, methode, pfad, werte, rumpf=b""):
        """Fuer den Webserver des Projekts. Gibt (code, inhalt, art) zurueck oder None,
        wenn die Adresse nicht zum Akku gehoert."""
        if not pfad.startswith("/akku"):
            return None
        if methode == "GET" and pfad == "/akku/status":
            return 200, json.dumps(self.status()), "application/json"
        if methode == "GET" and pfad == "/akku/geladen":           # auch fuer Siri
            return 200, self.geladen(), "text/plain"
        if methode == "GET" and pfad == "/akku/test":
            ok, text = self.test()
            return (200 if ok else 409), text, "text/plain"
        if methode == "GET" and pfad == "/akku/testlauf/start":
            return 200, self.testlauf_start(), "text/plain"
        if methode == "GET" and pfad == "/akku/testlauf/stop":
            return 200, self.testlauf_stop(), "text/plain"
        if methode == "GET" and pfad == "/akku/testlauf/uebernehmen":
            ok, text = self.testlauf_uebernehmen()
            return (200 if ok else 409), text, "text/plain"
        if methode == "GET" and pfad == "/akku/rest":               # Siri: "Wie voll ist der Akku?"
            n = int(self.rest_h() + 0.5)
            dauer = "unter einer Stunde" if n < 1 else "eine Stunde" if n == 1 else "%d Stunden" % n
            return 200, "%s: Akku noch ca. %s." % (self.name, dauer), "text/plain"
        if methode == "POST" and pfad == "/akku/einstellen":
            try:
                d = json.loads(rumpf or b"{}")
                self.einstellen(d.get("laufzeit_h"), d.get("warnen_bei_h"), d.get("ntfy_thema"))
            except (ValueError, TypeError):
                return 400, "Zahl erwartet", "text/plain"
            return 200, json.dumps(self.status()), "application/json"
        return 404, "Unbekannt. Beispiel: /akku/geladen", "text/plain"
