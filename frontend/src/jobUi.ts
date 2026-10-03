import type { Job, MarketDayReport, Plan, Transfer } from './api'

export type JobForm = {
  input_mb: number
  output_mb: number
  work: number
  deadline_offset: number
  source_id: string
  destination_id: string
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
  return {
    input_bytes: Math.round(form.input_mb * 1_000_000),
    output_bytes: Math.round(form.output_mb * 1_000_000),
    work: form.work,
    deadline_at: t + form.deadline_offset,
    source_id: form.source_id,
    destination_id: form.destination_id,
  }
}

export function deriveMarketMetrics(report: MarketDayReport | null) {
  if (!report) return null
  const rates = report.deadline_hit_rate || {}
  const fromRows = Object.fromEntries(
    (report.per_tenant || []).map((r) => [r.tenant_id, r.deadline_hit_rate]),
  )
  return {
    hitA: rates.alpha ?? rates.A ?? fromRows.alpha ?? fromRows.A,
    hitB: rates.beta ?? rates.B ?? fromRows.beta ?? fromRows.B,
    stolen: report.stolen_windows,
    costAware: report.cost_reservation_aware,
    costGlobal: report.cost_global_cheapest_ignores_tenants,
  }
}
