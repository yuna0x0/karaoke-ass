#!/usr/bin/env python3
"""
Check an applied karaoke .ass against where libass will put the glyphs.

The template draws each lyric line as one string, then positions the wipe edges
and the ruby from karaskel's syllable coordinates. Those agree only if the
coordinates are plain cumulative advances, which they are not once furigana
layout inserts gaps, so the two are compared directly:

  true_right(i)  = pos_x + sum(advance of syllables 0..i)   <- what libass draws
  clip_right(i)  = the \\t(...\\clip(...)) edge in the applied file
                                                            <- what the wipe uses
  drift(i)       = clip_right(i) - true_right(i)

and the same for ruby: a ruby run should sit centred over the base run it
annotates, in TRUE coordinates.

Usage:  check_layout.py source.ass applied.ass [-v]
"""
import re
import sys

from .measure import Measurer

TAG_RE = re.compile(r"\{[^}]*\}")
K_RE = re.compile(r"\{[^}]*\\[kK][fo]?(\d+)[^}]*\}")


def parse_style(path):
    styles = {}
    for line in open(path):
        if line.startswith("Style:"):
            v = line[6:].rstrip("\n").split(",")
            styles[v[0].strip()] = dict(
                font=v[1].strip(), size=float(v[2]), bold=1 if float(v[7]) else 0,
                italic=1 if float(v[8]) else 0, scalex=float(v[11]),
                scaley=float(v[12]), spacing=float(v[13]),
                outline=float(v[16]), shadow=float(v[17]))
    return styles


def source_lines(path):
    """Split each source lyric line into syllables with their furigana."""
    out = []
    for line in open(path):
        if not line.startswith("Dialogue:"):
            continue
        f = line.split(",", 9)
        text = f[9].rstrip("\n")
        if not K_RE.search(text):
            continue
        syls, pos = [], 0
        pending = None
        for m in re.finditer(r"\{[^}]*\}", text):
            run = text[pos:m.start()]
            if pending is not None:
                pending["text"] = run
                syls.append(pending)
            pos = m.end()
            km = re.search(r"\\[kK][fo]?(\d+)", m.group(0))
            pending = dict(dur=int(km.group(1)) * 10) if km else pending
        if pending is not None:
            pending["text"] = text[pos:]
            syls.append(pending)
        for s in syls:
            t = s["text"]
            if "|" in t or "｜" in t:
                t = t.replace("｜", "|")
                base, furi = t.split("|", 1)
                s["base"], s["furi"] = base, furi
            else:
                s["base"], s["furi"] = t, ""
        out.append(dict(start=f[1], end=f[2], style=f[3], syls=syls))
    return out


def applied_events(path):
    ev = []
    for line in open(path):
        if not line.startswith("Dialogue:"):
            continue
        f = line.split(",", 9)
        text = f[9].rstrip("\n")
        pm = re.search(r"\\pos\((-?\d+),(-?\d+)\)", text)
        if not pm:
            continue
        clip_re = r"\\t\([^)]*\\clip\(\d+,\d+,(\d+),\d+\)"
        ev.append(dict(layer=int(f[0].split(":")[1]), start=f[1], end=f[2],
                       style=f[3], x=int(pm.group(1)), y=int(pm.group(2)),
                       clips=[int(c) for c in re.findall(clip_re, text)],
                       text=TAG_RE.sub("", text)))
    return ev


def main():
    src, app = sys.argv[1], sys.argv[2]
    verbose = "-v" in sys.argv
    styles = parse_style(app) or parse_style(src)
    slines = source_lines(src)
    ev = applied_events(app)

    # The template RETIMES its output (lead-in / hold), so applied events cannot
    # be matched to source lines by time. Match on the rendered text instead:
    # the base layers carry exactly the line's stripped text.
    by_text = {}
    for e in ev:
        by_text.setdefault(e["text"], []).append(e)

    # one batch for every advance we will need
    jobs, jidx = [], {}
    def want(stylename, text):
        st = styles[stylename]
        key = (stylename, text)
        if key not in jidx:
            jidx[key] = len(jobs)
            jobs.append(dict(font=st["font"], size=st["size"], bold=st["bold"],
                             italic=st["italic"], spacing=st["spacing"],
                             scalex=st["scalex"], scaley=st["scaley"], text=text))
        return key

    for L in slines:
        st = L["style"]
        for i in range(len(L["syls"]) + 1):
            pre = "".join(s["base"] for s in L["syls"][:i])
            want(st, pre)
            want(st, pre.rstrip(" \t"))
        for s in L["syls"]:
            if s["furi"]:
                want(st + "-furigana", s["furi"])
    res = Measurer().run(jobs)
    def W(stylename, text):
        return res[jidx[(stylename, text)]][0]


    worst_wipe = worst_ruby = worst_tail = 0.0
    nlines = 0
    for L in slines:
        base_text = "".join(s["base"] for s in L["syls"])
        cands = by_text.get(base_text, [])
        wipe = [e for e in cands if e["clips"] and e["style"] == L["style"]]
        if not wipe:
            continue
        span = (wipe[0]["start"], wipe[0]["end"])
        cands = [x for x in ev if (x["start"], x["end"]) == span]
        nlines += 1
        e = wipe[0]
        st = L["style"]
        drifts = []
        for i, c in enumerate(e["clips"]):
            if i + 1 > len(L["syls"]):
                break
            pre = "".join(s["base"] for s in L["syls"][:i + 1]).rstrip(" \t")
            true_right = e["x"] + W(st, pre)
            drifts.append(c - true_right)
        # The FINAL edge is deliberately overshot so the last glyph's outline
        # and shadow are fully swept; it is reported separately, not as drift.
        if len(drifts) > 1:
            worst_wipe = max(worst_wipe, max(abs(x) for x in drifts[:-1]))
        if drifts:
            worst_tail = max(worst_tail, drifts[-1])

        # ruby: each furigana event should be centred over its base run
        rubies = [x for x in cands
                  if x["style"].endswith("-furigana") and x["layer"] == 4]
        ri = 0
        for i, s in enumerate(L["syls"]):
            if not s["furi"] or ri >= len(rubies):
                continue
            left = e["x"] + W(st, "".join(q["base"] for q in L["syls"][:i]))
            upto = "".join(q["base"] for q in L["syls"][:i + 1]).rstrip(" \t")
            right = e["x"] + W(st, upto)
            want_center = (left + right) / 2
            r = rubies[ri]
            ri += 1
            got_center = r["x"] + W(st + "-furigana", s["furi"]) / 2
            off = got_center - want_center
            worst_ruby = max(worst_ruby, abs(off))
            if verbose and abs(off) > 2:
                print("  ruby %-6s over %-4s off by %+7.1f px  (line %s)"
                      % (s["furi"], s["base"], off, L["start"]))
        if verbose and drifts and max(abs(x) for x in drifts) > 2:
            print("  wipe drift line %s: %s" % (L["start"],
                  " ".join("%+.0f" % x for x in drifts)))

    print("lines checked: %d" % nlines)
    print("worst wipe-edge drift : %7.1f px" % worst_wipe)
    print("worst ruby centring   : %7.1f px" % worst_ruby)
    print("final-edge overshoot  : %7.1f px  (intentional: outline+shadow+1)"
          % worst_tail)
    return 0


if __name__ == "__main__":
    sys.exit(main())
