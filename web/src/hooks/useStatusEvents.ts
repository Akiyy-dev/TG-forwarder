import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

export interface StatusEvent {
  ts: string
  pending_review: number
  queue_size: number
  publishing_paused: boolean
}

export function useStatusEvents(enabled = true) {
  const qc = useQueryClient()
  const [latest, setLatest] = useState<StatusEvent | null>(null)

  useEffect(() => {
    if (!enabled) return
    const es = new EventSource('/api/v1/events/stream', { withCredentials: true })
    const onStatus = (ev: MessageEvent) => {
      try {
        const data = JSON.parse(ev.data) as StatusEvent
        setLatest(data)
        void qc.invalidateQueries({ queryKey: ['dashboard'] })
        void qc.invalidateQueries({ queryKey: ['reviews'] })
        void qc.invalidateQueries({ queryKey: ['system'] })
      } catch {
        // ignore malformed payloads
      }
    }
    es.addEventListener('status', onStatus)
    es.onerror = () => {
      // Browser will reconnect; keep silent to avoid noise.
    }
    return () => {
      es.removeEventListener('status', onStatus)
      es.close()
    }
  }, [enabled, qc])

  return latest
}
