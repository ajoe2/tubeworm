# tubeworm

Load a YouTube video, preview and trim it in your browser, then download the
selected section as audio or video.

1. Paste a link and click **Load video**. Video and audio fetch in parallel to
   the app server, then a playable preview is prepared. No browser save starts.
2. Scrub through the video using the white playhead on the trim timeline or the player.
3. Drag the left and right edges of the highlighted trim bar, or seek and click **Set start here** /
   **Set end here**. The white playhead on the same bar scrubs without changing
   the selection. **Play from playhead** starts there; **Play selection** plays just that interval and stops at its end.
4. Choose an export format and click **Download selection**. The app trims the
   retained original and starts the browser download only after that explicit action.
   Enable **Loop selection** for repeated review. **Check start** and **Check end**
   play the first/last three seconds of the selected clip.
5. Keep editing to export more clips without fetching YouTube again.

The original full-quality source and a lightweight editing preview download in
parallel. The preview prefers H.264/AAC at up to 720p and reuses compatible MP4
files without re-encoding. This adds some network traffic but overlaps preview
preparation with the original download. If a separate preview cannot be fetched,
the app prepares one from the original as a fallback. Only incompatible codecs
need conversion. Exports still use the original full-quality source resolution. Precise cuts re-encode
video as H.264 and audio as Opus or AAC, so they can change quality. Preparing
long videos and exporting clips can take time. Live videos are not supported
by the editor.

## Export formats

| Type | Output choice | File | Codecs |
| --- | --- | --- | --- |
| Video | Compatible | `.mp4` | H.264 + AAC |
| Video | Quality | `.mkv` | H.264 + Opus |
| Audio | Compatible | `.m4a` | AAC |
| Audio | Quality | `.opus` | Opus |

Separate video/audio streams download concurrently, with up to eight concurrent
fragments per stream when supported. Each stream has its own progress bar.
Source files and previews stay on the app server for editing; recent results
are retained for one hour after use. New jobs clean up expired results; active
exports protect their source files. All temporary files are removed on shutdown.

## Run it with Docker

Docker manages all dependencies, so you don't have to install any yourself. The steps are the same on Linux, macOS,
and Windows.

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

## Project layout

```
app/                FastAPI backend
  main.py           routes, SSE, static hosting, lifespan cleanup
  downloader.py     yt-dlp format selection + run
  jobs.py           in-memory job manager, thread→asyncio bridge
  models.py         schemas + the (type, mode) → container map
frontend/           React + Vite + Tailwind + shadcn-style UI
Dockerfile          multi-stage: build UI, then Python runtime with ffmpeg
```

## Validation

```bash
.venv/bin/python -m unittest discover -s tests -v
cd frontend
npm test
npm run typecheck
npm run build
```

Backend tests use locally generated media and require `ffmpeg` and `ffprobe`.

## YouTube HTTP 403 errors

The app enables Node/Deno for YouTube JavaScript challenges and installs the
matching solver through `yt-dlp[default]`. Docker includes Node; local Python
runs require Node 22+ or Deno on `PATH` (in addition to ffmpeg).

After updating the code, rebuild Docker with `docker compose up --build`, or run
`uv sync` and restart the local server. A rejected media URL is automatically
refreshed and retried once. If it still fails, inspect the server's yt-dlp
warnings and update with `uv lock --upgrade-package yt-dlp` followed by `uv sync`
(or rebuild Docker). YouTube may also reject requests for reasons unrelated to
runtime support, such as restrictions on the video or the network address.

The editor preloads preview media and coalesces drag events into serialized seeks,
so new pointer positions do not repeatedly interrupt the video decoder. Drag
feedback stays responsive while the latest requested frame is decoded.
