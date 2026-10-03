import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api, getTenantContext, setTenantContext } from './api'

describe('tenant context', () => {
  beforeEach(() => {
    setTenantContext(null, null)
  })

  it('maps tenant ids to demo keys', () => {
    setTenantContext('alpha')
    expect(getTenantContext()).toEqual({ tenantId: 'alpha', apiKey: 'sdc-alpha' })
    api.setActiveTenant('beta')
    expect(getTenantContext()).toEqual({ tenantId: 'beta', apiKey: 'sdc-beta' })
    api.setActiveTenant(null)
    expect(getTenantContext().tenantId).toBe('local')
    expect(getTenantContext().apiKey).toBe('sdc-local')
  })
})

describe('runMarketDay', () => {
  beforeEach(() => {
    setTenantContext(null, null)
  })

  it('posts the v1 evaluation path first', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        stolen_windows: 0,
        deadline_hit_rate: { alpha: 1, beta: 1 },
        cost_reservation_aware: 1,
        cost_global_cheapest_ignores_tenants: 1,
      }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const report = await api.runMarketDay({ seed: 11, n_per_tenant: 3, max_steps: 2000 })
    expect(report.stolen_windows).toBe(0)
    expect(fetchMock).toHaveBeenCalled()
    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toContain('/evaluations/market-day')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ seed: 11, n_per_tenant: 3, max_steps: 2000 })
    vi.unstubAllGlobals()
  })
})
