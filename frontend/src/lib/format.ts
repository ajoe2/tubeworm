export function formatBytes(n?: number | null): string {
  if (n == null) return "—"
  if (n < 1024) return `${n} B`
  const units = ["KiB", "MiB", "GiB", "TiB"]
  let value = n / 1024
  let i = 0
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024
    i += 1
  }
  return `${value.toFixed(value >= 100 ? 0 : 1)} ${units[i]}`
}

export function formatSpeed(bytesPerSec?: number | null): string {
  if (!bytesPerSec || bytesPerSec <= 0) return "—"
  return `${formatBytes(bytesPerSec)}/s`
}

/** `m:ss`, or `h:mm:ss` past an hour; `decimals` adds fixed fractional seconds. */
export function formatTime(seconds?: number | null, decimals = 0): string {
  if (seconds == null || !Number.isFinite(seconds)) return "—"
  const scale = 10 ** decimals
  const total = Math.max(0, Math.round(seconds * scale) / scale)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = (total % 60).toFixed(decimals).padStart(decimals ? 3 + decimals : 2, "0")
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`
}
