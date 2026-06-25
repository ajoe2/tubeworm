# tubeworm

A lightweight, self-hosted YouTube downloader. Paste a link, choose **audio** or
**video**, choose **quality** or **compatibility**, and the file streams straight
to your browser's downloads. A live progress bar reports speed, ETA and size as
it works.

It runs entirely on your machine: a FastAPI backend drives
[yt-dlp](https://github.com/yt-dlp/yt-dlp) + `ffmpeg`, and a small React/shadcn UI
sits in front of it.

## What you get

| Type  | Priority      | Output  | Streams                                           |
| ----- | ------------- | ------- | ------------------------------------------------- |
| Video | Quality       | `.mkv`  | Best AV1/VP9 video + Opus audio, losslessly muxed |
| Video | Compatibility | `.mp4`  | H.264 + AAC — plays on anything                   |
| Audio | Quality       | `.opus` | Native Opus, the highest-quality audio            |
| Audio | Compatibility | `.m4a`  | AAC — plays on anything                            |

The *quality* paths copy the original streams without re-encoding, so there's no
generational quality loss — `ffmpeg` only muxes/remuxes the containers.

## Run it with Docker (recommended)

```bash
docker compose up --build
```

Then open <http://localhost:8000>. `ffmpeg` is included in the image; nothing else
to install.

To stop: `docker compose down`.

## Run it locally for development

Requires [uv](https://docs.astral.sh/uv/), Node.js, and `ffmpeg` on your `PATH`.

```bash
# Terminal 1 — backend (http://127.0.0.1:8000)
uv run python main.py

# Terminal 2 — frontend dev server with hot reload (http://localhost:5173)
cd frontend
npm install
npm run dev
```

The Vite dev server proxies `/api` to the backend, so use the 5173 URL while
developing. To serve the built UI directly from FastAPI instead, run
`npm run build` (it emits into `app/static/`) and open the backend URL.

## How it works

- `POST /api/info` — resolves title/thumbnail/duration for the preview card.
- `POST /api/jobs` — starts a download; returns a job id.
- `GET /api/jobs/{id}/events` — Server-Sent Events stream of progress, driven by
  yt-dlp's progress + postprocessor hooks.
- `GET /api/jobs/{id}/file` — streams the finished file with a
  `Content-Disposition: attachment` header so the browser saves it.

Downloads are written to a temporary directory and streamed to you; the finished
file is kept only until you start the next download (so you can re-save it), then
swept. Nothing is stored long-term.

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

## Note

For personal use. Respect YouTube's Terms of Service and the rights of content
owners — download only what you're permitted to.
