import { Music2, ShieldCheck, Sparkles, Video } from "lucide-react"

import { Segmented } from "@/components/Segmented"
import type { MediaType, Mode } from "@/lib/api"

export interface ExportFormat {
  mediaType: MediaType
  mode: Mode
}

/** Mirrors OUTPUT_CONTAINER on the server. */
export const CONTAINER: Record<MediaType, Record<Mode, string>> = {
  video: { quality: "mkv", compatibility: "mp4" },
  audio: { quality: "opus", compatibility: "m4a" },
}

interface Props {
  value: ExportFormat
  onChange: (value: ExportFormat) => void
  /** The selection covers the whole video. */
  whole: boolean
  /** Containers the server can produce for the whole video by stream copy. */
  lossless: string[]
  disabled: boolean
}

export function ExportOptions({ value, onChange, whole, lossless, disabled }: Props) {
  const ext = CONTAINER[value.mediaType][value.mode]
  return (
    <div className="space-y-3">
      <div className="grid gap-4 sm:grid-cols-2">
        <Segmented<MediaType>
          label="Format"
          value={value.mediaType}
          onChange={(mediaType) => onChange({ ...value, mediaType })}
          disabled={disabled}
          options={[
            { value: "video", label: "Video", icon: <Video className="h-4 w-4" /> },
            { value: "audio", label: "Audio", icon: <Music2 className="h-4 w-4" /> },
          ]}
        />
        <Segmented<Mode>
          label="Priority"
          value={value.mode}
          onChange={(mode) => onChange({ ...value, mode })}
          disabled={disabled}
          options={[
            { value: "compatibility", label: "Compatible", icon: <ShieldCheck className="h-4 w-4" /> },
            { value: "quality", label: "Quality", icon: <Sparkles className="h-4 w-4" /> },
          ]}
        />
      </div>
      <div className="flex items-center justify-between gap-3 rounded-lg border border-border bg-secondary/25 px-3.5 py-2.5">
        <span className="text-sm text-muted-foreground">
          {describe(value, whole, lossless.includes(ext))}
        </span>
        <span className="shrink-0 rounded-md bg-background/60 px-2 py-1 font-mono text-xs font-medium text-primary">
          .{ext}
        </span>
      </div>
    </div>
  )
}

function describe({ mediaType, mode }: ExportFormat, whole: boolean, lossless: boolean): string {
  const audio = mode === "quality" ? "Opus" : "AAC"
  if (!whole) {
    return mediaType === "video"
      ? `Cut exactly at your times and re-encoded as H.264 + ${audio}.`
      : `Cut exactly at your times and re-encoded as ${audio}.`
  }
  if (lossless) return "Copied straight from the original. No re-encoding, no quality loss."
  return mediaType === "video"
    ? `Whole video, converted to H.264 + ${audio} so it plays anywhere.`
    : `Whole audio track, converted to ${audio}.`
}
