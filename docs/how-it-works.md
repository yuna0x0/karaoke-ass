# How it works

The parts that are not obvious from reading the template.

## The editor and the renderer disagree about font size

An ASS `Fontsize` is not a unit. Each engine picks a rule for turning it into a
scale factor, and the two rules differ:

| | scales the face so that … equals `Fontsize` |
|---|---|
| the renderer (libass: preview, `ffmpeg`, most players) | `OS/2 usWinAscent + usWinDescent` |
| the editor (`text_extents`, which the templater's layout uses) | the platform's reported text height |

They coincide for a font whose `hhea` metrics match its `OS/2` win metrics and
whose `lineGap` is 0. Plenty of Japanese fonts do not:

| font | editor em/fs | renderer em/fs |
|---|---|---|
| a face with `lineGap` 0 | 0.696 | 0.696 |
| a face with `lineGap` 1000 | 0.500 | 0.603 |
| a face with `lineGap` 500 | 0.667 | 0.857 |

The template runs inside Aegisub, so every syllable coordinate it is handed is
in Aegisub's scale while the glyphs are drawn in the renderer's. At a 20%
disagreement the sweep advances 20% slower than the text it uncovers and the
furigana drift ~140 px left of their characters over a line at `Fontsize` 100.
That single cause produces offset furigana, a wipe that lags and looks cut off,
and lines that do not fit where they were measured to fit.

`emfix` is the ratio between the two, applied to every measured width in the
template:

```
emfix = (hhea.ascender - hhea.descender + hhea.lineGap) / (winAscent + winDescent)
```

It depends only on the font, never on the size, so it changes exactly when
`Fontname` does.

The template derives it at apply time: it walks the system font directories
comparing family names from each file's `name` table, then reads `head`, `hhea`
and `OS/2`. An installed font is found in a few hundredths of a second; the
worst case, a font that is absent, scans about a thousand files in ~0.2 s. The
result is cached per font name for the run.

A non-zero `emfix` in the config line overrides the detection.
`karaoke-ass font-metrics` prints the same numbers.

An absent font cannot be read, so `1.0` is assumed and a warning goes to the
automation log. That assumption holds only for fonts whose `lineGap` is 0.

The normalisation is still in `CalculateTextExtents` at `3.5.0-beta` and at
upstream HEAD, so no version upgrade removes the need for it.

### Where each side of this is established

Verified against Aegisub `3.5.0-beta` and libass `0.17.5`.

The renderer's rule is `set_font_metrics` and `ass_face_set_size` in libass
`ass_font.c`. It overrides the face's ascender and descender with
`usWinAscent` and `-usWinDescent`, commented "Mimicking GDI's behavior", then
sizes with `FT_SIZE_REQUEST_TYPE_REAL_DIM`, which maps that span onto the
requested size. It falls back to the typo metrics, then the bbox, when the win
values sum to zero. Checked against rendered output for four fonts at two sizes.

Aegisub's rule is `CalculateTextExtents` in `src/auto4_base.cpp`. Away from
Windows it measures with a `wxMemoryDC` and renormalises by the height that
comes back:

```cpp
double scaling = fontsize / (double)(lheight > 0 ? lheight : 1);
```

That height is `a + d + l` from `CTLineGetTypographicBounds` on macOS
(wxWidgets `src/osx/carbon/graphics.cpp`), so the leading is included, which is
where `lineGap` enters.

Windows takes the other branch, with no renormalisation: it sets GDI's
`lfHeight` to the font size and uses the returned width. A positive `lfHeight`
is matched against a font's *cell* height, per the
[`LOGFONT` documentation](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/ns-wingdi-logfontw),
and GDI takes that cell height from the win metrics, the behaviour libass
copies. The two therefore already agree and no correction is wanted, so the
template uses `1.0` on Windows. That branch is reasoned from those two sources
rather than measured, since it cannot be run from here.

Linux takes the same branch as macOS, so a correction applies, but the platform
metric underneath is Pango rather than Core Text and may compose its height
differently. If a Linux render looks misaligned, check it with
`karaoke-ass check` and pin `emfix` by hand.

### Why not just measure with the renderer

Inside Aegisub only Aegisub's measurement exists; the renderer cannot be
queried. A constant is the only bridge that works in both paths.

## Why embedded fonts do not help

ASS can carry font files inside the script, UUEncoded in a `[Fonts]` section,
and libass will use them if the host calls `ass_set_extract_fonts`. It can also
be pointed at an extra directory with `ass_set_fonts_dir`. Players do both.

Aegisub does neither. It calls `ass_set_fonts(renderer, nullptr, "Sans", 1,
nullptr, true)` and nothing else, so its preview sees system fonts only, and
`CalculateTextExtents` goes through the OS font manager by face name. Aegisub
can *write* attachments, and its Fonts Collector can copy a script's fonts into
a folder or an archive, but neither feeds back into what it measures or previews
with.

So the font has to be installed on the machine where the template is applied.
The `emfix` correction assumes both engines resolved the same face and differ
only in how they scale it. With a missing font that assumption breaks: Aegisub
lays out a substitute while the player renders the embedded original, and the
error is per glyph, not a constant, so no factor can undo it.

The same applies to the checkers here. `assprobe` does enable font extraction,
so it renders an applied file the way a player would, but advances are measured
from a synthetic script that carries no attachments. Comparing those two is only
meaningful when the style's font is installed.

## The line box, and what is safe to derive from it

The renderer lays out a line box **exactly `Fontsize` tall, for every font**.
That was measured across four fonts at two sizes; it is always exactly `fs`.

So the measured line height carries no font information; anything reading font
awareness into it is reading noise. The em does vary, between 0.60 and 0.86 of
`Fontsize` across ordinary Japanese faces, so treating `fs` as the em is wrong
by up to 40%.

Glyph ink always falls inside the line box, so with `\an4\pos(x,y)` the band
`[y - fs/2, y + fs/2]` bounds the text for any font. Rows, ruby rows and every
clip band are stacked from that box, which is why the vertical layout survives
a font change even though the horizontal layout needs `emfix`.

## The sweep is not `\kf`

`\kf` wipes only the fill, leaving the outline and shadow static, which reads as
a coloured fill sliding under a fixed border. Each syllable instead emits a
`\t(start, end, \clip(...))` walking a rectangular clip across the line on its
own layer pair, so fill, outline and shadow uncover together.

Intermediate clip edges land on syllable boundaries. Only the final edge
overshoots, by `outline + shadow + 1`, so the last glyph's border and shadow are
swept.

## Furigana are centred explicitly

`karaskel` left-aligns a reading wider than its character and lets it spill
right, so the coordinate it reports is not the centre. Using it directly put
readings up to 36 px off at `Fontsize` 100.

The template centres on the base syllable, reached through `syl.syl`. `basesyl`
is *not* it: in a furigana template that is the furigana itself.

## Timing

Each line appears early, holds unwiped, wipes, then holds again:

```
     appear        wipe starts                wipe ends    disappear
        |              |                          |            |
        |<- lead in ->|<------ sung ------------>|<- postwipe ->|
```

- `minlead` is guaranteed. With too little room between two lines on the same
  row the trailing hold is sacrificed first, never the lead: reading ahead
  matters more than seeing the finished line.
- A line can never appear while the previous line on its row is still being
  sung, regardless of `maxlead`.
- `fadein` and `fadeout` are ceilings, not settings. They are clamped so the
  fade-in always completes `fadegap` before the wipe reaches the first
  syllable, and the fade-out never starts before the wipe ends.

The rows alternate, so the next line fades in during the current one.

## How the checkers know what is correct

`check-layout` ignores the template's arithmetic. It measures the rendered
advance of every prefix of a line to find where each syllable boundary will be
drawn, then compares that against the clip edges and furigana positions in the
applied file.

The renderer exposes no measurement API, so advances are recovered from rendered
ink with a sentinel glyph on both sides, cancelling the side bearings and
preventing leading whitespace from being trimmed:

```
ink_x1(S s S) - ink_x1(S S) = advance(s)
```

Rendering happens at 16× and is divided back down, so integer bounding boxes
still yield sub-pixel advances; the renderer is unhinted, so that is linear.

`check-frame` renders many timestamps and reports ink outside the frame.

## Why there is a headless applier

Applying by hand and eyeballing the result is a slow, unreliable loop, and is
how the font-size bug survived as long as it did. `karaoke-ass apply` loads the
real templater and `karaskel` from an Aegisub install and emulates only the host
around them: the `aegisub.*` functions, the `subs` object, and `\k` parsing. No
layout logic is reimplemented.

Its text measurement reproduces Aegisub's convention, so its output predicts
what Aegisub would write, and the checkers judge that against what the renderer
will draw. Against real Aegisub output it lands within 2 px over 476 lines on a
font where the engines agree, and within 3 px (mean 0.2 px) on one where they
differ by 20%.
