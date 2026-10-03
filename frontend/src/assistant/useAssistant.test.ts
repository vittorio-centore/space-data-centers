import { renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api', () => ({
  getTenantContext: () => ({ tenantId: 'alpha', apiKey: 'sdc-alpha' }),
}))

import { useAssistant } from './useAssistant'

describe('useAssistant headers', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('sends tenant key on status and ask', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        mode: 'offline',
        grok: false,
        reply: 'ok',
      }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useAssistant())
    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    const statusHeaders = fetchMock.mock.calls[0][1]?.headers as Record<string, string>
    expect(statusHeaders['X-API-Key']).toBe('sdc-alpha')
    expect(statusHeaders['X-Tenant-Id']).toBe('alpha')

    await result.current.ask('pause')
    const askInit = fetchMock.mock.calls.at(-1)?.[1] as RequestInit
    const askHeaders = askInit.headers as Record<string, string>
    expect(askHeaders['X-API-Key']).toBe('sdc-alpha')
    expect(askHeaders['Content-Type']).toBe('application/json')
    expect(JSON.parse(String(askInit.body))).toEqual({ text: 'pause', source: 'text' })
  })
})
