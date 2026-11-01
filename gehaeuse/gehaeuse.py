#!/usr/bin/env python3
# OpenCCU Gartenfeuchtemesser - wasserdichtes Gehaeuse (Erzeuger fuer die STL-Dateien)
#
# Gleiche Konstruktion und gleiche Masse wie gehaeuse.scad. Wer nur Masse aendern will,
# nimmt am einfachsten gehaeuse.scad in OpenSCAD. Dieses Skript braucht die Python-Bibliothek
# manifold3d (pip install manifold3d) und schreibt gehaeuse_unterteil.stl und gehaeuse_deckel.stl.
#
# Achsen: X = Breite, Y = Laenge (bei der Montage senkrecht, Kabel unten), Z = Tiefe
# (Boden liegt an der Wand, Deckel zeigt nach vorn). Alle Masse in mm.

import struct
import sys

import manifold3d as m
from manifold3d import CrossSection, JoinType, Manifold

m.set_circular_segments(64)

# ---------------------------------------------------------------- Masse (wie gehaeuse.scad)
AKKU = (56.8, 51, 14.5)    # Akkupack Laenge x Breite x Hoehe: 4,8 V NiMH, 4 x AA nebeneinander, liegt flach
AKKU_LUFT = 1.0            # Spiel rundum im Akkuschacht
PICO_ZONE_B = 28           # Breite des Pico-Fachs (Pico W ist 21 mm breit)
TRENN = 2.0                # Trennwand Pico-Fach / Akkuschacht
INNEN_L = 86               # Innenlaenge: Kabelverschraubung unten, Pico W (51 mm), oben 25 mm fuer den USB-Stecker
INNEN_H = 28               # Innenhoehe (Pico mit Kabeln, Mutter der PG7)
WAND = 2.5
BODEN = 3.0
R_AUSSEN = 4.0             # Eckenradius aussen
R_FLANSCH = 5.0            # Eckenradius des Dichtrands (groesser schneidet die Eckschrauben ab)

FLANSCH = 10.0             # Dichtrand ragt so weit ueber die Aussenwand
FLANSCH_DICKE = 6.0        # gerader Teil des Dichtrands
# Rundschnur 3 mm: Nut 3,6 breit, 2,2 tief -> ca. 27 % Verpressung
NUT_B = 3.6
NUT_T = 2.2
NUT_ABST = 3.8             # Nutmitte ab Innenkante
SCHRAUBE_ABST = 9.2        # Schraubenmitte ab Innenkante (ausserhalb der Nut)
SCHRAUBE_ECKE_EIN = 1.2    # Eckschrauben etwas nach innen (diagonal)
SCHRAUBE_KERN = 2.6        # Kernloch fuer M3-Blechschraube (Einschmelzmutter: 4,0)
SCHRAUBE_TIEFE = 9.0
SCHRAUBE_DURCH = 3.4       # Durchgang im Deckel

DECKEL_D = 4.0
DECKEL_KRAGEN_H = 3.0      # Zentrierkragen, greift in den Innenraum
DECKEL_KRAGEN_W = 1.6
DECKEL_SPIEL = 0.3

LASCHE_B = 20              # Befestigungslaschen oben und unten
LASCHE_L = 24              # ab Aussenwand
LASCHE_D = 4.0
LASCHE_LOCH = 4.5          # fuer 4-mm-Holzschraube
LASCHE_SENK = 9.0          # Senkkopf
LASCHE_LOCH_ABST = 17      # Lochmitte ab Aussenwand

PG7_LOCH = 12.5            # Kabelverschraubung PG7 (M12x1,5: 12,2)
PG7_Z = 12                 # Hoehe der Lochmitte ueber dem Boden-Aussenmass
PG7_SITZ = 20              # flache Auflage aussen (die Fase des Dichtrands wird dort ausgespart)

PICO_LOCH_X = 11.4         # Lochabstand Pico W (quer)
PICO_LOCH_Y = 47.0         # Lochabstand Pico W (laengs)
PICO_STEG_H = 5.0
PICO_STEG_D = 5.0
PICO_STEG_LOCH = 1.8       # M2-Blechschraube
PICO_ABST_UNTEN = 10       # Pico-Unterkante ab Innenwand unten (Platz fuer die Mutter der PG7)
PICO_L = 51

TRENN_H = 16               # Trennwand niedriger als der Innenraum (Kabel drueber)

# ---------------------------------------------------------------- abgeleitete Masse
INNEN_B = PICO_ZONE_B + TRENN + AKKU[1] + 2 * AKKU_LUFT
assert INNEN_L >= AKKU[0] + 2 * AKKU_LUFT, "Akku zu lang fuer INNEN_L"
assert INNEN_H >= AKKU[2] + 1, "Akku zu hoch fuer INNEN_H"
AUSSEN_B = INNEN_B + 2 * WAND
AUSSEN_L = INNEN_L + 2 * WAND
KOERPER_H = BODEN + INNEN_H
R_INNEN = max(0.5, R_AUSSEN - WAND)


def rrect(b, l, r):
    """Abgerundetes Rechteck, mittig."""
    r = max(0.01, min(r, b / 2 - 0.01, l / 2 - 0.01))
    return CrossSection.square((b - 2 * r, l - 2 * r), True).offset(r, JoinType.Round)


def platte(b, l, r, h, z=0.0):
    return Manifold.extrude(rrect(b, l, r), h).translate((0, 0, z))


def zyl(d, h, x, y, z=0.0, d2=None):
    return Manifold.cylinder(h, d / 2, (d2 if d2 is not None else d) / 2).translate((x, y, z))


def rand_punkte(abst, n_quer=3, n_laengs=3):
    """Punkte auf dem Rechteck 'abst' ausserhalb der Innenkante: Ecken + Seitenmitten."""
    bx = INNEN_B / 2 + abst
    ly = INNEN_L / 2 + abst
    pkt = []
    e = SCHRAUBE_ECKE_EIN
    for i in range(n_quer):
        x = -bx + 2 * bx * i / (n_quer - 1)
        ecke = i in (0, n_quer - 1)
        xe = x - e if x > 0 and ecke else x + e if ecke else x
        ye = ly - e if ecke else ly
        pkt += [(xe, -ye), (xe, ye)]
    for j in range(1, n_laengs - 1):
        y = -ly + 2 * ly * j / (n_laengs - 1)
        pkt += [(-bx, y), (bx, y)]
    return pkt


def unterteil():
    flansch_b = AUSSEN_B + 2 * FLANSCH
    flansch_l = AUSSEN_L + 2 * FLANSCH
    z_flansch = KOERPER_H - FLANSCH_DICKE
    z_fase = z_flansch - FLANSCH            # 45-Grad-Fase: druckt ohne Stuetzen

    koerper = platte(AUSSEN_B, AUSSEN_L, R_AUSSEN, KOERPER_H)
    fase = Manifold.hull(
        platte(AUSSEN_B, AUSSEN_L, R_AUSSEN, 0.01, z_fase)
        + platte(flansch_b, flansch_l, R_FLANSCH, 0.01, z_flansch))
    rand = platte(flansch_b, flansch_l, R_FLANSCH, FLANSCH_DICKE, z_flansch)

    # Befestigungslaschen oben und unten (Y-Richtung), auf Bodenhoehe
    laschen = Manifold()
    for s in (-1, 1):
        y0 = s * (AUSSEN_L / 2 + LASCHE_L / 2 - R_AUSSEN / 2)
        laschen += platte(LASCHE_B, LASCHE_L + R_AUSSEN, 3, LASCHE_D).translate((0, y0, 0))

    teil = koerper + fase + rand + laschen

    # Innenraum
    teil -= platte(INNEN_B, INNEN_L, R_INNEN, INNEN_H + 1, BODEN)

    # Dichtnut (Rundschnur)
    nut_aussen = rrect(INNEN_B + 2 * (NUT_ABST + NUT_B / 2), INNEN_L + 2 * (NUT_ABST + NUT_B / 2),
                       R_INNEN + NUT_ABST + NUT_B / 2)
    nut_innen = rrect(INNEN_B + 2 * (NUT_ABST - NUT_B / 2), INNEN_L + 2 * (NUT_ABST - NUT_B / 2),
                      R_INNEN + NUT_ABST - NUT_B / 2)
    teil -= Manifold.extrude(nut_aussen - nut_innen, NUT_T + 1).translate((0, 0, KOERPER_H - NUT_T))

    # Schraubenloecher fuer den Deckel
    for x, y in rand_punkte(SCHRAUBE_ABST):
        teil -= zyl(SCHRAUBE_KERN, SCHRAUBE_TIEFE + 1, x, y, KOERPER_H - SCHRAUBE_TIEFE)

    # Laschenloecher mit Senkung
    for s in (-1, 1):
        y = s * (AUSSEN_L / 2 + LASCHE_LOCH_ABST)
        teil -= zyl(LASCHE_LOCH, LASCHE_D + 2, 0, y, -1)
        teil -= Manifold.hull(zyl(LASCHE_LOCH, 0.01, 0, y, LASCHE_D - (LASCHE_SENK - LASCHE_LOCH) / 2)
                              + zyl(LASCHE_SENK, 1, 0, y, LASCHE_D))

    # Kabelverschraubung PG7 unten (-Y), im Pico-Fach
    x_pico = -INNEN_B / 2 + PICO_ZONE_B / 2
    teil -= Manifold.cylinder(WAND * 4, PG7_LOCH / 2).rotate((90, 0, 0))\
        .translate((x_pico, -INNEN_L / 2 + WAND, PG7_Z))
    # flache Auflage fuer die Kabelverschraubung: Fase davor aussparen
    teil -= Manifold.cylinder(FLANSCH + 5, PG7_SITZ / 2).rotate((90, 0, 0))\
        .translate((x_pico, -AUSSEN_L / 2, PG7_Z))
    assert PG7_Z + PG7_SITZ / 2 < KOERPER_H - FLANSCH_DICKE, "Auflage PG7 schneidet in den Dichtrand"

    # Pico-Stege (Pico-Mitte so, dass unten die PG7-Mutter und oben der USB-Stecker Platz hat)
    y_pico = -INNEN_L / 2 + PICO_ABST_UNTEN + PICO_L / 2
    for dx in (-PICO_LOCH_X / 2, PICO_LOCH_X / 2):
        for dy in (-PICO_LOCH_Y / 2, PICO_LOCH_Y / 2):
            y = y_pico + dy
            steg = zyl(PICO_STEG_D, PICO_STEG_H + 0.5, x_pico + dx, y, BODEN - 0.5)
            steg -= zyl(PICO_STEG_LOCH, PICO_STEG_H + 1, x_pico + dx, y, BODEN)
            teil += steg

    # Trennwand mit Kabeldurchlass
    x_trenn = -INNEN_B / 2 + PICO_ZONE_B + TRENN / 2
    wand = Manifold.cube((TRENN, INNEN_L, TRENN_H + 0.5), True).translate((x_trenn, 0, BODEN + TRENN_H / 2))
    wand -= Manifold.cube((TRENN + 2, 12, 10), True).translate((x_trenn, INNEN_L / 4, BODEN + TRENN_H))
    teil += wand
    return teil


def deckel():
    flansch_b = AUSSEN_B + 2 * FLANSCH
    flansch_l = AUSSEN_L + 2 * FLANSCH
    d = platte(flansch_b, flansch_l, R_FLANSCH, DECKEL_D)
    kb = INNEN_B - 2 * DECKEL_SPIEL
    kl = INNEN_L - 2 * DECKEL_SPIEL
    kragen = platte(kb, kl, R_INNEN, DECKEL_KRAGEN_H + 0.01) \
        - platte(kb - 2 * DECKEL_KRAGEN_W, kl - 2 * DECKEL_KRAGEN_W, max(0.5, R_INNEN - DECKEL_KRAGEN_W),
                 DECKEL_KRAGEN_H + 1)
    # Deckel liegt mit der Aussenseite auf dem Druckbett: Kragen zeigt nach oben
    d += kragen.translate((0, 0, DECKEL_D))
    for x, y in rand_punkte(SCHRAUBE_ABST):
        d -= zyl(SCHRAUBE_DURCH, DECKEL_D + 2, x, y, -1)
    return d


def stl(teil, name):
    mesh = teil.to_mesh()
    v = mesh.vert_properties[:, :3]
    t = mesh.tri_verts
    with open(name, "wb") as f:
        f.write(b"OpenCCU Gartenfeuchtemesser".ljust(80, b" "))
        f.write(struct.pack("<I", len(t)))
        for a, b, c in t:
            p0, p1, p2 = v[a], v[b], v[c]
            n = [0.0, 0.0, 0.0]
            f.write(struct.pack("<12fH", *n, *p0, *p1, *p2, 0))
    bb = teil.bounding_box()
    print("%-28s %6d Dreiecke  %5.1f x %5.1f x %5.1f mm  %6.1f cm3" % (
        name, len(t), bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2], teil.volume() / 1000))


if __name__ == "__main__":
    ziel = sys.argv[1] if len(sys.argv) > 1 else "."
    u = unterteil()
    dk = deckel()
    assert u.status().name == "NoError" and dk.status().name == "NoError"
    print("Innenraum %d x %d x %d mm, Akkuschacht %.0f x %.0f mm" % (
        INNEN_B, INNEN_L, INNEN_H, AKKU[1] + 2 * AKKU_LUFT, INNEN_L))
    stl(u, ziel + "/gehaeuse_unterteil.stl")
    stl(dk, ziel + "/gehaeuse_deckel.stl")
