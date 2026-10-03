import { useEffect, useMemo, useState } from 'react'
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

  const selectedPlan = useMemo(() => {
    if (!selectedJobId) return null
    const job = jobs.find((j) => j.id === selectedJobId)
    if (!job?.plan_id) return null
    return plans[job.plan_id] || null
  }, [selectedJobId, jobs, plans])

  const refresh = async () => {
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
    const recs = await api.orbitalRecords()
    setOrbitalMeta(
      recs.map((r) => `${r.name} (NORAD ${r.norad_id})`).join(' · '),
    )
  }

  useEffect(() => {
    let ws: WebSocket | null = null
    let alive = true
    ;(async () => {
      try {
        await refresh()
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
            setSettings((s) => (s ? { ...s, t: ev.t, playing: s.playing } : s))
            setNodes((ns) =>
              ns.map((n) =>
                positions[n.id] ? { ...n, position_lla: positions[n.id] } : n,
              ),
            )
            setLinks((ls) => ls.map((L) => ({ ...L, up: up.has(L.id) })))
          } else if (ev.type === 'job_state' || ev.type === 'plan_created') {
            refresh().catch(() => undefined)
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
    }
  }, [])

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true)
    try {
      await fn()
      await refresh()
    } catch (e) {
      setStatus(`Error: ${(e as Error).message}`)
    } finally {
      setBusy(false)
    }
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
      setSelectedJobId(res.job.id)
      if (res.plan) setSelectedId(res.plan.compute_node_id)
    })

  const thesis = (c: 'a' | 'b') =>
    run(async () => {
      const res = await api.runThesis(c)
      setSelectedJobId(res.job.id)
      if (res.plan) setSelectedId(res.plan.compute_node_id)
      await api.play()
    })

  const selectedJob = jobs.find((j) => j.id === selectedJobId) || null
  const selectedNode = nodes.find((n) => n.id === selectedId) || null
  const selectedStation = stations.find((s) => s.id === selectedId) || null

  const bc: BaselineComparison | undefined = selectedPlan?.baseline_comparison

  return (
    <div className="app">
      <header className="top">
        <div className="brand-block">
          <div className="brand">Space Data Centers</div>
          <p className="tagline">
            Placement planner for Earth & orbital compute — cheapest is not always best.
          </p>
        </div>
        <div className="top-meta">
          <span className="tag real">Ephemeris / contacts: real SGP4</span>
          <span className="tag sim">Compute / bandwidth / $: simulated</span>
          <span className="status">{status}</span>
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
          />
          <div className="globe-caption muted">
            {orbitalMeta || 'Loading TLEs…'}
          </div>
        </section>

        <aside className="side">
          <section className="card controls">
            <h2>Simulation</h2>
            <div className="row">
              <button className="primary" disabled={busy} onClick={() => run(() => api.play())}>
                Play
              </button>
              <button disabled={busy} onClick={() => run(() => api.pause())}>
                Pause
              </button>
              <button disabled={busy} onClick={() => run(() => api.step())}>
                Step
              </button>
              <button className="danger" disabled={busy} onClick={() => run(() => api.reset())}>
                Reset
              </button>
            </div>
            <div className="stats-line">
              <span>t = {fmt(settings?.t, 0)} s</span>
              <span>step {settings?.sim_step_s ?? 5}s</span>
              <span>{settings?.playing ? 'playing' : 'paused'}</span>
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

          <section className="card">
            <h2>Thesis demos</h2>
            <p className="muted small">
              Case A: next ISS contact too late → Earth wins. Case B: contact soon → cheap
              orbital wins.
            </p>
            <div className="row">
              <button disabled={busy} onClick={() => thesis('a')}>
                Case A — cheap loses
              </button>
              <button className="primary" disabled={busy} onClick={() => thesis('b')}>
                Case B — cheap wins
              </button>
            </div>
          </section>

          <section className="card">
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
                Deadline (+s)
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
            <button className="primary wide" disabled={busy} onClick={submit}>
              Place & run image batch
            </button>
          </section>

          <section className="card">
            <h2>Jobs</h2>
            <div className="job-list">
              {jobs.length === 0 && <p className="muted small">No jobs yet.</p>}
              {jobs.map((j) => (
                <button
                  key={j.id}
                  className={`job-item ${selectedJobId === j.id ? 'active' : ''}`}
                  onClick={() => {
                    setSelectedJobId(j.id)
                    if (j.assigned_node_id) setSelectedId(j.assigned_node_id)
                  }}
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
          <section className="card">
            <h2>Inspector</h2>
            {!selectedNode && !selectedStation && !selectedJob && (
              <p className="muted small">Select a node, station, or job.</p>
            )}
            {selectedJob && (
              <div className="inspect">
                <h3>Job {selectedJob.id}</h3>
                <p>
                  State <strong>{selectedJob.state}</strong>
                  {selectedJob.fail_reason ? ` — ${selectedJob.fail_reason}` : ''}
                </p>
                <p className="muted small">
                  Assigned {selectedJob.assigned_node_id} · deadline{' '}
                  {fmt(selectedJob.deadline_at ?? undefined, 0)}s
                </p>
                {selectedPlan && (
                  <>
                    <p>
                      Est. complete {fmt(selectedPlan.estimated_completion, 1)}s · cost $
                      {fmt(selectedPlan.estimated_cost, 4)}
                    </p>
                    <p>
                      Actual complete {fmt(selectedJob.actual_completion ?? undefined, 1)}s
                    </p>
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
                    <p>
                      Chosen <strong>{bc.chosen_node_id}</strong> $
                      {fmt(bc.chosen_cost, 4)} / {fmt(bc.chosen_completion, 0)}s
                    </p>
                    <p>
                      Baseline <strong>{bc.baseline_node_id}</strong>{' '}
                      {bc.baseline_feasible
                        ? `$${fmt(bc.baseline_cost, 4)} / ${fmt(bc.baseline_completion, 0)}s`
                        : 'infeasible'}
                    </p>
                    <div className="reasons">
                      {bc.reason_codes.map((r) => (
                        <span key={r} className="tag">
                          {r}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                {selectedJob.state !== 'completed' &&
                  selectedJob.state !== 'failed' &&
                  selectedJob.state !== 'canceled' && (
                    <div className="row">
                      <button
                        disabled={busy}
                        onClick={() => run(() => api.replanJob(selectedJob.id))}
                      >
                        Replan routes
                      </button>
                      <button
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
                  Pricing/capacity: simulated
                  {selectedNode.kind === 'orbital'
                    ? ' · position: real TLE/SGP4'
                    : ' · site: configured'}
                </p>
              </div>
            )}
            {selectedStation && (
              <div className="inspect">
                <h3>{selectedStation.name}</h3>
                <p className="muted small">
                  {selectedStation.lat.toFixed(2)}°, {selectedStation.lon.toFixed(2)}° ·
                  configured site · contacts computed from real geometry
                </p>
              </div>
            )}
          </section>

          <section className="card">
            <h2>Disrupt link</h2>
            <select
              id="disrupt-link"
              defaultValue=""
              onChange={() => undefined}
            >
              <option value="" disabled>
                Select link
              </option>
              {links.map((L) => (
                <option key={L.id} value={L.id}>
                  {L.id} ({L.kind}) {L.up ? 'UP' : 'DOWN'}
                </option>
              ))}
            </select>
            <div className="row">
              <button
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

          <section className="card">
            <h2>Metrics</h2>
            <div className="metrics">
              <div>
                <span className="muted">Links up</span>
                <strong>
                  {metrics?.links_up ?? 0}/{metrics?.links_total ?? 0}
                </strong>
              </div>
              <div>
                <span className="muted">Active xfers</span>
                <strong>{metrics?.active_transfers ?? 0}</strong>
              </div>
              <div>
                <span className="muted">Mean delay</span>
                <strong>{fmt(metrics?.mean_completion_delay_s, 1)}s</strong>
              </div>
              <div>
                <span className="muted">Cost Δ vs baseline</span>
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
            <p className="muted small reality-line">
              Reality: {reality.ephemeris || 'tle'} · {reality.contacts || 'contacts'} ·{' '}
              {reality.compute_capacity_pricing || 'sim compute'}
            </p>
          </section>

          <section className="card events">
            <h2>Timeline</h2>
            <ul>
              {events
                .slice()
                .reverse()
                .slice(0, 24)
                .map((ev) => (
                  <li key={ev.id}>
                    <span className="muted">{fmt(ev.t, 0)}s</span> {ev.type}
                  </li>
                ))}
            </ul>
          </section>
        </aside>
      </div>
    </div>
  )
}
