# tubeworm

A simple YouTube downloader you run on your own computer. Paste a link, pick
**audio** or **video** and **quality** or **compatibility**, and the file saves
straight to your browser's downloads. A progress bar shows speed, ETA, and size
as it works.

Everything runs locally: a FastAPI backend driving
[yt-dlp](https://github.com/yt-dlp/yt-dlp) and `ffmpeg`, behind a small
React/shadcn UI.

## What you get

| Type  | Priority      | Output  | Streams                                           |
| ----- | ------------- | ------- | ------------------------------------------------- |
| Video | Quality       | `.mkv`  | Best AV1/VP9 video + Opus audio, losslessly muxed |
| Video | Compatibility | `.mp4`  | H.264 + AAC — plays on anything                   |
| Audio | Quality       | `.opus` | Native Opus, the highest-quality audio            |
| Audio | Compatibility | `.m4a`  | AAC — plays on anything                            |

The **quality** options copy YouTube's original streams without re-encoding, so
there's no quality loss — `ffmpeg` only repackages them into the chosen container.

## Run it with Docker

Docker bundles tubeworm with everything it needs (Python, `ffmpeg`, and the rest),
so you don't install any of that yourself. The steps are the same on Linux, macOS,
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

To open a terminal in the folder: on macOS use **Terminal**, on Windows use
**PowerShell**, on Linux your terminal app — then `cd` into the folder (many file
managers also have an "Open in Terminal" right-click option).

The first run builds the image, which can take a few minutes. When you see
`Uvicorn running on http://0.0.0.0:8000`, it's ready.

### 4. Open it

Go to **<http://localhost:8000>** in your browser.

### Stopping and restarting

- **Stop:** press `Ctrl+C` in the terminal, then run `docker compose down`.
- **Start again later:** `docker compose up` (no `--build` unless you changed the code).
- **Run in the background:** add `-d`, e.g. `docker compose up -d --build`, and stop
  later with `docker compose down`.

## Run it for development

Prefer to work without Docker? You'll need [uv](https://docs.astral.sh/uv/),
Node.js, and `ffmpeg` installed.

```bash
# Terminal 1 — backend on http://127.0.0.1:8000
uv run python main.py

# Terminal 2 — frontend with hot reload on http://localhost:5173
cd frontend && npm install && npm run dev
```

Use the 5173 URL while developing; Vite proxies `/api` to the backend. To serve the
built UI from FastAPI instead, run `npm run build` (it outputs to `app/static/`) and
open the backend URL.

## How it works

- `POST /api/info` — resolves title, thumbnail, and duration for the preview card.
- `POST /api/jobs` — starts a download and returns a job id.
- `GET /api/jobs/{id}/events` — a Server-Sent Events stream of progress, driven by
  yt-dlp's progress and postprocessor hooks.
- `GET /api/jobs/{id}/file` — streams the finished file with a
  `Content-Disposition: attachment` header so the browser saves it.

Each download is written to a temporary directory and streamed to you. The finished
file is kept only until you start the next download (so you can re-save it), then
removed — nothing is stored long-term.

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
