import { useEffect, useRef, useState } from "react"
import {
  AlertTriangle,
  ArrowDownToLine,
  CheckCircle2,
  Download,
  Link2,
  Music2,
  ShieldCheck,
  Sparkles,
  Video,
  X,
} from "lucide-react"

import { ProgressPanel } from "@/components/ProgressPanel"
import { Segmented } from "@/components/Segmented"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  createJob,
  eventsUrl,
  fetchInfo,
  fileUrl,
  type DownloadEvent,
  type MediaInfo,
  type MediaType,
  type Mode,
} from "@/lib/api"
import { formatBytes, formatDuration } from "@/lib/format"

type Phase = "idle" | "working" | "done" | "error"

interface FormatSpec {
  container: string
  blurb: string
}

const FORMAT_INFO: Record<MediaType, Record<Mode, FormatSpec>> = {
  video: {
    quality: { container: "mkv", blurb: "Best AV1/VP9 video + Opus, losslessly muxed" },
    compatibility: { container: "mp4", blurb: "H.264 + AAC — plays on anything" },
  },
  audio: {
    quality: { container: "opus", blurb: "Native Opus, the highest-quality audio" },
    compatibility: { container: "m4a", blurb: "AAC audio — plays on anything" },
  },
}

const YT_PATTERN =
  /(?:youtube\.com\/(?:watch\?v=|shorts\/|live\/|embed\/)|youtu\.be\/)[\w-]{11}/

function postprocessLabel(name?: string | null): string {
  switch (name) {
    case "Merger":
      return "Merging video and audio"
    case "ExtractAudio":
    case "FFmpegExtractAudio":
      return "Extracting audio"
    case "VideoConvertor":
    case "FFmpegVideoConvertor":
      return "Converting"
    default:
      return "Finalizing"
  }
}

export default function App() {
  const [url, setUrl] = useState("")
  const [mediaType, setMediaType] = useState<MediaType>("video")
  const [mode, setMode] = useState<Mode>("quality")

  const [info, setInfo] = useState<MediaInfo | null>(null)
  const [infoLoading, setInfoLoading] = useState(false)

  const [phase, setPhase] = useState<Phase>("idle")
  const [percent, setPercent] = useState(0)
  const [indeterminate, setIndeterminate] = useState(false)
  const [phaseLabel, setPhaseLabel] = useState("")
  const [speed, setSpeed] = useState<number | null>(null)
  const [eta, setEta] = useState<number | null>(null)
  const [downloaded, setDownloaded] = useState<number | null>(null)
  const [total, setTotal] = useState<number | null>(null)

  const [result, setResult] = useState<DownloadEvent | null>(null)
  const [error, setError] = useState<string | null>(null)

  const esRef = useRef<EventSource | null>(null)
  const finishedRef = useRef(false)
  const jobIdRef = useRef<string | null>(null)

  const spec = FORMAT_INFO[mediaType][mode]
  const busy = phase === "working"

  // Resolve a lightweight preview as the user settles on a link.
  useEffect(() => {
    const trimmed = url.trim()
    if (!YT_PATTERN.test(trimmed)) {
      setInfo(null)
      setInfoLoading(false)
      return
    }
    const controller = new AbortController()
    setInfoLoading(true)
    const timer = setTimeout(() => {
      fetchInfo(trimmed, controller.signal)
        .then(setInfo)
        .catch(() => setInfo(null))
        .finally(() => setInfoLoading(false))
    }, 450)
    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, [url])

  useEffect(() => () => esRef.current?.close(), [])

  function triggerSave(jobId: string, title?: string | null, ext?: string | null) {
    const a = document.createElement("a")
    a.href = fileUrl(jobId)
    if (title && ext) a.download = `${title}.${ext}`
    document.body.appendChild(a)
    a.click()
    a.remove()
  }

  function reset() {
    esRef.current?.close()
    setPhase("idle")
    setPercent(0)
    setIndeterminate(false)
    setResult(null)
    setError(null)
    setSpeed(null)
    setEta(null)
    setDownloaded(null)
    setTotal(null)
  }

  async function start() {
    if (!url.trim() || busy) return
    esRef.current?.close()
    setError(null)
    setResult(null)
    setPercent(0)
    setIndeterminate(true)
    setPhaseLabel("Starting…")
    setSpeed(null)
    setEta(null)
    setDownloaded(null)
    setTotal(null)
    setPhase("working")
    finishedRef.current = false

    const totalStreams = mediaType === "video" ? 2 : 1
    let completed = 0

    try {
      const id = await createJob(url.trim(), mediaType, mode)
      jobIdRef.current = id
      const es = new EventSource(eventsUrl(id))
      esRef.current = es

      es.onmessage = (e) => {
        const ev = JSON.parse(e.data) as DownloadEvent

        if (ev.phase === "download") {
          const finishedStream = ev.status === "finished"
          if (finishedStream) completed = Math.min(completed + 1, totalStreams)
          const frac = finishedStream ? 0 : (ev.percent ?? 0) / 100
          setIndeterminate(false)
          setPercent(Math.min(99, ((completed + frac) / totalStreams) * 100))
          setPhaseLabel(
            totalStreams > 1
              ? `Downloading stream ${Math.min(completed + 1, totalStreams)} of ${totalStreams}`
              : "Downloading",
          )
          setSpeed(ev.speed ?? null)
          setEta(ev.eta ?? null)
          setDownloaded(ev.downloaded ?? null)
          setTotal(ev.total ?? null)
        } else if (ev.phase === "postprocess") {
          setIndeterminate(true)
          setPhaseLabel(postprocessLabel(ev.postprocessor))
        } else if (ev.phase === "complete") {
          finishedRef.current = true
          es.close()
          if (ev.status === "completed") {
            setIndeterminate(false)
            setPercent(100)
            setResult(ev)
            setPhase("done")
            triggerSave(id, ev.title, ev.ext)
          } else {
            setPhase("error")
            setError(ev.error ?? "Download failed.")
          }
        }
      }

      es.onerror = () => {
        if (finishedRef.current) return
        finishedRef.current = true
        es.close()
        setPhase("error")
        setError("Lost connection to the server.")
      }
    } catch (err) {
      setPhase("error")
      setError(err instanceof Error ? err.message : "Something went wrong.")
    }
  }

  return (
    <div className="relative mx-auto flex min-h-dvh w-full max-w-xl flex-col px-5 py-12 sm:py-20">
      <Header />

      <main className="mt-10 space-y-5 rounded-2xl border border-border bg-card/50 p-5 shadow-2xl shadow-black/40 backdrop-blur-sm sm:p-6">
        <div className="relative">
          <Link2 className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") start()
            }}
            disabled={busy}
            placeholder="Paste a YouTube link"
            spellCheck={false}
            autoComplete="off"
            aria-label="YouTube link"
            className="pl-11 pr-10"
          />
          {url && !busy && (
            <button
              type="button"
              onClick={() => setUrl("")}
              aria-label="Clear link"
              className="absolute right-3 top-1/2 -translate-y-1/2 rounded-md p-1 text-muted-foreground transition-colors hover:bg-secondary/60 hover:text-foreground"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>

        {(info || infoLoading) && (
          <Preview info={info} loading={infoLoading} />
        )}

        <div className="grid gap-4 sm:grid-cols-2">
          <Segmented<MediaType>
            label="Format"
            value={mediaType}
            onChange={setMediaType}
            disabled={busy}
            options={[
              { value: "video", label: "Video", icon: <Video className="h-4 w-4" /> },
              { value: "audio", label: "Audio", icon: <Music2 className="h-4 w-4" /> },
            ]}
          />
          <Segmented<Mode>
            label="Priority"
            value={mode}
            onChange={setMode}
            disabled={busy}
            options={[
              { value: "quality", label: "Quality", icon: <Sparkles className="h-4 w-4" /> },
              {
                value: "compatibility",
                label: "Compatible",
                icon: <ShieldCheck className="h-4 w-4" />,
              },
            ]}
          />
        </div>

        <div className="flex items-center justify-between gap-3 rounded-lg border border-border bg-secondary/25 px-3.5 py-2.5">
          <span className="text-sm text-muted-foreground">{spec.blurb}</span>
          <span className="rounded-md bg-background/60 px-2 py-1 font-mono text-xs font-medium text-primary">
            .{spec.container}
          </span>
        </div>

        {phase === "done" && result ? (
          <DonePanel
            result={result}
            onSaveAgain={() =>
              jobIdRef.current &&
              triggerSave(jobIdRef.current, result.title, result.ext)
            }
            onReset={reset}
          />
        ) : busy ? (
          <ProgressPanel
            percent={percent}
            indeterminate={indeterminate}
            phaseLabel={phaseLabel}
            speed={speed}
            eta={eta}
            downloaded={downloaded}
            total={total}
          />
        ) : (
          <div className="space-y-3">
            {phase === "error" && error && <ErrorAlert message={error} />}
            <Button
              size="lg"
              onClick={start}
              disabled={!url.trim()}
              className="w-full"
            >
              <ArrowDownToLine className="h-5 w-5" />
              {phase === "error" ? "Try again" : "Pull it down"}
            </Button>
          </div>
        )}
      </main>

      <Footer />
    </div>
  )
}

function Header() {
  return (
    <header className="flex items-center gap-3">
      <PlumeMark />
      <div>
        <h1 className="font-display text-2xl font-bold lowercase tracking-tight text-foreground">
          tubeworm
        </h1>
        <p className="text-sm text-muted-foreground">
          Pull audio &amp; video off YouTube, at full quality.
        </p>
      </div>
    </header>
  )
}

function PlumeMark() {
  return (
    <svg
      viewBox="0 0 32 32"
      className="h-10 w-10 shrink-0"
      role="img"
      aria-label="tubeworm logo"
    >
      <rect
        x="11"
        y="17"
        width="10"
        height="14"
        rx="4.5"
        className="fill-secondary"
        stroke="hsl(var(--border))"
        strokeWidth="1"
      />
      <g
        className="animate-plume text-primary"
        stroke="currentColor"
        strokeWidth="2.4"
        strokeLinecap="round"
        fill="none"
        style={{ transformOrigin: "16px 19px" }}
      >
        <path d="M13 19 C 11.5 13, 11.5 10, 13 6.5" />
        <path d="M16 19 C 16 11.5, 16 8, 16 4.5" />
        <path d="M19 19 C 20.5 13, 20.5 10, 19 6.5" />
      </g>
    </svg>
  )
}

function Preview({ info, loading }: { info: MediaInfo | null; loading: boolean }) {
  if (loading && !info) {
    return (
      <div className="flex animate-pulse gap-3 rounded-xl border border-border bg-card/50 p-3">
        <div className="h-[3.75rem] w-28 shrink-0 rounded-md bg-secondary" />
        <div className="flex-1 space-y-2 py-1">
          <div className="h-3.5 w-3/4 rounded bg-secondary" />
          <div className="h-3 w-1/2 rounded bg-secondary" />
        </div>
      </div>
    )
  }
  if (!info) return null
  return (
    <div className="flex animate-fade-up gap-3 rounded-xl border border-border bg-card/60 p-3">
      {info.thumbnail ? (
        <img
          src={info.thumbnail}
          alt=""
          className="h-[3.75rem] w-28 shrink-0 rounded-md object-cover"
          loading="lazy"
        />
      ) : (
        <div className="flex h-[3.75rem] w-28 shrink-0 items-center justify-center rounded-md bg-secondary">
          <Video className="h-5 w-5 text-muted-foreground" />
        </div>
      )}
      <div className="min-w-0 flex-1 self-center">
        <p className="truncate font-medium text-foreground">
          {info.title ?? "Untitled"}
        </p>
        <p className="truncate text-sm text-muted-foreground">{info.uploader ?? ""}</p>
        {info.duration != null && (
          <span className="mt-1 inline-block font-mono text-xs text-muted-foreground/80">
            {formatDuration(info.duration)}
          </span>
        )}
      </div>
    </div>
  )
}

function DonePanel({
  result,
  onSaveAgain,
  onReset,
}: {
  result: DownloadEvent
  onSaveAgain: () => void
  onReset: () => void
}) {
  return (
    <div className="animate-fade-up space-y-4 rounded-xl border border-primary/30 bg-primary/[0.06] p-4">
      <div className="flex items-center gap-3">
        <CheckCircle2 className="h-6 w-6 shrink-0 text-primary" />
        <div className="min-w-0">
          <p className="font-medium text-foreground">Saved to your downloads</p>
          <p className="truncate text-sm text-muted-foreground">
            {result.title}.{result.ext}
            {result.filesize ? ` · ${formatBytes(result.filesize)}` : ""}
          </p>
        </div>
      </div>
      <div className="flex gap-2">
        <Button variant="secondary" onClick={onSaveAgain} className="flex-1">
          <Download className="h-4 w-4" />
          Save again
        </Button>
        <Button variant="outline" onClick={onReset} className="flex-1">
          Download another
        </Button>
      </div>
    </div>
  )
}

function ErrorAlert({ message }: { message: string }) {
  return (
    <div className="flex animate-fade-up items-start gap-2.5 rounded-lg border border-destructive/40 bg-destructive/10 px-3.5 py-3 text-sm text-destructive-foreground">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
      <span className="min-w-0 break-words">{message}</span>
    </div>
  )
}

function Footer() {
  return (
    <footer className="mt-auto pt-10 text-center text-xs text-muted-foreground/70">
      Runs entirely on your machine · yt-dlp + ffmpeg
    </footer>
  )
}
