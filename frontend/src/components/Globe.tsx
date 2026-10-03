import { Canvas, useFrame } from '@react-three/fiber'
import { Html, Line, OrbitControls, Stars } from '@react-three/drei'
import { useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'
import type { ComputeNode, GroundStation, LinkConfig, Plan, Transfer } from '../api'

const R_EARTH = 1
const COLORS = {
  ocean: '#0c2436',
  land: '#1e4a3a',
  grid: '#2a6b5a',
  station: '#6ec1ff',
  earthNode: '#f0b429',
  orbitalCheap: '#3ecf8e',
  orbitalAlt: '#d4a05a',
  linkUp: '#3a9b7a',
  linkActive: '#ffc857',
  linkPaused: '#ff8b6a',
  routeIn: '#e8f4ff',
  routeOut: '#f0d08a',
  isl: '#7eb8c9',
}

function latLonToVec(lat: number, lon: number, radius: number) {
  const phi = ((90 - lat) * Math.PI) / 180
  const theta = ((lon + 180) * Math.PI) / 180
  return new THREE.Vector3(
    -radius * Math.sin(phi) * Math.cos(theta),
    radius * Math.cos(phi),
    radius * Math.sin(phi) * Math.sin(theta),
  )
}

function makeEarthTexture() {
  const size = 1024
  const canvas = document.createElement('canvas')
  canvas.width = size
  canvas.height = size
  const ctx = canvas.getContext('2d')!
  // Ocean base
  const g = ctx.createLinearGradient(0, 0, 0, size)
  g.addColorStop(0, '#0a1c2c')
  g.addColorStop(0.5, '#123248')
  g.addColorStop(1, '#0a1c2c')
  ctx.fillStyle = g
  ctx.fillRect(0, 0, size, size)

  // Soft land masses (stylized, not political)
  const blobs = [
    [0.18, 0.32, 0.14, 0.22],
    [0.42, 0.28, 0.1, 0.16],
    [0.55, 0.45, 0.22, 0.14],
    [0.78, 0.35, 0.12, 0.2],
    [0.3, 0.62, 0.16, 0.12],
    [0.68, 0.68, 0.18, 0.1],
    [0.12, 0.55, 0.08, 0.18],
  ]
  for (const [x, y, rx, ry] of blobs) {
    const grd = ctx.createRadialGradient(
      x * size,
      y * size,
      0,
      x * size,
      y * size,
      Math.max(rx, ry) * size,
    )
    grd.addColorStop(0, 'rgba(46, 110, 82, 0.95)')
    grd.addColorStop(0.55, 'rgba(30, 78, 58, 0.7)')
    grd.addColorStop(1, 'rgba(18, 50, 72, 0)')
    ctx.fillStyle = grd
    ctx.beginPath()
    ctx.ellipse(x * size, y * size, rx * size, ry * size, 0, 0, Math.PI * 2)
    ctx.fill()
  }

  // Latitude / longitude haze
  ctx.strokeStyle = 'rgba(120, 190, 170, 0.12)'
  ctx.lineWidth = 1
  for (let i = 1; i < 12; i++) {
    const y = (i / 12) * size
    ctx.beginPath()
    ctx.moveTo(0, y)
    ctx.lineTo(size, y)
    ctx.stroke()
  }
  for (let i = 1; i < 24; i++) {
    const x = (i / 24) * size
    ctx.beginPath()
    ctx.moveTo(x, 0)
    ctx.lineTo(x, size)
    ctx.stroke()
  }

  const tex = new THREE.CanvasTexture(canvas)
  tex.colorSpace = THREE.SRGBColorSpace
  tex.anisotropy = 4
  return tex
}

function Earth() {
  const tex = useMemo(() => makeEarthTexture(), [])
  return (
    <group>
      <mesh>
        <sphereGeometry args={[R_EARTH, 72, 72]} />
        <meshStandardMaterial map={tex} roughness={0.92} metalness={0.05} />
      </mesh>
      <mesh>
        <sphereGeometry args={[R_EARTH * 1.012, 48, 48]} />
        <meshBasicMaterial color="#4ecf9a" transparent opacity={0.05} wireframe />
      </mesh>
      <mesh>
        <sphereGeometry args={[R_EARTH * 1.03, 32, 32]} />
        <meshBasicMaterial color="#1a3a4a" transparent opacity={0.12} side={THREE.BackSide} />
      </mesh>
    </group>
  )
}

function MarkerLabel({ text, tone }: { text: string; tone: 'real' | 'sim' }) {
  return (
    <Html distanceFactor={6} style={{ pointerEvents: 'none' }} center>
      <div className={`globe-label globe-label-${tone}`}>{text}</div>
    </Html>
  )
}

function StationMarker({
  station,
  selected,
  onSelect,
}: {
  station: GroundStation
  selected: boolean
  onSelect: (id: string) => void
}) {
  const pos = latLonToVec(station.lat, station.lon, R_EARTH * 1.02)
  const short = station.name.split('(')[0].trim()
  const color = selected ? COLORS.earthNode : COLORS.station
  return (
    <group position={pos}>
      <mesh
        onClick={(e) => {
          e.stopPropagation()
          onSelect(station.id)
        }}
      >
        <coneGeometry args={[selected ? 0.028 : 0.02, selected ? 0.055 : 0.04, 5]} />
        <meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.45} />
      </mesh>
      <group position={[0, 0.05, 0]}>
        <MarkerLabel text={`${short} · configured site`} tone="sim" />
      </group>
    </group>
  )
}

function OrbitalMarker({
  node,
  selected,
  onSelect,
  trail,
}: {
  node: ComputeNode
  selected: boolean
  onSelect: (id: string) => void
  trail: THREE.Vector3[]
}) {
  const lla = node.position_lla
  const pulse = useRef(0)
  const ring = useRef<THREE.Mesh>(null)
  useFrame((_, dt) => {
    pulse.current += dt
    if (ring.current) {
      const s = 1 + Math.sin(pulse.current * 3) * 0.12
      ring.current.scale.setScalar(s)
    }
  })
  if (!lla) return null
  const r = R_EARTH + Math.max(0.06, (lla.alt_km || 400) / 6371)
  const pos = latLonToVec(lla.lat, lla.lon, r)
  const color = node.id.includes('cheap') ? COLORS.orbitalCheap : COLORS.orbitalAlt
  const label = node.name.replace('Orbital Node ', '')
  return (
    <group>
      {trail.length > 1 && (
        <Line
          points={trail}
          color={color}
          lineWidth={selected ? 1.6 : 0.9}
          transparent
          opacity={selected ? 0.55 : 0.28}
        />
      )}
      <group position={pos}>
        <mesh
          onClick={(e) => {
            e.stopPropagation()
            onSelect(node.id)
          }}
        >
          <octahedronGeometry args={[selected ? 0.032 : 0.024, 0]} />
          <meshStandardMaterial
            color={color}
            emissive={color}
            emissiveIntensity={selected ? 0.7 : 0.4}
            roughness={0.35}
          />
        </mesh>
        <mesh ref={ring} rotation={[Math.PI / 2, 0, 0]}>
          <ringGeometry args={[0.04, 0.052, 28]} />
          <meshBasicMaterial
            color={color}
            transparent
            opacity={selected ? 0.7 : 0.35}
            side={THREE.DoubleSide}
          />
        </mesh>
        <group position={[0, 0.06, 0]}>
          <MarkerLabel
            text={`${label} · $${node.price_per_work}/wu · sim $`}
            tone="sim"
          />
        </group>
      </group>
    </group>
  )
}

function EarthNodeMarker({
  node,
  selected,
  onSelect,
}: {
  node: ComputeNode
  selected: boolean
  onSelect: (id: string) => void
}) {
  const pos = latLonToVec(node.lat || 0, node.lon || 0, R_EARTH * 1.035)
  return (
    <group position={pos}>
      <mesh
        onClick={(e) => {
          e.stopPropagation()
          onSelect(node.id)
        }}
      >
        <boxGeometry args={[selected ? 0.04 : 0.03, selected ? 0.04 : 0.03, selected ? 0.04 : 0.03]} />
        <meshStandardMaterial
          color={COLORS.earthNode}
          emissive={COLORS.earthNode}
          emissiveIntensity={0.4}
        />
      </mesh>
      <group position={[0, 0.05, 0]}>
        <MarkerLabel text={`${node.name.split(' ')[0]} DC · sim $`} tone="sim" />
      </group>
    </group>
  )
}

function LinkTube({
  a,
  b,
  color,
  opacity,
  radius,
  dashed,
  speed = 0,
}: {
  a: THREE.Vector3
  b: THREE.Vector3
  color: string
  opacity: number
  radius: number
  dashed?: boolean
  speed?: number
}) {
  const curve = useMemo(() => {
    const mid = a.clone().add(b).multiplyScalar(0.5)
    const lift = Math.max(a.length(), b.length()) * (1.08 + a.distanceTo(b) * 0.08)
    mid.normalize().multiplyScalar(lift)
    return new THREE.QuadraticBezierCurve3(a, mid, b)
  }, [a.x, a.y, a.z, b.x, b.y, b.z])

  const geom = useMemo(() => {
    return new THREE.TubeGeometry(curve, 48, radius, 6, false)
  }, [curve, radius])

  const matRef = useRef<THREE.MeshBasicMaterial>(null)
  useFrame(() => {
    if (matRef.current && speed > 0 && dashed) {
      matRef.current.opacity =
        opacity * (0.55 + 0.45 * Math.sin(performance.now() * 0.006 * speed))
    }
  })

  return (
    <mesh geometry={geom}>
      <meshBasicMaterial
        ref={matRef}
        color={color}
        transparent
        opacity={opacity}
        depthWrite={false}
      />
    </mesh>
  )
}

function TransferPulse({
  a,
  b,
  progress,
  color,
}: {
  a: THREE.Vector3
  b: THREE.Vector3
  progress: number
  color: string
}) {
  const curve = useMemo(() => {
    const mid = a.clone().add(b).multiplyScalar(0.5)
    mid.normalize().multiplyScalar(Math.max(a.length(), b.length()) * 1.12)
    return new THREE.QuadraticBezierCurve3(a, mid, b)
  }, [a.x, a.y, a.z, b.x, b.y, b.z])
  const p = curve.getPoint(Math.min(0.98, Math.max(0.02, progress)))
  return (
    <mesh position={p}>
      <sphereGeometry args={[0.022, 12, 12]} />
      <meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.9} />
    </mesh>
  )
}

function endpointPos(
  id: string,
  nodes: ComputeNode[],
  stations: GroundStation[],
): THREE.Vector3 | null {
  const st = stations.find((s) => s.id === id)
  if (st) return latLonToVec(st.lat, st.lon, R_EARTH * 1.02)
  const n = nodes.find((x) => x.id === id)
  if (!n) return null
  if (n.kind === 'earth') return latLonToVec(n.lat || 0, n.lon || 0, R_EARTH * 1.035)
  if (!n.position_lla) return null
  const r = R_EARTH + Math.max(0.06, (n.position_lla.alt_km || 400) / 6371)
  return latLonToVec(n.position_lla.lat, n.position_lla.lon, r)
}

function buildTrail(history: { lat: number; lon: number; alt_km: number }[]): THREE.Vector3[] {
  return history.map((lla) => {
    const r = R_EARTH + Math.max(0.06, (lla.alt_km || 400) / 6371)
    return latLonToVec(lla.lat, lla.lon, r)
  })
}

function Scene({
  nodes,
  stations,
  links,
  transfers,
  selectedPlan,
  selectedId,
  onSelect,
  trails,
}: {
  nodes: ComputeNode[]
  stations: GroundStation[]
  links: LinkConfig[]
  transfers: Transfer[]
  selectedPlan: Plan | null
  selectedId: string | null
  onSelect: (id: string) => void
  trails: Record<string, { lat: number; lon: number; alt_km: number }[]>
}) {
  const activeTransfers = transfers.filter(
    (t) => t.state === 'active' || t.state === 'paused',
  )
  const activeLinkIds = new Set(activeTransfers.map((t) => t.active_link_id))

  const routeIn = selectedPlan?.input_route ?? []
  const routeOut = selectedPlan?.output_route ?? []

  return (
    <>
      <ambientLight intensity={0.45} />
      <directionalLight position={[5, 3, 2]} intensity={1.25} color="#fff2d8" />
      <directionalLight position={[-3, -1, -4]} intensity={0.25} color="#6ec1ff" />
      <Stars radius={90} depth={50} count={3200} factor={2.8} fade speed={0.25} />
      <Earth />

      {stations.map((s) => (
        <StationMarker
          key={s.id}
          station={s}
          selected={selectedId === s.id}
          onSelect={onSelect}
        />
      ))}
      {nodes.map((n) =>
        n.kind === 'earth' ? (
          <EarthNodeMarker
            key={n.id}
            node={n}
            selected={selectedId === n.id}
            onSelect={onSelect}
          />
        ) : (
          <OrbitalMarker
            key={n.id}
            node={n}
            selected={selectedId === n.id}
            onSelect={onSelect}
            trail={buildTrail(trails[n.id] || [])}
          />
        ),
      )}

      {/* Up links */}
      {links
        .filter((L) => L.up)
        .map((L) => {
          const a = endpointPos(L.endpoint_a, nodes, stations)
          const b = endpointPos(L.endpoint_b, nodes, stations)
          if (!a || !b) return null
          const active = activeLinkIds.has(L.id)
          const isTerrestrial = L.kind === 'terrestrial'
          if (isTerrestrial && !active) {
            return (
              <LinkTube
                key={L.id}
                a={a}
                b={b}
                color={COLORS.station}
                opacity={0.12}
                radius={0.003}
              />
            )
          }
          return (
            <LinkTube
              key={L.id}
              a={a}
              b={b}
              color={
                active
                  ? COLORS.linkActive
                  : L.kind === 'isl'
                    ? COLORS.isl
                    : COLORS.linkUp
              }
              opacity={active ? 0.85 : L.kind === 'isl' ? 0.28 : 0.4}
              radius={active ? 0.01 : 0.005}
              dashed={active}
              speed={active ? 1.4 : 0}
            />
          )
        })}

      {/* Selected plan routes */}
      {routeIn.map((h, i) => {
        const a = endpointPos(h.from_id, nodes, stations)
        const b = endpointPos(h.to_id, nodes, stations)
        if (!a || !b) return null
        return (
          <LinkTube
            key={`in-${i}`}
            a={a}
            b={b}
            color={COLORS.routeIn}
            opacity={0.7}
            radius={0.008}
          />
        )
      })}
      {routeOut.map((h, i) => {
        const a = endpointPos(h.from_id, nodes, stations)
        const b = endpointPos(h.to_id, nodes, stations)
        if (!a || !b) return null
        return (
          <LinkTube
            key={`out-${i}`}
            a={a}
            b={b}
            color={COLORS.routeOut}
            opacity={0.65}
            radius={0.008}
          />
        )
      })}

      {/* Transfer progress pulses */}
      {activeTransfers.map((tr) => {
        const a = endpointPos(tr.from_id, nodes, stations)
        const b = endpointPos(tr.to_id, nodes, stations)
        if (!a || !b || !tr.bytes_total) return null
        return (
          <TransferPulse
            key={tr.id}
            a={a}
            b={b}
            progress={tr.bytes_sent / tr.bytes_total}
            color={tr.state === 'paused' ? COLORS.linkPaused : COLORS.linkActive}
          />
        )
      })}

      <OrbitControls enablePan={false} minDistance={2.1} maxDistance={7} />
    </>
  )
}

export default function Globe(props: {
  nodes: ComputeNode[]
  stations: GroundStation[]
  links: LinkConfig[]
  transfers: Transfer[]
  selectedPlan: Plan | null
  selectedId: string | null
  onSelect: (id: string) => void
}) {
  const [trails, setTrails] = useState<
    Record<string, { lat: number; lon: number; alt_km: number }[]>
  >({})

  // Accumulate orbital trails from live positions
  useEffect(() => {
    setTrails((prev) => {
      const next = { ...prev }
      for (const n of props.nodes) {
        if (n.kind !== 'orbital' || !n.position_lla) continue
        const hist = (next[n.id] || []).slice()
        const last = hist[hist.length - 1]
        const p = n.position_lla
        if (
          !last ||
          Math.abs(last.lat - p.lat) > 0.05 ||
          Math.abs(last.lon - p.lon) > 0.05
        ) {
          hist.push({ ...p })
          if (hist.length > 90) hist.shift()
          next[n.id] = hist
        }
      }
      return next
    })
  }, [props.nodes])

  const activeCount = props.transfers.filter(
    (t) => t.state === 'active' || t.state === 'paused',
  ).length
  const upLinks = props.links.filter((L) => L.up && L.kind !== 'terrestrial').length

  return (
    <div className="globe-wrap">
      <Canvas camera={{ position: [0, 1.15, 3.15], fov: 42 }} dpr={[1, 1.75]}>
        <Scene {...props} trails={trails} />
      </Canvas>
      <div className="globe-legend">
        <span className="leg real">Orbit trails · real TLE/SGP4</span>
        <span className="leg sim">Node $ / bandwidth · simulated</span>
        <span className="leg">Links up {upLinks}</span>
        <span className="leg accent">Transfers {activeCount}</span>
        {props.selectedPlan && <span className="leg route">Route highlighted</span>}
      </div>
    </div>
  )
}
