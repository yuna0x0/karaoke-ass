#!/usr/bin/env python3
"""
Report the em size Aegisub and libass each assume for a font, and the factor
converting between them:

  libass  scales the face so  OS/2 usWinAscent + usWinDescent  == Fontsize
  Aegisub scales the face so  hhea ascender - descender + lineGap == Fontsize

The rules coincide for a font with lineGap 0 and win == hhea. For one with a
large lineGap they do not, and Aegisub then lays out syllables tighter than
libass draws them, so every wipe edge and ruby position drifts left.

  emfix = (hhea.asc - hhea.desc + hhea.lineGap) / (winAscent + winDescent)

The template derives this itself; `emfix` in the config line pins it.

Usage:  font_metrics.py "FOT-TsukuMin Pr6" ["Another Font" ...]
"""
import re
import struct
import sys

from . import _platform


def resolve(name):
    """Font family name -> (file, face index, declared families).

    Resolution lives in _platform.find_font: fontconfig when available, a scan
    of the system font directories otherwise. Note that a family MUST reach
    fontconfig as ':family=NAME', in a bare pattern a hyphen separates family
    from size, so "FOT-TsukuMin Pr6" would parse as family "FOT" at size
    "TsukuMin Pr6" and silently match something unrelated.
    """
    return _platform.find_font(name)


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def installed(requested, families):
    """True only if the matched font really is the one asked for."""
    return any(norm(requested) == norm(f) for f in families.split(","))


def tables(path, index=0):
    d = open(path, "rb").read()
    off = 0
    if d[:4] == b"ttcf":
        n, = struct.unpack(">I", d[8:12])
        if index >= n:
            index = 0
        off, = struct.unpack(">I", d[12 + 4 * index:16 + 4 * index])
    num, = struct.unpack(">H", d[off + 4:off + 6])
    t = {}
    for i in range(num):
        p = off + 12 + 16 * i
        tag = d[p:p + 4].decode("latin1")
        off_t, len_t = struct.unpack(">II", d[p + 8:p + 16])
        t[tag] = d[off_t:off_t + len_t]
    return t


def metrics(path, index=0):
    t = tables(path, index)
    upm, = struct.unpack(">H", t["head"][18:20])
    ha, hd, hg = struct.unpack(">hhh", t["hhea"][4:10])
    os2 = t["OS/2"]
    # libass reads these as SIGNED and falls back to the typo metrics when they
    # sum to zero (ass_font.c, set_font_metrics). Match that, or a font with an
    # out-of-range value would be corrected against a denominator the renderer
    # never uses.
    wa, wd = struct.unpack(">hh", os2[74:78])
    ta, td = struct.unpack(">hh", os2[68:72])
    aeg = ha - hd + hg
    lib = wa + wd
    if lib == 0:
        lib = ta - td
    return dict(upm=upm, hhea=(ha, hd, hg), win=(wa, wd),
                em_aegisub=upm / aeg if aeg else 0,
                em_libass=upm / lib if lib else 0,
                emfix=(aeg / lib) if lib else 1.0)


def main():
    names = sys.argv[1:]
    if not names:
        print(__doc__)
        return 2
    print("%-26s %9s %9s %8s  %s"
          % ("font", "em/fs Aeg", "em/fs ass", "emfix", "resolved to"))
    for n in names:
        path, idx, fam = resolve(n)
        if not path:
            print("%-26s  NOT FOUND" % n)
            continue
        try:
            m = metrics(path, idx)
        except Exception as e:
            print("%-26s  ERROR %s" % (n, e))
            continue
        warn = "" if installed(n, fam) else "   <-- NOT INSTALLED, fallback"
        print("%-26s %9.4f %9.4f %8.4f  %s%s"
              % (n, m["em_aegisub"], m["em_libass"], m["emfix"],
                 path.split("/")[-1], warn))
    return 0


if __name__ == "__main__":
    sys.exit(main())
