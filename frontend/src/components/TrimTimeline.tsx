import { useRef, type KeyboardEvent, type PointerEvent } from "react"
import { GripVertical } from "lucide-react"

import { formatTime } from "@/lib/format"

type Edge = "start" | "end" | "playhead"

interface Props {
  duration: number
  start: number
  end: number
  position: number
  disabled: boolean
  onSeek: (time: number) => void
  /** New in/out points plus the time to show the user (the moved edge). */
  onChange: (start: number, end: number, seekTo: number) => void
  onInteractionStart: () => void
  onInteractionEnd: () => void
}

/** The trim bar: a draggable selection with a separate playhead for scrubbing. */
export function TrimTimeline({
  duration,
  start,
  end,
  position,
  disabled,
  onSeek,
  onChange,
  onInteractionStart,
  onInteractionEnd,
}: Props) {
  const track = useRef<HTMLDivElement>(null)
  const drag = useRef<{ edge: Edge; x: number; origin: number; width: number } | null>(null)
  const gap = Math.min(0.01, duration)
  const clamp = (t: number) => Math.max(0, Math.min(duration, t))
  const pct = (t: number) => `${(t / duration) * 100}%`

  const apply = (edge: Edge, value: number) => {
    if (edge === "playhead") onSeek(clamp(value))
    else if (edge === "start") {
      const next = Math.max(0, Math.min(end - gap, value))
      onChange(next, end, next)
    } else {
      const next = Math.min(duration, Math.max(start + gap, value))
      onChange(start, next, next)
    }
  }

  const begin = (edge: Edge, origin: number, e: PointerEvent<HTMLElement>) => {
    if (!track.current) return
    e.preventDefault()
    onInteractionStart()
    e.currentTarget.setPointerCapture(e.pointerId)
    drag.current = { edge, x: e.clientX, origin, width: track.current.getBoundingClientRect().width }
  }
  const move = (e: PointerEvent<HTMLElement>) => {
    const d = drag.current
    if (!d || disabled || !e.currentTarget.hasPointerCapture(e.pointerId)) return
    apply(d.edge, d.origin + ((e.clientX - d.x) / d.width) * duration)
  }
  const finish = () => {
    if (drag.current) onInteractionEnd()
    drag.current = null
  }
  const keyboard = (edge: Edge, e: KeyboardEvent<HTMLElement>) => {
    const value = edge === "playhead" ? position : edge === "start" ? start : end
    const step = e.shiftKey ? 1 : 0.1
    const next = { ArrowLeft: value - step, ArrowDown: value - step, ArrowRight: value + step,
      ArrowUp: value + step, Home: 0, End: duration }[e.key]
    if (next === undefined) return
    e.preventDefault()
    apply(edge, next)
  }
  const handleProps = (edge: Edge, value: number) => ({
    disabled,
    onPointerDown: (e: PointerEvent<HTMLButtonElement>) => {
      if (disabled || e.button !== 0) return
      e.currentTarget.focus()
      begin(edge, value, e)
    },
    onPointerMove: move,
    onPointerUp: finish,
    onPointerCancel: finish,
    onLostPointerCapture: finish,
    onKeyDown: (e: KeyboardEvent<HTMLButtonElement>) => keyboard(edge, e),
  })
  // Pressing anywhere on the bar jumps the playhead there and keeps scrubbing while held.
  const scrub = (e: PointerEvent<HTMLDivElement>) => {
    if (disabled || e.button !== 0 || (e.target as HTMLElement).closest("button")) return
    const bounds = e.currentTarget.getBoundingClientRect()
    const time = clamp(((e.clientX - bounds.left) / bounds.width) * duration)
    begin("playhead", time, e)
    onSeek(time)
  }

  return (
    <div className="px-3 pb-1 pt-7">
      <div
        ref={track}
        className="relative h-12 touch-none rounded-lg bg-secondary"
        onPointerDown={scrub}
        onPointerMove={move}
        onPointerUp={finish}
        onPointerCancel={finish}
        onLostPointerCapture={finish}
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
          style={{ left: pct(start), width: pct(end - start) }}
        />

        <button
          type="button"
          role="slider"
          aria-label="Playhead"
          aria-orientation="horizontal"
          aria-valuemin={0}
          aria-valuemax={duration}
          aria-valuenow={position}
          aria-valuetext={formatTime(position, 1)}
          className="absolute -top-6 z-20 flex h-6 w-7 -translate-x-1/2 touch-none cursor-ew-resize flex-col items-center justify-end rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-foreground disabled:opacity-50"
          style={{ left: pct(position) }}
          {...handleProps("playhead", position)}
        >
          <span
            aria-hidden="true"
            className={`pointer-events-none absolute top-0 whitespace-nowrap font-mono text-[10px] leading-none text-foreground ${
              position / duration > 0.85 ? "right-full mr-1" : "left-full ml-1"
            }`}
          >
            {formatTime(position, 1)}
          </span>
          <span aria-hidden="true" className="h-4 w-3 rounded-t-sm bg-foreground" />
          <span
            aria-hidden="true"
            className="pointer-events-none absolute left-1/2 top-full h-12 w-0.5 -translate-x-1/2 bg-foreground shadow"
          />
        </button>

        {(["start", "end"] as const).map((edge) => {
          const value = edge === "start" ? start : end
          return (
            <button
              key={edge}
              type="button"
              role="slider"
              aria-label={edge === "start" ? "Selection start" : "Selection end"}
              aria-orientation="horizontal"
              aria-valuemin={edge === "start" ? 0 : start + gap}
              aria-valuemax={edge === "start" ? end - gap : duration}
              aria-valuenow={value}
              aria-valuetext={formatTime(value, 1)}
              className="absolute inset-y-0 z-10 flex w-6 -translate-x-1/2 touch-none cursor-ew-resize items-center justify-center rounded-md bg-primary text-primary-foreground shadow-md outline-none focus-visible:ring-2 focus-visible:ring-foreground focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-50"
              style={{ left: pct(value) }}
              {...handleProps(edge, value)}
            >
              <GripVertical className="h-6 w-4" />
            </button>
          )
        })}
      </div>
      <div aria-hidden="true" className="mt-1 flex justify-between font-mono text-[10px] text-muted-foreground">
        <span>0:00</span>
        <span>{formatTime(duration / 2)}</span>
        <span>{formatTime(duration)}</span>
      </div>
    </div>
  )
}
