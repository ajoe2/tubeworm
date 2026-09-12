import { CheckCircle2, Loader2, Music2, Video } from "lucide-react"
import type { StreamProgress } from "@/lib/api"
import { formatBytes, formatEta, formatSpeed } from "@/lib/format"

interface ProgressPanelProps {
  purpose?: "preview" | "export"
  stage: "prepare" | "download" | "process" | "retry"
  streams: StreamProgress[]
  cropped: boolean
  selection: string
  percent: number
  indeterminate: boolean
  phaseLabel: string
  speed?: number | null
  eta?: number | null
  downloaded?: number | null
  total?: number | null
}

export function ProgressPanel({
  purpose,
  stage,
  streams,
  cropped,
  selection,
  percent,
  indeterminate,
  phaseLabel,
  speed,
  eta,
  downloaded,
  total,
}: ProgressPanelProps) {
  const downloading = stage === "download"
  const processing = stage === "process"
  const steps =
    purpose === "preview"
      ? ["Fetch video", "Prepare preview", "Edit"]
      : ["Source ready", "Trim clip", "Save"]
  return (
    <section
      aria-label="Download progress"
      className="animate-fade-up space-y-4 rounded-xl border border-border bg-card/70 p-4"
    >
      <ol className="flex gap-2 text-xs">
        {steps.map((label, index) => (
          <li
            key={label}
            aria-current={index === (processing ? 1 : 0) ? "step" : undefined}
            className={`flex flex-1 items-center gap-1.5 border-t-2 pt-2 ${index <= (processing ? 1 : 0) ? "border-primary text-foreground" : "border-border text-muted-foreground"}`}
          >
            {index === 0 && processing ? (
              <CheckCircle2 className="h-3.5 w-3.5" />
            ) : (
              <span>{index + 1}.</span>
            )}
            {label}
          </li>
        ))}
      </ol>
      <p className="text-xs text-muted-foreground">{selection}</p>
      <div className="flex items-start justify-between gap-3">
        <p role="status" className="flex items-start gap-2 text-sm font-medium">
          <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-primary" />
          {phaseLabel}
        </p>
        {downloading && !indeterminate && (
          <span className="shrink-0 font-mono text-sm text-primary">
            {Math.round(percent)}%
          </span>
        )}
      </div>
      <Bar
        label={downloading ? "Combined download progress" : phaseLabel}
        percent={indeterminate ? null : percent}
      />
      {downloading && streams.length > 0 && (
        <div className="space-y-3">
          {streams.map((stream) => {
            const finished = stream.status === "finished"
            const Icon = stream.label === "Audio" ? Music2 : Video
            return (
              <div
                key={stream.id}
                className="space-y-2 rounded-lg bg-secondary/30 p-3"
              >
                <div className="flex items-center justify-between gap-2 text-xs">
                  <span className="flex items-center gap-2">
                    <Icon className="h-3.5 w-3.5 text-muted-foreground" />
                    {stream.label}
                  </span>
                  <span
                    className={
                      finished ? "text-primary" : "text-muted-foreground"
                    }
                  >
                    {finished
                      ? "Downloaded"
                      : stream.status === "pending"
                        ? "Connecting…"
                        : stream.percent == null
                          ? "Downloading…"
                          : `${Math.round(stream.percent)}%`}
                  </span>
                </div>
                <Bar
                  label={`${stream.label} download`}
                  percent={finished ? 100 : stream.percent}
                />
                {stream.downloaded != null && (
                  <p className="font-mono text-xs text-muted-foreground">
                    {formatBytes(stream.downloaded)}
                    {stream.total
                      ? ` / ${formatBytes(stream.total)}`
                      : " downloaded"}
                  </p>
                )}
              </div>
            )
          })}
        </div>
      )}
      {downloading ? (
        <>
          <dl className="grid grid-cols-2 gap-2 font-mono text-xs">
            <Readout label="Combined speed" value={formatSpeed(speed)} />
            <Readout label="Download ETA" value={formatEta(eta)} />
          </dl>
          <p className="text-xs text-muted-foreground">
            {total
              ? `${formatBytes(downloaded)} of approximately ${formatBytes(total)}`
              : `${formatBytes(downloaded)} downloaded`}{" "}
            ·{" "}
            {cropped
              ? "Source download; trimming follows."
              : purpose === "preview"
                ? "Playable preview follows."
                : "File preparation follows."}
          </p>
        </>
      ) : (
        <p className="text-sm text-muted-foreground">
          {stage === "retry"
            ? "The source rejected the download. Refreshing the link automatically for one more attempt."
            : processing
              ? cropped
                ? "Downloads complete. Cutting your selected interval and preparing the file. This can take a moment."
                : purpose === "preview"
                  ? "Creating a playable preview. The editor will open automatically when it’s ready."
                  : "Downloads complete. Preparing your file for the browser."
              : "Resolving media streams. Downloads will begin shortly."}
        </p>
      )}
    </section>
  )
}

function Bar({ label, percent }: { label: string; percent?: number | null }) {
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={percent == null ? undefined : Math.round(percent)}
      className="relative h-1.5 overflow-hidden rounded-full bg-secondary"
    >
      {percent == null ? (
        <div className="absolute inset-y-0 left-0 w-1/4 animate-indeterminate rounded-full bg-primary" />
      ) : (
        <div
          className="h-full rounded-full bg-primary transition-[width] duration-200"
          style={{ width: `${Math.max(0, Math.min(100, percent))}%` }}
        />
      )}
    </div>
  )
}

function Readout({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-secondary/40 px-2.5 py-2">
      <dt className="text-[10px] uppercase tracking-wider text-muted-foreground">
        {label}
      </dt>
      <dd className="mt-1 tabular-nums">{value}</dd>
    </div>
  )
}
