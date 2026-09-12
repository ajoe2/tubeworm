# tubeworm

A YouTube downloader and clip trimmer you run on your own computer. Paste a
link, preview the video in your browser, keep all of it or trim a section, and
download it as video or audio.

## How it works

1. **Paste a link and click Load video.** The full-quality video and a small
   editing preview download to the app server in parallel. Nothing is saved
   to your Downloads folder yet.
2. **Trim.** Drag the coral handles on the timeline, or scrub to a spot and use
   *Set start here* / *Set end here*. *Play selection* plays just your clip;
   click a start or end time to hear that edge. Or leave the selection alone
   to keep the whole video.
3. **Pick a format and click Download.** The file is prepared from the retained
   original and saved through your browser. Keep editing to export more clips
   without fetching YouTube again.

## Export formats

| Format | Priority   | File    | Whole video                          | Trimmed clip           |
| ------ | ---------- | ------- | ------------------------------------ | ---------------------- |
| Video  | Quality    | `.mkv`  | Original streams copied, no loss     | H.264 + Opus           |
| Video  | Compatible | `.mp4`  | Copied if H.264/AAC, else converted  | H.264 + AAC            |
| Audio  | Quality    | `.opus` | Original Opus copied, no loss        | Opus 192 kb/s          |
| Audio  | Compatible | `.m4a`  | Copied if AAC, else converted        | AAC 192 kb/s           |

Whole-video exports copy the original streams whenever the container allows it,
so they are fast and lossless. Trimmed clips are re-encoded so the cut lands
exactly on your times; the UI tells you which will happen before you export.
YouTube's best streams are usually AV1/VP9 + Opus, so `.mkv` and `.opus` are the
lossless choices. Live streams cannot be edited.

Downloaded originals stay on the app server for an hour after their last use so
you can export more clips, then they are removed. Everything is removed on
shutdown.

## Run it with Docker

Docker manages all dependencies, so you don't have to install any yourself. The
steps are the same on Linux, macOS, and Windows.

### 1. Install Docker

**macOS** — Download Docker Desktop from
[docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/).
Open the `.dmg`, drag Docker to Applications, then launch it and wait for the whale
icon in the menu bar to stop animating.

**Windows** — Download Docker Desktop from the same page and run the installer.
Accept the WSL 2 option if prompted (it sets up the Linux layer Docker needs), then
restart if asked. Launch Docker Desktop and wait for it to report "Engine running."

**Linux** — Install Docker Engine by following
[docs.docker.com/engine/install](https://docs.docker.com/engine/install/), or use the
official convenience script:

```bash
curl -fsSL https://get.docker.com | sh
```

This includes the `docker compose` command used below. You may need to log out and
back in (or prefix commands with `sudo`).

Check that it's working:

```bash
docker --version
```

### 2. Get the code

Clone the repository (or download it as a ZIP and unzip it), then move into the
folder:

```bash
git clone <your-repo-url> tubeworm
cd tubeworm
```

### 3. Start the app

From inside the `tubeworm` folder, run:

```bash
docker compose up --build
```

The first run builds the image, which can take a few minutes. When you see
`Uvicorn running on http://0.0.0.0:8000`, it's ready.

### 4. Open it

Go to **<http://localhost:8000>** in your browser.

### Stopping and restarting

- **Stop:** press `Ctrl+C` in the terminal, then run `docker compose down`.
- **Start again later:** `docker compose up` (no `--build` unless you changed the code).
- **Run in the background:** add `-d`, e.g. `docker compose up -d --build`, and stop
  later with `docker compose down`.

## Run it without Docker

You need `ffmpeg` and `ffprobe`, Node 22+ (yt-dlp uses it to solve YouTube's
JavaScript challenges), and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
(cd frontend && npm ci && npm run build)   # emits app/static
uv run python main.py                      # http://127.0.0.1:8000
```

For frontend development run `npm run dev` in `frontend/` alongside the API;
Vite proxies `/api` to it.

## Project layout

```
app/                FastAPI backend
  main.py           routes, SSE, static hosting, lifespan cleanup
  jobs.py           in-memory jobs, thread→asyncio bridge, retention sweep
  downloader.py     yt-dlp: metadata cache, parallel stream downloads
  media.py          ffmpeg: probing, lossless mux, preview proxy, clip export
  models.py         schemas + the (format, priority) → container map
frontend/           React + Vite + Tailwind
  src/App.tsx       screens: link form → editor
  src/lib/useJob.ts follows one server job over SSE
  src/components/   ClipEditor, TrimTimeline, ExportOptions, ProgressPanel, LinkForm
tests/              backend tests (need ffmpeg/ffprobe; no network)
Dockerfile          multi-stage: build UI, then Python runtime with ffmpeg + node
```

## Validation

```bash
uv run python -m unittest discover -s tests
cd frontend && npm test && npm run typecheck && npm run build
```

## YouTube HTTP 403 errors

A rejected media URL is refreshed and retried once automatically. If downloads
still fail with HTTP 403, YouTube has probably changed something: update yt-dlp
with `uv lock --upgrade-package yt-dlp && uv sync` (or rebuild Docker) and check
the server log for JavaScript-challenge warnings. YouTube may also reject
requests for reasons unrelated to the app, such as restrictions on the video or
on your network address.
