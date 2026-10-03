import { Canvas, useFrame } from '@react-three/fiber'
import { OrbitControls, Stars } from '@react-three/drei'
import { useMemo, useRef } from 'react'
import * as THREE from 'three'
import type { ComputeNode, GroundStation, LinkConfig, Plan, Transfer } from '../api'

function latLonToVec(lat: number, lon: number, radius: number) {
  const phi = ((90 - lat) * Math.PI) / 180
  const theta = ((lon + 180) * Math.PI) / 180
  return new THREE.Vector3(
    -radius * Math.sin(phi) * Math.cos(theta),
    radius * Math.cos(phi),
    radius * Math.sin(phi) * Math.sin(theta),
  )
}

function Earth() {
  const mat = useMemo(
    () =>
      new THREE.MeshStandardMaterial({
        color: '#1b3a55',
        roughness: 0.85,
        metalness: 0.1,
        emissive: '#0a2030',
        emissiveIntensity: 0.25,
      }),
    [],
  )
  return (
    <mesh>
      <sphereGeometry args={[1, 64, 64]} />
      <primitive object={mat} attach="material" />
      <mesh>
        <sphereGeometry args={[1.01, 48, 48]} />
        <meshBasicMaterial color="#3ecf8e" wireframe transparent opacity={0.06} />
      </mesh>
    </mesh>
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
  const pos = latLonToVec(station.lat, station.lon, 1.02)
  return (
    <mesh position={pos} onClick={(e) => { e.stopPropagation(); onSelect(station.id) }}>
      <sphereGeometry args={[selected ? 0.035 : 0.025, 16, 16]} />
      <meshStandardMaterial
        color={selected ? '#f0b429' : '#5eb0ff'}
        emissive={selected ? '#f0b429' : '#5eb0ff'}
        emissiveIntensity={0.6}
      />
    </mesh>
  )
}

function OrbitalMarker({
  node,
  selected,
  onSelect,
}: {
  node: ComputeNode
  selected: boolean
  onSelect: (id: string) => void
}) {
  const lla = node.position_lla
  if (!lla) return null
  const r = 1 + Math.max(0.05, (lla.alt_km || 400) / 6371)
  const pos = latLonToVec(lla.lat, lla.lon, r)
  const color = node.id.includes('cheap') ? '#3ecf8e' : '#9b7bff'
  return (
    <group position={pos}>
      <mesh onClick={(e) => { e.stopPropagation(); onSelect(node.id) }}>
        <sphereGeometry args={[selected ? 0.04 : 0.03, 16, 16]} />
        <meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.7} />
      </mesh>
      <mesh>
        <ringGeometry args={[0.05, 0.065, 24]} />
        <meshBasicMaterial color={color} transparent opacity={0.45} side={THREE.DoubleSide} />
      </mesh>
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
  const pos = latLonToVec(node.lat || 0, node.lon || 0, 1.03)
  return (
    <mesh position={pos} onClick={(e) => { e.stopPropagation(); onSelect(node.id) }}>
      <boxGeometry args={[selected ? 0.04 : 0.03, selected ? 0.04 : 0.03, selected ? 0.04 : 0.03]} />
      <meshStandardMaterial
        color="#5eb0ff"
        emissive="#5eb0ff"
        emissiveIntensity={0.5}
      />
    </mesh>
  )
}

function LinkArc({
  a,
  b,
  color,
  opacity = 0.55,
}: {
  a: THREE.Vector3
  b: THREE.Vector3
  color: string
  opacity?: number
}) {
  const curve = useMemo(() => {
    const mid = a.clone().add(b).multiplyScalar(0.5)
    mid.normalize().multiplyScalar(Math.max(a.length(), b.length()) * 1.15)
    return new THREE.QuadraticBezierCurve3(a, mid, b)
  }, [a, b])
  const points = useMemo(() => curve.getPoints(32), [curve])
  const geom = useMemo(() => new THREE.BufferGeometry().setFromPoints(points), [points])
  return (
    <primitive object={new THREE.Line(geom, new THREE.LineBasicMaterial({ color, transparent: true, opacity }))} />
  )
}

function endpointPos(
  id: string,
  nodes: ComputeNode[],
  stations: GroundStation[],
): THREE.Vector3 | null {
  const st = stations.find((s) => s.id === id)
  if (st) return latLonToVec(st.lat, st.lon, 1.02)
  const n = nodes.find((x) => x.id === id)
  if (!n) return null
  if (n.kind === 'earth') return latLonToVec(n.lat || 0, n.lon || 0, 1.03)
  if (!n.position_lla) return null
  const r = 1 + Math.max(0.05, (n.position_lla.alt_km || 400) / 6371)
  return latLonToVec(n.position_lla.lat, n.position_lla.lon, r)
}

function Scene({
  nodes,
  stations,
  links,
  transfers,
  selectedPlan,
  selectedId,
  onSelect,
}: {
  nodes: ComputeNode[]
  stations: GroundStation[]
  links: LinkConfig[]
  transfers: Transfer[]
  selectedPlan: Plan | null
  selectedId: string | null
  onSelect: (id: string) => void
}) {
  const pulse = useRef(0)
  useFrame((_, dt) => {
    pulse.current = (pulse.current + dt) % 2
  })

  const activeTransferLinks = new Set(
    transfers.filter((t) => t.state === 'active' || t.state === 'paused').map((t) => t.active_link_id),
  )

  const routeHops = selectedPlan
    ? [...selectedPlan.input_route, ...selectedPlan.output_route]
    : []

  return (
    <>
      <ambientLight intensity={0.55} />
      <directionalLight position={[4, 2, 3]} intensity={1.1} />
      <Stars radius={80} depth={40} count={2500} factor={3} fade speed={0.4} />
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
          <EarthNodeMarker key={n.id} node={n} selected={selectedId === n.id} onSelect={onSelect} />
        ) : (
          <OrbitalMarker key={n.id} node={n} selected={selectedId === n.id} onSelect={onSelect} />
        ),
      )}
      {links
        .filter((L) => L.up && L.kind !== 'terrestrial')
        .map((L) => {
          const a = endpointPos(L.endpoint_a, nodes, stations)
          const b = endpointPos(L.endpoint_b, nodes, stations)
          if (!a || !b) return null
          const active = activeTransferLinks.has(L.id)
          return (
            <LinkArc
              key={L.id}
              a={a}
              b={b}
              color={active ? '#f0b429' : L.kind === 'isl' ? '#9b7bff' : '#3ecf8e'}
              opacity={active ? 0.95 : 0.35}
            />
          )
        })}
      {routeHops.map((h, i) => {
        const a = endpointPos(h.from_id, nodes, stations)
        const b = endpointPos(h.to_id, nodes, stations)
        if (!a || !b) return null
        return <LinkArc key={`route-${i}`} a={a} b={b} color="#ffffff" opacity={0.75} />
      })}
      <OrbitControls enablePan={false} minDistance={2.2} maxDistance={6} />
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
  return (
    <div className="globe-wrap">
      <Canvas camera={{ position: [0, 1.2, 3.2], fov: 45 }}>
        <Scene {...props} />
      </Canvas>
    </div>
  )
}
