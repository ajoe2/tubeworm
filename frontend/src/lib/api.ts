export type MediaType = "audio" | "video"
export type Mode = "quality" | "compatibility"

export interface MediaInfo {
  title: string | null
  uploader: string | null
  duration: number | null
  thumbnail: string | null
}

export interface DownloadEvent {
  phase: "download" | "postprocess" | "complete"
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
  const body = (await res.json().catch(() => null)) as { detail?: string } | null
  return body?.detail ?? fallback
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
  if (!res.ok) throw new Error(await readError(res, "Could not read that link."))
  return res.json()
}

export async function createJob(
  url: string,
  mediaType: MediaType,
  mode: Mode,
): Promise<string> {
  const res = await fetch("/api/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, media_type: mediaType, mode }),
  })
  if (!res.ok) throw new Error(await readError(res, "Could not start the download."))
  const data = (await res.json()) as { id: string }
  return data.id
}

export function eventsUrl(jobId: string): string {
  return `/api/jobs/${jobId}/events`
}

export function fileUrl(jobId: string): string {
  return `/api/jobs/${jobId}/file`
}
