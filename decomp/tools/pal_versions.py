"""The five PAL discs and the few version constants the disc tools need.

Same game, built once per language (docs/pal_versions.md). Tools that read
the player's disc detect the version from SYSTEM.CNF; addresses come from
tools/version_map.py (checked by matching the referenced bytes).
"""
import re
from pathlib import Path

VERSIONS = {
    # serial: language, ENGINE1 address of the sprite decoder's distance table
    "SCES-00891": dict(lang="en", dist_table=0x8006AB4F),
    "SCES-00892": dict(lang="fr", dist_table=0x8006AB3F),
    "SCES-00893": dict(lang="de", dist_table=0x8006AB3B),
    "SCES-00894": dict(lang="it", dist_table=0x8006AB3B),
    "SCES-00895": dict(lang="es", dist_table=0x8006AB03),
}


def detect(files):
    """Serial of an extracted disc (its SYSTEM.CNF boot file), e.g. SCES-00891."""
    cnf = (Path(files) / "SYSTEM.CNF").read_text(errors="replace")
    m = re.search(r"cdrom:\\?(SCES)_(\d{3})\.(\d{2})", cnf)
    serial = f"{m[1]}-{m[2]}{m[3]}" if m else None
    if serial not in VERSIONS:
        raise SystemExit(f"{files}: not a known PAL Hercules disc ({serial})")
    return serial
