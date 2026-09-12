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
  status: string
  percent?: number | null
  downloaded?: number | null
  total?: number | null
}

export interface DownloadEvent {
  duration?: number | null
  streams?: StreamProgress[]
  phase: "download" | "postprocess" | "complete" | "preview"
  status?: string
  percent?: number | null
  downloaded?: number | null
  total?: number | null
  speed?: number | null
  eta?: number | null
  postprocessor?: string | null
  title?: string | null
  ext?: string | null
  filesize?: number | null
  error?: string | null
}

async function readError(res: Response, fallback: string): Promise<string> {
  const body = await res.json().catch(() => null)
  if (typeof body?.detail === "string") return body.detail
  if (Array.isArray(body?.detail))
    return body.detail.map((e: { msg: string }) => e.msg).join("; ")
  return fallback
}

export async function fetchInfo(
  url: string,
  signal?: AbortSignal,
): Promise<MediaInfo> {
  const res = await fetch("/api/info", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
    signal,
  })
  if (!res.ok)
    throw new Error(await readError(res, "Could not read that link."))
  return res.json()
}

export async function createJob(
  url: string,
  mediaType: MediaType,
  mode: Mode,
  startTime = 0,
  endTime?: number,
): Promise<string> {
  const res = await fetch("/api/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      url,
      media_type: mediaType,
      mode,
      start_time: startTime,
      end_time: endTime,
    }),
  })
  if (!res.ok)
    throw new Error(await readError(res, "Could not start the download."))
  const data = (await res.json()) as { id: string }
  return data.id
}

export function eventsUrl(jobId: string): string {
  return `/api/jobs/${jobId}/events`
}

export function fileUrl(jobId: string): string {
  return `/api/jobs/${jobId}/file`
}

export async function createPreview(url: string): Promise<string> {
  const res = await fetch("/api/previews", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  })
  if (!res.ok) throw new Error(await readError(res, "Could not load video."))
  return (await res.json()).id
}

export async function exportSelection(
  id: string,
  start: number,
  end: number,
  media_type: MediaType,
  mode: Mode,
): Promise<string> {
  const res = await fetch(`/api/previews/${id}/exports`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      start_time: start,
      end_time: end,
      media_type,
      mode,
    }),
  })
  if (!res.ok)
    throw new Error(await readError(res, "Could not export selection."))
  return (await res.json()).id
}
