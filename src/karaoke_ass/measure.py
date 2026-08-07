#!/usr/bin/env python3
"""
Batch text measurement backed by libass rendering.

libass exposes no measurement API, so advances are recovered from rendered ink
with a sentinel glyph, which cancels the side bearings exactly:

    ink_x1(s .. SENT) = adv(s) + adv(SENT) - rsb(SENT)
    ink_x1(SENT)      =          adv(SENT) - rsb(SENT)
    => adv(s) = ink_x1(s .. SENT) - ink_x1(SENT)

Rendering happens at OVERSAMPLE x the real size and is divided back down, so
integer pixel boxes still yield sub-pixel advances; libass is unhinted, so that
is linear.

Usage:  karaoke-ass measure jobs.tsv out.tsv [--editor] [--editor]
  jobs.tsv  font \t size \t bold \t italic \t spacing \t scalex \t scaley \t text
  out.tsv   width \t height \t descent \t extlead      (one row per job, in order)
"""
import os
import subprocess
import sys

from . import _platform, font_metrics

OVERSAMPLE = 16
SENT = "囗"        # 囗, full width, always inked, present in any CJK font
FRAME_W = 80000        # wide enough that no probe line is clipped at 4x
FRAME_H = 1200
PROBE_Y = 200


def _t(sec):
    return "%d:%02d:%02d.00" % (sec // 3600, sec // 60 % 60, sec % 60)


def esc(t):
    """ASS-escape a plain text run so it cannot be read as tags or a break."""
    return (t.replace("\\", "⧵")   # a literal backslash would start a tag
             .replace("{", "❴")
             .replace("}", "❵"))


class Measurer:
    def __init__(self, workdir=None, convention="libass"):
        self.workdir = workdir or _platform.workdir("karaoke-ass-measure")
        # "libass" , what the renderer actually draws
        # "editor" , what the editor's text measurement reports, which
        #              renormalises so the measured HEIGHT equals Fontsize.
        #              The template runs inside the editor, so predicting its
        #              output means reproducing its convention.
        self.convention = convention
        self._emfix = {}

    def _fix(self, font):
        """Editor/renderer em ratio for a font, or 1.0 when it can't be known.

        If the font is not installed, both engines fall back independently and
        no conversion is defensible: applying the ratio of whatever the matcher
        happened to return would inject error rather than remove it. Assume
        they agree, and say so.
        """
        if font not in self._emfix:
            path, idx, fams = font_metrics.resolve(font)
            if not path or not font_metrics.installed(font, fams):
                sys.stderr.write(
                    "warning: font %r is not installed; assuming the editor and "
                    "the renderer agree about its size\n" % font)
                self._emfix[font] = 1.0
            else:
                try:
                    self._emfix[font] = font_metrics.metrics(path, idx)["emfix"]
                except Exception:
                    self._emfix[font] = 1.0
        return self._emfix[font]

    def _script(self, styles, events):
        out = ["[Script Info]", "ScriptType: v4.00+", "WrapStyle: 2",
               "ScaledBorderAndShadow: yes",
               "PlayResX: %d" % FRAME_W, "PlayResY: %d" % FRAME_H, "",
               "[V4+ Styles]",
               "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
               "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
               "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
               "Alignment, MarginL, MarginR, MarginV, Encoding"]
        for name, s in styles:
            out.append(
                "Style: {n},{font},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,"
                "&H00000000,{bold},{italic},0,0,{sx},{sy},{sp},0,1,0,0,7,0,0,0,1"
                .format(n=name, font=s["font"], size=s["size"] * OVERSAMPLE,
                        bold=-1 if s["bold"] else 0,
                        italic=-1 if s["italic"] else 0,
                        sx=s["scalex"], sy=s["scaley"],
                        sp=s["spacing"] * OVERSAMPLE))
        out += ["", "[Events]",
                "Format: Layer, Start, End, Style, Name, MarginL, MarginR, "
                "MarginV, Effect, Text"]
        for i, (stylename, text) in enumerate(events):
            # scan mode samples t = i*1000+500 ms, so event i owns second i
            out.append("Dialogue: 0,%s,%s,%s,,0,0,0,,%s"
                       % (_t(i), _t(i + 1), stylename, text))
        return "\n".join(out) + "\n"

    def _render(self, script, n, tag):
        path = os.path.join(self.workdir, "m_%s.ass" % tag)
        with open(path, "w") as f:
            f.write(script)
        r = subprocess.run([_platform.probe_path(), path, "--scan", str(n),
                            "-w", str(FRAME_W), "-h", str(FRAME_H)],
                           capture_output=True, text=True)
        rows = {}
        for line in r.stdout.splitlines():
            p = line.split()
            if len(p) != 6:
                continue
            i = int(p[0])
            rows[i] = None if p[1] == "-" else tuple(int(v) for v in p[1:5])
        if len(rows) < n:
            sys.stderr.write(r.stderr[-2000:])
            raise RuntimeError("probe returned %d of %d frames" % (len(rows), n))
        return rows

    def run(self, jobs):
        """jobs: list of dicts with font,size,bold,italic,spacing,scalex,scaley,text"""
        # One style per distinct style-spec; sentinel and baseline probes per style.
        def keyof(j):
            return (j["font"], j["size"], j["bold"], j["italic"],
                    j["spacing"], j["scalex"], j["scaley"])

        styles, order = {}, []
        for j in jobs:
            k = keyof(j)
            if k not in styles:
                styles[k] = "S%d" % len(styles)
                order.append((styles[k], j))

        stylelist = [(name, dict(font=j["font"], size=j["size"], bold=j["bold"],
                                 italic=j["italic"], spacing=j["spacing"],
                                 scalex=j["scalex"], scaley=j["scaley"]))
                     for name, j in order]

        events, index = [], {}
        pos = r"{\an7\pos(%d,%d)\bord0\shad0}" % (100, PROBE_Y)
        # Sentinels on BOTH sides: libass trims leading whitespace at the start
        # of a line, so a bare " " would measure as zero. The leading sentinel
        # keeps the run interior, and both sentinels cancel in the difference.
        for name, _ in order:
            index[("sent", name)] = len(events)
            events.append((name, pos + esc(SENT + SENT)))
        for n, j in enumerate(jobs):
            index[("job", n)] = len(events)
            events.append((styles[keyof(j)],
                           pos + esc(SENT + j["text"] + SENT)))

        rows = self._render(self._script(stylelist, events), len(events), "batch")

        sent_x1 = {}
        for name, _ in order:
            r = rows[index[("sent", name)]]
            sent_x1[name] = r[1] if r else 0

        out = []
        for n, j in enumerate(jobs):
            name = styles[keyof(j)]
            r = rows[index[("job", n)]]
            width = ((r[1] if r else sent_x1[name]) - sent_x1[name]) / OVERSAMPLE
            if self.convention == "editor":
                width /= self._fix(j["font"])
            # libass lays out a line box exactly Fontsize tall for EVERY font --
            # measured across four fonts at two sizes, always exactly fs. The
            # glyph ink always falls inside that box, so the box is all the
            # vertical truth the template needs.
            #
            # descent is reported as 0: karaskel stores it but never uses it,
            # and recovering a real baseline from libass output is not reliable
            # (drawings, the only baseline probe available, perturb the very
            # line metrics they would be measuring). Anything that needs the
            # baseline should be derived from the box instead.
            out.append((max(width, 0.0), float(j["size"]), 0.0, 0.0))
        return out


def main():
    jobs = []
    with open(sys.argv[1]) as f:
        for line in f:
            if not line.strip("\n"):
                continue
            p = line.rstrip("\n").split("\t")
            jobs.append(dict(font=p[0], size=float(p[1]), bold=int(p[2]),
                             italic=int(p[3]), spacing=float(p[4]),
                             scalex=float(p[5]), scaley=float(p[6]),
                             text=p[7] if len(p) > 7 else ""))
    conv = "editor" if "--editor" in sys.argv else "libass"
    res = Measurer(convention=conv).run(jobs)
    with open(sys.argv[2], "w") as f:
        for w, h, d, e in res:
            f.write("%.4f\t%.4f\t%.4f\t%.4f\n" % (w, h, d, e))


if __name__ == "__main__":
    main()
