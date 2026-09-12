import { useEffect, useState } from "react"
import { Link2, Video, X } from "lucide-react"

import { ProgressPanel } from "@/components/ProgressPanel"
import { ErrorAlert } from "@/components/ErrorAlert"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { fetchInfo, type MediaInfo } from "@/lib/api"
import { formatTime } from "@/lib/format"
import type { JobProgress } from "@/lib/useJob"

const YT_PATTERN =
  /(?:youtube\.com\/(?:watch\?v=|shorts\/|live\/|embed\/)|youtu\.be\/)[\w-]{11}/

interface Props {
  onLoad: (url: string) => void
  busy: boolean
  progress: JobProgress
  error: string | null
}

export function LinkForm({ onLoad, busy, progress, error }: Props) {
  const [url, setUrl] = useState("")
  const [info, setInfo] = useState<MediaInfo | null>(null)
  const [loadingInfo, setLoadingInfo] = useState(false)
  const trimmed = url.trim()

  // Show what the link points at as soon as the user settles on it. The server
  // caches the lookup, so loading the video afterwards costs nothing extra.
  useEffect(() => {
    setInfo(null)
    if (!YT_PATTERN.test(trimmed)) {
      setLoadingInfo(false)
      return
    }
    const controller = new AbortController()
    setLoadingInfo(true)
    const timer = setTimeout(() => {
      fetchInfo(trimmed, controller.signal)
        .then(setInfo)
        .catch(() => setInfo(null))
        .finally(() => setLoadingInfo(false))
    }, 450)
    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, [trimmed])

  return (
    <div className="space-y-5">
      <label className="block space-y-2">
        <span className="text-sm font-medium">YouTube link</span>
        <div className="relative">
          <Link2 className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && trimmed && !busy) onLoad(trimmed)
            }}
            disabled={busy}
            placeholder="https://www.youtube.com/watch?v=…"
            spellCheck={false}
            autoComplete="off"
            autoFocus
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
      </label>

      {(info || loadingInfo) && <LinkPreview info={info} />}

      {busy ? (
        <ProgressPanel progress={progress} />
      ) : (
        <div className="space-y-3">
          {error && <ErrorAlert message={error} />}
          <Button size="lg" className="w-full" disabled={!trimmed} onClick={() => onLoad(trimmed)}>
            <Video className="h-5 w-5" />
            Load video
          </Button>
          <p className="text-center text-xs text-muted-foreground">
            Fetches the video at full quality and opens the editor. Nothing is saved to your
            Downloads folder until you export.
          </p>
        </div>
      )}
    </div>
  )
}

function LinkPreview({ info }: { info: MediaInfo | null }) {
  if (!info) {
    return (
      <div className="flex animate-pulse gap-3 rounded-xl border border-border bg-card/50 p-3" aria-hidden="true">
        <div className="h-[3.75rem] w-28 shrink-0 rounded-md bg-secondary" />
        <div className="flex-1 space-y-2 py-1">
          <div className="h-3.5 w-3/4 rounded bg-secondary" />
          <div className="h-3 w-1/2 rounded bg-secondary" />
        </div>
      </div>
    )
  }
  return (
    <div className="flex animate-fade-up gap-3 rounded-xl border border-border bg-card/60 p-3">
      {info.thumbnail ? (
        <img src={info.thumbnail} alt="" className="h-[3.75rem] w-28 shrink-0 rounded-md object-cover" />
      ) : (
        <div className="flex h-[3.75rem] w-28 shrink-0 items-center justify-center rounded-md bg-secondary">
          <Video className="h-5 w-5 text-muted-foreground" />
        </div>
      )}
      <div className="min-w-0 flex-1 self-center">
        <p className="truncate font-medium">{info.title ?? "Untitled"}</p>
        <p className="truncate text-sm text-muted-foreground">
          {info.uploader ?? ""}
          {info.duration != null && (
            <span className="ml-2 font-mono text-xs">{formatTime(info.duration)}</span>
          )}
          {info.duration == null && (
            <span className="ml-2 text-xs text-destructive">Live streams can’t be edited</span>
          )}
        </p>
      </div>
    </div>
  )
}
