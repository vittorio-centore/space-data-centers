import { Canvas, useFrame, useLoader } from '@react-three/fiber'
import { Html, Line, OrbitControls } from '@react-three/drei'
import { Suspense, useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'
import { api, type ComputeNode, type GroundStation, type LinkConfig, type Plan, type Transfer } from '../api'

const R_EARTH = 1
const COLORS = {
  station: '#3a657c',
  earthNode: '#7a6230',
  orbital: '#2f6f5e',
  orbitalAlt: '#5c6b75',
  linkUp: '#5a8a7a',
  linkActive: '#a67c2d',
  linkPaused: '#9b3b3b',
  routeIn: '#2c4a5e',
  routeOut: '#7a6230',
  isl: '#7a909a',
  orbit: '#6a7d88',
}

/** Equirectangular Earth map; muted via material color for a calm look. */
const EARTH_TEX_URL =
  'https://cdn.jsdelivr.net/npm/three-globe@2.31.1/example/img/earth-blue-marble.jpg'

function latLonToVec(lat: number, lon: number, radius: number) {
  const phi = ((90 - lat) * Math.PI) / 180
  const theta = ((lon + 180) * Math.PI) / 180
  return new THREE.Vector3(
    -radius * Math.sin(phi) * Math.cos(theta),
    radius * Math.cos(phi),
    radius * Math.sin(phi) * Math.sin(theta),
  )
}

function OutlineEarth() {
  // Soft classic fallback if texture CDN fails
  const tex = useMemo(() => {
    const size = 1024
    const c = document.createElement('canvas')
    c.width = size
    c.height = size
    const ctx = c.getContext('2d')!
    ctx.fillStyle = '#a8c0d0'
    ctx.fillRect(0, 0, size, size)
    // Rough continent silhouettes (equirectangular-ish)
    const land = '#c5d0b8'
    ctx.fillStyle = land
    const polys: [number, number][][] = [
      // N America
      [[0.12, 0.22], [0.28, 0.18], [0.32, 0.32], [0.22, 0.42], [0.1, 0.38]],
      // S America
      [[0.28, 0.48], [0.34, 0.45], [0.36, 0.72], [0.28, 0.78], [0.24, 0.58]],
      // Europe / Africa
      [[0.48, 0.22], [0.58, 0.2], [0.6, 0.35], [0.52, 0.55], [0.48, 0.7], [0.44, 0.4]],
      // Asia
      [[0.58, 0.18], [0.85, 0.2], [0.88, 0.38], [0.7, 0.42], [0.58, 0.35]],
      // Australia
      [[0.78, 0.58], [0.9, 0.55], [0.92, 0.68], [0.8, 0.7]],
    ]
    for (const poly of polys) {
      ctx.beginPath()
      poly.forEach(([x, y], i) => {
        const X = x * size
        const Y = y * size
        if (i === 0) ctx.moveTo(X, Y)
        else ctx.lineTo(X, Y)
      })
      ctx.closePath()
      ctx.fill()
      ctx.strokeStyle = 'rgba(70, 90, 80, 0.25)'
      ctx.lineWidth = 1.2
      ctx.stroke()
    }
    const t = new THREE.CanvasTexture(c)
    t.colorSpace = THREE.SRGBColorSpace
    return t
  }, [])
  return (
    <mesh>
      <sphereGeometry args={[R_EARTH, 64, 64]} />
      <meshStandardMaterial map={tex} roughness={0.92} metalness={0} color="#e8eef2" />
    </mesh>
  )
}

function TexturedEarth() {
  const tex = useLoader(THREE.TextureLoader, EARTH_TEX_URL)
  tex.colorSpace = THREE.SRGBColorSpace
  tex.anisotropy = 4
  return (
    <mesh>
      <sphereGeometry args={[R_EARTH, 72, 72]} />
      <meshStandardMaterial
        map={tex}
        roughness={0.92}
        metalness={0}
        color="#eef3f6"
      />
    </mesh>
  )
}

function Earth() {
  return (
    <Suspense fallback={<OutlineEarth />}>
      <TexturedEarth />
    </Suspense>
  )
}

function MarkerLabel({ text }: { text: string }) {
  return (
    <Html
      distanceFactor={32}
      center
      pointerEvents="none"
      zIndexRange={[1, 0]}
      style={{ pointerEvents: 'none', transform: 'translate3d(0,0,0)' }}
    >
      <div
        className="globe-label"
        style={{
          pointerEvents: 'none',
          fontSize: '9px',
          padding: '1px 5px',
          maxWidth: '88px',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
        }}
      >
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
  const pos = latLonToVec(station.lat, station.lon, R_EARTH * 1.018)
  const short = station.name.split('(')[0].trim()
  return (
    <group position={pos}>
      <mesh
        onClick={(e) => {
          e.stopPropagation()
          onSelect(station.id)
        }}
      >
        <sphereGeometry args={[selected ? 0.018 : 0.014, 12, 12]} />
        <meshStandardMaterial color={selected ? COLORS.earthNode : COLORS.station} />
      </mesh>
      {selected && (
        <group position={[0, 0.03, 0]}>
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
  const segments = useMemo(() => {
    if (trail.length < 2) return [] as THREE.Vector3[][]
    const segs: THREE.Vector3[][] = [[trail[0]]]
    for (let i = 1; i < trail.length; i++) {
      const prev = trail[i - 1]
      const cur = trail[i]
      if (prev.distanceTo(cur) > 0.45) segs.push([cur])
      else segs[segs.length - 1].push(cur)
    }
    return segs.filter((s) => s.length > 1)
  }, [trail])
  if (!lla) return null
  const r = R_EARTH + Math.max(0.055, (lla.alt_km || 400) / 6371)
  const pos = latLonToVec(lla.lat, lla.lon, r)
  const color = node.id.includes('cheap') ? COLORS.orbital : COLORS.orbitalAlt
  const label = node.name.replace('Orbital Node ', '')

  return (
    <group>
      {segments.map((pts, i) => (
        <Line
          key={`${node.id}-orb-${i}`}
          points={pts}
          color={COLORS.orbit}
          lineWidth={selected ? 1.2 : 0.7}
          transparent
          opacity={selected ? 0.45 : 0.22}
        />
      ))}
      <group position={pos}>
        <mesh
          onClick={(e) => {
            e.stopPropagation()
            onSelect(node.id)
          }}
        >
          <sphereGeometry args={[selected ? 0.016 : 0.012, 12, 12]} />
          <meshStandardMaterial color={color} />
        </mesh>
        <mesh rotation={[Math.PI / 2, 0, 0]}>
          <ringGeometry args={[0.02, 0.024, 24]} />
          <meshBasicMaterial
            color={color}
            transparent
            opacity={selected ? 0.55 : 0.28}
            side={THREE.DoubleSide}
          />
        </mesh>
        {selected && (
          <group position={[0, 0.032, 0]}>
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
  const pos = latLonToVec(node.lat || 0, node.lon || 0, R_EARTH * 1.025)
  return (
    <group position={pos}>
      <mesh
        onClick={(e) => {
          e.stopPropagation()
          onSelect(node.id)
        }}
      >
        <boxGeometry args={[0.016, 0.016, 0.016]} />
        <meshStandardMaterial color={COLORS.earthNode} />
      </mesh>
      {selected && (
        <group position={[0, 0.028, 0]}>
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
  const mesh = useRef<THREE.Mesh>(null)
  useFrame(() => {
    if (mesh.current) {
      const s = 1 + Math.sin(performance.now() * 0.004) * 0.12
      mesh.current.scale.setScalar(s)
    }
  })
  return (
    <mesh ref={mesh} position={p}>
      <sphereGeometry args={[0.014, 12, 12]} />
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
  if (st) return latLonToVec(st.lat, st.lon, R_EARTH * 1.018)
  const n = nodes.find((x) => x.id === id)
  if (!n) return null
  if (n.kind === 'earth') return latLonToVec(n.lat || 0, n.lon || 0, R_EARTH * 1.025)
  if (!n.position_lla) return null
  const r = R_EARTH + Math.max(0.055, (n.position_lla.alt_km || 400) / 6371)
  return latLonToVec(n.position_lla.lat, n.position_lla.lon, r)
}

function toTrailVecs(points: { lat: number; lon: number; alt_km: number }[]): THREE.Vector3[] {
  return points.map((lla) => {
    const r = R_EARTH + Math.max(0.055, (lla.alt_km || 400) / 6371)
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
  orbitTrails,
}: {
  nodes: ComputeNode[]
  stations: GroundStation[]
  links: LinkConfig[]
  transfers: Transfer[]
  selectedPlan: Plan | null
  selectedId: string | null
  onSelect: (id: string) => void
  orbitTrails: Record<string, THREE.Vector3[]>
}) {
  const activeTransfers = transfers.filter((t) => t.state === 'active' || t.state === 'paused')
  const activeLinkIds = new Set(activeTransfers.map((t) => t.active_link_id))
  const routeIn = selectedPlan?.input_route ?? []
  const routeOut = selectedPlan?.output_route ?? []

  return (
    <>
      <color attach="background" args={['#e7eef2']} />
      <ambientLight intensity={0.9} />
      <directionalLight position={[5, 3, 2]} intensity={0.75} color="#fffaf2" />
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
            trail={orbitTrails[n.id] || []}
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
              opacity={active ? 0.7 : 0.22}
              radius={active ? 0.008 : 0.0035}
            />
          )
        })}

      {routeIn.map((h, i) => {
        const a = endpointPos(h.from_id, nodes, stations)
        const b = endpointPos(h.to_id, nodes, stations)
        if (!a || !b) return null
        return (
          <LinkTube key={`in-${i}`} a={a} b={b} color={COLORS.routeIn} opacity={0.5} radius={0.006} />
        )
      })}
      {routeOut.map((h, i) => {
        const a = endpointPos(h.from_id, nodes, stations)
        const b = endpointPos(h.to_id, nodes, stations)
        if (!a || !b) return null
        return (
          <LinkTube key={`out-${i}`} a={a} b={b} color={COLORS.routeOut} opacity={0.45} radius={0.006} />
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
  simT?: number
}) {
  const [orbitTrails, setOrbitTrails] = useState<Record<string, THREE.Vector3[]>>({})
  const orbitalIds = props.nodes.filter((n) => n.kind === 'orbital').map((n) => n.id).join(',')

  useEffect(() => {
    let cancelled = false
    const ids = orbitalIds.split(',').filter(Boolean)
    ;(async () => {
      const next: Record<string, THREE.Vector3[]> = {}
      await Promise.all(
        ids.map(async (id) => {
          try {
            const res = await api.nodeTrack(id, 5600, 40)
            next[id] = toTrailVecs(res.points)
          } catch {
            /* keep empty */
          }
        }),
      )
      if (!cancelled) setOrbitTrails(next)
    })()
    return () => {
      cancelled = true
    }
  }, [orbitalIds, props.simT != null ? Math.floor(props.simT / 600) : 0])

  return (
    <div className="globe-wrap">
      <Canvas camera={{ position: [0, 1.05, 3.15], fov: 42 }} dpr={[1, 1.75]}>
        <Scene {...props} orbitTrails={orbitTrails} />
      </Canvas>
    </div>
  )
}
