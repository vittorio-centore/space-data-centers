import { Canvas, useFrame, useLoader } from '@react-three/fiber'
import { Html, Line, OrbitControls } from '@react-three/drei'
import { Suspense, useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'
import { api, type ComputeNode, type GroundStation, type LinkConfig, type Plan, type Transfer } from '../api'

const R_EARTH = 1
const COLORS = {
  station: '#1f5f7a',
  earthNode: '#8a5a1f',
  orbital: '#1f6b54',
  orbitalAlt: '#3d5a6c',
  linkUp: '#2f7a66',
  linkActive: '#c4891e',
  linkPaused: '#a04444',
  routeIn: '#1d4f74',
  routeOut: '#8a6520',
  isl: '#4a6d7c',
  orbit: '#5a7382',
}

/** Brighter day map; we lighten further in canvas. */
const EARTH_TEX_URL =
  'https://cdn.jsdelivr.net/npm/three-globe@2.31.1/example/img/earth-day.jpg'

function latLonToVec(lat: number, lon: number, radius: number) {
  const phi = ((90 - lat) * Math.PI) / 180
  const theta = ((lon + 180) * Math.PI) / 180
  return new THREE.Vector3(
    -radius * Math.sin(phi) * Math.cos(theta),
    radius * Math.cos(phi),
    radius * Math.sin(phi) * Math.sin(theta),
  )
}

function lightenMap(source: THREE.Texture): THREE.CanvasTexture {
  const img = source.image as HTMLImageElement | ImageBitmap
  const w = ('width' in img ? img.width : 1024) || 1024
  const h = ('height' in img ? img.height : 512) || 512
  const canvas = document.createElement('canvas')
  canvas.width = w
  canvas.height = h
  const ctx = canvas.getContext('2d')!
  // Soft paper-ocean base, then muted day map, then lift toward cream.
  ctx.fillStyle = '#d4e2ea'
  ctx.fillRect(0, 0, w, h)
  ctx.globalAlpha = 0.55
  ctx.drawImage(img as CanvasImageSource, 0, 0, w, h)
  ctx.globalAlpha = 1
  ctx.fillStyle = 'rgba(255, 252, 247, 0.42)'
  ctx.fillRect(0, 0, w, h)
  // Slight desaturation via soft gray wash
  ctx.fillStyle = 'rgba(220, 228, 232, 0.18)'
  ctx.fillRect(0, 0, w, h)
  const tex = new THREE.CanvasTexture(canvas)
  tex.colorSpace = THREE.SRGBColorSpace
  tex.anisotropy = 4
  tex.needsUpdate = true
  return tex
}

function OutlineEarth() {
  const tex = useMemo(() => {
    const size = 1024
    const c = document.createElement('canvas')
    c.width = size
    c.height = size / 2
    const ctx = c.getContext('2d')!
    ctx.fillStyle = '#b9cdd9'
    ctx.fillRect(0, 0, c.width, c.height)
    ctx.fillStyle = '#cfd9c4'
    const polys: [number, number][][] = [
      [[0.12, 0.22], [0.28, 0.18], [0.32, 0.32], [0.22, 0.42], [0.1, 0.38]],
      [[0.28, 0.48], [0.34, 0.45], [0.36, 0.72], [0.28, 0.78], [0.24, 0.58]],
      [[0.48, 0.22], [0.58, 0.2], [0.6, 0.35], [0.52, 0.55], [0.48, 0.7], [0.44, 0.4]],
      [[0.58, 0.18], [0.85, 0.2], [0.88, 0.38], [0.7, 0.42], [0.58, 0.35]],
      [[0.78, 0.58], [0.9, 0.55], [0.92, 0.68], [0.8, 0.7]],
    ]
    for (const poly of polys) {
      ctx.beginPath()
      poly.forEach(([x, y], i) => {
        const X = x * c.width
        const Y = y * c.height
        if (i === 0) ctx.moveTo(X, Y)
        else ctx.lineTo(X, Y)
      })
      ctx.closePath()
      ctx.fill()
      ctx.strokeStyle = 'rgba(80, 100, 90, 0.2)'
      ctx.stroke()
    }
    const t = new THREE.CanvasTexture(c)
    t.colorSpace = THREE.SRGBColorSpace
    return t
  }, [])
  return (
    <mesh>
      <sphereGeometry args={[R_EARTH, 64, 64]} />
      <meshStandardMaterial map={tex} roughness={0.95} metalness={0} color="#f4f7f8" />
    </mesh>
  )
}

function TexturedEarth() {
  const raw = useLoader(THREE.TextureLoader, EARTH_TEX_URL)
  const tex = useMemo(() => lightenMap(raw), [raw])
  return (
    <mesh>
      <sphereGeometry args={[R_EARTH, 72, 72]} />
      <meshStandardMaterial map={tex} roughness={0.94} metalness={0} color="#ffffff" />
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
      distanceFactor={64}
      center
      pointerEvents="none"
      zIndexRange={[10, 0]}
      style={{ pointerEvents: 'none', transform: 'translate3d(0,0,0)' }}
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
  const short = station.name.split('(')[0].trim().split(' ')[0]
  return (
    <group position={pos}>
      <mesh
        onClick={(e) => {
          e.stopPropagation()
          onSelect(station.id)
        }}
      >
        <sphereGeometry args={[selected ? 0.028 : 0.024, 16, 16]} />
        <meshStandardMaterial
          color={selected ? COLORS.earthNode : COLORS.station}
          emissive={selected ? COLORS.earthNode : COLORS.station}
          emissiveIntensity={0.22}
        />
      </mesh>
      <group position={[0, 0.042, 0]}>
        <MarkerLabel text={short} />
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
  const segments = useMemo(() => {
    if (trail.length < 2) return [] as THREE.Vector3[][]
    const segs: THREE.Vector3[][] = [[trail[0]]]
    for (let i = 1; i < trail.length; i++) {
      if (trail[i - 1].distanceTo(trail[i]) > 0.45) segs.push([trail[i]])
      else segs[segs.length - 1].push(trail[i])
    }
    return segs.filter((s) => s.length > 1)
  }, [trail])
  if (!lla) return null
  const r = R_EARTH + Math.max(0.06, (lla.alt_km || 400) / 6371)
  const pos = latLonToVec(lla.lat, lla.lon, r)
  const color = node.id.includes('cheap') ? COLORS.orbital : COLORS.orbitalAlt
  const label =
    node.id.includes('iss') ? 'ISS' : node.id.includes('css') ? 'CSS' : node.id.includes('noaa') ? 'NOAA' : node.name.split(' ').pop() || node.id

  return (
    <group>
      {segments.map((pts, i) => (
        <Line
          key={`${node.id}-orb-${i}`}
          points={pts}
          color={COLORS.orbit}
          lineWidth={selected ? 2.2 : 1.55}
          transparent
          opacity={selected ? 0.7 : 0.5}
        />
      ))}
      <group position={pos}>
        <mesh
          onClick={(e) => {
            e.stopPropagation()
            onSelect(node.id)
          }}
        >
          <sphereGeometry args={[selected ? 0.032 : 0.028, 18, 18]} />
          <meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.28} />
        </mesh>
        <mesh rotation={[Math.PI / 2, 0, 0]}>
          <ringGeometry args={[0.036, 0.046, 32]} />
          <meshBasicMaterial
            color={color}
            transparent
            opacity={selected ? 0.85 : 0.6}
            side={THREE.DoubleSide}
          />
        </mesh>
        <group position={[0, 0.052, 0]}>
          <MarkerLabel text={label} />
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
  const pos = latLonToVec(node.lat || 0, node.lon || 0, R_EARTH * 1.028)
  return (
    <group position={pos}>
      <mesh
        onClick={(e) => {
          e.stopPropagation()
          onSelect(node.id)
        }}
      >
        <boxGeometry args={[0.028, 0.028, 0.028]} />
        <meshStandardMaterial
          color={COLORS.earthNode}
          emissive={COLORS.earthNode}
          emissiveIntensity={0.2}
        />
      </mesh>
      <group position={[0, 0.048, 0]}>
        <MarkerLabel text="Earth" />
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
  const geom = useMemo(() => new THREE.TubeGeometry(curve, 48, radius, 6, false), [curve, radius])
  return (
    <mesh geometry={geom}>
      <meshBasicMaterial color={color} transparent opacity={opacity} depthWrite={false} />
    </mesh>
  )
}

/** Moving bead along a curve to show data motion. */
function FlowBead({
  a,
  b,
  color,
  speed = 0.35,
  phase = 0,
}: {
  a: THREE.Vector3
  b: THREE.Vector3
  color: string
  speed?: number
  phase?: number
}) {
  const curve = useMemo(() => {
    const mid = a.clone().add(b).multiplyScalar(0.5)
    mid.normalize().multiplyScalar(Math.max(a.length(), b.length()) * 1.12)
    return new THREE.QuadraticBezierCurve3(a, mid, b)
  }, [a.x, a.y, a.z, b.x, b.y, b.z])
  const mesh = useRef<THREE.Mesh>(null)
  useFrame(({ clock }) => {
    if (!mesh.current) return
    const u = (clock.getElapsedTime() * speed + phase) % 1
    const p = curve.getPoint(u)
    mesh.current.position.copy(p)
  })
  return (
    <mesh ref={mesh}>
      <sphereGeometry args={[0.016, 12, 12]} />
      <meshStandardMaterial color={color} />
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
      const s = 1 + Math.sin(performance.now() * 0.005) * 0.18
      mesh.current.scale.setScalar(s)
    }
  })
  return (
    <mesh ref={mesh} position={p}>
      <sphereGeometry args={[0.02, 14, 14]} />
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
  if (n.kind === 'earth') return latLonToVec(n.lat || 0, n.lon || 0, R_EARTH * 1.028)
  if (!n.position_lla) return null
  const r = R_EARTH + Math.max(0.06, (n.position_lla.alt_km || 400) / 6371)
  return latLonToVec(n.position_lla.lat, n.position_lla.lon, r)
}

function toTrailVecs(points: { lat: number; lon: number; alt_km: number }[]): THREE.Vector3[] {
  return points.map((lla) => {
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
  const jobActive = activeTransfers.filter((t) => t.job_id === selectedPlan?.job_id)

  return (
    <>
      <color attach="background" args={['#eef3f5']} />
      <ambientLight intensity={1.2} />
      <directionalLight position={[5, 3, 2]} intensity={0.75} color="#fffaf4" />
      <hemisphereLight args={['#f7fafc', '#d8e2e8', 0.45]} />
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

      {/* Active contact / ISL links */}
      {links
        .filter((L) => L.up)
        .map((L) => {
          const a = endpointPos(L.endpoint_a, nodes, stations)
          const b = endpointPos(L.endpoint_b, nodes, stations)
          if (!a || !b) return null
          const active = activeLinkIds.has(L.id)
          if (L.kind === 'terrestrial' && !active) {
            return (
              <LinkTube key={L.id} a={a} b={b} color={COLORS.station} opacity={0.14} radius={0.003} />
            )
          }
          return (
            <LinkTube
              key={L.id}
              a={a}
              b={b}
              color={active ? COLORS.linkActive : L.kind === 'isl' ? COLORS.isl : COLORS.linkUp}
              opacity={active ? 0.9 : L.kind === 'terrestrial' ? 0.22 : L.kind === 'isl' ? 0.55 : 0.5}
              radius={active ? 0.012 : L.kind === 'isl' ? 0.007 : 0.006}
            />
          )
        })}

      {/* Selected job routes + flowing beads */}
      {routeIn.map((h, i) => {
        const a = endpointPos(h.from_id, nodes, stations)
        const b = endpointPos(h.to_id, nodes, stations)
        if (!a || !b) return null
        return (
          <group key={`in-${i}`}>
            <LinkTube a={a} b={b} color={COLORS.routeIn} opacity={0.55} radius={0.007} />
            <FlowBead a={a} b={b} color={COLORS.routeIn} speed={0.28} phase={i * 0.2} />
          </group>
        )
      })}
      {routeOut.map((h, i) => {
        const a = endpointPos(h.from_id, nodes, stations)
        const b = endpointPos(h.to_id, nodes, stations)
        if (!a || !b) return null
        return (
          <group key={`out-${i}`}>
            <LinkTube a={a} b={b} color={COLORS.routeOut} opacity={0.5} radius={0.007} />
            <FlowBead a={a} b={b} color={COLORS.routeOut} speed={0.28} phase={0.5 + i * 0.2} />
          </group>
        )
      })}

      {/* Live transfer progress for selected job (or all active) */}
      {(jobActive.length ? jobActive : activeTransfers).map((tr) => {
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
            const res = await api.nodeTrack(id, 5600, 35)
            next[id] = toTrailVecs(res.points)
          } catch {
            /* ignore */
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
