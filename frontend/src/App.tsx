import { useEffect, useRef, useState } from "react"
import {
  AlertTriangle,
  ArrowDownToLine,
  Link2,
  Music2,
  ShieldCheck,
  Sparkles,
  Video,
} from "lucide-react"
import { ClipEditor } from "@/components/ClipEditor"
import { ProgressPanel } from "@/components/ProgressPanel"
import { Segmented } from "@/components/Segmented"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  eventsUrl,
  fileUrl,
  createPreview,
  exportSelection,
  type DownloadEvent,
  type MediaType,
  type Mode,
  type StreamProgress,
} from "@/lib/api"
import { formatDuration } from "@/lib/format"

export default function App() {
  const [url, setUrl] = useState("")
  const [preview, setPreview] = useState<{
    id: string
    title: string
    duration: number
  } | null>(null)
  const [phase, setPhase] = useState<"idle" | "ingest" | "edit" | "export">(
    "idle",
  )
  const [event, setEvent] = useState<DownloadEvent | null>(null)
  const [previewStatus, setPreviewStatus] = useState(
    "Preparing the editing preview alongside the original download.",
  )
  const [streams, setStreams] = useState<StreamProgress[]>([])
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<string | null>(null)
  const [start, setStart] = useState(0)
  const [end, setEnd] = useState(0)
  const [mediaType, setMediaType] = useState<MediaType>("video")
  const [mode, setMode] = useState<Mode>("compatibility")
  const es = useRef<EventSource | null>(null)
  const busyRef = useRef(false)
  const busy = phase === "ingest" || phase === "export"
  useEffect(() => () => es.current?.close(), [])

  function save(id: string) {
    const a = document.createElement("a")
    a.href = fileUrl(id)
    a.download = ""
    document.body.appendChild(a)
    a.click()
    a.remove()
  }

  async function run(kind: "ingest" | "export") {
    if (busyRef.current || !url.trim() || (kind === "export" && !preview))
      return
    busyRef.current = true
    es.current?.close()
    setError(null)
    setResult(null)
    setEvent(null)
    setStreams([])
    setPreviewStatus(
      "Preparing the editing preview alongside the original download.",
    )
    setPhase(kind)
    try {
      const id =
        kind === "ingest"
          ? await createPreview(url.trim())
          : await exportSelection(preview!.id, start, end, mediaType, mode)
      const stream = new EventSource(eventsUrl(id))
      es.current = stream
      stream.onmessage = ({ data }) => {
        const next = JSON.parse(data) as DownloadEvent
        if (next.phase === "preview") {
          setPreviewStatus(
            next.status === "completed"
              ? "Editing preview ready. Finishing the original download."
              : next.postprocessor
                ? "Preparing the browser preview alongside the original download."
                : "Fetching the lightweight preview alongside the original download.",
          )
          return
        }
        setEvent(next)
        if (next.phase === "download") setStreams(next.streams ?? [])
        if (next.postprocessor === "Refresh") setStreams([])
        if (next.phase !== "complete") return
        stream.close()
        busyRef.current = false
        if (next.status !== "completed") {
          setError(next.error ?? "Could not prepare the video.")
          setPhase(kind === "ingest" ? "idle" : "edit")
          return
        }
        if (kind === "ingest") {
          if (!next.duration || next.duration <= 0) {
            setError("The video has no playable duration.")
            setPhase("idle")
            return
          }
          setPreview({
            id,
            title: next.title ?? "Video",
            duration: next.duration,
          })
          setStart(0)
          setEnd(next.duration)
          setPhase("edit")
        } else {
          setResult(id)
          setPhase("edit")
          save(id)
        }
      }
      stream.onerror = () => {
        stream.close()
        busyRef.current = false
        setError("Lost connection to the server. Please try again.")
        setPhase(kind === "ingest" ? "idle" : "edit")
      }
    } catch (err) {
      busyRef.current = false
      setError(err instanceof Error ? err.message : "Something went wrong.")
      setPhase(kind === "ingest" ? "idle" : "edit")
    }
  }
  const processing = event?.phase === "postprocess"
  const refreshing = event?.postprocessor === "Refresh"
  const stage = refreshing
    ? "retry"
    : processing || phase === "export"
      ? "process"
      : event?.phase === "download"
        ? "download"
        : "prepare"
  const label = refreshing
    ? "Refreshing link and retrying…"
    : phase === "export"
      ? "Preparing your selected clip"
      : event?.postprocessor === "PreviewWait"
        ? "Finishing the editing preview…"
        : event?.postprocessor === "PreviewRemux"
          ? "Packaging the preview…"
          : event?.postprocessor === "Preview"
            ? "Converting video for browser playback…"
            : processing
              ? "Combining video and audio"
              : event?.phase === "download"
                ? streams.length > 1
                  ? "Fetching video and audio in parallel"
                  : "Fetching video"
                : "Reading your YouTube link…"

  return (
    <div className="relative mx-auto flex min-h-dvh w-full max-w-2xl flex-col px-5 py-10 sm:py-16">
      <Header />
      <main className="mt-8 space-y-5 rounded-2xl border border-border bg-card/50 p-5 shadow-2xl shadow-black/40 sm:p-6">
        <ol className="flex justify-between gap-2 text-xs text-muted-foreground">
          <li className={!preview ? "text-primary" : ""}>1. Load video</li>
          <li className={preview && !busy ? "text-primary" : ""}>
            2. Preview &amp; trim
          </li>
          <li className={phase === "export" || result ? "text-primary" : ""}>
            3. Download selection
          </li>
        </ol>
        {!preview && (
          <>
            <label className="block space-y-2 text-sm">
              <span>YouTube link</span>
              <div className="relative">
                <Link2 className="absolute left-4 top-4 h-4 w-4 text-muted-foreground" />
                <Input
                  aria-label="YouTube link"
                  className="pl-11"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") run("ingest")
                  }}
                  disabled={busy}
                  placeholder="Paste a YouTube link"
                />
              </div>
            </label>
            {!busy && (
              <>
                <Button
                  size="lg"
                  className="w-full"
                  disabled={!url.trim()}
                  onClick={() => run("ingest")}
                >
                  <Video className="h-4 w-4" />
                  Load video
                </Button>
                <p className="text-sm text-muted-foreground">
                  We’ll fetch the video and open a playable preview. Nothing is
                  saved to your Downloads folder yet.
                </p>
              </>
            )}
          </>
        )}
        {preview && (
          <>
            <div className="flex items-start justify-between gap-3">
              <h2 className="min-w-0 font-medium">{preview.title}</h2>
              <Button
                variant="outline"
                size="default"
                disabled={busy}
                onClick={() => {
                  setPreview(null)
                  setResult(null)
                  setError(null)
                  setPhase("idle")
                }}
              >
                New video
              </Button>
            </div>
            <ClipEditor
              key={preview.id}
              src={`/api/previews/${preview.id}/media`}
              duration={preview.duration}
              start={start}
              end={end}
              disabled={busy}
              onChange={(a, b) => {
                setStart(a)
                setEnd(b)
                setResult(null)
              }}
            />
            <div className="grid gap-4 sm:grid-cols-2">
              <Segmented<MediaType>
                label="Export format"
                value={mediaType}
                onChange={(v) => {
                  setMediaType(v)
                  setResult(null)
                }}
                disabled={busy}
                options={[
                  {
                    value: "video",
                    label: "Video",
                    icon: <Video className="h-4 w-4" />,
                  },
                  {
                    value: "audio",
                    label: "Audio",
                    icon: <Music2 className="h-4 w-4" />,
                  },
                ]}
              />
              <Segmented<Mode>
                label="Output"
                value={mode}
                onChange={(v) => {
                  setMode(v)
                  setResult(null)
                }}
                disabled={busy}
                options={[
                  {
                    value: "compatibility",
                    label: "Compatible",
                    icon: <ShieldCheck className="h-4 w-4" />,
                  },
                  {
                    value: "quality",
                    label: "Quality",
                    icon: <Sparkles className="h-4 w-4" />,
                  },
                ]}
              />
            </div>
            <p className="text-xs text-muted-foreground">
              .
              {mediaType === "video"
                ? mode === "quality"
                  ? "mkv"
                  : "mp4"
                : mode === "quality"
                  ? "opus"
                  : "m4a"}{" "}
              · Exports use the original source with precise cuts. Video is
              re-encoded as H.264; audio uses{" "}
              {mode === "quality" ? "Opus" : "AAC"}.
            </p>
            {!busy && (
              <Button
                size="lg"
                className="w-full"
                onClick={() => run("export")}
              >
                <ArrowDownToLine className="h-4 w-4" />
                Download selection · {formatDuration(end - start)}
              </Button>
            )}
          </>
        )}
        {busy && (
          <ProgressPanel
            stage={stage}
            streams={streams}
            cropped={phase === "export"}
            selection={
              phase === "ingest"
                ? "Preparing the full video for the editor"
                : `${formatDuration(start)} – ${formatDuration(end)}`
            }
            percent={event?.percent ?? 0}
            indeterminate={stage !== "download" || event?.percent == null}
            phaseLabel={label}
            speed={event?.speed}
            eta={event?.eta}
            downloaded={event?.downloaded}
            total={event?.total}
            purpose={phase === "ingest" ? "preview" : "export"}
          />
        )}
        {phase === "ingest" && (
          <p className="text-xs text-muted-foreground">{previewStatus}</p>
        )}
        {error && <ErrorAlert message={error} />}
        {result && (
          <div
            role="status"
            className="space-y-2 rounded-xl border border-primary/30 bg-primary/5 p-4"
          >
            <p className="text-sm">
              Your clip is ready and the browser download has started. You can
              keep editing to export another clip.
            </p>
            <Button variant="secondary" onClick={() => save(result)}>
              Save clip again
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
          Download YouTube audio &amp; video. Keep it all, or trim a clip.
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

function ErrorAlert({ message }: { message: string }) {
  return (
    <div
      role="alert"
      className="flex animate-fade-up items-start gap-2.5 rounded-lg border border-destructive/40 bg-destructive/10 px-3.5 py-3 text-sm text-destructive-foreground"
    >
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
