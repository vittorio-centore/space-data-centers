import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  api,
  connectWs,
  type ComputeNode,
  type EvaluationReport,
  type GroundStation,
  type Job,
  type LinkConfig,
  type Plan,
  type PowerThermal,
  type ScenarioInfo,
  type Settings,
  type Transfer,
} from './api'
import Globe from './components/Globe'
import AskPanel from './assistant/AskPanel'
import './App.css'

function fmt(n: number | null | undefined, d = 1) {
  if (n == null || Number.isNaN(n) || !Number.isFinite(n)) return '—'
  return n.toFixed(d)
}

function bytes(n: number) {
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)} MB`
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)} KB`
  return `${n} B`
}

const STAGE_LABEL: Record<Job['state'], string> = {
  submitted: 'Submitted',
  planned: 'Planned',
  input_transfer: 'Input transfer',
  queued: 'Queued',
  running: 'Computing',
  output_transfer: 'Output transfer',
  completed: 'Done',
  failed: 'Failed',
  canceled: 'Canceled',
}

function jobTransferProgress(job: Job, transfers: Transfer[]) {
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
  // Blend route progress with stage so compute shows mid-job progress.
  const raw = (sent / total) * 100
  if (job.state === 'running' || job.state === 'queued') return Math.max(raw, 55)
  if (job.state === 'completed') return 100
  return raw
}

function etaSeconds(job: Job, plan: Plan | null, t: number): number | null {
  if (job.state === 'completed' || job.state === 'failed' || job.state === 'canceled') return null
  if (!plan) return null
  return Math.max(0, plan.estimated_completion - t)
}

export default function App() {
  const [nodes, setNodes] = useState<ComputeNode[]>([])
  const [stations, setStations] = useState<GroundStation[]>([])
  const [links, setLinks] = useState<LinkConfig[]>([])
  const [jobs, setJobs] = useState<Job[]>([])
  const [plans, setPlans] = useState<Record<string, Plan>>({})
  const [transfers, setTransfers] = useState<Transfer[]>([])
  const [settings, setSettings] = useState<Settings | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null)
  const [orbitalMeta, setOrbitalMeta] = useState('')
  const [busy, setBusy] = useState(false)
  const [showMore, setShowMore] = useState(false)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [scenarios, setScenarios] = useState<ScenarioInfo[]>([])
  const [evalReport, setEvalReport] = useState<EvaluationReport | null>(null)
  const [evalBusy, setEvalBusy] = useState(false)
  const [evalErr, setEvalErr] = useState<string | null>(null)
  const [powerThermal, setPowerThermal] = useState<PowerThermal | null>(null)
  const [form, setForm] = useState({
    input_mb: 5,
    output_mb: 1,
    work: 200,
    deadline_offset: 3600,
    source_id: 'gs-ashburn',
    destination_id: 'gs-ashburn',
  })
  const refreshTimer = useRef<number | null>(null)
  const selectedJobIdRef = useRef<string | null>(null)
  selectedJobIdRef.current = selectedJobId

  const selectJob = useCallback((job: Job, _plan?: Plan | null) => {
    setSelectedJobId(job.id)
    selectedJobIdRef.current = job.id
    // Do not auto-select globe nodes — keeps labels small/off until user clicks the globe
    setSelectedId(null)
  }, [])

  const selectedPlan = useMemo(() => {
    if (!selectedJobId) return null
    const job = jobs.find((j) => j.id === selectedJobId)
    if (!job?.plan_id) return null
    return plans[job.plan_id] || null
  }, [selectedJobId, jobs, plans])

  const applySnapshot = useCallback(async () => {
    const snap = await api.snapshot()
    setNodes(snap.nodes)
    setStations(snap.stations)
    setLinks(snap.links)
    setJobs(snap.jobs)
    setPlans(Object.fromEntries(snap.plans.map((p) => [p.id, p])))
    setTransfers(snap.transfers)
    setSettings(snap.settings)
    if (!selectedJobIdRef.current && snap.jobs.length > 0) {
      const newest = [...snap.jobs].sort((a, b) => b.submitted_at - a.submitted_at)[0]
      const plan = newest.plan_id
        ? snap.plans.find((p) => p.id === newest.plan_id)
        : undefined
      selectJob(newest, plan || null)
    }
    return snap
  }, [selectJob])

  const scheduleRefresh = useCallback(() => {
    if (refreshTimer.current != null) window.clearTimeout(refreshTimer.current)
    refreshTimer.current = window.setTimeout(() => {
      applySnapshot().catch(() => undefined)
    }, 150)
  }, [applySnapshot])

  useEffect(() => {
    api.scenarios().then(setScenarios).catch(() => undefined)
  }, [])

  const selectedOrbital = useMemo(
    () => nodes.find((n) => n.id === selectedId && n.kind === 'orbital') || null,
    [nodes, selectedId],
  )
  const powerTick = settings?.t != null ? Math.floor(settings.t / 30) : 0

  useEffect(() => {
    if (!selectedOrbital) {
      setPowerThermal(null)
      return
    }
    if (selectedOrbital.power_thermal) setPowerThermal(selectedOrbital.power_thermal)
    let cancelled = false
    api
      .nodePower(selectedOrbital.id)
      .then((res) => {
        if (!cancelled) setPowerThermal(res.power_thermal)
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [selectedOrbital?.id, powerTick])

  useEffect(() => {
    let ws: WebSocket | null = null
    let alive = true
    ;(async () => {
      try {
        await applySnapshot()
        const recs = await api.orbitalRecords()
        setOrbitalMeta(recs.map((r) => `${r.name} (${r.norad_id})`).join(', '))
        ws = connectWs((ev) => {
          if (!alive) return
          if (ev.type === 'tick') {
            const positions = ev.payload.positions as Record<
              string,
              { lat: number; lon: number; alt_km: number }
            >
            const up = new Set(ev.payload.links_up as string[])
            setSettings((s) => (s ? { ...s, t: ev.t } : s))
            setNodes((ns) =>
              ns.map((n) => (positions[n.id] ? { ...n, position_lla: positions[n.id] } : n)),
            )
            setLinks((ls) => ls.map((L) => ({ ...L, up: up.has(L.id) })))
          } else if (ev.type === 'plan_created') {
            const plan = ev.payload.plan as Plan
            const jobId = (ev.payload.job_id as string) || plan?.job_id
            if (plan) setPlans((prev) => ({ ...prev, [plan.id]: plan }))
            if (jobId) {
              setSelectedJobId(jobId)
              selectedJobIdRef.current = jobId
              setSelectedId(null)
            }
            scheduleRefresh()
          } else if (ev.type === 'job_state') {
            const jobId = ev.payload.job_id as string
            const state = ev.payload.state as Job['state']
            const actualCompletion =
              typeof ev.payload.actual_completion === 'number'
                ? (ev.payload.actual_completion as number)
                : undefined
            const actualCost =
              typeof ev.payload.actual_cost === 'number'
                ? (ev.payload.actual_cost as number)
                : undefined
            setJobs((prev) => {
              const i = prev.findIndex((j) => j.id === jobId)
              if (i < 0) {
                scheduleRefresh()
                return prev
              }
              const next = prev.slice()
              next[i] = {
                ...next[i],
                state,
                ...(actualCompletion != null ? { actual_completion: actualCompletion } : {}),
                ...(actualCost != null ? { actual_cost: actualCost } : {}),
              }
              return next
            })
            if (state === 'completed' || state === 'failed') {
              scheduleRefresh()
            }
            if (!selectedJobIdRef.current && jobId) {
              setSelectedJobId(jobId)
              selectedJobIdRef.current = jobId
            }
          } else if (ev.type === 'transfer_progress') {
            const tr = ev.payload.transfer as Transfer
            setTransfers((prev) => {
              const i = prev.findIndex((x) => x.id === tr.id)
              if (i < 0) return [...prev, tr]
              const next = prev.slice()
              next[i] = tr
              return next
            })
          } else if (ev.type === 'metric') {
            if ('playing' in ev.payload) {
              setSettings((s) => (s ? { ...s, playing: Boolean(ev.payload.playing) } : s))
            }
            if (ev.payload.reset || ev.payload.seek) scheduleRefresh()
          } else if (ev.type === 'link_up' || ev.type === 'link_down') {
            const id = ev.payload.link_id as string
            setLinks((ls) =>
              ls.map((L) => (L.id === id ? { ...L, up: ev.type === 'link_up' } : L)),
            )
          }
        })
      } catch {
        /* ignore */
      }
    })()
    return () => {
      alive = false
      ws?.close()
      if (refreshTimer.current != null) window.clearTimeout(refreshTimer.current)
    }
  }, [applySnapshot, scheduleRefresh])

  const run = async (fn: () => Promise<unknown>, timeoutMs = 30000) => {
    if (busy) return
    setBusy(true)
    const safety = window.setTimeout(() => setBusy(false), timeoutMs)
    try {
      await fn()
      await applySnapshot()
      const recs = await api.orbitalRecords()
      setOrbitalMeta(recs.map((r) => `${r.name} (${r.norad_id})`).join(', '))
    } finally {
      window.clearTimeout(safety)
      setBusy(false)
    }
  }

  const switchScenario = (id: string) =>
    run(async () => {
      setSelectedJobId(null)
      selectedJobIdRef.current = null
      setSelectedId(null)
      setEvalReport(null)
      await api.loadScenario(id)
      const snap = await api.snapshot()
      const first = snap.stations[0]?.id
      if (first) {
        setForm((f) => ({ ...f, source_id: first, destination_id: first }))
      }
    })

  const runEval = async () => {
    if (busy || evalBusy) return
    setEvalBusy(true)
    setEvalErr(null)
    setBusy(true)
    try {
      const report = await api.runEvaluation({
        seed: 1,
        n_jobs: 3,
        policies: ['planner', 'cheapest', 'earth_only'],
        max_steps: 2000,
      })
      setEvalReport(report)
      await api.reset()
      await applySnapshot()
    } catch (e) {
      setEvalErr(e instanceof Error ? e.message : 'Evaluation failed')
      try {
        await api.reset()
        await applySnapshot()
      } catch {
        /* ignore */
      }
    } finally {
      setEvalBusy(false)
      setBusy(false)
    }
  }

  const play = () => {
    if (settings?.playing) return
    setSettings((s) => (s ? { ...s, playing: true } : s))
    api.play().catch(() => undefined)
  }
  const pause = () => {
    if (settings && !settings.playing) return
    setSettings((s) => (s ? { ...s, playing: false } : s))
    api.pause().catch(() => undefined)
  }

  const submit = () =>
    run(async () => {
      const t = settings?.t ?? 0
      const res = await api.submitJob({
        input_bytes: Math.round(form.input_mb * 1_000_000),
        output_bytes: Math.round(form.output_mb * 1_000_000),
        work: form.work,
        deadline_at: t + form.deadline_offset,
        source_id: form.source_id,
        destination_id: form.destination_id,
      })
      selectJob(res.job, res.plan)
    })

  const thesis = (c: 'a' | 'b') =>
    run(async () => {
      const res = await api.runThesis(c)
      selectJob(res.job, res.plan)
      setSettings((s) => (s ? { ...s, playing: true, t: res.sought_t ?? s.t } : s))
      await api.play()
    })

  const selectedJob = jobs.find((j) => j.id === selectedJobId) || null
  const bc = selectedPlan?.baseline_comparison
  const sortedJobs = [...jobs].sort((a, b) => b.submitted_at - a.submitted_at)
  const simT = settings?.t ?? 0

  const summary = useMemo(() => {
    const done = jobs.filter((j) => j.state === 'completed')
    let onTime = 0
    for (const j of done) {
      const finish = j.actual_completion
      if (finish == null) continue
      if (j.deadline_at == null || finish <= j.deadline_at) onTime += 1
    }
    let totalCost = 0
    let baselineCost = 0
    let costPairs = 0
    for (const j of jobs) {
      const plan = j.plan_id ? plans[j.plan_id] : null
      const cost = j.actual_cost ?? plan?.estimated_cost
      const base = plan?.baseline_comparison?.baseline_cost
      if (cost != null) totalCost += cost
      if (cost != null && base != null && plan?.baseline_comparison?.baseline_feasible) {
        baselineCost += base
        costPairs += 1
      }
    }
    return {
      jobsDone: done.length,
      jobsTotal: jobs.length,
      onTimePct: done.length ? (onTime / done.length) * 100 : null,
      totalCost: jobs.length ? totalCost : null,
      baselineCost: costPairs ? baselineCost : null,
    }
  }, [jobs, plans])

  const selectedProgress = selectedJob
    ? jobTransferProgress(selectedJob, transfers)
    : null
  const selectedEta = selectedJob ? etaSeconds(selectedJob, selectedPlan, simT) : null
  const selectedTransfers = selectedJob
    ? transfers.filter((t) => t.job_id === selectedJob.id)
    : []

  return (
    <div className="app">
      <header className="top">
        <div>
          <div className="brand">Space Data Centers</div>
          <p className="caption">
            Place a batch job on Earth or orbital compute. Orbits use real TLEs; prices and
            bandwidth are simulated.
          </p>
        </div>
        <div className="top-right">
          <div className="transport">
            <button
              type="button"
              data-action="play"
              className={settings?.playing ? 'active' : 'primary'}
              onClick={play}
            >
              Play
            </button>
            <button
              type="button"
              data-action="pause"
              className={!settings?.playing ? 'active' : ''}
              onClick={pause}
            >
              Pause
            </button>
            <label className="speed">
              Speed
              <input
                type="range"
                min={1}
                max={100}
                value={settings?.speed ?? 10}
                onChange={(e) => {
                  const speed = Number(e.target.value)
                  setSettings((s) => (s ? { ...s, speed } : s))
                  api.patchSettings({ speed }).catch(() => undefined)
                }}
              />
              <span>{fmt(settings?.speed, 0)}×</span>
            </label>
          </div>
          <span className="muted" style={{ fontSize: '0.88rem' }}>
            t = {fmt(settings?.t, 0)} s
          </span>
        </div>
      </header>

      <div className="layout">
        <section className="globe-panel">
          <Globe
            nodes={nodes}
            stations={stations}
            links={links}
            transfers={transfers}
            selectedPlan={selectedPlan}
            selectedId={selectedId}
            onSelect={setSelectedId}
            simT={settings?.t}
          />
          <div className="globe-foot">
            <span>
              {settings?.scenario_id ? `${settings.scenario_id} · ` : ''}
              {orbitalMeta || 'Loading satellites…'}
            </span>
            <span className="globe-foot-links">
              <a href="http://127.0.0.1:43124/operator/" target="_blank" rel="noreferrer">
                Operator
              </a>
              <a href="http://127.0.0.1:43124/docs" target="_blank" rel="noreferrer">
                Docs
              </a>
            </span>
          </div>
        </section>

        <aside className="side">
          <section className="section">
            <h2>New job</h2>
            <div className="form-grid">
              <label>
                Input (MB)
                <input
                  type="number"
                  min={0.1}
                  step={0.1}
                  value={form.input_mb}
                  onChange={(e) => setForm({ ...form, input_mb: Number(e.target.value) })}
                />
              </label>
              <label>
                Output (MB)
                <input
                  type="number"
                  min={0.1}
                  step={0.1}
                  value={form.output_mb}
                  onChange={(e) => setForm({ ...form, output_mb: Number(e.target.value) })}
                />
              </label>
              <label>
                Work units
                <input
                  type="number"
                  value={form.work}
                  onChange={(e) => setForm({ ...form, work: Number(e.target.value) })}
                />
              </label>
              <label>
                Deadline (s)
                <input
                  type="number"
                  value={form.deadline_offset}
                  onChange={(e) =>
                    setForm({ ...form, deadline_offset: Number(e.target.value) })
                  }
                />
              </label>
              <label>
                Source
                <select
                  value={form.source_id}
                  onChange={(e) => setForm({ ...form, source_id: e.target.value })}
                >
                  {stations.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Destination
                <select
                  value={form.destination_id}
                  onChange={(e) => setForm({ ...form, destination_id: e.target.value })}
                >
                  {stations.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <button
              type="button"
              className="primary wide"
              disabled={busy}
              onClick={submit}
            >
              Submit
            </button>

            <button
              type="button"
              className="more"
              onClick={() => setShowMore((v) => !v)}
            >
              {showMore ? 'Hide examples' : 'Examples'}
            </button>
            {showMore && (
              <div className="more-row">
                <button
                  type="button"
                  data-action="thesis-a"
                  disabled={busy}
                  onClick={() => thesis('a')}
                >
                  Case A: cheap loses
                </button>
                <button
                  type="button"
                  data-action="thesis-b"
                  disabled={busy}
                  onClick={() => thesis('b')}
                >
                  Case B: cheap wins
                </button>
              </div>
            )}
          </section>

          <section className="section">
            <h2>Jobs</h2>
            <div className="summary-row" aria-label="Job summary">
              <div>
                <span className="summary-label">Done</span>
                <span className="summary-value">
                  {summary.jobsDone}
                  <span className="summary-of">/{summary.jobsTotal}</span>
                </span>
              </div>
              <div>
                <span className="summary-label">On time</span>
                <span className="summary-value">
                  {summary.onTimePct == null ? '—' : `${fmt(summary.onTimePct, 0)}%`}
                </span>
              </div>
              <div>
                <span className="summary-label">Cost vs baseline</span>
                <span className="summary-value">
                  {summary.totalCost == null
                    ? '—'
                    : summary.baselineCost == null
                      ? `$${fmt(summary.totalCost, 3)}`
                      : `$${fmt(summary.totalCost, 3)} / $${fmt(summary.baselineCost, 3)}`}
                </span>
              </div>
            </div>
            <div className="job-list">
              {sortedJobs.length === 0 && <p className="empty">No jobs yet.</p>}
              {sortedJobs.map((j) => {
                const pct = jobTransferProgress(j, transfers)
                return (
                  <button
                    type="button"
                    key={j.id}
                    className={`job-item ${selectedJobId === j.id ? 'active' : ''}`}
                    onClick={() => selectJob(j, j.plan_id ? plans[j.plan_id] : null)}
                  >
                    <div className="job-top">
                      <span>{j.id.slice(0, 12)}</span>
                      <span className={`state state-${j.state}`}>
                        {STAGE_LABEL[j.state] || j.state}
                      </span>
                    </div>
                    <div className="muted" style={{ fontSize: '0.85rem' }}>
                      {j.assigned_node_id || 'unassigned'} · {bytes(j.input_bytes)}
                      {pct != null ? ` · ${fmt(pct, 0)}%` : ''}
                    </div>
                    {pct != null && j.state !== 'completed' && j.state !== 'failed' && (
                      <div className="job-bar" aria-hidden>
                        <div className="job-bar-fill" style={{ width: `${Math.min(100, pct)}%` }} />
                      </div>
                    )}
                  </button>
                )
              })}
            </div>

            {!selectedJob && <p className="empty">Select a job to see its plan.</p>}
            {selectedJob && (
              <div className="detail">
                <p>
                  <strong>{selectedJob.assigned_node_id || 'Unassigned'}</strong>
                  {' · '}
                  {STAGE_LABEL[selectedJob.state] || selectedJob.state}
                </p>
                <div className="progress-block">
                  <div className="progress-head">
                    <span>Progress</span>
                    <span>
                      {selectedProgress == null ? '—' : `${fmt(selectedProgress, 0)}%`}
                      {selectedEta != null ? ` · ETA ${fmt(selectedEta, 0)} s` : ''}
                    </span>
                  </div>
                  <div className="job-bar tall">
                    <div
                      className="job-bar-fill"
                      style={{ width: `${Math.min(100, selectedProgress ?? 0)}%` }}
                    />
                  </div>
                  {selectedTransfers.length > 0 && (
                    <ul className="xfer-list">
                      {selectedTransfers.map((tr) => {
                        const p = tr.bytes_total
                          ? (tr.bytes_sent / tr.bytes_total) * 100
                          : 0
                        return (
                          <li key={tr.id}>
                            <span>
                              {tr.direction}: {tr.from_id} → {tr.to_id}
                            </span>
                            <span>
                              {fmt(p, 0)}% · {tr.state}
                            </span>
                          </li>
                        )
                      })}
                    </ul>
                  )}
                </div>
                <dl>
                  <dt>Stage</dt>
                  <dd>{STAGE_LABEL[selectedJob.state] || selectedJob.state}</dd>
                  <dt>Transferred</dt>
                  <dd>
                    {selectedProgress == null ? '—' : `${fmt(selectedProgress, 0)}%`}
                  </dd>
                  <dt>ETA</dt>
                  <dd>
                    {selectedJob.state === 'completed'
                      ? 'Done'
                      : selectedEta != null
                        ? `${fmt(selectedEta, 0)} s`
                        : '—'}
                  </dd>
                  <dt>Estimated finish</dt>
                  <dd>
                    {selectedPlan
                      ? `${fmt(selectedPlan.estimated_completion, 1)} s`
                      : '—'}
                  </dd>
                  <dt>Simulated finish</dt>
                  <dd>
                    {selectedJob.actual_completion != null
                      ? `${fmt(selectedJob.actual_completion, 1)} s`
                      : selectedJob.state === 'completed'
                        ? '…'
                        : '—'}
                  </dd>
                  <dt>Estimated cost</dt>
                  <dd>
                    {selectedPlan ? `$${fmt(selectedPlan.estimated_cost, 4)}` : '—'}
                  </dd>
                  <dt>Simulated cost</dt>
                  <dd>
                    {selectedJob.actual_cost != null
                      ? `$${fmt(selectedJob.actual_cost, 4)}`
                      : selectedJob.state === 'completed' && selectedPlan
                        ? `$${fmt(selectedPlan.estimated_cost, 4)}`
                        : '—'}
                  </dd>
                  <dt>Deadline</dt>
                  <dd>
                    {selectedJob.deadline_at != null
                      ? `${fmt(selectedJob.deadline_at, 0)} s`
                      : '—'}
                  </dd>
                </dl>
                {selectedPlan && (
                  <>
                    <p className="muted" style={{ marginTop: '0.65rem' }}>
                      Route
                    </p>
                    <ol className="routes">
                      {selectedPlan.input_route.map((h, i) => (
                        <li key={`in-${i}`}>
                          {h.from_id} → {h.to_id}
                        </li>
                      ))}
                      <li>Compute on {selectedPlan.compute_node_id}</li>
                      {selectedPlan.output_route.map((h, i) => (
                        <li key={`out-${i}`}>
                          {h.from_id} → {h.to_id}
                        </li>
                      ))}
                    </ol>
                  </>
                )}
                {bc && (
                  <div className="baseline">
                    <p>
                      Compared with cheapest node (<strong>{bc.baseline_node_id}</strong>
                      {bc.baseline_feasible
                        ? `: $${fmt(bc.baseline_cost, 4)}, finish ${fmt(bc.baseline_completion, 0)} s`
                        : ', infeasible'}
                      ).
                    </p>
                    {bc.reason_codes.length > 0 && (
                      <ul>
                        {bc.reason_codes.map((r) => (
                          <li key={r}>{r.replace(/_/g, ' ')}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}
              </div>
            )}

            {selectedOrbital && powerThermal && (
              <div className="power-block">
                <p className="power-head">
                  Power / thermal · <strong>{selectedOrbital.id}</strong>
                </p>
                <dl className="power-dl">
                  <dt>Sun</dt>
                  <dd>{powerThermal.eclipse ? 'Eclipse' : powerThermal.sunlit ? 'Sunlit' : '—'}</dd>
                  <dt>Battery</dt>
                  <dd>{fmt(powerThermal.battery_soc * 100, 0)}%</dd>
                  <dt>Temp</dt>
                  <dd>{fmt(powerThermal.temperature_k, 0)} K</dd>
                  <dt>Rate factor</dt>
                  <dd>{fmt(powerThermal.effective_rate_factor, 2)}</dd>
                </dl>
                <p className="power-note">
                  {powerThermal.notes || 'Assumption-labelled model; not spacecraft telemetry.'}
                </p>
              </div>
            )}

            <button
              type="button"
              className="more"
              onClick={() => setShowAdvanced((v) => !v)}
            >
              {showAdvanced ? 'Hide advanced' : 'Advanced'}
            </button>
            {showAdvanced && (
              <div className="advanced">
                <label className="adv-label">
                  Scenario
                  <select
                    value={settings?.scenario_id || 'mvp-thesis'}
                    disabled={busy || evalBusy}
                    onChange={(e) => void switchScenario(e.target.value)}
                  >
                    {(scenarios.length
                      ? scenarios
                      : [
                          { id: 'mvp-thesis', label: 'MVP thesis', description: '' },
                          { id: 'leo-constellation', label: 'LEO constellation', description: '' },
                        ]
                    ).map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.id}
                      </option>
                    ))}
                  </select>
                </label>
                <p className="muted adv-hint">
                  {scenarios.find((s) => s.id === settings?.scenario_id)?.description ||
                    'mvp-thesis for Case A/B; leo-constellation for a larger demo.'}
                </p>

                <div className="adv-row">
                  <button type="button" disabled={busy || evalBusy} onClick={() => void runEval()}>
                    {evalBusy ? 'Evaluating…' : 'Run evaluation'}
                  </button>
                  <button
                    type="button"
                    disabled={busy || evalBusy}
                    onClick={() =>
                      run(async () => {
                        setSelectedJobId(null)
                        selectedJobIdRef.current = null
                        setEvalReport(null)
                        await api.reset()
                      })
                    }
                  >
                    Reset simulation
                  </button>
                </div>
                {evalErr && <p className="adv-err">{evalErr}</p>}
                {evalReport && (
                  <div className="eval-report">
                    <p className="muted" style={{ margin: '0 0 0.35rem', fontSize: '0.85rem' }}>
                      Eval {evalReport.id} · {evalReport.scenario_id} · seed {evalReport.seed}
                    </p>
                    <table>
                      <thead>
                        <tr>
                          <th>Policy</th>
                          <th>On time</th>
                          <th>Cost</th>
                          <th>Wait</th>
                        </tr>
                      </thead>
                      <tbody>
                        {evalReport.policies.map((p) => (
                          <tr key={p.policy}>
                            <td>{p.policy}</td>
                            <td>{fmt(p.deadline_hit_rate * 100, 0)}%</td>
                            <td>${fmt(p.mean_cost, 3)}</td>
                            <td>{fmt(p.mean_compute_wait_s, 0)} s</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {(() => {
                      const planner = evalReport.policies.find((p) => p.policy === 'planner')
                      const cheap = evalReport.policies.find((p) => p.policy === 'cheapest')
                      if (!planner || !cheap) return null
                      const ratio = cheap.mean_cost > 0 ? planner.mean_cost / cheap.mean_cost : null
                      return (
                        <p className="muted" style={{ margin: '0.4rem 0 0', fontSize: '0.85rem' }}>
                          Planner cost vs cheapest baseline:{' '}
                          {ratio == null ? '—' : `${fmt(ratio, 2)}×`}
                        </p>
                      )
                    })()}
                  </div>
                )}

                <p className="muted" style={{ margin: '0.7rem 0 0.35rem', fontSize: '0.88rem' }}>
                  Disrupt a link (simulated)
                </p>
                <select id="disrupt-link" defaultValue="">
                  <option value="" disabled>
                    Choose a link
                  </option>
                  {links.map((L) => (
                    <option key={L.id} value={L.id}>
                      {L.kind}: {L.endpoint_a} ↔ {L.endpoint_b}
                    </option>
                  ))}
                </select>
                <div className="more-row">
                  <button
                    type="button"
                    onClick={() => {
                      const el = document.getElementById('disrupt-link') as HTMLSelectElement
                      if (el?.value) run(() => api.disrupt(el.value, { down: true }))
                    }}
                  >
                    Force down
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      const el = document.getElementById('disrupt-link') as HTMLSelectElement
                      if (el?.value) run(() => api.clearDisrupt(el.value))
                    }}
                  >
                    Clear
                  </button>
                </div>
                <p className="adv-links">
                  <a href="http://127.0.0.1:43124/operator/" target="_blank" rel="noreferrer">
                    Operator console
                  </a>
                  {' · '}
                  <a href="http://127.0.0.1:43124/docs" target="_blank" rel="noreferrer">
                    API docs
                  </a>
                </p>
              </div>
            )}
          </section>

          <AskPanel onAfterAction={applySnapshot} />
        </aside>
      </div>
    </div>
  )
}
