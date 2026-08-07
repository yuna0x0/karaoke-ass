# karaoke-ass

A two-row karaoke subtitle template for ASS. Furigana sit on their own row, the
sweep wipes fill, outline and shadow together, and each line fades in early
enough to be read before it has to be sung.

![The template in use: two rows, the sung line in red with a white outline, furigana above each kanji, the next line already faded in](assets/preview.webp)

## Requirements

[Aegisub](https://aegisub.org/). Its
[Karaoke Templater](https://aegisub.org/docs/latest/automation/karaoke_templater/)
is bundled and enabled by default.

Optional command line tools merge timed lyrics, apply the template without
opening Aegisub, and check the result by rendering it. None of the steps below
need them: see [docs/advanced.md](docs/advanced.md).

## Download

Download the template archive from the
[latest release](https://github.com/yuna0x0/karaoke-ass/releases/latest) and
unzip it. It holds the template and the examples, which is everything the steps
below need.

Clone the repository instead if you also want the command line tools.

## Quick start

1. Open `template/two-row-karaoke.ass` from the unzipped folder (File, Open
   Subtitles). Leave the `Comment:` lines alone, they are the template.
2. Bring in syllable-timed lyrics, meaning a `\k` tag per syllable. Either
   route below works.
3. Set the font: Subtitle, Styles Manager, edit the `Kara` style.
4. Run Automation, Apply karaoke template. Save.
5. Import the `.ass` into your editor, or burn it in:

   ```sh
   ffmpeg -i video.mp4 -vf "ass=song.ass" -c:a copy out.mp4
   ```

   That filter needs an ffmpeg built with libass, which several prebuilt
   packages, Homebrew's included, are not. `ffmpeg -filters | grep " ass "`
   says whether yours is.

### Route A: time the lyrics in Aegisub

Type the lines into the grid, open the audio, and time each line against the
waveform. Then switch the audio panel to karaoke mode to split a line into
syllables and time each one, as described in the
[karaoke timing tutorial](https://aegisub.org/docs/latest/karaoke_timing_tutorial/).

For Japanese, Timing, Kanji Timer copies timing from a romaji or kana line onto
the kanji line.

### Route B: time them elsewhere and paste them in

[amll-ttml-tool](https://github.com/amll-dev/amll-ttml-tool) times lyrics word by
word and exports ASS. Any tool emitting `\k`, `\kf` or `\ko` works, as does a
word-timed LRC or TTML converted to ASS.

Open the export in Aegisub, copy the lines from the grid, then use Edit, Paste
Lines to put them into the template.

Either way, set the lyric lines to the `Kara` style and leave out translation
and romanisation tracks. The optional command line tools can do this merge for
you instead, dropping the extra tracks automatically: see
[docs/advanced.md](docs/advanced.md).

## Writing lyrics

### Furigana

Aegisub's syntax: a `|` after the syllable, then the reading.

```
{\kf60}星|ほし{\kf30}の{\kf60}光|ひかり{\kf30}を
```

`星|ほし` is one syllable, so it wipes as a unit and its reading wipes with it.
Readings are drawn at half size on their own row; consecutive readings are
grouped and centred over the group.

The `!` and `<` prefixes from the
[furigana tutorial](https://aegisub.org/docs/latest/furigana_karaoke/) work as
documented, except that a reading wider than its character is always centred, so
`<` is the default.

### Lead-in

Give a line a syllable before its first sung one and the sweep runs through it
during the intro, so the singer sees when to come in:

```
{\kf200}＿{\kf60}星|ほし{\kf30}の
```

`＿`, a fullwidth underscore, is the default here. The sweep is continuous, so
the bar fills as a progress bar and reads correctly in any meter.

Dots are the other convention. A single `…` looks like a countdown but does not
step, and three dots cannot mark four beats, so the fill drifts against the
rhythm. For a countdown that behaves like a karaoke machine, write one dot per
beat as its own syllable and time them to the intro:

```
{\kf50}・{\kf50}・{\kf50}・{\kf50}・
```

### Reserved characters

A pipe, `|` (U+007C), starts a furigana reading, so a pipe with nothing before
it annotates nothing and is not rendered. A syllable that is only a hash, `#`
(U+0023), repeats the previous highlight, so a syllable like `#tag` loses its
text. The fullwidth forms `｜` (U+FF5C) and `＃` (U+FF03) behave the same.

Where the character belongs to the lyric, substitute a lookalike karaskel
ignores: `│` (U+2502) for the pipe, `♯` (U+266F) for the hash. `karaoke-ass
import` flags both cases and ignores correct furigana.

### Rows

Lines alternate between the two rows, so the next line fades in during the
current one. Put `top` or `bot` in a line's Actor field to pin it.

## Fonts

Install the font in the operating system before applying the template. A font
that is only embedded in the `.ass`, or sitting in a folder beside it, is
invisible to Aegisub, both when it measures text and when it previews. If the
font is missing, the template applies no correction and says so in the
automation log.

Embed fonts afterwards, for distribution: Subtitle, Attachments, or Subtitle,
Fonts Collector. [docs/how-it-works.md](docs/how-it-works.md) explains why the
order matters.

The examples use Source Han Serif JP Heavy, free under the SIL Open Font License
from [adobe-fonts/source-han-serif](https://github.com/adobe-fonts/source-han-serif/releases)
(the `SourceHanSerifJP` package).

## Tuning

The config lines below the styles hold lead in and hold times, fade lengths,
ruby gap, row spacing and colours, each documented in the file's own header.

`layoutmode` picks one of three:

1. upper row at the left margin, lower row right-aligned
2. centred block, rows nudged apart
3. screen split in half, each row centred in its half

A line wider than the frame is compressed horizontally to fit, down to the
`minscale` percentage, 50 by default. A line that hits that floor should be
split in two.

`examples/` has one file per layout mode: Japanese with furigana, Latin script,
and bare syllables. Between them they show both lead-in forms and a line with
none.

## Documentation

- [Advanced usage](docs/advanced.md): merging lyrics, applying and checking
  without a GUI, build requirements
- [How it works](docs/how-it-works.md): the font sizing mismatch, why embedded
  fonts do not help, the sweep, the timing model

## License

MIT, see [LICENSE](LICENSE).
