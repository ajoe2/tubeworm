import { useRef, type KeyboardEvent, type PointerEvent } from "react"
import { GripVertical } from "lucide-react"
import { formatDuration } from "@/lib/format"

export function TrimTimeline({
  duration,
  start,
  end,
  disabled,
  position,
  onSeek,
  onChange,
  onInteractionStart,
  onInteractionEnd,
}: {
  duration: number
  start: number
  end: number
  disabled: boolean
  position: number
  onSeek: (time: number) => void
  onChange: (start: number, end: number, seekTo: number) => void
  onInteractionStart: () => void
  onInteractionEnd: () => void
}) {
  const track = useRef<HTMLDivElement>(null)
  const drag = useRef<{
    edge: "start" | "end" | "playhead"
    x: number
    start: number
    end: number
    position: number
    width: number
  } | null>(null)
  const gap = Math.min(0.01, duration)
  const update = (
    edge: "start" | "end" | "playhead",
    value: number,
    a = start,
    b = end,
  ) => {
    if (edge === "playhead") {
      onSeek(Math.max(0, Math.min(duration, value)))
      return
    }
    const next =
      edge === "start"
        ? Math.max(0, Math.min(b - gap, value))
        : Math.min(duration, Math.max(a + gap, value))
    onChange(edge === "start" ? next : a, edge === "end" ? next : b, next)
  }
  const begin = (
    edge: "start" | "end" | "playhead",
    e: PointerEvent<HTMLButtonElement>,
  ) => {
    if (disabled || e.button !== 0 || !track.current) return
    e.preventDefault()
    onInteractionStart()
    e.currentTarget.focus()
    e.currentTarget.setPointerCapture(e.pointerId)
    drag.current = {
      edge,
      x: e.clientX,
      start,
      end,
      position,
      width: track.current.getBoundingClientRect().width,
    }
  }
  const move = (e: PointerEvent<HTMLButtonElement>) => {
    if (
      disabled ||
      !drag.current ||
      !e.currentTarget.hasPointerCapture(e.pointerId)
    )
      return
    const d = drag.current
    update(
      d.edge,
      (d.edge === "playhead"
        ? d.position
        : d.edge === "start"
          ? d.start
          : d.end) +
        ((e.clientX - d.x) / d.width) * duration,
      d.start,
      d.end,
    )
  }
  const keyboard = (
    edge: "start" | "end" | "playhead",
    e: KeyboardEvent<HTMLButtonElement>,
  ) => {
    const value =
      edge === "playhead" ? position : edge === "start" ? start : end
    const step = e.shiftKey ? 1 : 0.1
    let next: number
    switch (e.key) {
      case "ArrowLeft":
      case "ArrowDown":
        next = value - step
        break
      case "ArrowRight":
      case "ArrowUp":
        next = value + step
        break
      case "Home":
        next = 0
        break
      case "End":
        next = duration
        break
      default:
        return
    }
    e.preventDefault()
    update(edge, next)
  }
  return (
    <div className="space-y-3">
      <div className="flex justify-between gap-2 text-xs">
        <span>
          Start{" "}
          <span className="font-mono text-primary">
            {formatDuration(start)}
          </span>
        </span>
        <span className="text-muted-foreground">
          {formatDuration(end - start)} selected
        </span>
        <span>
          End{" "}
          <span className="font-mono text-primary">{formatDuration(end)}</span>
        </span>
      </div>
      <div className="px-3 pt-5">
        <div
          ref={track}
          className="relative h-14 rounded-lg bg-secondary"
          aria-label="Trim timeline"
          onPointerDown={(e) => {
            if (
              disabled ||
              e.button !== 0 ||
              (e.target as HTMLElement).closest("button")
            )
              return
            const bounds = e.currentTarget.getBoundingClientRect()
            onSeek(
              Math.max(
                0,
                Math.min(
                  duration,
                  ((e.clientX - bounds.left) / bounds.width) * duration,
                ),
              ),
            )
          }}
        >
          <div
            aria-hidden="true"
            className="absolute inset-0 overflow-hidden rounded-lg opacity-30"
            style={{
              backgroundImage:
                "repeating-linear-gradient(90deg, transparent, transparent calc(10% - 1px), hsl(var(--muted-foreground)) calc(10% - 1px), hsl(var(--muted-foreground)) 10%)",
            }}
          />
          <div
            aria-hidden="true"
            className="absolute inset-y-0 border-y-2 border-primary bg-primary/20"
            style={{
              left: `${(start / duration) * 100}%`,
              width: `${((end - start) / duration) * 100}%`,
            }}
          />
          <button
            type="button"
            role="slider"
            aria-label="Playhead"
            aria-orientation="horizontal"
            aria-valuemin={0}
            aria-valuemax={duration}
            aria-valuenow={position}
            aria-valuetext={formatDuration(position)}
            disabled={disabled}
            className="absolute -top-5 z-20 flex h-5 w-7 -translate-x-1/2 touch-none cursor-ew-resize items-end justify-center rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-foreground disabled:opacity-50"
            style={{ left: `${(position / duration) * 100}%` }}
            onPointerDown={(e) => begin("playhead", e)}
            onPointerMove={move}
            onPointerUp={() => {
              if (drag.current) onInteractionEnd()
              drag.current = null
            }}
            onPointerCancel={() => {
              if (drag.current) onInteractionEnd()
              drag.current = null
            }}
            onLostPointerCapture={() => {
              if (drag.current) onInteractionEnd()
              drag.current = null
            }}
            onKeyDown={(e) => keyboard("playhead", e)}
          >
            <span
              aria-hidden="true"
              className="h-4 w-3 rounded-t-sm bg-foreground"
            />
            <span
              aria-hidden="true"
              className="pointer-events-none absolute left-1/2 top-5 h-14 w-0.5 -translate-x-1/2 bg-foreground shadow"
            />
          </button>
          {(["start", "end"] as const).map((edge) => (
            <button
              key={edge}
              type="button"
              role="slider"
              aria-label={
                edge === "start" ? "Selection start" : "Selection end"
              }
              aria-orientation="horizontal"
              aria-valuemin={edge === "start" ? 0 : start + gap}
              aria-valuemax={edge === "start" ? end - gap : duration}
              aria-valuenow={edge === "start" ? start : end}
              aria-valuetext={formatDuration(edge === "start" ? start : end)}
              aria-describedby="trim-help"
              disabled={disabled}
              className="absolute inset-y-0 z-10 flex w-6 -translate-x-1/2 touch-none cursor-ew-resize items-center justify-center rounded-md bg-primary text-primary-foreground shadow-md outline-none focus-visible:ring-2 focus-visible:ring-foreground focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-50"
              style={{
                left: `${((edge === "start" ? start : end) / duration) * 100}%`,
              }}
              onPointerDown={(e) => begin(edge, e)}
              onPointerMove={move}
              onPointerUp={() => {
                if (drag.current) onInteractionEnd()
                drag.current = null
              }}
              onPointerCancel={() => {
                if (drag.current) onInteractionEnd()
                drag.current = null
              }}
              onLostPointerCapture={() => {
                if (drag.current) onInteractionEnd()
                drag.current = null
              }}
              onKeyDown={(e) => keyboard(edge, e)}
            >
              <GripVertical className="h-6 w-4" />
            </button>
          ))}
        </div>
        <div
          aria-hidden="true"
          className="mt-1 flex justify-between font-mono text-[10px] text-muted-foreground"
        >
          <span>0:00</span>
          <span>{formatDuration(duration / 2)}</span>
          <span>{formatDuration(duration)}</span>
        </div>
      </div>
      <p className="text-center font-mono text-xs text-muted-foreground">
        Playhead {formatDuration(position)} / {formatDuration(duration)}
      </p>
      <p id="trim-help" className="text-xs text-muted-foreground">
        Drag the coral edges to trim. Drag the white playhead or click the bar
        to scrub. Arrow keys fine-tune the focused handle; Shift moves by one
        second.
      </p>
    </div>
  )
}
