# tubeworm

A YouTube downloader you run on your own computer. Paste a link, pick
a file type, and click download.

## Supported file types

| Type  | Priority      | Output  | Streams                                           |
| ----- | ------------- | ------- | ------------------------------------------------- |
| Video | Quality       | `.mkv`  | Best AV1/VP9 video + Opus audio, losslessly muxed |
| Video | Compatibility | `.mp4`  | H.264 + AAC — plays on anything                   |
| Audio | Quality       | `.opus` | Native Opus, the highest-quality audio            |
| Audio | Compatibility | `.m4a`  | AAC — plays on anything                            |

The quality options copy YouTube's original streams without re-encoding, so
there's no quality loss.

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
