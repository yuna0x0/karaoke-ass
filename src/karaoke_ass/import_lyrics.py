#!/usr/bin/env python3
"""
Merge syllable-timed lyrics into a karaoke template.

Input is any .ass whose dialogue carries karaoke tags (\\k, \\kf, \\ko). That
covers the editor's own karaoke timing mode and every external timing tool that
exports ASS; nothing here is specific to one of them. Lines without karaoke
tags are skipped, so translation and romanisation tracks are dropped unless you
ask for them.

    import_lyrics.py timed.ass -t template/two-row-karaoke.ass -o song.ass

Common adjustments:

    --name v1              keep only lines whose Name/Actor field is v1
    --style Kara           target style name (default: the template's first)
    --tag kf               rewrite \\k to \\kf (cosmetic; the sweep here is
                           driven by syllable times, not by the tag)
    --row alternate        leave row assignment to the template (default), or
                           pass through the Name field as top/bot
    --keep-names           keep the source Name field instead of clearing it

The template's own Dialogue lines, if any, are replaced. Its Comment lines --
the code and template definitions, are always preserved.
"""
import argparse
import re
import sys

K_TAG = re.compile(r"\\[kK][fo]?\d+")

# Two characters carry meaning inside lyric text, and both are legitimate most
# of the time, so only the broken uses are worth reporting.
#
#   base|reading  is furigana, which is the whole point
#   a bare |      has no base to annotate, so the pipe simply never renders
#   a bare #      is the deliberate multi-highlight marker
#   #word         is not: karaskel drops that syllable's text from the line
SYL_SPLIT = re.compile(r"\{[^}]*\}")


def reserved_problems(text):
    """Uses of | and # that will silently lose text. Legitimate ones are quiet."""
    out = []
    for syl in SYL_SPLIT.split(text):
        if not syl:
            continue
        bar = min((syl.find(c) for c in "|\uff5c" if c in syl), default=-1)
        if bar >= 0 and not syl[:bar].strip():
            out.append("a pipe with no text before it: it annotates nothing and "
                       "will not render")
        head = syl.lstrip()
        if head[:1] in ("#", "\uff03") and head[1:].strip():
            out.append("a syllable starting with %s: karaskel drops its text "
                       "from the line" % head[:1])
    return out


DIALOGUE = re.compile(r"^(Dialogue|Comment)\s*:\s*(.*)$")


def split_event(body, n=10):
    """Split an event's fields; the text field may itself contain commas."""
    out, pos = [], 0
    for _ in range(n - 1):
        c = body.find(",", pos)
        if c < 0:
            break
        out.append(body[pos:c])
        pos = c + 1
    out.append(body[pos:])
    return out


def read_events(path):
    events = []
    for line in open(path, encoding="utf-8-sig"):
        m = DIALOGUE.match(line.rstrip("\n"))
        if not m:
            continue
        kind, body = m.group(1), m.group(2)
        f = split_event(body)
        if len(f) < 10:
            continue
        events.append(dict(kind=kind, layer=f[0].strip(), start=f[1].strip(),
                           end=f[2].strip(), style=f[3].strip(),
                           name=f[4].strip(), ml=f[5].strip(), mr=f[6].strip(),
                           mv=f[7].strip(), effect=f[8].strip(), text=f[9]))
    return events


def template_style(path):
    for line in open(path, encoding="utf-8-sig"):
        if line.startswith("Style:"):
            name = line[6:].split(",")[0].strip()
            if not name.endswith("-furigana"):
                return name
    return "Default"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", help="an .ass containing karaoke-tagged lines")
    ap.add_argument("-t", "--template", required=True)
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--style", default=None)
    ap.add_argument("--name", default=None,
                    help="keep only lines whose Name field matches this")
    ap.add_argument("--tag", choices=["k", "kf", "ko"], default=None,
                    help="rewrite all karaoke tags to this one")
    ap.add_argument("--row", choices=["alternate", "name"], default="alternate")
    ap.add_argument("--keep-names", action="store_true")
    a = ap.parse_args()

    style = a.style or template_style(a.template)
    src = read_events(a.source)

    lyric = [e for e in src if e["kind"] == "Dialogue" and K_TAG.search(e["text"])]
    if a.name:
        lyric = [e for e in lyric if e["name"] == a.name]
    if not lyric:
        sys.exit("No karaoke-tagged dialogue found in %s.\n"
                 "Lines need \\k tags, time the lyrics first." % a.source)

    lyric.sort(key=lambda e: e["start"])

    warned = 0
    for e in lyric:
        for why in reserved_problems(e["text"]):
            warned += 1
            print("warning: %s: %s" % (e["start"], why), file=sys.stderr)
    if warned:
        print("warning: %d issue(s) above will lose text. If the character is "
              "part of the lyric, substitute a lookalike: \u2502 (U+2502) for | "
              "or \u266f (U+266F) for #." % warned, file=sys.stderr)

    out = []
    for e in lyric:
        text = e["text"]
        if a.tag:
            text = re.sub(r"\\[kK][fo]?(\d+)", r"\\%s\1" % a.tag, text)
        name = e["name"] if (a.keep_names or a.row == "name") else ""
        if a.row == "name" and name not in ("top", "bot"):
            name = ""
        out.append("Dialogue: 0,%s,%s,%s,%s,0,0,0,,%s"
                   % (e["start"], e["end"], style, name, text))

    kept, dropped_dialogue = [], 0
    for line in open(a.template, encoding="utf-8-sig"):
        if line.startswith("Dialogue:"):
            dropped_dialogue += 1
            continue
        kept.append(line.rstrip("\n"))

    with open(a.output, "w", encoding="utf-8") as f:
        f.write("\n".join(kept + out) + "\n")

    skipped = len(src) - len(lyric)
    print("imported %d lyric lines into %s" % (len(out), a.output))
    if skipped:
        print("skipped %d source line(s) with no karaoke tags "
              "(translations, romanisations, comments)" % skipped)
    if dropped_dialogue:
        print("replaced %d existing lyric line(s) in the template" % dropped_dialogue)
    print("\nNext: set the font in the Style line of %s, then apply the "
          "template." % a.output)


if __name__ == "__main__":
    main()
