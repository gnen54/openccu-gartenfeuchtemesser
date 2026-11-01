// OpenCCU Gartenfeuchtemesser - wasserdichtes Gehaeuse mit Akkuschacht (OpenSCAD)
//
// Zwei Teile: Unterteil (Pico-Fach + Akkuschacht) und Deckel. Abdichtung mit einer
// Rundschnur 3 mm (Silikon oder EPDM) in der Nut des Dichtrands, 8 Schrauben M3.
// Befestigung: zwei Laschen oben und unten fuer 4-mm-Schrauben.
// Kabel zum Sensor durch eine Kabelverschraubung PG7 (oder M12x1,5) unten.
//
// Aufbau: Boden liegt an der Wand/am Pfahl, Deckel zeigt nach vorn, Kabel nach UNTEN.
// Masse in mm. Unten "teil" waehlen, F6 (Rendern), F7 (STL exportieren).
// Die gleichen Masse stehen in gehaeuse.py (erzeugt die mitgelieferten STL-Dateien).

teil = "unterteil";   // "unterteil", "deckel" oder "beide"

/* [Akkupack] */
AKKU = [54, 32, 32];   // Laenge x Breite x Hoehe (4 x AA als 2x2-Block) - an deinen Akku anpassen!
AKKU_LUFT = 1.0;       // Spiel rundum

/* [Innenraum] */
PICO_ZONE_B = 28;      // Breite Pico-Fach
TRENN = 2.0;           // Trennwand
INNEN_L = 86;          // Kabelverschraubung unten, Pico 51 mm, oben 25 mm fuer USB-Stecker
INNEN_H = 36;
WAND = 2.5;
BODEN = 3.0;
R_AUSSEN = 4.0;

/* [Dichtrand] */
FLANSCH = 10.0;        // ragt so weit ueber die Aussenwand
FLANSCH_DICKE = 6.0;
R_FLANSCH = 5.0;
NUT_B = 3.6;           // Rundschnur 3 mm -> ca. 27 % Verpressung
NUT_T = 2.2;
NUT_ABST = 3.8;        // Nutmitte ab Innenkante
SCHRAUBE_ABST = 9.2;   // Schraubenmitte ab Innenkante
SCHRAUBE_ECKE_EIN = 1.2;
SCHRAUBE_KERN = 2.6;   // M3-Blechschraube; Einschmelzmutter M3: 4.0
SCHRAUBE_TIEFE = 9.0;
SCHRAUBE_DURCH = 3.4;

/* [Deckel] */
DECKEL_D = 4.0;
DECKEL_KRAGEN_H = 3.0;
DECKEL_KRAGEN_W = 1.6;
DECKEL_SPIEL = 0.3;

/* [Befestigung] */
LASCHE_B = 20;
LASCHE_L = 24;
LASCHE_D = 4.0;
LASCHE_LOCH = 4.5;
LASCHE_SENK = 9.0;
LASCHE_LOCH_ABST = 17;

/* [Kabel und Pico] */
PG7_LOCH = 12.5;       // PG7; M12x1,5: 12.2
PG7_Z = 12;
PICO_LOCH_X = 11.4;
PICO_LOCH_Y = 47.0;
PICO_STEG_H = 5.0;
PICO_STEG_D = 5.0;
PICO_STEG_LOCH = 1.8;
PICO_ABST_UNTEN = 10;
PICO_L = 51;
TRENN_H = 22;

$fn = 64;

INNEN_B = PICO_ZONE_B + TRENN + AKKU[1] + 2 * AKKU_LUFT;
AUSSEN_B = INNEN_B + 2 * WAND;
AUSSEN_L = INNEN_L + 2 * WAND;
KOERPER_H = BODEN + INNEN_H;
R_INNEN = max(0.5, R_AUSSEN - WAND);
FL_B = AUSSEN_B + 2 * FLANSCH;
FL_L = AUSSEN_L + 2 * FLANSCH;

assert(INNEN_L >= AKKU[0] + 2 * AKKU_LUFT, "Akku zu lang fuer INNEN_L");
assert(INNEN_H >= AKKU[2] + 1, "Akku zu hoch fuer INNEN_H");

module rrect(b, l, r) {
    rr = max(0.01, min(r, b / 2 - 0.01, l / 2 - 0.01));
    offset(r = rr) square([b - 2 * rr, l - 2 * rr], center = true);
}
module platte(b, l, r, h, z = 0) {
    translate([0, 0, z]) linear_extrude(h) rrect(b, l, r);
}

// Ecken + Seitenmitten im Abstand "abst" von der Innenkante
function rand_punkte(abst) =
    let(bx = INNEN_B / 2 + abst, ly = INNEN_L / 2 + abst, e = SCHRAUBE_ECKE_EIN)
    [[-bx + e, -ly + e], [0, -ly], [bx - e, -ly + e],
     [-bx + e,  ly - e], [0,  ly], [bx - e,  ly - e],
     [-bx, 0], [bx, 0]];

module unterteil() {
    z_flansch = KOERPER_H - FLANSCH_DICKE;
    z_fase = z_flansch - FLANSCH;          // 45-Grad-Fase: druckt ohne Stuetzen
    x_pico = -INNEN_B / 2 + PICO_ZONE_B / 2;
    y_pico = -INNEN_L / 2 + PICO_ABST_UNTEN + PICO_L / 2;
    x_trenn = -INNEN_B / 2 + PICO_ZONE_B + TRENN / 2;

    difference() {
        union() {
            platte(AUSSEN_B, AUSSEN_L, R_AUSSEN, KOERPER_H);
            hull() {
                platte(AUSSEN_B, AUSSEN_L, R_AUSSEN, 0.01, z_fase);
                platte(FL_B, FL_L, R_FLANSCH, 0.01, z_flansch);
            }
            platte(FL_B, FL_L, R_FLANSCH, FLANSCH_DICKE, z_flansch);
            for (s = [-1, 1])
                translate([0, s * (AUSSEN_L / 2 + LASCHE_L / 2 - R_AUSSEN / 2), 0])
                    platte(LASCHE_B, LASCHE_L + R_AUSSEN, 3, LASCHE_D);
        }
        // Innenraum
        platte(INNEN_B, INNEN_L, R_INNEN, INNEN_H + 1, BODEN);
        // Dichtnut
        translate([0, 0, KOERPER_H - NUT_T]) linear_extrude(NUT_T + 1) difference() {
            rrect(INNEN_B + 2 * (NUT_ABST + NUT_B / 2), INNEN_L + 2 * (NUT_ABST + NUT_B / 2),
                  R_INNEN + NUT_ABST + NUT_B / 2);
            rrect(INNEN_B + 2 * (NUT_ABST - NUT_B / 2), INNEN_L + 2 * (NUT_ABST - NUT_B / 2),
                  R_INNEN + NUT_ABST - NUT_B / 2);
        }
        // Schraubenloecher Deckel
        for (p = rand_punkte(SCHRAUBE_ABST))
            translate([p[0], p[1], KOERPER_H - SCHRAUBE_TIEFE])
                cylinder(h = SCHRAUBE_TIEFE + 1, d = SCHRAUBE_KERN);
        // Laschenloecher mit Senkung (Schraubenkopf vorn)
        for (s = [-1, 1]) translate([0, s * (AUSSEN_L / 2 + LASCHE_LOCH_ABST), 0]) {
            translate([0, 0, -1]) cylinder(h = LASCHE_D + 2, d = LASCHE_LOCH);
            translate([0, 0, LASCHE_D - (LASCHE_SENK - LASCHE_LOCH) / 2])
                cylinder(h = (LASCHE_SENK - LASCHE_LOCH) / 2 + 1, d1 = LASCHE_LOCH,
                         d2 = LASCHE_SENK + 2);
        }
        // Kabelverschraubung unten (-Y), im Pico-Fach
        translate([x_pico, -INNEN_L / 2 + WAND, PG7_Z]) rotate([90, 0, 0])
            cylinder(h = WAND * 4, d = PG7_LOCH);
    }
    // Pico-Stege
    for (dx = [-PICO_LOCH_X / 2, PICO_LOCH_X / 2], dy = [-PICO_LOCH_Y / 2, PICO_LOCH_Y / 2])
        translate([x_pico + dx, y_pico + dy, BODEN - 0.5]) difference() {
            cylinder(h = PICO_STEG_H + 0.5, d = PICO_STEG_D);
            translate([0, 0, 0.5]) cylinder(h = PICO_STEG_H + 1, d = PICO_STEG_LOCH);
        }
    // Trennwand mit Kabeldurchlass
    difference() {
        translate([x_trenn, 0, BODEN + TRENN_H / 2]) cube([TRENN, INNEN_L, TRENN_H + 0.5], center = true);
        translate([x_trenn, INNEN_L / 4, BODEN + TRENN_H]) cube([TRENN + 2, 12, 10], center = true);
    }
}

module deckel() {
    kb = INNEN_B - 2 * DECKEL_SPIEL;
    kl = INNEN_L - 2 * DECKEL_SPIEL;
    difference() {
        union() {
            platte(FL_B, FL_L, R_FLANSCH, DECKEL_D);
            // Zentrierkragen (Deckel liegt aussen auf dem Druckbett, Kragen zeigt nach oben)
            translate([0, 0, DECKEL_D]) difference() {
                platte(kb, kl, R_INNEN, DECKEL_KRAGEN_H);
                platte(kb - 2 * DECKEL_KRAGEN_W, kl - 2 * DECKEL_KRAGEN_W,
                       max(0.5, R_INNEN - DECKEL_KRAGEN_W), DECKEL_KRAGEN_H + 1, -0.5);
            }
        }
        for (p = rand_punkte(SCHRAUBE_ABST))
            translate([p[0], p[1], -1]) cylinder(h = DECKEL_D + 2, d = SCHRAUBE_DURCH);
    }
}

if (teil == "unterteil") unterteil();
else if (teil == "deckel") deckel();
else { unterteil(); translate([FL_B + 10, 0, 0]) deckel(); }
