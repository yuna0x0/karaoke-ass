#!/usr/bin/env python3
"""
Render an applied .ass at many timestamps and report ink that leaves the frame.

Judged on rendered ink rather than predicted extents.

Usage:  karaoke-ass check-frame applied.ass [-w W] [-h H]
"""
import re
import subprocess
import sys

from . import _platform


def times(path):
    """Sample each event a third and two thirds of the way through."""
    out = set()
    for line in open(path):
        if not line.startswith("Dialogue:"):
            continue
        f = line.split(",", 9)
        def ms(t):
            h, m, rest = t.split(":")
            sec, cs = rest.split(".")
            return ((int(h) * 60 + int(m)) * 60 + int(sec)) * 1000 + int(cs) * 10
        a, b = ms(f[1]), ms(f[2])
        if b > a:
            out.add(a + (b - a) // 3)
            out.add(a + 2 * (b - a) // 3)
    return sorted(out)


def main():
    path = sys.argv[1]
    W = H = None
    for i, a in enumerate(sys.argv):
        if a == "-w":
            W = int(sys.argv[i + 1])
        if a == "-h":
            H = int(sys.argv[i + 1])
    if W is None:
        src = open(path).read()
        W = int(re.search(r"PlayResX:\s*(\d+)", src).group(1))
        H = int(re.search(r"PlayResY:\s*(\d+)", src).group(1))

    ts = times(path)
    worst_left = worst_right = worst_top = worst_bottom = 0
    bad = []
    for t in ts:
        r = subprocess.run(
            [_platform.probe_path(), path, str(t), "-w", str(W), "-h", str(H)],
            capture_output=True, text=True)
        m = re.search(r"^ALL x (-?\d+)\.\.(-?\d+) \(w \d+\)  y (-?\d+)\.\.(-?\d+)",
                      r.stdout, re.M)
        if not m:
            continue
        x0, x1, y0, y1 = (int(g) for g in m.groups())
        over = []
        if x0 < 0:
            over.append("left by %d" % -x0)
            worst_left = max(worst_left, -x0)
        if x1 > W - 1:
            over.append("right by %d" % (x1 - W + 1))
            worst_right = max(worst_right, x1 - W + 1)
        if y0 < 0:
            over.append("top by %d" % -y0)
            worst_top = max(worst_top, -y0)
        if y1 > H - 1:
            over.append("bottom by %d" % (y1 - H + 1))
            worst_bottom = max(worst_bottom, y1 - H + 1)
        if over:
            bad.append((t, ", ".join(over)))

    print("frame %dx%d, %d sampled timestamps" % (W, H, len(ts)))
    for t, why in bad[:12]:
        print("  t=%-8d ink leaves frame: %s" % (t, why))
    if len(bad) > 12:
        print("  ... and %d more" % (len(bad) - 12))
    print("overflow  left %d  right %d  top %d  bottom %d"
          % (worst_left, worst_right, worst_top, worst_bottom))
    print("frames with overflow: %d of %d" % (len(bad), len(ts)))


if __name__ == "__main__":
    main()
