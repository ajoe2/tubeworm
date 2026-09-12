export type MediaType = "audio" | "video"
export type Mode = "quality" | "compatibility"

export interface MediaInfo {
  title: string | null
  uploader: string | null
  duration: number | null
  thumbnail: string | null
}

export interface StreamProgress {
  id: string
  label: string
  status: "pending" | "downloading" | "finished" | "error"
  percent: number | null
  downloaded: number | null
  total: number | null
}

export interface DownloadEvent {
  phase: "download"
  streams: StreamProgress[]
  downloaded: number
  total: number | null
  speed: number | null
  eta: number | null
  percent: number | null
}

export type ProcessStep =
  | "merge"
  | "retry"
  | "preview-wait"
  | "preview"
  | "trim"
  | "remux"
  | "convert"

export type ProxyStatus = "downloading" | "converting" | "ready"

export interface CompletedEvent {
  phase: "complete"
  status: "completed"
  title: string
  ext: string
  filesize: number
  duration: number | null
  /** Containers a whole-video export reaches by pure stream copy. */
  lossless: string[]
}

export type JobEvent =
  | DownloadEvent
  | { phase: "process"; step: ProcessStep }
  | { phase: "proxy"; status: ProxyStatus }
  | CompletedEvent
  | { phase: "complete"; status: "error"; error: string }

async function post<T>(path: string, body: unknown, fallback: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok) throw new Error(await readError(res, fallback))
  return res.json()
}

async function readError(res: Response, fallback: string): Promise<string> {
  const body = await res.json().catch(() => null)
  if (typeof body?.detail === "string") return body.detail
  if (Array.isArray(body?.detail))
    return body.detail.map((e: { msg: string }) => e.msg).join("; ")
  return fallback
}

export function fetchInfo(url: string, signal?: AbortSignal): Promise<MediaInfo> {
  return post("/api/info", { url }, "Could not read that link.", signal)
}

export async function createPreview(url: string): Promise<string> {
  const { id } = await post<{ id: string }>("/api/previews", { url }, "Could not load the video.")
  return id
}

export interface ExportParams {
  start: number
  end: number
  mediaType: MediaType
  mode: Mode
}

export async function createExport(previewId: string, opts: ExportParams): Promise<string> {
  const { id } = await post<{ id: string }>(
    `/api/previews/${previewId}/exports`,
    { start_time: opts.start, end_time: opts.end, media_type: opts.mediaType, mode: opts.mode },
    "Could not export the selection.",
  )
  return id
}

export const eventsUrl = (jobId: string) => `/api/jobs/${jobId}/events`
export const fileUrl = (jobId: string) => `/api/jobs/${jobId}/file`
export const previewMediaUrl = (jobId: string) => `/api/previews/${jobId}/media`
