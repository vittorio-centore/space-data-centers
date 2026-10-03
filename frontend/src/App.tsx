import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  api,
  connectWs,
  type BaselineComparison,
  type ComputeNode,
  type GroundStation,
  type Job,
  type LinkConfig,
  type Metrics,
  type Plan,
  type Settings,
  type SimEvent,
  type Transfer,
} from './api'
import Globe from './components/Globe'
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

export default function App() {
  const [nodes, setNodes] = useState<ComputeNode[]>([])
  const [stations, setStations] = useState<GroundStation[]>([])
  const [links, setLinks] = useState<LinkConfig[]>([])
  const [jobs, setJobs] = useState<Job[]>([])
  const [plans, setPlans] = useState<Record<string, Plan>>({})
  const [transfers, setTransfers] = useState<Transfer[]>([])
  const [settings, setSettings] = useState<Settings | null>(null)
  const [metrics, setMetrics] = useState<Metrics | null>(null)
  const [events, setEvents] = useState<SimEvent[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null)
  const [reality, setReality] = useState<Record<string, string>>({})
  const [orbitalMeta, setOrbitalMeta] = useState<string>('')
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('Connecting…')
  const [form, setForm] = useState({
    input_bytes: 5_000_000,
    output_bytes: 1_000_000,
    work: 200,
    deadline_offset: 3600,
    source_id: 'gs-ashburn',
    destination_id: 'gs-ashburn',
  })
  const refreshTimer = useRef<number | null>(null)
  const selectedJobIdRef = useRef<string | null>(null)
  selectedJobIdRef.current = selectedJobId

  const selectJob = useCallback((job: Job, plan?: Plan | null) => {
    setSelectedJobId(job.id)
    selectedJobIdRef.current = job.id
    const nodeId = plan?.compute_node_id || job.assigned_node_id
    if (nodeId) setSelectedId(nodeId)
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
    setReality(snap.reality)
    setMetrics(await api.metrics())
    // Auto-select newest job if nothing selected (e.g. job created via API)
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
    let ws: WebSocket | null = null
    let alive = true
    ;(async () => {
      try {
        await applySnapshot()
        const recs = await api.orbitalRecords()
        setOrbitalMeta(recs.map((r) => `${r.name} (NORAD ${r.norad_id})`).join(' · '))
        setStatus('Live')
        ws = connectWs((ev) => {
          if (!alive) return
          setEvents((prev) => [...prev.slice(-80), ev])
          if (ev.type === 'tick') {
            const positions = ev.payload.positions as Record<
              string,
              { lat: number; lon: number; alt_km: number }
            >
            const up = new Set(ev.payload.links_up as string[])
            setSettings((s) => (s ? { ...s, t: ev.t } : s))
            setNodes((ns) =>
              ns.map((n) =>
                positions[n.id] ? { ...n, position_lla: positions[n.id] } : n,
              ),
            )
            setLinks((ls) => ls.map((L) => ({ ...L, up: up.has(L.id) })))
          } else if (ev.type === 'plan_created') {
            const plan = ev.payload.plan as Plan
            const jobId = (ev.payload.job_id as string) || plan?.job_id
            if (plan) {
              setPlans((prev) => ({ ...prev, [plan.id]: plan }))
            }
            if (jobId) {
              setSelectedJobId(jobId)
              selectedJobIdRef.current = jobId
              if (plan?.compute_node_id) setSelectedId(plan.compute_node_id)
            }
            scheduleRefresh()
          } else if (ev.type === 'job_state') {
            const jobId = ev.payload.job_id as string
            const state = ev.payload.state as Job['state']
            setJobs((prev) => {
              const i = prev.findIndex((j) => j.id === jobId)
              if (i < 0) {
                scheduleRefresh()
                return prev
              }
              const next = prev.slice()
              next[i] = { ...next[i], state }
              return next
            })
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
              setSettings((s) =>
                s ? { ...s, playing: Boolean(ev.payload.playing) } : s,
              )
            }
            if (ev.payload.reset || ev.payload.seek) {
              scheduleRefresh()
            }
            api.metrics().then(setMetrics).catch(() => undefined)
          } else if (ev.type === 'link_up' || ev.type === 'link_down') {
            const id = ev.payload.link_id as string
            setLinks((ls) =>
              ls.map((L) => (L.id === id ? { ...L, up: ev.type === 'link_up' } : L)),
            )
          }
        })
        ws.onopen = () => setStatus('Live')
        ws.onclose = () => setStatus('WS disconnected')
      } catch (e) {
        setStatus(`Error: ${(e as Error).message}`)
      }
    })()
    const iv = setInterval(() => {
      api.metrics().then(setMetrics).catch(() => undefined)
    }, 4000)
    return () => {
      alive = false
      ws?.close()
      clearInterval(iv)
      if (refreshTimer.current != null) window.clearTimeout(refreshTimer.current)
    }
  }, [applySnapshot, scheduleRefresh])

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true)
    try {
      await fn()
      await applySnapshot()
      const recs = await api.orbitalRecords()
      setOrbitalMeta(recs.map((r) => `${r.name} (NORAD ${r.norad_id})`).join(' · '))
    } catch (e) {
      setStatus(`Error: ${(e as Error).message}`)
    } finally {
      setBusy(false)
    }
  }

  const play = () => {
    setSettings((s) => (s ? { ...s, playing: true } : s))
    api.play().catch((e) => setStatus(`Error: ${(e as Error).message}`))
  }

  const pause = () => {
    setSettings((s) => (s ? { ...s, playing: false } : s))
    api.pause().catch((e) => setStatus(`Error: ${(e as Error).message}`))
  }

  const stepOnce = () => {
    api.step()
      .then(() => applySnapshot())
      .catch((e) => setStatus(`Error: ${(e as Error).message}`))
  }

  const submit = () =>
    run(async () => {
      const t = settings?.t ?? 0
      const res = await api.submitJob({
        input_bytes: form.input_bytes,
        output_bytes: form.output_bytes,
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
  const selectedNode = nodes.find((n) => n.id === selectedId) || null
  const selectedStation = stations.find((s) => s.id === selectedId) || null

  const bc: BaselineComparison | undefined = selectedPlan?.baseline_comparison

  const [activeThesis, setActiveThesis] = useState<'a' | 'b' | null>(null)

  const runThesis = (c: 'a' | 'b') => {
    setActiveThesis(c)
    thesis(c)
  }

  return (
    <div className="app">
      <header className="top">
        <div className="brand-block">
          <div className="brand">Space Data Centers</div>
          <p className="tagline">
            Place batch jobs across Earth and orbital compute. Contact windows come from real
            TLEs — prices and bandwidth are simulated.
          </p>
        </div>
        <div className="top-meta">
          <span className="tag real">Real: TLE · SGP4 · contacts</span>
          <span className="tag sim">Sim: FLOPS · bandwidth · $</span>
          <span className="status">{status}</span>
        </div>
      </header>

      <div className="reality-strip">
        <div className="bit">
          <span className="tag real">Real</span>
          <strong>Ephemeris & elevation contacts</strong>
          <span>from cached CelesTrak TLEs</span>
        </div>
        <div className="bit">
          <span className="tag sim">Simulated</span>
          <strong>Compute rates, link Mbps, pricing</strong>
          <span>configured for the thesis demo</span>
        </div>
        <div className="bit">
          <span>Epoch</span>
          <strong>{settings?.epoch_utc?.slice(0, 19) || '—'}Z</strong>
        </div>
      </div>

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
          />
          <div className="globe-caption muted">
            <span>{orbitalMeta || 'Loading TLEs…'}</span>
            <span>
              White/amber tubes = selected plan · Gold pulse = active transfer
            </span>
          </div>
        </section>

        <aside className="side">
          <section className="panel controls">
            <h2>Simulation</h2>
            <div className="row">
              <button
                type="button"
                className={`primary ${settings?.playing ? 'active' : ''}`}
                onClick={play}
              >
                Play
              </button>
              <button
                type="button"
                className={!settings?.playing ? 'active' : ''}
                onClick={pause}
              >
                Pause
              </button>
              <button type="button" onClick={stepOnce}>
                Step
              </button>
              <button
                type="button"
                className="danger"
                disabled={busy}
                onClick={() =>
                  run(async () => {
                    setSelectedJobId(null)
                    selectedJobIdRef.current = null
                    setActiveThesis(null)
                    await api.reset()
                  })
                }
              >
                Reset
              </button>
            </div>
            <div className="stats-line">
              <span>t = {fmt(settings?.t, 0)} s</span>
              <span>step {settings?.sim_step_s ?? 5}s</span>
              <span className={settings?.playing ? 'playing-pill' : ''}>
                {settings?.playing ? 'playing' : 'paused'}
              </span>
            </div>
            <label className="field">
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
          </section>

          <section className="panel">
            <h2>Thesis demos</h2>
            <p className="muted small">
              Same job shape, different contact phasing. Seeks sim time automatically.
            </p>
            <div className="thesis-grid">
              <button
                type="button"
                className={`thesis-btn case-a ${activeThesis === 'a' ? 'active' : ''}`}
                disabled={busy}
                onClick={() => runThesis('a')}
              >
                <strong>Case A — cheap loses</strong>
                <span>
                  After an ISS pass, tight deadline → planner picks Earth; baseline ISS misses
                  contact.
                </span>
              </button>
              <button
                type="button"
                className={`thesis-btn case-b ${activeThesis === 'b' ? 'active' : ''}`}
                disabled={busy}
                onClick={() => runThesis('b')}
              >
                <strong>Case B — cheap wins</strong>
                <span>
                  Before the next pass → cheapest orbital meets the deadline at lowest cost.
                </span>
              </button>
            </div>
            {busy && <p className="muted small">Seeking contact window & placing…</p>}
          </section>

          <section className="panel">
            <h2>Submit job</h2>
            <div className="form-grid">
              <label>
                Input bytes
                <input
                  type="number"
                  value={form.input_bytes}
                  onChange={(e) => setForm({ ...form, input_bytes: Number(e.target.value) })}
                />
              </label>
              <label>
                Output bytes
                <input
                  type="number"
                  value={form.output_bytes}
                  onChange={(e) => setForm({ ...form, output_bytes: Number(e.target.value) })}
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
                Deadline (+s from now)
                <input
                  type="number"
                  value={form.deadline_offset}
                  onChange={(e) =>
                    setForm({ ...form, deadline_offset: Number(e.target.value) })
                  }
                />
              </label>
              <label>
                Source gateway
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
            <button type="button" className="primary wide" disabled={busy} onClick={submit}>
              Place & run image batch
            </button>
          </section>

          <section className="panel">
            <h2>Jobs</h2>
            <div className="job-list">
              {jobs.length === 0 && <p className="muted small">No jobs yet.</p>}
              {[...jobs]
                .sort((a, b) => b.submitted_at - a.submitted_at)
                .map((j) => (
                  <button
                    type="button"
                    key={j.id}
                    className={`job-item ${selectedJobId === j.id ? 'active' : ''}`}
                    onClick={() => selectJob(j, j.plan_id ? plans[j.plan_id] : null)}
                  >
                    <div className="job-top">
                      <strong>{j.id.slice(0, 14)}</strong>
                      <span className={`state state-${j.state}`}>{j.state}</span>
                    </div>
                    <div className="muted small">
                      {j.assigned_node_id || 'unassigned'} · {bytes(j.input_bytes)} in
                      {j.preset ? ` · ${j.preset}` : ''}
                    </div>
                  </button>
                ))}
            </div>
          </section>
        </aside>

        <aside className="side right">
          <section className="panel">
            <h2>Inspector</h2>
            {!selectedNode && !selectedStation && !selectedJob && (
              <p className="muted small">Select a job, node, or ground station.</p>
            )}
            {selectedJob && (
              <div className="inspect">
                <h3>Job {selectedJob.id}</h3>
                <p>
                  State <strong>{selectedJob.state}</strong>
                  {selectedJob.fail_reason ? ` — ${selectedJob.fail_reason}` : ''}
                </p>
                <div className="kv">
                  <div>
                    <span className="lbl">Assigned</span>
                    <strong>{selectedJob.assigned_node_id || '—'}</strong>
                  </div>
                  <div>
                    <span className="lbl">Deadline</span>
                    <strong>{fmt(selectedJob.deadline_at ?? undefined, 0)}s</strong>
                  </div>
                  <div>
                    <span className="lbl">Est. complete</span>
                    <strong>{fmt(selectedPlan?.estimated_completion, 1)}s</strong>
                  </div>
                  <div>
                    <span className="lbl">Actual</span>
                    <strong>{fmt(selectedJob.actual_completion ?? undefined, 1)}s</strong>
                  </div>
                  <div>
                    <span className="lbl">Est. cost</span>
                    <strong>${fmt(selectedPlan?.estimated_cost, 4)}</strong>
                  </div>
                  <div>
                    <span className="lbl">Workload</span>
                    <strong>{bytes(selectedJob.input_bytes)} → batch</strong>
                  </div>
                </div>
                {selectedPlan && (
                  <>
                    <h3>Routes</h3>
                    <ol className="hops">
                      {selectedPlan.input_route.map((h, i) => (
                        <li key={`in-${i}`}>
                          IN {h.from_id} → {h.to_id} @ {fmt(h.window_start, 0)}–
                          {fmt(h.window_end, 0)}s
                        </li>
                      ))}
                      <li>
                        COMPUTE {selectedPlan.compute_node_id}{' '}
                        {fmt(selectedPlan.compute_start, 0)}–{fmt(selectedPlan.compute_end, 0)}s
                      </li>
                      {selectedPlan.output_route.map((h, i) => (
                        <li key={`out-${i}`}>
                          OUT {h.from_id} → {h.to_id} @ {fmt(h.window_start, 0)}–
                          {fmt(h.window_end, 0)}s
                        </li>
                      ))}
                    </ol>
                  </>
                )}
                {bc && (
                  <div className="baseline">
                    <h3>vs cheapest-node baseline</h3>
                    <div className="kv">
                      <div>
                        <span className="lbl">Chosen</span>
                        <strong>
                          {bc.chosen_node_id}
                          <br />${fmt(bc.chosen_cost, 4)} / {fmt(bc.chosen_completion, 0)}s
                        </strong>
                      </div>
                      <div>
                        <span className="lbl">Baseline</span>
                        <strong>
                          {bc.baseline_node_id}
                          <br />
                          {bc.baseline_feasible
                            ? `$${fmt(bc.baseline_cost, 4)} / ${fmt(bc.baseline_completion, 0)}s`
                            : 'infeasible'}
                        </strong>
                      </div>
                    </div>
                    <div className="reasons">
                      {bc.reason_codes.map((r) => (
                        <span
                          key={r}
                          className={`tag ${r.includes('deadline') || r.includes('misses') ? 'sim' : ''}`}
                        >
                          {r}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                {selectedJob.state !== 'completed' &&
                  selectedJob.state !== 'failed' &&
                  selectedJob.state !== 'canceled' && (
                    <div className="row" style={{ marginTop: '0.55rem' }}>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => run(() => api.replanJob(selectedJob.id))}
                      >
                        Replan routes
                      </button>
                      <button
                        type="button"
                        className="danger"
                        disabled={busy}
                        onClick={() => run(() => api.cancelJob(selectedJob.id))}
                      >
                        Cancel
                      </button>
                    </div>
                  )}
              </div>
            )}
            {selectedNode && (
              <div className="inspect">
                <h3>{selectedNode.name}</h3>
                <p>
                  {selectedNode.kind} · {selectedNode.compute_rate} work/s · $
                  {selectedNode.price_per_work}/work
                </p>
                <p className="muted small">
                  <span className="tag sim">sim</span> pricing & capacity
                  {selectedNode.kind === 'orbital' ? (
                    <>
                      {' '}
                      · <span className="tag real">real</span> TLE/SGP4 position
                    </>
                  ) : (
                    <> · configured site</>
                  )}
                </p>
              </div>
            )}
            {selectedStation && (
              <div className="inspect">
                <h3>{selectedStation.name}</h3>
                <p className="muted small">
                  {selectedStation.lat.toFixed(2)}°, {selectedStation.lon.toFixed(2)}° ·
                  configured site · contacts from real geometry + elevation rules
                </p>
              </div>
            )}
          </section>

          <section className="panel">
            <h2>Disrupt link</h2>
            <p className="muted small">Simulated outage / throttle — does not change orbits.</p>
            <select id="disrupt-link" defaultValue="">
              <option value="" disabled>
                Select link
              </option>
              {links.map((L) => (
                <option key={L.id} value={L.id}>
                  {L.kind} · {L.endpoint_a.replace(/^(gs-|orbital-|earth-)/, '')}↔
                  {L.endpoint_b.replace(/^(gs-|orbital-|earth-)/, '')} {L.up ? 'UP' : 'DOWN'}
                </option>
              ))}
            </select>
            <div className="row" style={{ marginTop: '0.45rem' }}>
              <button
                type="button"
                className="danger"
                disabled={busy}
                onClick={() => {
                  const el = document.getElementById('disrupt-link') as HTMLSelectElement
                  if (!el.value) return
                  run(() => api.disrupt(el.value, { down: true }))
                }}
              >
                Force down
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  const el = document.getElementById('disrupt-link') as HTMLSelectElement
                  if (!el.value) return
                  run(() => api.disrupt(el.value, { down: false, bandwidth_factor: 0.2 }))
                }}
              >
                20% bandwidth
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  const el = document.getElementById('disrupt-link') as HTMLSelectElement
                  if (!el.value) return
                  run(() => api.clearDisrupt(el.value))
                }}
              >
                Clear
              </button>
            </div>
          </section>

          <section className="panel">
            <h2>Metrics</h2>
            <div className="metrics">
              <div>
                <span className="lbl">Links up</span>
                <strong>
                  {metrics?.links_up ?? 0}/{metrics?.links_total ?? 0}
                </strong>
              </div>
              <div>
                <span className="lbl">Active xfers</span>
                <strong>{metrics?.active_transfers ?? 0}</strong>
              </div>
              <div>
                <span className="lbl">Mean delay</span>
                <strong>{fmt(metrics?.mean_completion_delay_s, 1)}s</strong>
              </div>
              <div>
                <span className="lbl">Cost Δ vs baseline</span>
                <strong>${fmt(metrics?.mean_cost_vs_baseline, 4)}</strong>
              </div>
            </div>
            <div className="state-counts">
              {Object.entries(metrics?.jobs_by_state || {}).map(([k, v]) => (
                <span key={k} className="tag">
                  {k}: {v}
                </span>
              ))}
            </div>
            <p className="muted small" style={{ marginTop: '0.55rem' }}>
              {reality.ephemeris || 'tle'} · {reality.contacts || 'contacts'} ·{' '}
              {reality.compute_capacity_pricing || 'sim compute'}
            </p>
          </section>

          <section className="panel events">
            <h2>Timeline</h2>
            <ul>
              {events
                .slice()
                .reverse()
                .slice(0, 28)
                .map((ev) => (
                  <li key={ev.id}>
                    <span className="t">{fmt(ev.t, 0)}s</span>
                    <span className="ty">{ev.type}</span>
                  </li>
                ))}
              {events.length === 0 && (
                <li>
                  <span className="t">—</span>
                  <span className="ty muted">Waiting for events…</span>
                </li>
              )}
            </ul>
          </section>
        </aside>
      </div>
    </div>
  )
}
