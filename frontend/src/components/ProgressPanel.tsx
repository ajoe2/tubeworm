import { formatBytes, formatEta, formatSpeed } from "@/lib/format"

interface ProgressPanelProps {
  percent: number
  indeterminate: boolean
  phaseLabel: string
  speed?: number | null
  eta?: number | null
  downloaded?: number | null
  total?: number | null
}

export function ProgressPanel({
  percent,
  indeterminate,
  phaseLabel,
  speed,
  eta,
  downloaded,
  total,
}: ProgressPanelProps) {
  const sizeReadout = total
    ? `${formatBytes(downloaded)} / ${formatBytes(total)}`
    : formatBytes(downloaded)

  return (
    <div className="animate-fade-up space-y-4 rounded-xl border border-border bg-card/70 p-4">
      <div className="flex items-baseline justify-between">
        <span className="flex items-center gap-2 text-sm font-medium text-foreground">
          <span className="h-2 w-2 animate-plume rounded-full bg-primary" />
          {phaseLabel}
        </span>
        <span className="font-mono text-sm tabular-nums text-primary">
          {indeterminate ? "•••" : `${Math.round(percent)}%`}
        </span>
      </div>

      <div className="relative h-2 w-full overflow-hidden rounded-full bg-secondary">
        {indeterminate ? (
          <div className="absolute inset-y-0 left-0 w-1/4 animate-indeterminate rounded-full bg-primary" />
        ) : (
          <div
            className="h-full rounded-full bg-primary transition-[width] duration-200 ease-out"
            style={{
              width: `${percent}%`,
              boxShadow: "0 0 14px hsl(var(--primary) / 0.65)",
            }}
          />
        )}
      </div>

      <dl className="grid grid-cols-3 gap-2 font-mono text-xs">
        <Readout label="speed" value={formatSpeed(speed)} />
        <Readout label="eta" value={formatEta(eta)} />
        <Readout label="size" value={sizeReadout} />
      </dl>
    </div>
  )
}

function Readout({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-secondary/40 px-2.5 py-2">
      <dt className="text-[10px] uppercase tracking-wider text-muted-foreground/70">
        {label}
      </dt>
      <dd className="truncate tabular-nums text-foreground/90">{value}</dd>
    </div>
  )
}
