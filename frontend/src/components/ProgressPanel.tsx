import { Loader2, Music2, Video } from "lucide-react"

import type { ProcessStep, ProxyStatus, StreamProgress } from "@/lib/api"
import { formatBytes, formatSpeed, formatTime } from "@/lib/format"
import type { JobProgress } from "@/lib/useJob"

const STEP_LABELS: Record<ProcessStep, string> = {
  merge: "Combining video and audio…",
  retry: "The link expired. Refreshing and retrying…",
  "preview-wait": "Finishing the editing preview…",
  preview: "Converting the preview for playback…",
  trim: "Cutting and encoding your clip…",
  remux: "Packaging the original streams…",
  convert: "Converting for compatibility…",
}

const PROXY_LABELS: Record<ProxyStatus, string> = {
  downloading: "downloading",
  converting: "converting",
  ready: "ready",
}

export function ProgressPanel({ progress }: { progress: JobProgress }) {
  const { download, step, proxy } = progress
  const label = step
    ? STEP_LABELS[step]
    : download
      ? download.streams.length > 1
        ? "Downloading video and audio…"
        : "Downloading…"
      : "Reading the link…"
  const percent = step || !download ? null : download.percent

  return (
    <section
      aria-label="Progress"
      aria-live="polite"
      className="animate-fade-up space-y-3 rounded-xl border border-border bg-card/70 p-4"
    >
      <div className="flex items-center justify-between gap-3 text-sm">
        <span className="flex items-center gap-2 font-medium">
          <Loader2 className="h-4 w-4 shrink-0 animate-spin text-primary" />
          {label}
        </span>
        {percent != null && (
          <span className="font-mono tabular-nums text-primary">{Math.round(percent)}%</span>
        )}
      </div>
      <Bar label="Overall progress" percent={percent} />

      {download && !step && (
        <>
          {download.streams.length > 1 && (
            <ul className="space-y-2">
              {download.streams.map((stream) => (
                <StreamRow key={stream.id} stream={stream} />
              ))}
            </ul>
          )}
          <p className="font-mono text-xs tabular-nums text-muted-foreground">
            {formatBytes(download.downloaded)}
            {download.total ? ` / ${formatBytes(download.total)}` : ""}
            {download.speed ? ` · ${formatSpeed(download.speed)}` : ""}
            {download.eta != null ? ` · ${formatTime(download.eta)} left` : ""}
          </p>
        </>
      )}

      {proxy && (
        <p className="text-xs text-muted-foreground">
          Editing preview: {PROXY_LABELS[proxy]}
        </p>
      )}
    </section>
  )
}

function StreamRow({ stream }: { stream: StreamProgress }) {
  const Icon = stream.label === "Audio" ? Music2 : Video
  const finished = stream.status === "finished"
  const status = finished
    ? "done"
    : stream.status === "pending"
      ? "connecting…"
      : stream.percent == null
        ? formatBytes(stream.downloaded)
        : `${Math.round(stream.percent)}%`
  return (
    <li className="space-y-1.5">
      <div className="flex items-center justify-between gap-2 text-xs">
        <span className="flex items-center gap-1.5 text-muted-foreground">
          <Icon className="h-3.5 w-3.5" />
          {stream.label}
        </span>
        <span className={finished ? "text-primary" : "font-mono tabular-nums text-muted-foreground"}>
          {status}
        </span>
      </div>
      <Bar label={`${stream.label} download`} percent={finished ? 100 : stream.percent} thin />
    </li>
  )
}

function Bar({ label, percent, thin }: { label: string; percent: number | null; thin?: boolean }) {
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={percent == null ? undefined : Math.round(percent)}
      className={`relative overflow-hidden rounded-full bg-secondary ${thin ? "h-1" : "h-2"}`}
    >
      {percent == null ? (
        <div className="absolute inset-y-0 left-0 w-1/4 animate-indeterminate rounded-full bg-primary" />
      ) : (
        <div
          className="h-full rounded-full bg-primary transition-[width] duration-200 ease-out"
          style={{ width: `${Math.max(0, Math.min(100, percent))}%` }}
        />
      )}
    </div>
  )
}
