import { useCallback, useEffect, useRef, useState } from "react"

import {
  eventsUrl,
  type CompletedEvent,
  type DownloadEvent,
  type JobEvent,
  type ProcessStep,
  type ProxyStatus,
} from "@/lib/api"

export interface JobProgress {
  download: DownloadEvent | null
  /** The processing step in flight, or null while downloading. */
  step: ProcessStep | null
  /** Editing-proxy status, reported by preview jobs only. */
  proxy: ProxyStatus | null
}

export type JobResult = CompletedEvent & { id: string }

const IDLE: JobProgress = { download: null, step: null, proxy: null }

/**
 * Runs one server job at a time: creates it, follows its event stream, and
 * resolves with the completion event (or null after storing the error).
 */
export function useJob() {
  const [running, setRunning] = useState(false)
  const [progress, setProgress] = useState<JobProgress>(IDLE)
  const [error, setError] = useState<string | null>(null)
  const stream = useRef<EventSource | null>(null)

  useEffect(() => () => stream.current?.close(), [])

  const run = useCallback(async (create: () => Promise<string>): Promise<JobResult | null> => {
    stream.current?.close()
    setRunning(true)
    setProgress(IDLE)
    setError(null)
    try {
      const id = await create()
      return await new Promise<JobResult>((resolve, reject) => {
        const es = new EventSource(eventsUrl(id))
        stream.current = es
        es.onmessage = ({ data }) => {
          const event = JSON.parse(data) as JobEvent
          switch (event.phase) {
            case "download":
              setProgress((p) => ({ ...p, download: event, step: null }))
              break
            case "process":
              setProgress((p) => ({ ...p, step: event.step }))
              break
            case "proxy":
              setProgress((p) => ({ ...p, proxy: event.status }))
              break
            case "complete":
              es.close()
              if (event.status === "completed") resolve({ ...event, id })
              else reject(new Error(event.error))
          }
        }
        es.onerror = () => {
          es.close()
          reject(new Error("Lost the connection to the server."))
        }
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.")
      return null
    } finally {
      setRunning(false)
    }
  }, [])

  const clearError = useCallback(() => setError(null), [])
  return { running, progress, error, run, clearError }
}
