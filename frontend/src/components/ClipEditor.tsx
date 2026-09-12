import { useEffect, useRef, useState } from "react"
import { ArrowLeftToLine, ArrowRightToLine, Pause, Play, Repeat, RotateCcw } from "lucide-react"

import { TrimTimeline } from "@/components/TrimTimeline"
import { Button } from "@/components/ui/button"
import { formatTime } from "@/lib/format"
import { SeekQueue } from "@/lib/seekQueue"

const FRAME = 1 / 30
const CHECK_SECONDS = 3

interface Props {
  src: string
  duration: number
  start: number
  end: number
  onChange: (start: number, end: number) => void
  disabled: boolean
}

/** Video preview plus the trim bar and the few controls needed to set a clip. */
export function ClipEditor({ src, duration, start, end, onChange, disabled }: Props) {
  const video = useRef<HTMLVideoElement>(null)
  const queue = useRef<SeekQueue | null>(null)
  /** The interval "Play selection" is bounded to; null during free playback. */
  const range = useRef<{ start: number; end: number } | null>(null)
  const playAfterSeek = useRef(false)
  const ownPlay = useRef(false)
  const dragging = useRef(false)
  const loopRef = useRef(false)
  const [position, setPosition] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [loop, setLoop] = useState(false)
  const [error, setError] = useState<string | null>(null)
  loopRef.current = loop

  useEffect(() => {
    const player = video.current!
    const play = () => {
      ownPlay.current = true
      player.play().catch((e: DOMException) => {
        ownPlay.current = false
        if (e.name !== "AbortError") setError("Could not play the preview. Please try again.")
      })
    }
    const q = new SeekQueue(player, () => {
      if (!dragging.current) setPosition(player.currentTime)
      if (playAfterSeek.current) {
        playAfterSeek.current = false
        play()
      }
    })
    queue.current = q

    // Poll only while playing: stop at the selection end and move the playhead.
    let frame = 0
    const tick = () => {
      frame = requestAnimationFrame(tick)
      if (player.paused || q.busy || dragging.current) return
      const r = range.current
      if (r && player.currentTime >= r.end) {
        player.pause()
        if (loopRef.current) {
          playAfterSeek.current = true
          q.request(r.start, true)
        } else {
          range.current = null
          q.request(Math.max(r.start, r.end - FRAME), true) // rest on the last included frame
        }
      } else {
        setPosition(player.currentTime)
      }
    }
    const listeners: Record<string, () => void> = {
      play: () => {
        setPlaying(true)
        if (!ownPlay.current) range.current = null // the native play button: free playback
        ownPlay.current = false
        cancelAnimationFrame(frame)
        frame = requestAnimationFrame(tick)
      },
      pause: () => {
        setPlaying(false)
        cancelAnimationFrame(frame)
      },
      seeking: () => {
        if (!q.seeking) range.current = null // scrubbed with the native controls
      },
      seeked: () => q.onSeeked(),
      loadedmetadata: () => q.flush(true),
      ended: () => {
        if (range.current && loopRef.current) {
          playAfterSeek.current = true
          q.request(range.current.start, true)
        } else {
          range.current = null
        }
      },
    }
    for (const [name, fn] of Object.entries(listeners)) player.addEventListener(name, fn)
    return () => {
      q.dispose()
      queue.current = null
      cancelAnimationFrame(frame)
      for (const [name, fn] of Object.entries(listeners)) player.removeEventListener(name, fn)
    }
  }, [src])

  const seek = (time: number) => {
    range.current = null
    playAfterSeek.current = false
    video.current?.pause()
    setPosition(time)
    queue.current?.request(time, !dragging.current)
  }
  const playRange = (a: number, b: number) => {
    setError(null)
    video.current?.pause()
    range.current = { start: a, end: b }
    playAfterSeek.current = true
    setPosition(a)
    queue.current?.request(a, true)
  }
  const change = (a: number, b: number, seekTo: number) => {
    onChange(a, b)
    // The end point is exclusive: show the last included frame, not the next one.
    seek(seekTo === b ? Math.max(a, b - FRAME) : seekTo)
  }
  const trimmed = start > 0 || end < duration

  return (
    <section aria-label="Clip editor" className="space-y-3">
      <video
        ref={video}
        src={src}
        controls
        playsInline
        preload="auto"
        className="aspect-video w-full rounded-xl bg-black"
        aria-label="Video preview"
        onError={() => setError("The preview could not load. If it expired, load the video again.")}
      />
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}

      <fieldset disabled={disabled} className="space-y-2 disabled:opacity-60">
        <div className="flex items-center justify-between gap-2 text-xs">
          <TimeButton
            label="Start"
            time={start}
            title={`Play the first ${CHECK_SECONDS} seconds of the clip`}
            onClick={() => playRange(start, Math.min(end, start + CHECK_SECONDS))}
          />
          <span className="text-muted-foreground">{formatTime(end - start, 1)} selected</span>
          <TimeButton
            label="End"
            time={end}
            title={`Play the last ${CHECK_SECONDS} seconds of the clip`}
            onClick={() => playRange(Math.max(start, end - CHECK_SECONDS), end)}
          />
        </div>

        <TrimTimeline
          duration={duration}
          start={start}
          end={end}
          position={position}
          disabled={disabled}
          onSeek={seek}
          onChange={change}
          onInteractionStart={() => {
            dragging.current = true
            playAfterSeek.current = false
            video.current?.pause()
          }}
          onInteractionEnd={() => {
            dragging.current = false
            queue.current?.flush(true)
          }}
        />

        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                const s = Math.min(position, end - 0.01)
                change(s, end, s)
              }}
            >
              <ArrowLeftToLine className="h-3.5 w-3.5" />
              Set start here
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                const e = Math.max(position, start + 0.01)
                change(start, e, e)
              }}
            >
              Set end here
              <ArrowRightToLine className="h-3.5 w-3.5" />
            </Button>
            {trimmed && (
              <Button variant="ghost" size="sm" onClick={() => change(0, duration, 0)}>
                <RotateCcw className="h-3.5 w-3.5" />
                Reset
              </Button>
            )}
          </div>
          <div className="flex gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => (playing ? video.current?.pause() : playRange(start, end))}
            >
              {playing ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
              {playing ? "Pause" : "Play selection"}
            </Button>
            <Button
              variant={loop ? "default" : "outline"}
              size="sm"
              aria-pressed={loop}
              onClick={() => setLoop(!loop)}
            >
              <Repeat className="h-3.5 w-3.5" />
              Loop
            </Button>
          </div>
        </div>
      </fieldset>

      <p className="text-xs text-muted-foreground">
        Drag the coral handles to trim, or scrub and use “Set start / end here”. Click a time to
        hear that edge. Arrow keys nudge a focused handle by 0.1 s (Shift: 1 s).
      </p>
    </section>
  )
}

function TimeButton({
  label,
  time,
  title,
  onClick,
}: {
  label: string
  time: number
  title: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      title={title}
      aria-label={`${label} ${formatTime(time, 1)}. ${title}`}
      onClick={onClick}
      className="inline-flex items-center gap-1.5 rounded-md px-1.5 py-1 transition-colors hover:bg-secondary/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <span className="text-muted-foreground">{label}</span>
      <span className="font-mono text-primary">{formatTime(time, 1)}</span>
      <Play className="h-3 w-3 text-muted-foreground" />
    </button>
  )
}
