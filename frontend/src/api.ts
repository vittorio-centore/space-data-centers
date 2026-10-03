const API = '/api'
const WS_URL = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api-ws/ws`

/** Active tenant context for platform control-plane calls (header X-Tenant-Id). */
let activeTenantId: string | null = null
let activeTenantKey: string | null = null

export function getTenantContext(): { tenantId: string | null; apiKey: string | null } {
  return { tenantId: activeTenantId, apiKey: activeTenantKey }
}

export function setTenantContext(tenantId: string | null, apiKey?: string | null) {
  activeTenantId = tenantId
  activeTenantKey = apiKey ?? (tenantId ? `sdc-${tenantId}` : null)
}

function tenantHeaders(): Record<string, string> {
  const h: Record<string, string> = {}
  if (activeTenantId) h['X-Tenant-Id'] = activeTenantId
  if (activeTenantKey) h['X-API-Key'] = activeTenantKey
  return h
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...tenantHeaders(),
      ...(init?.headers || {}),
    },
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || res.statusText)
  }
  return res.json()
}

async function reqOptional<T>(path: string, init?: RequestInit): Promise<T | null> {
  try {
    return await req<T>(path, init)
  } catch (e) {
    const msg = e instanceof Error ? e.message : ''
    if (msg.includes('404') || msg.includes('Not Found')) return null
    throw e
  }
}

export const api = {
  health: () => req<{ ok: boolean }>('/health'),
  topology: () => req<Topology>('/topology'),
  orbitalRecords: () => req<OrbitalRecordMeta[]>('/orbital-records'),
  settings: () => req<Settings>('/settings'),
  patchSettings: (body: Partial<Settings>) =>
    req<Settings>('/settings', { method: 'PATCH', body: JSON.stringify(body) }),
  play: () => req('/sim/play', { method: 'POST' }),
  pause: () => req('/sim/pause', { method: 'POST' }),
  step: () => req('/sim/step', { method: 'POST' }),
  reset: () => req('/sim/reset', { method: 'POST' }),
  seek: (t: number) => req('/sim/seek', { method: 'POST', body: JSON.stringify({ t }) }),
  jobs: () => req<Job[]>('/jobs'),
  submitJob: (body: JobSubmit) =>
    req<SubmitResult>('/jobs', { method: 'POST', body: JSON.stringify(body) }),
  job: (id: string) => req<{ job: Job; plan: Plan | null }>(`/jobs/${id}`),
  cancelJob: (id: string) => req(`/jobs/${id}/cancel`, { method: 'POST' }),
  replanJob: (id: string) => req(`/jobs/${id}/replan`, { method: 'POST' }),
  transfers: () => req<Transfer[]>('/transfers'),
  events: () => req<SimEvent[]>('/events?limit=100'),
  metrics: () => req<Metrics>('/metrics'),
  snapshot: () => req<Snapshot>('/snapshot'),
  thesisPresets: () => req<ThesisPresets>('/presets/thesis'),
  runThesis: (c: 'a' | 'b') => req<SubmitResult>(`/presets/thesis/${c}`, { method: 'POST' }),
  disrupt: (linkId: string, body: { down?: boolean; bandwidth_factor?: number }) =>
    req(`/links/${encodeURIComponent(linkId)}/disrupt`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  clearDisrupt: (linkId: string) =>
    req(`/links/${encodeURIComponent(linkId)}/disrupt`, { method: 'DELETE' }),
  workers: () => req<WorkerStatus[]>('/workers'),
  nodeTrack: (nodeId: string, duration = 5400, step = 45) =>
    req<{ node_id: string; t0: number; points: { lat: number; lon: number; alt_km: number }[] }>(
      `/nodes/${encodeURIComponent(nodeId)}/track?duration=${duration}&step=${step}`,
    ),
  scenarios: () => req<ScenarioInfo[]>('/scenarios'),
  loadScenario: (id: string) =>
    req<{ scenario: string; nodes: ComputeNode[]; stations: GroundStation[]; links: LinkConfig[] }>(
      '/scenarios',
      { method: 'POST', body: JSON.stringify({ id }) },
    ),
  nodePower: (nodeId: string) =>
    req<{ node_id: string; power_thermal: PowerThermal | null }>(
      `/nodes/${encodeURIComponent(nodeId)}/power`,
    ),
  runEvaluation: (body?: {
    seed?: number
    n_jobs?: number
    policies?: string[]
    max_steps?: number
  }) =>
    req<EvaluationReport>('/evaluations', {
      method: 'POST',
      body: JSON.stringify(body ?? {}),
    }),
  listEvaluations: () => req<EvaluationReport[]>('/evaluations'),

  /** Platform: list tenants (null if control-plane routes not mounted yet). */
  listTenants: async () => {
    const a = await reqOptional<TenantInfo[] | { tenants: TenantInfo[] }>('/tenants')
    if (!a) return null
    return Array.isArray(a) ? a : a.tenants || []
  },

  /** Seed demo tenants alpha / beta (plan names). */
  ensureDemoTenants: async () => {
    const seeded =
      (await reqOptional<{ tenants: TenantInfo[] }>('/tenants/demo', { method: 'POST', body: '{}' })) ||
      (await reqOptional<{ tenants: TenantInfo[] }>('/tenants/seed', {
        method: 'POST',
        body: JSON.stringify({ ids: ['alpha', 'beta'] }),
      }))
    if (seeded?.tenants) return seeded.tenants
    // Fall back to create-one endpoints
    const out: TenantInfo[] = []
    for (const id of ['alpha', 'beta'] as const) {
      const created =
        (await reqOptional<TenantInfo>('/tenants', {
          method: 'POST',
          body: JSON.stringify({ id, name: id === 'alpha' ? 'Tenant A' : 'Tenant B' }),
        })) ||
        (await reqOptional<TenantInfo>(`/tenants/${id}`, {
          method: 'PUT',
          body: JSON.stringify({ name: id === 'alpha' ? 'Tenant A' : 'Tenant B' }),
        }))
      if (created) out.push(created)
      else out.push({ id, name: id === 'alpha' ? 'Tenant A' : 'Tenant B' })
    }
    return out
  },

  setActiveTenant: (tenantId: string | null) => {
    setTenantContext(tenantId, tenantId ? `sdc-${tenantId}` : null)
  },

  runMarketDay: async (body?: { seed?: number; scenario_id?: string }) => {
    const report =
      (await reqOptional<MarketDayReport>('/market-day', {
        method: 'POST',
        body: JSON.stringify(body ?? { seed: 1, scenario_id: 'mvp-thesis' }),
      })) ||
      (await reqOptional<MarketDayReport>('/evaluations/market-day', {
        method: 'POST',
        body: JSON.stringify(body ?? { seed: 1, scenario_id: 'mvp-thesis' }),
      })) ||
      (await reqOptional<MarketDayReport>('/platform/market-day', {
        method: 'POST',
        body: JSON.stringify(body ?? { seed: 1, scenario_id: 'mvp-thesis' }),
      }))
    if (!report) {
      throw new Error('Market day API not available yet (platform slice).')
    }
    return report
  },
}

export function connectWs(onEvent: (ev: SimEvent) => void): WebSocket {
  const ws = new WebSocket(WS_URL)
  ws.onmessage = (m) => {
    try {
      onEvent(JSON.parse(m.data))
    } catch {
      /* ignore */
    }
  }
  return ws
}

export type NodeKind = 'earth' | 'orbital'
export type JobState =
  | 'submitted'
  | 'planned'
  | 'input_transfer'
  | 'queued'
  | 'running'
  | 'output_transfer'
  | 'completed'
  | 'failed'
  | 'canceled'

export interface PowerThermal {
  sunlit: boolean
  eclipse: boolean
  solar_w: number
  battery_soc: number
  temperature_k: number
  power_factor: number
  thermal_factor: number
  effective_rate_factor: number
  labels?: Record<string, string>
  notes?: string
}

export interface ComputeNode {
  id: string
  kind: NodeKind
  name: string
  orbital_record_id?: string
  lat?: number
  lon?: number
  alt_km?: number
  compute_rate: number
  price_per_work: number
  available_at: number
  position_lla?: { lat: number; lon: number; alt_km: number }
  reality_flags?: Record<string, string>
  power_thermal?: PowerThermal | null
}

export interface GroundStation {
  id: string
  name: string
  lat: number
  lon: number
  alt_m: number
  min_elevation_deg: number
}

export interface LinkConfig {
  id: string
  kind: 'ground_space' | 'isl' | 'terrestrial'
  endpoint_a: string
  endpoint_b: string
  bandwidth_bps: number
  price_per_bit: number
  up: boolean
  rules: Record<string, unknown>
}

export interface Topology {
  nodes: ComputeNode[]
  ground_stations: GroundStation[]
  links: LinkConfig[]
  reality: Record<string, string>
}

export interface OrbitalRecordMeta {
  id: string
  name: string
  norad_id: string
  source: string
  epoch: string
  reality: string
}

export interface Settings {
  sim_step_s: number
  plan_horizon_s: number
  epoch_utc: string
  playing: boolean
  speed: number
  t: number
  disrupted_links: Record<string, { down?: boolean; bandwidth_factor?: number; until?: number }>
  scenario_id?: string
  headless?: boolean
  persist?: boolean
}

export interface ScenarioInfo {
  id: string
  label: string
  description: string
}

export interface EvaluationPolicyRow {
  policy: string
  n_jobs: number
  deadline_hit_rate: number
  mean_cost: number
  mean_completion: number
  mean_compute_wait_s: number
  completion_prediction_mae?: number
  cost_prediction_mae?: number
  n_failed: number
}

export interface EvaluationReport {
  id: string
  scenario_id: string
  seed: number
  created_t: number
  policies: EvaluationPolicyRow[]
}

export interface TenantInfo {
  id: string
  name?: string
  api_key?: string | null
  quota?: Record<string, number>
}

export interface MarketDayReport {
  id?: string
  scenario_id?: string
  seed?: number
  /** Per-tenant on-time rates (0–1). */
  deadline_hit_rate?: Record<string, number>
  per_tenant?: { tenant_id: string; deadline_hit_rate: number; mean_cost?: number }[]
  stolen_windows: number
  cost_reservation_aware: number
  cost_global_cheapest_ignores_tenants: number
  deadline_hit_rate_global_cheapest?: number
  notes?: string
}

export interface Hop {
  from_id: string
  to_id: string
  link_id?: string
  window_start: number
  window_end: number
  bytes: number
}

export interface BaselineComparison {
  baseline_node_id: string
  baseline_cost: number
  baseline_completion: number
  baseline_feasible: boolean
  chosen_node_id: string
  chosen_cost: number
  chosen_completion: number
  reason_codes: string[]
}

export interface Plan {
  id: string
  job_id: string
  compute_node_id: string
  input_route: Hop[]
  output_route: Hop[]
  compute_start: number
  compute_end: number
  estimated_cost: number
  estimated_completion: number
  baseline_comparison?: BaselineComparison
  transfer_cost: number
  compute_cost: number
}

export interface Job {
  id: string
  submitted_at: number
  input_bytes: number
  output_bytes: number
  work: number
  deadline_at?: number | null
  source_id: string
  destination_id: string
  state: JobState
  assigned_node_id?: string | null
  plan_id?: string | null
  fail_reason?: string | null
  actual_completion?: number | null
  actual_cost?: number | null
  preset?: string | null
  worker_done?: boolean
}

export interface Transfer {
  id: string
  job_id: string
  direction: 'input' | 'output'
  from_id: string
  to_id: string
  bytes_total: number
  bytes_sent: number
  state: string
  active_link_id?: string
}

export interface SimEvent {
  id: string
  t: number
  type: string
  payload: Record<string, unknown>
}

export interface Metrics {
  jobs_by_state: Record<string, number>
  mean_completion_delay_s: number
  mean_cost_vs_baseline: number
  links_up: number
  links_total: number
  t: number
  active_transfers: number
}

export interface Snapshot {
  settings: Settings
  nodes: ComputeNode[]
  stations: GroundStation[]
  links: LinkConfig[]
  jobs: Job[]
  plans: Plan[]
  transfers: Transfer[]
  reality: Record<string, string>
}

export interface JobSubmit {
  input_bytes: number
  output_bytes: number
  work: number
  deadline_at?: number | null
  source_id: string
  destination_id: string
  preset?: string
}

export interface SubmitResult {
  job: Job
  plan: Plan | null
  baseline_comparison?: BaselineComparison | null
  error?: string
  preset?: Record<string, unknown>
  sought_t?: number
}

export interface ThesisPresets {
  cheap_node_id: string
  contact_windows_gs_ashburn: [number, number][]
  case_a: Record<string, unknown>
  case_b: Record<string, unknown>
  objective: string
}

export interface WorkerStatus {
  id: string
  job_id?: string | null
  state: string
}
