# Advanced usage

Merging timed lyrics, applying the template without a GUI, and checking the
result by rendering it. None of this is needed for normal use.

## Extra requirements

These need more than Python:

| | needed for |
|---|---|
| libass (runtime and headers) | the render probe |
| a C compiler and `make` | building the probe |
| LuaJIT, or Lua `5.1` | the headless applier |
| `pkg-config` | locating libass at build time |
| `ffmpeg` | optional: burning subtitles, converting probe output |
| `fontconfig` | optional; font lookup otherwise scans font directories |

```sh
# macOS
brew install libass luajit ffmpeg pkg-config

# Debian / Ubuntu
sudo apt install libass-dev luajit ffmpeg build-essential pkg-config python3

# Fedora
sudo dnf install libass-devel luajit ffmpeg gcc make pkgconf-pkg-config python3

# Arch
sudo pacman -S libass luajit ffmpeg base-devel pkgconf python

# Windows, in an MSYS2 UCRT64 shell
pacman -S mingw-w64-ucrt-x86_64-{libass,luajit,ffmpeg,gcc,pkgconf} make python
```

Then `make`, which builds `bin/assprobe`.

The Python side is run through [uv](https://docs.astral.sh/uv/), which creates
its environment on first use; install it as its documentation describes. If you
would rather not, `pip install .` and drop the `uv run` prefix from the commands
below.

The applier reads the karaoke templater scripts out of an Aegisub install,
looking in the usual locations on each platform. Set `KARA_AUTOMATION_DIR` to
the folder containing `autoload/kara-templater.lua` if yours is elsewhere.

## Applying without a GUI

```sh
uv run karaoke-ass apply song.ass song-applied.ass
```

Same output as Apply karaoke template, for regenerating a song from a script
while iterating on config values.

`--renderer-metrics` measures in the renderer's sizing convention instead of
Aegisub's. It does not predict Aegisub's output; it isolates whether a
discrepancy comes from measurement or from the template.

## Checking the result

```sh
uv run karaoke-ass check song.ass song-applied.ass      # add -v to list lines
```

- **wipe-edge drift**: distance from each sweep boundary to its syllable
  boundary. Under ~1 px is correct.
- **ruby centring**: distance from each reading's centre to its character's.
  Under ~1 px is correct.
- **final-edge overshoot**: deliberate, `outline + shadow + 1`, so the last
  glyph's border and shadow are swept.

Larger values usually mean the style names a font that is not installed.

`check-frame` runs separately and reports ink that leaves the frame:

```sh
uv run karaoke-ass check-frame song-applied.ass
```

To look at a real frame:

```sh
bin/assprobe song-applied.ass 55000 -o /tmp/f.ppm
ffmpeg -y -i /tmp/f.ppm /tmp/f.png
```

`make check` runs the whole loop over everything in `examples/`.

## Command reference

### `import`

Merges timed lyrics into a copy of the template instead of pasting them into
the grid by hand.

```sh
karaoke-ass import timed.ass -t template/two-row-karaoke.ass -o song.ass
```

Accepts any `.ass` carrying `\k`, `\kf` or `\ko` tags. Lines without them are
skipped, which drops translation and romanisation tracks.

| flag | effect |
|---|---|
| `--name v1` | keep only lines whose Name/Actor field matches, for files marking several voices |
| `--style Kara` | target style name; defaults to the template's own |
| `--tag kf` | rewrite all karaoke tags to one type (cosmetic; the sweep runs off syllable times, not the tag) |
| `--row name` | pass `top`/`bot` through from the Name field instead of alternating |
| `--keep-names` | keep the source Name field |

### `emfix`

```sh
karaoke-ass emfix song.ass --write     # omit --write for a dry run
```

Pins the font correction factor into the config line instead of letting the
template derive it at apply time. For a fixed value in the file, or a font the
template's scan does not find.

### `font-metrics`

```sh
karaoke-ass font-metrics "Some Font" "Another Font"
```

Shows how each engine sizes a font and the ratio between them.

### `assprobe`

```sh
bin/assprobe file.ass 55000 -o frame.ppm      # one frame, plus a dump
bin/assprobe file.ass 55000 -o frame.pam      # same, with alpha
bin/assprobe file.ass --scan 40               # 40 frames, one per second
```

Renders with libass and reports per-layer and total ink bounding boxes plus a
per-scanline coverage profile. `--scan` renders N frames in one process.

A `.pam` output keeps the alpha channel, so a frame can be composited over
video without an ffmpeg that has libass:

```sh
bin/assprobe song-applied.ass 4000 -o /tmp/subs.pam
ffmpeg -ss 4 -i video.mp4 -i /tmp/subs.pam -filter_complex "[0:v][1:v]overlay" \
       -frames:v 1 /tmp/preview.png
```

### Environment variables

| variable | effect |
|---|---|
| `KARA_AUTOMATION_DIR` | where to find `autoload/kara-templater.lua` |
| `KARA_ASSPROBE` | path to the probe binary |
| `KARA_LUA` | Lua interpreter to use |
| `KARA_PYTHON` | Python interpreter the Lua driver calls back into |
| `KARA_MEASURE=libass` | measure in the renderer's convention |

## A note on precision

ASS karaoke tags are centiseconds, so any route into this format quantises
timings to 10 ms. Round-tripping is therefore lossy; keep your timing tool's own
project file.

## Releasing

```sh
make dist
```

Runs the checks, then writes both release assets into `dist/`, taking the
version from `pyproject.toml`:

| file | contents |
|---|---|
| `karaoke-ass-template-vX.Y.Z.zip` | template, examples, README, LICENSE |
| `karaoke_ass-X.Y.Z-py3-none-any.whl` | the command line tools |

It depends on `check`, so a template that fails verification cannot be packed.
No source tarball is built: the wheel is `py3-none-any` and needs no build step,
and GitHub attaches source archives to every tag by itself.

Publishing stays a separate, deliberate step:

```sh
gh release create vX.Y.Z dist/* --title vX.Y.Z --notes-file notes.md
```

## Source layout

| path | what |
|---|---|
| `native/assprobe.c` | the render probe |
| `lua/apply_template.lua` | headless applier: a two-pass measure-then-run driver |
| `lua/host_env.lua` | the emulated host: `.ass` parsing, the `subs` object, karaoke tag parsing, cached measurement |
| `src/karaoke_ass/measure.py` | advance measurement via rendered ink |
| `src/karaoke_ass/font_metrics.py` | font table reader, and both engines' sizing rules |
| `src/karaoke_ass/_platform.py` | binary discovery, scratch dirs, font lookup |
| `src/karaoke_ass/check_layout.py` | wipe and ruby placement checks |
| `src/karaoke_ass/check_frame.py` | frame containment |

`bin/.extents-cache-*.tsv` are measurement caches; `make clean` removes them.

## Scope

The headless applier is not a general command line interface for Aegisub. It
emulates the part of the automation API this template touches, so the real
templater and `karaskel` can run outside a GUI.
