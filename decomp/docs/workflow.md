# Workflow: vom Disc-Abbild zum nativen Linux-Port

Stand 2026-10-12. Beschreibt, wie wir von der PS1-Fassung (SCES-00893) zu
einem nativen Linux-Port in 1080p kommen, ohne die Spiellogik zu verändern.
Ergänzt `docs/port_plan.md` (Grafik-Entscheidungen) und `docs/HANDOFF.md`
(Stand). Quellen am Ende; Aussagen über fremde Projekte stammen aus einer
Recherche vom 12.10.2026 und sollten vor einer Entscheidung selbst geprüft
werden.

## Grundidee: Hybrid aus Recompilation und Decompilation

| Weg | Was entsteht | Aufwand | Rolle bei uns |
|-----|--------------|---------|---------------|
| **Matching-Decomp** (GCC 2.7.2 + maspsx, byte-identisch) | lesbarer C-Code, beweisbar gleich | sehr hoch (Monate–Jahre) | Wahrheit über die Spiellogik, liefert Symbole/Typen |
| **Statische Recompilation** (MIPS → C, Befehl für Befehl) | unlesbarer, aber sofort lauffähiger C-Code | mittel (Wochen) | schneller Weg zu einem spielbaren Port |
| **Native Port auf PsyQ-Ersatz** (wie sotn-decomp/PsyZ, REDRIVER2/PsyCross) | sauberer C-Code ohne Emulation | braucht vollständige Decomp | Langfristziel |

Ablauf: **erst recompilieren** (spielbar), **dann Funktion für Funktion durch
decompilierten C-Code ersetzen**, am Ende den MIPS-Unterbau ganz entfernen.
Die Decomp läuft durchgehend parallel; jede fertige Funktion ersetzt ihr
recompiliertes Gegenstück. Für den Port muss eine Funktion nicht „matchen“ –
verhaltensgleich reicht; Matching bleibt aber der beste Beweis dafür.

Warum Hybrid: Alle PS1-Recompiler nennen dieselbe Schwachstelle –
Funktionsgrenzen, Sprungtabellen und Daten/Code-Trennung. Genau das liefert
unsere splat-Zerlegung. Umgekehrt dauert eine reine Decomp zu lange, bis man
überhaupt etwas spielen kann.

---

## Phase 0 – Grundlagen (größtenteils erledigt)

- [x] Disc entpackt (`files/`), Startdatei byte-identisch baubar (`make`).
- [x] Werkzeuge: GCC 2.7.2-psx, maspsx 2.34, splat, m2c, permuter, objdiff.
- [x] ENGINE1 mit splat zerlegt (nur Assembler).
- [x] Formate: Level, Sprites, Videos, Vollbilder.
- [x] HD-Grafik-Pipeline: Level-Texturen (HDcube), Sprites (DAT2 + `sprite_palettize.py`),
      Zerlegung in hochgeladene Blöcke (`sprite_cells.py`, Prüfwert je Block).
- [ ] **objdiff-Fortschrittsbericht** einrichten (`objdiff.json` per Skript, Kategorien
      `game`/`sdk`, `objdiff-cli report generate`); optional decomp.dev. Billig, zeigt Fortschritt.

## Phase 1 – Alles zerlegen

Ziel: jede ausführbare Datei und jedes Overlay als splat-Projekt mit
Funktionsgrenzen, Symbolen und Ladeadresse.

1. **Ladeadressen bestimmen.** ENGINE1/ENGINE3/TITLE werden zur Laufzeit an
   dieselbe Stelle geladen und gegeneinander getauscht; OV0–OV11 liegen im
   Overlay-Bereich über ENGINE1 (siehe `docs/level_format.md`, Zeiger im
   Level-Kopf). Lader-Funktionen in der Startdatei/ENGINE1 suchen (CD-Lesen +
   Sprung), Zieladressen notieren.
2. **splat-YAML je Datei**: `engine3.yaml`, `title.yaml`, `ov0.yaml` … nach dem
   Muster von `engine1.yaml` (gemeinsame `symbol_addrs.main.txt`, weil alle die
   PsyQ-Bibliothek in der Startdatei aufrufen).
   Option `make_full_disasm_for_code: True` für vollständige Zielobjekte (objdiff).
3. **PsyQ-Bibliothek erkennen.** PsyQ 3.7 per Signaturen identifizieren
   (ghidra_psx_ldr oder xsig) und benennen. Diese Funktionen werden im Port
   nicht recompiliert, sondern durch eigene Implementierungen ersetzt
   (GPU/SPU/CD/Pad/Speicherkarte).
4. **Sprungtabellen und Funktionszeiger** markieren. Achtung: GCC legt das
   `sll` oft in den Delay-Slot vor dem `jr` – einfache Muster-Erkenner
   übersehen das.
5. **Ergebnis prüfen:** jede Datei baut wieder byte-identisch (`make check`
   pro Datei).

**Stand 12.10.:** Schritte 1, 2 und 5 erledigt. `make check-all` baut alle
16 Dateien byte-identisch (Startdatei, ENGINE1/3, TITLE, OV0–OV11).

| Datei | Ladeadresse | Code | Daten ab | Funktionen |
|-------|-------------|------|----------|-----------:|
| ENGINE1 | 0x80038350 | 0x800 | 0x32138 | 627 |
| ENGINE3 | 0x80038350 | 0x800 | 0x29B28 | 536 |
| TITLE | 0x80038350 | 0x800 | 0x2D13C | 456 |
| OV0 (Level 0) | 0x80074A4C | – | 0x0 | 0 |
| OV1, 3, 5, 6, 7, 9, 11 | 0x80074A4C (über ENGINE1) | nach Sprungtabellen | nach letztem `jr ra` | 20–152 |
| OV2, 8, 10 | 0x800684A0 (über ENGINE3) | 0xC0 / 0x1B0 / 0x120 | nach letztem `jr ra` | 71–102 |
| OV4 | 0x80074A4C | Stummel (`jr ra`) | – | 1 |

Ladeadressen der Overlays: die Basis, bei der die meisten `jal`-Ziele im
Overlay auf `addiu sp,sp,-x` treffen; stimmt mit den Zeigern der
ENGINE1-Level-Tabelle überein. OV10 ruft nichts in sich selbst auf, Basis
von OV2/OV8 übernommen. Welche Engine: die `jal`-Ziele unter dem Overlay
treffen Funktionsanfänge nur in einer der beiden Engines.
Fallen: Overlay-Basis nicht 16-ausgerichtet (`ld_align_*: False`), OV1-Größe
nicht durch 4 teilbar (`bin`-Rest), PsyQ-Startnamen (`__main`, `stup0–2`)
gibt es in Startdatei und ENGINE1 (in ENGINE1 mit Präfix `engine1_`).
Die Funktionszahlen der Engines enthalten deren eigene PsyQ-Kopien.

Ausgabe: vollständige Funktionsliste mit Adressen, Größen, Namen (soweit
bekannt) – die Eingabe für Phase 2.

## Phase 2 – Recompiler (MIPS → C)

Zwei Möglichkeiten; Entscheidung nach einem kurzen Test (Phase 2a).

### 2a – Test mit einem bestehenden Recompiler

Kandidaten (Recherche 12.10.2026, selbst prüfen):

| Projekt | Stand | Passt | Haken |
|---------|-------|-------|-------|
| **PSXRecomp** (RetroPortingToolKit) | am weitesten; mehrere Spiele laufen | Linux, SDL3/OpenGL, PGXP-artige Präzision bei ganzzahliger Spiellogik, Supersampling, **HD-Pakete im DuckStation-Format** (passt zu unserem Adapter), Overlays per Inhalts-Hash | Lizenz nicht-kommerziell (für Fan-Projekt ok), großer Code, PAL/50 Hz unklar |
| **RecompOne** | SotN-Port (SymphonyRecomp) darauf | MIT, nutzt Decomp/ELF-Symbole | C#/.NET; Autor schließt KI-erstellte Ports ausdrücklich aus |
| **PS1Recomp** | Prototyp (Abschlussarbeit) | gute Idee: PsyQ per Signatur → HLE | zu unreif |

Test: Startdatei + ENGINE1 + ein Level-Overlay einspeisen, Ziel „Titelbild
erscheint“ bzw. „Level 1 startet“. Prüfen: PAL-Timing (50 Hz), Overlay-Tausch,
Grafikfehler.

### 2b – Eigener schlanker Recompiler (falls 2a nicht passt)

Nach dem Vorbild N64Recomp, gefüttert mit unseren splat-Daten:

- Disassembler: rabbitizer (wie splat/spimdisasm).
- Jede Funktion → eine C-Funktion `void f_80012474(Ctx* r)`; jeder Befehl → eine
  Zeile auf dem Registersatz (`r->v0 = r->a0 + r->a1;`).
- **Delay-Slots**: Befehl im Slot vor dem Sprung ausführen (Sprungbedingung
  vorher sichern).
- **Load-Delay** des R3000: im Spielcode selten relevant; bei Abweichungen
  gezielt nachbilden.
- **Sprungtabellen** → `switch`; **indirekte Aufrufe** → Nachschlagetabelle
  Adresse → Funktion, unbekannte Ziele protokollieren (später ergänzen).
- **Speicher**: 2 MB RAM + 1 KB Scratchpad (`0x1F800000`) als Byte-Arrays;
  Lese-/Schreibmakros mit Adressmaskierung (KSEG0/KSEG1).
- **Overlays**: weil wir alle Overlays und Ladeadressen kennen, werden sie
  vorab übersetzt (kein Einfangen zur Laufzeit nötig). Der Lader schaltet nur
  die aktive Funktionstabelle für den Overlay-Bereich um.
- **GTE (COP2)**: Befehle als Funktionsaufrufe (`gte_rtps(r)` …) in die
  Plattformschicht – dort sitzt die Float-Variante für 1080p (siehe Phase 3).
- **Hardware-Register** (`0x1F801xxx`) und BIOS-Aufrufe (`A0/B0/C0`) →
  Plattformschicht. Wo möglich PsyQ-Funktionen komplett ersetzen statt
  Register zu emulieren.

Prüfung: Lockstep-Vergleich gegen einen Emulator (gleiche Eingaben,
RAM-Abgleich pro Bild) für die ersten Level.

## Phase 3 – Plattformschicht

Wird für jeden Weg gebraucht (Recompilation und späterer nativer Port) und
ist der größte Brocken.

| Teil | Umsetzung | Hinweise |
|------|-----------|----------|
| Fenster/Eingabe | SDL3 | Gamepad + Tastatur, 4:3 mit Rändern |
| Grafik (GPU) | Renderer für PS1-Primitive (OT-Reihenfolge, kein Z-Buffer) in OpenGL/Vulkan | 1080p, scharfe Pixel, Nebel als 31 CLUT-Stufen, kein Dithering (`port_plan.md`) |
| GTE | Float-Implementierung der 27 bekannten Aufrufstellen in ENGINE1 (+ ENGINE3/Overlays) | Sub-Pixel-Positionen, perspektivisch korrekte Texturen (PGXP-artig); Spiellogik bekommt weiter ganzzahlige Werte |
| HD-Grafik | Ersetzung beim Hochladen in den VRAM, Schlüssel = Prüfwert | Sprites: `sprite_cells.py` (blake2b über Blockdaten + Palette); Level: Textur-ID aus `port_plan.md` |
| Sound (SPU) | SPU-Nachbildung oder PsyQ-SPU-Funktionen ersetzen | ADPCM-Samples, Hall |
| CD/XA/Videos | Dateien direkt aus `files/` lesen; XA-Audio und `MV/`-Videos dekodieren | |
| Zeit | 50 Hz Spiellogik (PAL) | höhere Bildraten nur mit Interpolation |
| Speicherkarte | Datei im Benutzerordner | |

Bestehende Bausteine zum Wiederverwenden prüfen: PsyZ (PsyQ-Ersatz für
sotn-decomp, SDL3, Overlays als Shared Libraries), PsyCross (PsyQ-Ersatz mit
PGXP, REDRIVER2/Silent Hill).

## Phase 4 – Decomp ersetzt Recompilation

Laufend, Funktion für Funktion:

1. Funktion mit m2c vorbereiten (`tools/auto_m2c.py`), matchen
   (`tools/try_func.py`, permuter zuletzt).
2. Im Port die recompilierte Fassung durch den C-Code ersetzen (gleicher
   Funktionsname/Adresse in der Nachschlagetabelle).
3. Lockstep-Test laufen lassen.

Priorität: was für Grafik und Port-Komfort zählt – Zeichenfunktionen,
GTE-Aufrufer (`port_plan.md`), Sprite-/Animationssystem, HUD/Schrift,
Kamera (16:9 später), Overlay-Lader.

Arbeitsweise beim Matchen (nach Lindholms -O2-Leitfaden, auf GCC übertragbar):
zuerst Daten nach C holen, alle Warnungen beseitigen und jeden Aufruf
deklarieren, dann Kontrollfluss, dann Umsortierungen, Registerbelegung und
permuter ganz zum Schluss.

**Regeln, damit decompilierter Code später nativ (64-bit) läuft** (aus dem
PsyZ-Portierungsleitfaden):
- keine überlappenden `D_`-Symbole – Arrays statt `D_800A1230[2]` + `D_800A1234`
- keine fest eingetragenen Adressen (`0x80xxxxxx`, Scratchpad `0x1F80xxxx`) im C-Code
- `u_long`, das 32-bit-Werte hält → `unsigned int`; OT-Zeiger mit eigenem Typ
- Overlay-Einsprünge über Kopf-/Funktionszeigertabellen, nicht über feste Adressen

## Phase 5 – Nativer Port ohne MIPS-Unterbau

Wenn (fast) alles decompiliert ist: Spielcode direkt gegen die
Plattformschicht bauen (wie sotn-decomp `src/pc` auf PsyZ). Danach Extras:
16:9 (FOV, Culling `func_8003AA08`, HUD), höhere Bildrate mit Interpolation,
neu gezeichnete Figuren.

---

## Zwischenschritt: Test im Emulator (jetzt möglich)

Unabhängig von den Phasen: das Original in DuckStation mit HD-Grafik.

1. HD-Sprites in Blöcke schneiden:
   `python3 tools/sprite_cells.py assets/sprites_hd/DAT2-schutz assets/sprite_cells/DAT2-schutz`
2. DuckStation: Einstellungen → Grafik → Texture Replacements → „Dump Textures“
   an; einige Minuten spielen, Spiel beenden (Dumps werden dann geschrieben).
   `textures/SCES-00893/config.yaml` senkt die Dump-Schwelle auf 8 px.
3. `python3 tools/sprite_duckstation.py assets/sprite_cells/DAT2-schutz`
   → `textures/SCES-00893/replacements/sprites/`
4. Dumping aus, Spiel neu starten.

Prüft nebenbei die Zerlege-Logik, die der Port später braucht.

## Reihenfolge der nächsten Schritte

1. ~~Emulator-Test mit HD-Sprites (oben)~~ – erledigt, Ergebnis in `HANDOFF.md` (3b).
2. objdiff-Bericht einrichten (Phase 0).
3. Ladeadressen + splat für ENGINE3, TITLE, OV0–OV11 (Phase 1).
4. PsyQ-Signaturen (Phase 1.3).
5. Recompiler-Test mit PSXRecomp (Phase 2a) → Entscheidung 2a/2b.
6. Plattformschicht schrittweise (Phase 3), Decomp parallel (Phase 4).

## Quellen

- Decompedia, PlayStation: https://decomp.wiki/platforms/playstation
  (Toolchain PsyQ/GCC, maspsx, ghidra_psx_ldr, psyq2elf, xsig)
- Decompedia, decomp.dev/objdiff: https://decomp.wiki/tools/decomp-dev
- decompilation.wiki (Decompiler-Grundlagen, Liste rekonstruierter Spiele):
  https://decompilation.wiki/ und /applications/program-reconstruction/
- Simon Lindholm, „-O2 decompilation (IDO)“: https://hackmd.io/vPmcgdaFSlq4R2mfkq4bJg
  (Vorgehensreihenfolge beim Matchen; Compiler-Details gelten für IDO, nicht GCC)
- PSXRecomp: https://github.com/RetroPortingToolKit/psxrecomp
- PS1Recomp: https://github.com/PS1Recomp/ps1-recomp
- RecompOne: https://github.com/BlackLabelHQ/RecompOne
- PsyZ: https://github.com/Xeeynamo/psyz · PsyCross: https://github.com/OpenDriver2/PsyCross
- maspsx: https://github.com/mkst/maspsx · decomp-permuter: https://github.com/simonlindholm/decomp-permuter
