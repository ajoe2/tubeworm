import { useEffect, useRef, useState } from "react"
import { Play, Pause, Scissors } from "lucide-react"
import { SeekQueue } from "@/lib/seekQueue"
import { formatDuration } from "@/lib/format"
import { TrimTimeline } from "@/components/TrimTimeline"
import { Button } from "@/components/ui/button"

export function ClipEditor({
  src,
  duration,
  start,
  end,
  onChange,
  disabled,
}: {
  src: string
  duration: number
  start: number
  end: number
  onChange: (start: number, end: number) => void
  disabled: boolean
}) {
  const video = useRef<HTMLVideoElement>(null)
  const selectionPlayback = useRef(false)
  const dragging = useRef(false)
  const playAfterSeek = useRef(false)
  const stopAt = useRef(end)
  const loopStart = useRef(start)
  const transport = useRef<SeekQueue | null>(null)
  const [position, setPosition] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [loop, setLoop] = useState(false)
  const [buffering, setBuffering] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const latest = useRef({ start, end, loop })
  latest.current = { start, end, loop }

  useEffect(() => {
    const player = video.current!
    const play = () => {
      void player.play().catch((e) => {
        if (e.name !== "AbortError")
          setError("Could not play the preview. Please try again.")
      })
    }
    const queue = new SeekQueue(player, () => {
      if (!dragging.current) setPosition(player.currentTime)
      if (playAfterSeek.current) {
        playAfterSeek.current = false
        play()
      }
    })
    transport.current = queue
    const seeked = () => queue.onSeeked()
    const loaded = () => queue.flush(true)
    player.addEventListener("seeked", seeked)
    player.addEventListener("loadedmetadata", loaded)
    let frame = 0
    let lastUpdate = 0
    const tick = (now: number) => {
      if (!player.paused && !queue.busy && !dragging.current) {
        if (selectionPlayback.current && player.currentTime >= stopAt.current) {
          player.pause()
          if (latest.current.loop) {
            playAfterSeek.current = true
            queue.request(loopStart.current, true)
          } else {
            selectionPlayback.current = false
            queue.request(stopAt.current, true)
          }
        } else if (now - lastUpdate > 50) {
          setPosition(player.currentTime)
          lastUpdate = now
        }
      }
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => {
      queue.dispose()
      transport.current = null
      cancelAnimationFrame(frame)
      player.removeEventListener("seeked", seeked)
      player.removeEventListener("loadedmetadata", loaded)
    }
  }, [src])

  const seek = (time: number) => {
    selectionPlayback.current = false
    playAfterSeek.current = false
    video.current?.pause()
    setPosition(time)
    transport.current?.request(time, !dragging.current)
  }
  const playRange = (a: number, b: number) => {
    setError(null)
    video.current?.pause()
    selectionPlayback.current = true
    loopStart.current = a
    stopAt.current = b
    playAfterSeek.current = true
    setPosition(a)
    transport.current?.request(a, true)
  }
  const playSelection = () => playRange(start, end)
  const change = (a: number, b: number, seekTo: number) => {
    onChange(a, b)
    // An end point is exclusive: inspect the last included frame, not the next clip.
    seek(seekTo === b ? Math.max(a, b - 1 / 30) : seekTo)
  }
  return (
    <section aria-label="Clip editor" className="space-y-4">
      <div className="flex items-center gap-2 font-medium">
        <Scissors className="h-4 w-4 text-primary" />
        Preview &amp; trim
      </div>
      <video
        ref={video}
        src={src}
        playsInline
        preload="auto"
        className="aspect-video w-full rounded-xl bg-black"
        aria-label="Video preview"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onWaiting={() => setBuffering(true)}
        onPlaying={() => setBuffering(false)}
        onCanPlay={() => setBuffering(false)}
        onEnded={() => {
          setBuffering(false)
          if (selectionPlayback.current && loop)
            playRange(loopStart.current, stopAt.current)
          else {
            selectionPlayback.current = false
            setPlaying(false)
            setPosition(video.current?.currentTime ?? duration)
          }
        }}
        onError={() =>
          setError(
            "The preview could not load. If it expired, load the video again.",
          )
        }
      />
      {buffering && playing && (
        <p role="status" className="text-xs text-muted-foreground">
          Buffering preview…
        </p>
      )}
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <fieldset
        disabled={disabled}
        className="space-y-3 rounded-xl border border-border p-4"
      >
        <legend className="px-1 text-sm font-medium">
          Trim &amp; playhead
        </legend>
        <TrimTimeline
          duration={duration}
          start={start}
          end={end}
          disabled={disabled}
          onChange={change}
          position={position}
          onSeek={seek}
          onInteractionStart={() => {
            dragging.current = true
            playAfterSeek.current = false
            video.current?.pause()
          }}
          onInteractionEnd={() => {
            dragging.current = false
            transport.current?.flush(true)
          }}
        />
        <div className="flex flex-wrap gap-2">
          <Button
            variant="outline"
            size="default"
            onClick={() =>
              change(
                Math.min(position, end - 0.01),
                end,
                Math.min(position, end - 0.01),
              )
            }
          >
            Set start here
          </Button>
          <Button
            variant="outline"
            size="default"
            onClick={() =>
              change(
                start,
                Math.max(position, start + 0.01),
                Math.max(position, start + 0.01),
              )
            }
          >
            Set end here
          </Button>
          <Button
            variant="outline"
            size="default"
            onClick={() => change(0, duration, 0)}
          >
            Use full video
          </Button>
        </div>
      </fieldset>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button
          variant="secondary"
          onClick={playing ? () => video.current?.pause() : playSelection}
        >
          {playing ? (
            <Pause className="h-4 w-4" />
          ) : (
            <Play className="h-4 w-4" />
          )}
          {playing ? "Pause" : "Play selection"}
        </Button>
        <Button
          variant="outline"
          onClick={() => {
            if (playing) {
              video.current?.pause()
              return
            }
            selectionPlayback.current = false
            playAfterSeek.current = true
            transport.current?.request(position, true)
          }}
        >
          {playing ? "Pause" : "Play from playhead"}
        </Button>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="outline"
          onClick={() => playRange(start, Math.min(end, start + 3))}
        >
          Check start
        </Button>
        <Button
          variant="outline"
          onClick={() => playRange(Math.max(start, end - 3), end)}
        >
          Check end
        </Button>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={loop}
            onChange={(e) => setLoop(e.target.checked)}
            className="h-4 w-4 accent-primary"
          />
          Loop selection
        </label>
      </div>
      <p className="font-mono text-sm text-primary">
        {formatDuration(start)} – {formatDuration(end)} ·{" "}
        {formatDuration(end - start)} selected
      </p>
      <p className="text-xs text-muted-foreground">
        Check start/end plays the first/last three seconds of your clip. Play
        selection starts at your in-point and stops at your out-point.
        Previewing does not save a file to your downloads.
      </p>
    </section>
  )
}
