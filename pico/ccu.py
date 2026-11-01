# OpenCCU-Anbindung - Systemvariablen per Homematic-Script setzen
# fuer Raspberry Pi Pico W / Pico 2 W (MicroPython) UND Raspberry Pi (Python 3).
#
# Weg: HTTP-POST an die "Remote Homematic-Script API" der OpenCCU
#   http://<ccu>:8181/tclrega.exe      (mit TLS: https://<ccu>:48181/tclrega.exe)
# Im Rumpf steht ein kurzes Homematic-Script, das die Systemvariablen setzt. Die Antwort
# ist XML und enthaelt am Ende die Variablen des Skripts - daran sieht man, ob alles
# geklappt hat und welche Systemvariable in der OpenCCU fehlt.
#
# In der OpenCCU freischalten: Einstellungen -> Systemsteuerung -> Firewall-Konfiguration
#   "Remote Homematic-Script API": "Eingeschraenkt" + die IP des Messers (oder ihr Netz)
#   bei "IP-Adressen fuer den eingeschraenkten Zugriff" eintragen.
# Ist unter Systemsteuerung -> Sicherheit die "Authentifizierung" an, braucht es Benutzer
# und Passwort eines WebUI-Benutzers (CCU_BENUTZER / CCU_PASSWORT in main.py).
#
# Keine Zusatzsoftware (XML-API, CUxD) noetig.

try:
    import ubinascii as binascii
except ImportError:
    import binascii

ZEIT = "zeit"     # besonderer Wert: Uhrzeit der OpenCCU eintragen (z. B. "01.11. 05:10")


def _rega_text(s):
    """Text fuer ein Homematic-Script-Literal: nur einfache Zeichen, keine Anfuehrungszeichen."""
    s = str(s)
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("Ä", "Ae"), ("Ö", "Oe"), ("Ü", "Ue"),
                 ("ß", "ss")):
        s = s.replace(a, b)
    return "".join(z for z in s if 32 <= ord(z) < 127 and z not in "\"\\")


def _wert(w, vorsatz=""):
    if w is ZEIT:
        v = _rega_text(vorsatz)
        return ('"%s" # system.Date("%%d.%%m. %%H:%%M")' % v) if v else 'system.Date("%d.%m. %H:%M")'
    if isinstance(w, bool):                 # bool vor int pruefen (bool ist auch int)
        return "true" if w else "false"
    if isinstance(w, (int, float)):
        return "%.1f" % w
    return '"%s"' % _rega_text(w)


def skript(werte):
    """werte: Liste von (name, wert) oder (name, wert, vorsatz).
    wert = Zahl, True/False, Text oder ccu.ZEIT (Uhrzeit der CCU, ggf. mit Vorsatz).
    Gibt das Homematic-Script als Text zurueck."""
    zeilen = ["object o;", 'string fehlt = "";', "integer gesetzt = 0;"]
    for eintrag in werte:
        name, w = eintrag[0], eintrag[1]
        vorsatz = eintrag[2] if len(eintrag) > 2 else ""
        n = _rega_text(name)
        zeilen.append('o = dom.GetObject(ID_SYSTEM_VARIABLES).Get("%s");' % n)
        zeilen.append('if (o) { o.State(%s); gesetzt = gesetzt + 1; } else { fehlt = fehlt # "%s;"; }'
                      % (_wert(w, vorsatz), n))
    return "\n".join(zeilen) + "\n"


def _xml_feld(text, feld):
    a = text.find("<" + feld + ">")
    if a < 0:
        return None
    a += len(feld) + 2
    e = text.find("</" + feld + ">", a)
    return text[a:e] if e >= 0 else None


def auswerten(antwort, anzahl):
    """Antwort von tclrega.exe pruefen. Gibt (ok, info, fehlende_namen) zurueck."""
    gesetzt = _xml_feld(antwort, "gesetzt")
    fehlt = _xml_feld(antwort, "fehlt")
    if gesetzt is None:
        return False, "Antwort der OpenCCU ohne Ergebnis (Skriptfehler?)", []
    fehlend = [n for n in (fehlt or "").split(";") if n]
    try:
        g = int(gesetzt)
    except ValueError:
        g = -1
    if fehlend:
        return False, "Systemvariable fehlt in der OpenCCU: " + ", ".join(fehlend), fehlend
    if g != anzahl:
        return False, "nur %d von %d Werten gesetzt" % (g, anzahl), []
    return True, "ok", []


def senden(ip, werte, port=8181, benutzer="", passwort="", https=False, timeout=8):
    """Werte an die OpenCCU schicken. Gibt (ok, info, fehlende_namen) zurueck."""
    if not ip:
        return False, "keine OpenCCU eingetragen", []
    text = skript(werte)
    url = "%s://%s:%d/tclrega.exe" % ("https" if https else "http", ip, port)
    kopf = {"Content-Type": "text/plain"}
    if benutzer:
        z = binascii.b2a_base64(("%s:%s" % (benutzer, passwort)).encode()).decode().strip()
        kopf["Authorization"] = "Basic " + z
    try:
        antwort, code = _post(url, text.encode(), kopf, timeout)
    except Exception as fehler:
        return False, "OpenCCU nicht erreichbar (%s)" % fehler, []
    if code == 401:
        return False, "OpenCCU verlangt Anmeldung - CCU_BENUTZER/CCU_PASSWORT pruefen", []
    if code == 403:
        return False, "OpenCCU lehnt ab (Firewall: Remote Homematic-Script API freigeben)", []
    if code != 200:
        return False, "OpenCCU antwortet HTTP %d" % code, []
    return auswerten(antwort, len(werte))


def _post(url, daten, kopf, timeout):
    try:                                       # MicroPython (Pico W)
        try:
            import requests
        except ImportError:
            import urequests as requests
        if not hasattr(requests, "post"):
            raise ImportError
    except ImportError:
        requests = None
    if requests is not None and not hasattr(requests, "Session"):
        import gc
        gc.collect()
        try:
            r = requests.post(url, data=daten, headers=kopf, timeout=timeout)
        except TypeError:                      # aeltere Firmware ohne timeout
            r = requests.post(url, data=daten, headers=kopf)
        try:
            return r.text, r.status_code
        finally:
            r.close()
            gc.collect()
    # Python 3 auf dem Raspberry Pi: nur Standardbibliothek
    import urllib.request
    import urllib.error
    import ssl
    anfrage = urllib.request.Request(url, data=daten, headers=kopf, method="POST")
    kontext = None
    if url.startswith("https"):                # OpenCCU hat meist ein selbst signiertes Zertifikat
        kontext = ssl.create_default_context()
        kontext.check_hostname = False
        kontext.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(anfrage, timeout=timeout, context=kontext) as r:
            return r.read().decode("latin-1"), r.status
    except urllib.error.HTTPError as e:
        return "", e.code
