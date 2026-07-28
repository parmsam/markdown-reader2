<img src="static/favicon.svg" alt="Lector logo" width="72" height="72">

# Lector

*Lector* (lek-tor): historically, someone employed to read aloud to others --
famously the workers who read newspapers and novels aloud to cigar factories
and textile mills before radio. This app is the same idea, run locally: a
personal library of Markdown/PDF articles, read aloud with natural-sounding AI
voices, with real-time sentence and word highlighting. Runs as a single Python
process on your machine, reachable from any device on your local network
(phone, tablet, another computer) -- no cloud services, no accounts,
everything runs on-device via Apple's MLX framework.

This is a rewrite of a previous Tauri desktop-app version as a network-
accessible web app with a real persistent article library. See `CLAUDE.md` for
the architecture and `LEARNINGS.md` for the design decisions behind it.

## Features

- Read aloud any Markdown or PDF file with Kokoro TTS (7 voices), running
  entirely on-device via MLX (Apple Silicon only)
- Real-time highlighting: the current sentence is highlighted, and individual
  words light up as they're spoken
- Full playback control: play, pause, stop, skip forward/back, speed
  (0.5x-2.5x), voice picker
- Click any sentence to jump playback there; auto-generated table of contents
  from headings, also click-to-jump
- A persistent library: paste markdown, upload a `.md`/`.txt` file, upload a
  PDF (converted to markdown via marker-pdf), or add a web page by URL
  (fetched clean via defuddle.md, falling back to Jina AI's reader) --
  everything is saved to a local SQLite database and stays there across
  restarts. Add-by-URL can also be triggered by sharing a link straight from
  your phone's Share Sheet, see "Mobile: home screen + sharing links in" below
- Organize articles into folders (nested, e.g. `Notes/Work`) -- move one from
  its library-row dropdown, tag one on the way in from any "Add an article"
  form, or upload a whole folder at once (subfolder structure preserved)
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

## Mobile: home screen + sharing links in

This app is a valid installable [Web App Manifest](static/manifest.json)
(name, icons, `display: standalone`) -- on both iOS and Android you can add
it to your home screen and launch it full-screen, no browser chrome. Sharing
a link from any other app straight into your library works on both
platforms, but gets there differently:

### Android

Android's Chrome supports the [Web Share Target
API](https://developer.chrome.com/docs/capabilities/web-apis/web-share-target)
natively, no extra setup:

1. Open the LAN URL in Chrome, tap the **⋮** menu -> **Add to Home screen** /
   **Install app**.
2. From then on, Lector shows up as a share target -- share a link from any
   app (browser, a social app, etc.) -> **Lector**, and it opens straight to
   the finished article (`static/manifest.json`'s `share_target` points at
   `/add?autofetch=1`, which fetches and adds with no extra taps; `/add` also
   handles apps that put the shared link in a free-text field rather than a
   dedicated URL field).

**Caveat:** Chrome's install/share-target machinery generally requires a
secure context (HTTPS, or `localhost`). Served over plain HTTP on your LAN,
some Chrome versions may not offer the full install prompt or register the
share target -- if so, a plain bookmark to the LAN URL still works fine, just
without native sharing. Getting HTTPS working on the LAN is a separate,
bigger change (self-signed cert + trusting it on each device).

### iOS

iOS Safari doesn't support the Web Share Target API, so the practical
equivalent is a small Shortcut that opens `/add?url=...&autofetch=1`
(prefills the URL and submits it automatically):

1. Open the **Shortcuts** app -> **+** to create a new shortcut.
2. Add action **Get URLs from Input** (so it works whether the share sheet
   hands it a URL or a plain text string).
3. Add action **URL Encode** on that result.
4. Add action **Text**, and set its content to
   `http://<your-mac's-LAN-IP>:5001/add?url=` followed by the URL-encoded
   result from step 3, followed by `&autofetch=1`. (Find your LAN IP from
   `start.sh`'s printed output, or `ipconfig getifaddr en0`.)
5. Add action **Open URLs**, using that text.
6. Tap the shortcut's name at the top, rename it (e.g. "Add to Reader"), tap
   the settings/info icon, turn on **Show in Share Sheet**, and set it to
   accept **URLs** and **Safari web pages**.

Now sharing a link from Safari (or any app) -> **Add to Reader** opens the
article straight in your library, fetched via defuddle.md/Jina (see below).
Drop `&autofetch=1` from step 4 if you'd rather review/edit the URL before
fetching.

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
