import { describe, expect, it } from 'vitest'
import type { Job, MarketDayReport, Plan, Reservation, Transfer } from './api'
import {
  deriveBookings,
  deriveMarketMetrics,
  etaSeconds,
  jobSubmitBody,
  jobTransferProgress,
  quotaRemaining,
  shortNodeName,
  tenantShort,
} from './jobUi'

const job = (state: Job['state'], extra: Partial<Job> = {}): Job =>
  ({
    id: 'job-1',
    tenant_id: 'local',
    submitted_at: 0,
    input_bytes: 1,
    output_bytes: 1,
    work: 10,
    source_id: 'gs-ashburn',
    destination_id: 'gs-ashburn',
    state,
    ...extra,
  }) as Job

describe('jobSubmitBody', () => {
  it('converts MB and deadline offset against sim clock', () => {
    expect(
      jobSubmitBody(
        {
          input_mb: 5,
          output_mb: 1.5,
          work: 200,
          deadline_offset: 3600,
          source_id: 'gs-madrid',
          destination_id: 'gs-ashburn',
        },
        100,
      ),
    ).toEqual({
      input_bytes: 5_000_000,
      output_bytes: 1_500_000,
      work: 200,
      deadline_at: 3700,
      source_id: 'gs-madrid',
      destination_id: 'gs-ashburn',
    })
  })
})

describe('jobTransferProgress', () => {
  it('uses stage fallbacks when no transfers', () => {
    expect(jobTransferProgress(job('submitted'), [])).toBe(0)
    expect(jobTransferProgress(job('running'), [])).toBe(50)
    expect(jobTransferProgress(job('completed'), [])).toBe(100)
  })

  it('blends input bytes with running floor', () => {
    const transfers = [
      {
        id: 'x',
        job_id: 'job-1',
        direction: 'input',
        from_id: 'gs-ashburn',
        to_id: 'earth-us-east',
        bytes_total: 100,
        bytes_sent: 10,
        state: 'active',
      },
    ] as Transfer[]
    expect(jobTransferProgress(job('running'), transfers)).toBe(55)
    expect(jobTransferProgress(job('input_transfer'), transfers)).toBe(10)
  })
})

describe('etaSeconds', () => {
  const plan = { estimated_completion: 500 } as Plan
  it('is null for terminal jobs', () => {
    expect(etaSeconds(job('completed'), plan, 10)).toBeNull()
    expect(etaSeconds(job('planned'), null, 10)).toBeNull()
  })
  it('clamps remaining time to zero', () => {
    expect(etaSeconds(job('running'), plan, 600)).toBe(0)
    expect(etaSeconds(job('running'), plan, 200)).toBe(300)
  })
})

describe('deriveMarketMetrics', () => {
  it('reads per-tenant rates and stolen windows', () => {
    const report: MarketDayReport = {
      stolen_windows: 0,
      cost_reservation_aware: 1.2,
      cost_global_cheapest_ignores_tenants: 0.9,
      deadline_hit_rate: { alpha: 0.5, beta: 1 },
    }
    expect(deriveMarketMetrics(report)).toEqual({
      hitA: 0.5,
      hitB: 1,
      stolen: 0,
      costAware: 1.2,
      costGlobal: 0.9,
    })
    expect(deriveMarketMetrics(null)).toBeNull()
  })
})

describe('control-plane helpers', () => {
  it('shortens tenant and node labels', () => {
    expect(tenantShort('alpha')).toBe('A')
    expect(tenantShort('beta')).toBe('B')
    expect(tenantShort('local')).toBe('Local')
    expect(shortNodeName('orbital-iss-cheap')).toBe('ISS')
  })

  it('prefers reservations for bookings and surfaces ISS first', () => {
    const reservations: Reservation[] = [
      {
        job_id: 'j2',
        tenant_id: 'beta',
        node_id: 'earth-us-east',
        start: 10,
        end: 20,
      },
      {
        job_id: 'j1',
        tenant_id: 'alpha',
        node_id: 'orbital-iss-cheap',
        start: 30,
        end: 40,
      },
    ]
    const rows = deriveBookings(reservations, [], 0, 8)
    expect(rows[0].resource).toBe('ISS')
    expect(rows[0].tenantId).toBe('alpha')
    expect(rows).toHaveLength(2)
  })

  it('falls back to plans when reservations are empty', () => {
    const plans = [
      {
        id: 'p1',
        job_id: 'j1',
        tenant_id: 'beta',
        compute_node_id: 'orbital-iss-cheap',
        compute_start: 100,
        compute_end: 110,
        input_route: [],
        output_route: [],
      },
    ] as Plan[]
    const rows = deriveBookings([], plans, 50, 4)
    expect(rows[0]).toMatchObject({ tenantId: 'beta', resource: 'ISS', start: 100 })
  })

  it('computes remaining quota', () => {
    expect(
      quotaRemaining({
        outstanding_jobs: 2,
        quota_outstanding_jobs: 64,
        reserved_s: 5,
        quota_reserved_s: 100,
      }),
    ).toEqual({
      jobsLeft: 62,
      jobsCap: 64,
      reservedLeft: 95,
      reservedCap: 100,
      reservedUsed: 5,
    })
    expect(quotaRemaining(null)).toBeNull()
  })
})
