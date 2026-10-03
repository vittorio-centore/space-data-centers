import { Canvas, useFrame } from '@react-three/fiber'
import { Html, Line, OrbitControls } from '@react-three/drei'
import { useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'
import type { ComputeNode, GroundStation, LinkConfig, Plan, Transfer } from '../api'

const R_EARTH = 1
const COLORS = {
  ocean: '#9eb6c4',
  land: '#b7c4a8',
  station: '#3d6e8c',
  earthNode: '#8a6a2f',
  orbitalCheap: '#2f6f5e',
  orbitalAlt: '#6b5b4a',
  linkUp: '#5a8a7a',
  linkActive: '#a67c2d',
  linkPaused: '#9b3b3b',
  routeIn: '#2c4a5e',
  routeOut: '#7a6230',
  isl: '#6a8490',
  stars: '#d9e2e8',
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
  ctx.fillStyle = COLORS.ocean
  ctx.fillRect(0, 0, size, size)

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
    grd.addColorStop(0, 'rgba(140, 158, 120, 0.95)')
    grd.addColorStop(0.7, 'rgba(155, 170, 140, 0.55)')
    grd.addColorStop(1, 'rgba(158, 182, 196, 0)')
    ctx.fillStyle = grd
    ctx.beginPath()
    ctx.ellipse(x * size, y * size, rx * size, ry * size, 0, 0, Math.PI * 2)
    ctx.fill()
  }

  ctx.strokeStyle = 'rgba(60, 80, 90, 0.08)'
  ctx.lineWidth = 1
  for (let i = 1; i < 12; i++) {
    const y = (i / 12) * size
    ctx.beginPath()
    ctx.moveTo(0, y)
    ctx.lineTo(size, y)
    ctx.stroke()
  }

  const tex = new THREE.CanvasTexture(canvas)
  tex.colorSpace = THREE.SRGBColorSpace
  return tex
}

function Earth() {
  const tex = useMemo(() => makeEarthTexture(), [])
  return (
    <mesh>
      <sphereGeometry args={[R_EARTH, 64, 64]} />
      <meshStandardMaterial map={tex} roughness={0.95} metalness={0} />
    </mesh>
  )
}

function MarkerLabel({ text }: { text: string }) {
  return (
    <Html
      distanceFactor={7}
      center
      pointerEvents="none"
      zIndexRange={[1, 0]}
      style={{ pointerEvents: 'none' }}
    >
      <div className="globe-label" style={{ pointerEvents: 'none' }}>
        {text}
      </div>
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
  return (
    <group position={pos}>
      <mesh
        onClick={(e) => {
          e.stopPropagation()
          onSelect(station.id)
        }}
      >
        <sphereGeometry args={[selected ? 0.028 : 0.02, 16, 16]} />
        <meshStandardMaterial color={selected ? COLORS.earthNode : COLORS.station} />
      </mesh>
      {selected && (
        <group position={[0, 0.045, 0]}>
          <MarkerLabel text={short} />
        </group>
      )}
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
          lineWidth={selected ? 1.4 : 0.8}
          transparent
          opacity={selected ? 0.5 : 0.22}
        />
      )}
      <group position={pos}>
        <mesh
          onClick={(e) => {
            e.stopPropagation()
            onSelect(node.id)
          }}
        >
          <sphereGeometry args={[selected ? 0.03 : 0.022, 16, 16]} />
          <meshStandardMaterial color={color} />
        </mesh>
        {selected && (
          <group position={[0, 0.05, 0]}>
            <MarkerLabel text={label} />
          </group>
        )}
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
        <boxGeometry args={[selected ? 0.036 : 0.028, selected ? 0.036 : 0.028, selected ? 0.036 : 0.028]} />
        <meshStandardMaterial color={COLORS.earthNode} />
      </mesh>
      {selected && (
        <group position={[0, 0.045, 0]}>
          <MarkerLabel text="Earth DC" />
        </group>
      )}
    </group>
  )
}

function LinkTube({
  a,
  b,
  color,
  opacity,
  radius,
}: {
  a: THREE.Vector3
  b: THREE.Vector3
  color: string
  opacity: number
  radius: number
}) {
  const curve = useMemo(() => {
    const mid = a.clone().add(b).multiplyScalar(0.5)
    const lift = Math.max(a.length(), b.length()) * (1.08 + a.distanceTo(b) * 0.08)
    mid.normalize().multiplyScalar(lift)
    return new THREE.QuadraticBezierCurve3(a, mid, b)
  }, [a.x, a.y, a.z, b.x, b.y, b.z])

  const geom = useMemo(() => new THREE.TubeGeometry(curve, 40, radius, 5, false), [curve, radius])
  return (
    <mesh geometry={geom}>
      <meshBasicMaterial color={color} transparent opacity={opacity} depthWrite={false} />
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
  const pulse = useRef(0)
  const mesh = useRef<THREE.Mesh>(null)
  useFrame((_, dt) => {
    pulse.current += dt
    if (mesh.current) {
      const s = 1 + Math.sin(pulse.current * 4) * 0.15
      mesh.current.scale.setScalar(s)
    }
  })
  return (
    <mesh ref={mesh} position={p}>
      <sphereGeometry args={[0.018, 12, 12]} />
      <meshStandardMaterial color={color} />
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
  const activeTransfers = transfers.filter((t) => t.state === 'active' || t.state === 'paused')
  const activeLinkIds = new Set(activeTransfers.map((t) => t.active_link_id))
  const routeIn = selectedPlan?.input_route ?? []
  const routeOut = selectedPlan?.output_route ?? []

  return (
    <>
      <color attach="background" args={['#e7eef2']} />
      <ambientLight intensity={0.85} />
      <directionalLight position={[4, 3, 2]} intensity={0.85} color="#fff8ef" />
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

      {links
        .filter((L) => L.up && L.kind !== 'terrestrial')
        .map((L) => {
          const a = endpointPos(L.endpoint_a, nodes, stations)
          const b = endpointPos(L.endpoint_b, nodes, stations)
          if (!a || !b) return null
          const active = activeLinkIds.has(L.id)
          return (
            <LinkTube
              key={L.id}
              a={a}
              b={b}
              color={active ? COLORS.linkActive : L.kind === 'isl' ? COLORS.isl : COLORS.linkUp}
              opacity={active ? 0.75 : 0.28}
              radius={active ? 0.009 : 0.004}
            />
          )
        })}

      {routeIn.map((h, i) => {
        const a = endpointPos(h.from_id, nodes, stations)
        const b = endpointPos(h.to_id, nodes, stations)
        if (!a || !b) return null
        return (
          <LinkTube key={`in-${i}`} a={a} b={b} color={COLORS.routeIn} opacity={0.55} radius={0.007} />
        )
      })}
      {routeOut.map((h, i) => {
        const a = endpointPos(h.from_id, nodes, stations)
        const b = endpointPos(h.to_id, nodes, stations)
        if (!a || !b) return null
        return (
          <LinkTube key={`out-${i}`} a={a} b={b} color={COLORS.routeOut} opacity={0.5} radius={0.007} />
        )
      })}

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

      <OrbitControls enablePan={false} minDistance={2.2} maxDistance={6.5} />
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

  return (
    <div className="globe-wrap">
      <Canvas camera={{ position: [0, 1.1, 3.2], fov: 42 }} dpr={[1, 1.75]}>
        <Scene {...props} trails={trails} />
      </Canvas>
    </div>
  )
}
