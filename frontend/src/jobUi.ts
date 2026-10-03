import type {
  Job,
  MarketDayReport,
  Plan,
  QuotaSnapshot,
  Reservation,
  Transfer,
} from './api'

export type JobForm = {
  input_mb: number
  output_mb: number
  work: number
  deadline_offset: number
  source_id: string
  destination_id: string
  /** Advanced: opt-in planner split across compatible nodes. */
  allow_split?: boolean
  /** Advanced: migrate_on_disruption only when checkpointable. */
  disruption_policy?: 'node_fixed' | 'migrate_on_disruption'
}

export function jobTransferProgress(job: Job, transfers: Transfer[]): number | null {
  const own = transfers.filter((t) => t.job_id === job.id)
  if (own.length === 0) {
    if (job.state === 'completed') return 100
    if (job.state === 'running' || job.state === 'queued') return 50
    if (job.state === 'output_transfer') return 75
    return job.state === 'planned' || job.state === 'submitted' ? 0 : null
  }
  const relevant =
    job.state === 'input_transfer'
      ? own.filter((t) => t.direction === 'input')
      : job.state === 'output_transfer'
        ? own.filter((t) => t.direction === 'output')
        : own
  const list = relevant.length ? relevant : own
  const total = list.reduce((s, t) => s + t.bytes_total, 0)
  const sent = list.reduce((s, t) => s + t.bytes_sent, 0)
  if (!total) return job.state === 'completed' ? 100 : 0
  const raw = (sent / total) * 100
  if (job.state === 'running' || job.state === 'queued') return Math.max(raw, 55)
  if (job.state === 'completed') return 100
  return raw
}

export function etaSeconds(job: Job, plan: Plan | null, t: number): number | null {
  if (job.state === 'completed' || job.state === 'failed' || job.state === 'canceled') return null
  if (!plan) return null
  return Math.max(0, plan.estimated_completion - t)
}

export function jobSubmitBody(form: JobForm, t: number) {
  const body: {
    input_bytes: number
    output_bytes: number
    work: number
    deadline_at: number
    source_id: string
    destination_id: string
    allow_split?: boolean
    disruption_policy?: 'node_fixed' | 'migrate_on_disruption'
  } = {
    input_bytes: Math.round(form.input_mb * 1_000_000),
    output_bytes: Math.round(form.output_mb * 1_000_000),
    work: form.work,
    deadline_at: t + form.deadline_offset,
    source_id: form.source_id,
    destination_id: form.destination_id,
  }
  if (form.allow_split) body.allow_split = true
  if (form.disruption_policy && form.disruption_policy !== 'node_fixed') {
    body.disruption_policy = form.disruption_policy
  }
  return body
}

export function deriveMarketMetrics(report: MarketDayReport | null) {
  if (!report) return null
  const rates = report.deadline_hit_rate || {}
  const fromRows = Object.fromEntries(
    (report.per_tenant || []).map((r) => [r.tenant_id, r.deadline_hit_rate]),
  )
  const hit = (id: string, alias?: string) =>
    rates[id] ?? (alias ? rates[alias] : undefined) ?? fromRows[id] ?? (alias ? fromRows[alias] : undefined)
  return {
    hitA: hit('alpha', 'A'),
    hitB: hit('beta', 'B'),
    hitC: hit('gamma', 'C'),
    hitD: hit('delta', 'D'),
    stolen: report.stolen_windows,
    costAware: report.cost_reservation_aware,
    costGlobal: report.cost_global_cheapest_ignores_tenants,
    equity: report.hit_rate_equity,
    minHit: report.min_tenant_hit_rate,
    fairnessBeats: report.fairness_beats_ignore_tenants,
    tenants: report.tenants || ['alpha', 'beta', 'gamma', 'delta'],
  }
}

export function tenantShort(id: string | null | undefined): string {
  if (!id || id === 'local') return 'Local'
  if (id === 'alpha') return 'A'
  if (id === 'beta') return 'B'
  if (id === 'gamma') return 'C'
  if (id === 'delta') return 'D'
  return id
}

export function tenantOptionLabel(id: string, display?: string | null): string {
  if (id === 'alpha') return 'Tenant A'
  if (id === 'beta') return 'Tenant B'
  if (id === 'gamma') return 'Tenant C'
  if (id === 'delta') return 'Tenant D'
  return display || id
}

export function shortNodeName(id: string): string {
  if (/iss/i.test(id)) return 'ISS'
  if (id.startsWith('orbital-')) return id.slice('orbital-'.length)
  if (id.startsWith('earth-')) return id.slice('earth-'.length)
  return id
}

export type BookingRow = {
  key: string
  jobId: string
  tenantId: string
  resource: string
  start: number
  end: number
  kind: 'compute' | 'window'
}

/** Who holds compute / contact windows — reservations first, else plans. */
export function deriveBookings(
  reservations: Reservation[] | null | undefined,
  plans: Plan[],
  simT: number,
  limit = 8,
): BookingRow[] {
  const rows: BookingRow[] = []
  if (reservations?.length) {
    for (const r of reservations) {
      rows.push({
        key: `r-${r.job_id}-${r.node_id}-${r.start}`,
        jobId: r.job_id,
        tenantId: r.tenant_id || 'local',
        resource: shortNodeName(r.node_id),
        start: r.start,
        end: r.end,
        kind: 'compute',
      })
    }
  } else {
    for (const p of plans) {
      if (p.compute_start == null || p.compute_end == null) continue
      rows.push({
        key: `p-${p.id}`,
        jobId: p.job_id,
        tenantId: p.tenant_id || 'local',
        resource: shortNodeName(p.compute_node_id),
        start: p.compute_start,
        end: p.compute_end,
        kind: 'compute',
      })
      for (const hop of [...(p.input_route || []), ...(p.output_route || [])]) {
        rows.push({
          key: `h-${p.id}-${hop.link_id || hop.from_id}-${hop.window_start}`,
          jobId: p.job_id,
          tenantId: p.tenant_id || 'local',
          resource: `${shortNodeName(hop.from_id)}→${shortNodeName(hop.to_id)}`,
          start: hop.window_start,
          end: hop.window_end,
          kind: 'window',
        })
      }
    }
  }
  const active = rows.filter((r) => r.end >= simT - 1)
  const pool = active.length ? active : rows
  return pool
    .slice()
    .sort((a, b) => {
      const aIss = /iss/i.test(a.resource) ? 0 : 1
      const bIss = /iss/i.test(b.resource) ? 0 : 1
      if (aIss !== bIss) return aIss - bIss
      return a.start - b.start
    })
    .slice(0, limit)
}

export function quotaRemaining(quota?: QuotaSnapshot | Record<string, number> | null) {
  if (!quota) return null
  const jobsCap = Number(quota.quota_outstanding_jobs ?? 0)
  const jobsUsed = Number(quota.outstanding_jobs ?? 0)
  const reservedCap = Number(quota.quota_reserved_s ?? 0)
  const reservedUsed = Number(quota.reserved_s ?? 0)
  return {
    jobsLeft: Math.max(0, jobsCap - jobsUsed),
    jobsCap,
    reservedLeft: Math.max(0, reservedCap - reservedUsed),
    reservedCap,
    reservedUsed,
  }
}
