#!/usr/bin/env python3
"""
Set the `emfix` value in a template to match the font its style names.

The editor and the renderer size a font differently (see font_metrics.py), and
`emfix` is the ratio that reconciles them. It depends only on the font, not on
the size, so it changes exactly when you change Fontname.

  set_emfix.py file.ass          show what it would set
  set_emfix.py file.ass --write  set it

Run this after changing the style's Fontname, then re-apply the template.
"""
import re
import sys

from . import font_metrics


def main():
    path = sys.argv[1]
    write = "--write" in sys.argv
    src = open(path).read()

    m = re.search(r"^Style:\s*([^,]+),([^,]*),", src, re.M)
    if not m:
        print("no Style line found")
        return 1
    font = m.group(2).strip()

    fpath, idx, fam = font_metrics.resolve(font)
    if not fpath:
        print("font not found: %s" % font)
        return 1
    met = font_metrics.metrics(fpath, idx)
    fix = met["emfix"]

    cur = re.search(r"emfix\s*=\s*([\d.]+)", src)
    print("font        : %s" % font)
    print("resolved to : %s%s" % (fpath.rsplit("/", 1)[-1],
          "" if font_metrics.installed(font, fam)
          else "   <-- NOT INSTALLED, fallback; positions will be unreliable"))
    print("em/fs editor: %.4f   renderer: %.4f" % (met["em_aegisub"], met["em_libass"]))
    print("emfix       : %.4f  (currently %s)"
          % (fix, cur.group(1) if cur else "absent"))

    if not write:
        print("\n(dry run, pass --write to apply)")
        return 0
    if not cur:
        print("no emfix setting found in the file")
        return 1
    out = src[:cur.start(1)] + ("%.4f" % fix) + src[cur.end(1):]
    open(path, "w").write(out)
    print("\nwritten")
    return 0


if __name__ == "__main__":
    sys.exit(main())
