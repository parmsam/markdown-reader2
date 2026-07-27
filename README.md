# Markdown Reader 2

A locally-hosted web app for a personal library of Markdown/PDF articles, read
aloud with natural-sounding AI voices, with real-time sentence and word
highlighting. Runs as a single Python process on your machine, reachable from
any device on your local network (phone, tablet, another computer) -- no cloud
services, no accounts, everything runs on-device via Apple's MLX framework.

This is a rewrite of a previous Tauri desktop-app version as a network-
accessible web app with a real persistent article library. See `CLAUDE.md` for
the architecture and `LEARNINGS.md` for the design decisions behind it.

## Features

- Read aloud any Markdown or PDF file with Kokoro TTS (7 voices), running
  entirely on-device via MLX (Apple Silicon only)
- Real-time highlighting: the current sentence is highlighted, and individual
  words light up as they're spoken
- Full playback control: play, pause, stop, skip forward/back, speed
  (0.5x-2x), voice picker
- Click any sentence to jump playback there; auto-generated table of contents
  from headings, also click-to-jump
- A persistent library: paste markdown, upload a `.md`/`.txt` file, or upload
  a PDF (converted to markdown on upload via marker-pdf) -- everything is
  saved to a local SQLite database and stays there across restarts
- Generated audio is cached to disk, so replaying an article (from the same
  device or another one on your network) is instant after the first listen
- Reading progress (segment position, voice, speed) is saved server-side per
  article, so it's shared across every device you open it from

## Tech stack

| Layer | Technology |
|---|---|
| Web framework | [FastHTML](https://fastht.ml/) (Starlette/ASGI under the hood, server-rendered HTML) |
| Database | SQLite via FastHTML's bundled `fastlite` |
| TTS | [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) via [mlx-audio](https://github.com/Blaizzy/mlx-audio), running on [MLX](https://github.com/ml-explore/mlx) (Apple Silicon) |
| Text -> phonemes | [misaki](https://github.com/hexgrad/misaki) + spaCy + num2words + phonemizer/espeak-ng |
| PDF -> Markdown | [marker-pdf](https://github.com/VikParuchuri/marker) (OCR + layout parsing) |
| Markdown -> HTML | [markdown-it-py](https://github.com/executablebooks/markdown-it-py) |
| Frontend | Plain vanilla JavaScript, no build step, no framework (Web Audio API for playback/highlighting) |
| Packaging | [uv](https://github.com/astral-sh/uv) |

## Requirements

- macOS on Apple Silicon (MLX requirement)
- [uv](https://github.com/astral-sh/uv) installed
- Homebrew packages: `espeak-ng` (`brew install espeak-ng`)

This project is pinned to Python 3.12 (see `.python-version`) rather than a
newer system Python, because `spacy` (required by the TTS text-processing
pipeline) doesn't yet publish wheels for newer CPython versions. `uv` will
download and manage 3.12 automatically.

## Setup

```bash
brew install espeak-ng   # if not already installed
uv sync                  # installs all Python dependencies into .venv, downloads Python 3.12 if needed
```

## Running

```bash
./start.sh   # runs the server in the foreground -- Ctrl+C to stop
./stop.sh    # stops it from another terminal instead, if you'd rather not Ctrl+C
```

`start.sh` prints both the local and LAN URLs to open, and automatically stops
any already-running instance first (so it's also how you restart after
pulling changes). It tracks the process in `data/server.pid` so `stop.sh` can
find it from a different terminal.

The server binds to `0.0.0.0` on port 5001 (override with the
`PORT` environment variable). Open `http://localhost:5001` on the same
machine, or find your machine's LAN IP (e.g. `ipconfig getifaddr en0` on
macOS) and browse to `http://<that-ip>:5001` from any other device on your
network.

**Security note:** there is no authentication. Anyone who can reach that port
on your network can view, add, and delete library articles. This is meant for
personal use on a trusted home/local network -- don't expose the port beyond
your LAN (e.g. via port forwarding).

The first run downloads the Kokoro model weights (a few hundred MB) from
Hugging Face and creates a `data/` directory (gitignored) containing:
- `data/library.db` -- the SQLite article library
- `data/pdfs/` -- retained original PDF uploads
- `data/audio_cache/` -- generated speech audio, cached per article/segment/voice/speed

## Voices

| id | Name | Language |
|---|---|---|
| `af_heart` | Heart | US, female |
| `af_nova` | Nova | US, female |
| `af_sky` | Sky | US, female |
| `am_adam` | Adam | US, male |
| `am_michael` | Michael | US, male |
| `bf_emma` | Emma | UK, female |
| `bm_george` | George | UK, male |

## Known limitations

- Word timing is estimated (character-length weighted), not derived from real
  forced alignment -- Kokoro/mlx-audio doesn't expose per-word timestamps.
- PDF support is best-effort: marker-pdf can be slow on first run (downloads
  its own OCR/layout models) and has occasionally had dependency conflicts
  with the TTS stack's `transformers` version. If PDF upload ever breaks,
  converting the PDF to markdown yourself (any tool) and pasting the result in
  is always a working fallback.
- Segmentation (splitting markdown into speakable sentences) is regex/
  heuristic-based, not a full CommonMark parse -- unusual layouts (tables,
  deeply nested lists inside blockquotes) may split imperfectly.
- Very short segments (under ~3 words) are padded before being sent to Kokoro
  to avoid a known MLX decoder crash on very short inputs; a small number of
  segments may still fail to generate even after a retry/bisect fallback, and
  are skipped during playback rather than blocking it.
- Editing an article's content resets its resume position (segment indices
  can shift), and invalidates its cached audio (a fresh cache namespace is
  used automatically).

## Development

```bash
uv run pytest tests/         # segmentation unit tests
```
