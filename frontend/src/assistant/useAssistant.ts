import { useCallback, useEffect, useState } from 'react'
import { getTenantContext } from '../api'
import type { AssistantAskResult, AssistantStatus } from './types'

const API = '/api'

function assistantHeaders(json = false): Record<string, string> {
  const { tenantId, apiKey } = getTenantContext()
  const h: Record<string, string> = {}
  if (json) h['Content-Type'] = 'application/json'
  if (tenantId) h['X-Tenant-Id'] = tenantId
  if (apiKey) h['X-API-Key'] = apiKey
  return h
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, init)
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || res.statusText)
  }
  return res.json()
}

export function useAssistant() {
  const [status, setStatus] = useState<AssistantStatus | null>(null)
  const [error, setError] = useState<string | null>(null)

  const refreshStatus = useCallback(async () => {
    try {
      const s = await req<AssistantStatus>('/assistant/status', { headers: assistantHeaders() })
      setStatus(s)
      setError(null)
      return s
    } catch (e) {
      setError(e instanceof Error ? e.message : 'status failed')
      return null
    }
  }, [])

  useEffect(() => {
    void refreshStatus()
  }, [refreshStatus])

  const ask = useCallback(async (text: string, source: 'text' | 'voice' = 'text') => {
    return req<AssistantAskResult>('/assistant/ask', {
      method: 'POST',
      headers: assistantHeaders(true),
      body: JSON.stringify({ text, source }),
    })
  }, [])

  const sendVoice = useCallback(async (blob: Blob) => {
    const fd = new FormData()
    fd.append('file', blob, 'clip.webm')
    return req<AssistantAskResult>('/assistant/voice?speak=true', {
      method: 'POST',
      headers: assistantHeaders(false),
      body: fd,
    })
  }, [])

  return { status, error, refreshStatus, ask, sendVoice }
}

export function playAudioB64(b64: string) {
  const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0))
  const url = URL.createObjectURL(new Blob([bytes], { type: 'audio/mpeg' }))
  const audio = new Audio(url)
  void audio.play()
  audio.onended = () => URL.revokeObjectURL(url)
}
