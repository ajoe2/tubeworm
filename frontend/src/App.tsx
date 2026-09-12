import { useState } from "react"
import { ArrowDownToLine, CheckCircle2, Download } from "lucide-react"

import { ClipEditor } from "@/components/ClipEditor"
import { ErrorAlert } from "@/components/ErrorAlert"
import { ExportOptions, type ExportFormat } from "@/components/ExportOptions"
import { LinkForm } from "@/components/LinkForm"
import { ProgressPanel } from "@/components/ProgressPanel"
import { Button } from "@/components/ui/button"
import { createExport, createPreview, fileUrl, previewMediaUrl } from "@/lib/api"
import { formatBytes, formatTime } from "@/lib/format"
import { useJob, type JobResult } from "@/lib/useJob"

// Mirrors WHOLE_TOLERANCE on the server.
const WHOLE_TOLERANCE = 0.05

interface Source {
  id: string
  title: string
  duration: number
  lossless: string[]
}

export default function App() {
  const job = useJob()
  const [source, setSource] = useState<Source | null>(null)
  const [selection, setSelection] = useState({ start: 0, end: 0 })
  const [format, setFormat] = useState<ExportFormat>({ mediaType: "video", mode: "compatibility" })
  const [saved, setSaved] = useState<JobResult | null>(null)

  async function load(url: string) {
    const result = await job.run(() => createPreview(url))
    if (!result) return
    const duration = result.duration ?? 0
    setSource({ id: result.id, title: result.title, duration, lossless: result.lossless })
    setSelection({ start: 0, end: duration })
    setSaved(null)
  }

  async function exportClip() {
    if (!source) return
    const result = await job.run(() => createExport(source.id, { ...selection, ...format }))
    if (!result) return
    setSaved(result)
    saveFile(result.id)
  }

  function reset() {
    setSource(null)
    setSaved(null)
    job.clearError()
  }

  const whole =
    source != null &&
    selection.start <= WHOLE_TOLERANCE &&
    selection.end >= source.duration - WHOLE_TOLERANCE

  return (
    <div className="mx-auto flex min-h-dvh w-full max-w-2xl flex-col px-5 py-10 sm:py-16">
      <Header />
      <main className="mt-8 space-y-5 rounded-2xl border border-border bg-card/50 p-5 shadow-2xl shadow-black/40 sm:p-6">
        {source ? (
          <>
            <div className="flex items-start justify-between gap-3">
              <h2 className="min-w-0 truncate font-medium" title={source.title}>
                {source.title}
              </h2>
              <Button variant="outline" size="sm" disabled={job.running} onClick={reset}>
                New video
              </Button>
            </div>

            <ClipEditor
              key={source.id}
              src={previewMediaUrl(source.id)}
              duration={source.duration}
              start={selection.start}
              end={selection.end}
              disabled={job.running}
              onChange={(start, end) => {
                setSelection({ start, end })
                setSaved(null)
              }}
            />

            <ExportOptions
              value={format}
              onChange={(next) => {
                setFormat(next)
                setSaved(null)
              }}
              whole={whole}
              lossless={source.lossless}
              disabled={job.running}
            />

            {job.running ? (
              <ProgressPanel progress={job.progress} />
            ) : (
              <div className="space-y-3">
                {job.error && <ErrorAlert message={job.error} />}
                <Button size="lg" className="w-full" onClick={exportClip}>
                  <ArrowDownToLine className="h-5 w-5" />
                  {whole
                    ? "Download full video"
                    : `Download clip · ${formatTime(selection.end - selection.start, 1)}`}
                </Button>
                {saved && <SavedNotice result={saved} />}
              </div>
            )}
          </>
        ) : (
          <LinkForm onLoad={load} busy={job.running} progress={job.progress} error={job.error} />
        )}
      </main>
      <Footer />
    </div>
  )
}

function saveFile(jobId: string) {
  const a = document.createElement("a")
  a.href = fileUrl(jobId)
  a.download = "" // the server sets the filename
  document.body.appendChild(a)
  a.click()
  a.remove()
}

function SavedNotice({ result }: { result: JobResult }) {
  return (
    <div
      role="status"
      className="flex animate-fade-up flex-wrap items-center justify-between gap-3 rounded-xl border border-primary/30 bg-primary/[0.06] px-4 py-3"
    >
      <div className="flex min-w-0 items-center gap-3">
        <CheckCircle2 className="h-5 w-5 shrink-0 text-primary" />
        <div className="min-w-0">
          <p className="text-sm font-medium">Saved to your downloads</p>
          <p className="truncate text-xs text-muted-foreground">
            {result.title}.{result.ext} · {formatBytes(result.filesize)}
          </p>
        </div>
      </div>
      <Button variant="ghost" size="sm" onClick={() => saveFile(result.id)}>
        <Download className="h-3.5 w-3.5" />
        Save again
      </Button>
    </div>
  )
}

function Header() {
  return (
    <header className="flex items-center gap-3">
      <PlumeMark />
      <div>
        <h1 className="font-display text-2xl font-bold lowercase tracking-tight">tubeworm</h1>
        <p className="text-sm text-muted-foreground">
          Download YouTube video or audio. Keep it all, or trim a clip.
        </p>
      </div>
    </header>
  )
}

function PlumeMark() {
  return (
    <svg viewBox="0 0 32 32" className="h-10 w-10 shrink-0" role="img" aria-label="tubeworm logo">
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

function Footer() {
  return (
    <footer className="mt-auto pt-10 text-center text-xs text-muted-foreground/70">
      Runs entirely on your machine · yt-dlp + ffmpeg
    </footer>
  )
}
