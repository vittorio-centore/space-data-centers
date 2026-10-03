import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const snapshot = {
  nodes: [],
  stations: [
    { id: 'gs-ashburn', name: 'Ashburn', lat: 0, lon: 0, alt_m: 0, min_elevation_deg: 10 },
    { id: 'gs-madrid', name: 'Madrid', lat: 0, lon: 0, alt_m: 0, min_elevation_deg: 10 },
  ],
  links: [],
  jobs: [],
  plans: [],
  transfers: [],
  settings: {
    t: 10,
    playing: false,
    speed: 10,
    sim_step_s: 5,
    scenario_id: 'mvp-thesis',
  },
}

const submitResult = {
  job: {
    id: 'job-00000001',
    tenant_id: 'local',
    submitted_at: 10,
    input_bytes: 2_000_000,
    output_bytes: 1_000_000,
    work: 99,
    source_id: 'gs-ashburn',
    destination_id: 'gs-ashburn',
    state: 'planned',
    plan_id: 'plan-1',
  },
  plan: {
    id: 'plan-1',
    job_id: 'job-00000001',
    compute_node_id: 'earth-us-east',
    estimated_cost: 1,
    estimated_completion: 100,
    input_route: [],
    output_route: [],
  },
}

const marketReport = {
  stolen_windows: 0,
  deadline_hit_rate: { alpha: 0.5, beta: 1 },
  cost_reservation_aware: 2,
  cost_global_cheapest_ignores_tenants: 1,
  seed: 11,
  scenario_id: 'mvp-thesis',
}

const api = {
  snapshot: vi.fn(async () => snapshot),
  scenarios: vi.fn(async () => [{ id: 'mvp-thesis', label: 'MVP thesis', description: '' }]),
  orbitalRecords: vi.fn(async () => [{ name: 'ISS', norad_id: '25544' }]),
  listTenants: vi.fn(async () => [
    { id: 'local', display_name: 'Local default' },
    { id: 'alpha', display_name: 'Tenant A' },
    { id: 'beta', display_name: 'Tenant B' },
  ]),
  ensureDemoTenants: vi.fn(async () => [
    { id: 'local', display_name: 'Local default' },
    { id: 'alpha', display_name: 'Tenant A' },
    { id: 'beta', display_name: 'Tenant B' },
  ]),
  setActiveTenant: vi.fn(),
  submitJob: vi.fn(async () => submitResult),
  runThesis: vi.fn(async () => ({ ...submitResult, sought_t: 120 })),
  play: vi.fn(async () => ({})),
  pause: vi.fn(async () => ({})),
  patchSettings: vi.fn(async () => snapshot.settings),
  runMarketDay: vi.fn(async () => marketReport),
  nodePower: vi.fn(async () => ({ node_id: 'x', power_thermal: null })),
}

vi.mock('./api', () => ({
  api,
  connectWs: () => ({ close() {} }),
  getTenantContext: () => ({ tenantId: null, apiKey: null }),
}))

vi.mock('./components/Globe', () => ({
  default: () => <div data-testid="globe" />,
}))

vi.mock('./assistant/AskPanel', () => ({
  default: () => null,
}))

import App from './App'

describe('dashboard wiring', () => {
  beforeEach(() => {
    Object.values(api).forEach((fn) => {
      if (typeof fn === 'function' && 'mockClear' in fn) fn.mockClear()
    })
  })

  afterEach(() => {
    cleanup()
  })

  it('submits the job form through the API', async () => {
    render(<App />)
    await waitFor(() => expect(api.snapshot).toHaveBeenCalled())
    fireEvent.change(screen.getByTestId('input-mb'), { target: { value: '2' } })
    fireEvent.change(screen.getByTestId('work'), { target: { value: '99' } })
    fireEvent.click(screen.getByTestId('submit-job'))
    await waitFor(() => expect(api.submitJob).toHaveBeenCalled())
    expect(api.submitJob).toHaveBeenCalledWith(
      expect.objectContaining({
        input_bytes: 2_000_000,
        work: 99,
        source_id: 'gs-ashburn',
        deadline_at: 10 + 3600,
      }),
    )
  })

  it('runs thesis presets from the examples row', async () => {
    render(<App />)
    await waitFor(() => expect(api.snapshot).toHaveBeenCalled())
    fireEvent.click(screen.getByTestId('toggle-examples'))
    fireEvent.click(screen.getByTestId('thesis-a'))
    await waitFor(() => expect(api.runThesis).toHaveBeenCalledWith('a'))
    expect(api.play).toHaveBeenCalled()
  })

  it('switches tenant and runs market day', async () => {
    render(<App />)
    await waitFor(() => expect(api.listTenants).toHaveBeenCalled())
    fireEvent.click(screen.getByTestId('toggle-advanced'))
    fireEvent.change(screen.getByTestId('tenant-select'), { target: { value: 'beta' } })
    expect(api.setActiveTenant).toHaveBeenCalledWith('beta')
    fireEvent.click(screen.getByTestId('run-market-day'))
    await waitFor(() => expect(api.runMarketDay).toHaveBeenCalled())
    expect(api.runMarketDay).toHaveBeenCalledWith({ seed: 11, n_per_tenant: 3, max_steps: 2000 })
    await waitFor(() => expect(screen.getByTestId('market-report')).toBeTruthy())
    expect(screen.getByTestId('market-report').textContent).toContain('Stolen windows')
  })
})
