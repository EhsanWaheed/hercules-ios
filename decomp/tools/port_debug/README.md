# Port-Testwerkzeuge (TCP-Debugserver von PSXRecomp)

Nur mit `HerculesRecomp/build-debugtools` (gebaut mit `-DPSX_DEBUG_TOOLS=ON`).
Start, unsichtbar mit OpenGL und eigenem Memory-Card-Ordner:

    cd ~/psx-decomp/HerculesRecomp/build-debugtools
    ./Hercules_Recompiled --no-launcher --headless-opengl --debug-port 4370 --memcard-dir /tmp/hc-mc &

- `dbg.py`      kleiner Client (eine Verbindung pro Befehl; der Server trennt
                nach Antworten). `python3 dbg.py start wait2 shot1 '{"cmd":"mod_counters"}'`
                Tasten: Namen aus `BTN`, `shotNAME` = Screenshot neben dem Skript.
- `ovstat.py`   Zähler des Overlay-Laders (nativ vs. Interpreter) + `p()` zum Drücken.
- `to_game.py`  vom Boot bis ins Spiel (Level 1) navigieren (~30 s).
- `herc_cmp.py` Screenshot 5× mit HD an/aus, Ausschnitt Herkules am Levelstart.

Nützliche Befehle: `hd_textures` (`replacements`, `dump`, `reload`),
`mod_counters`, `overlay_loader_status`, `overlay_static_entries`,
`screenshot_hires`, `vram_peek`, `read_ram`/`write_ram` (ein Byte), `quit`.
Level erzwingen: im Titel „Spiel starten“, dabei `0x80035048` laufend per
`write_ram` auf die Levelnummer setzen.
Spiel beenden: `{"cmd":"quit"}` (kein `pkill` mit Mustern, die in der eigenen
Kommandozeile vorkommen).
