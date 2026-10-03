"""Time-expanded placement + cheapest-node baseline comparison.

Objective (constants):
  1. Among plans that meet deadline (if set), minimize estimated_cost.
  2. If no deadline (or none meet it), minimize estimated_completion, then cost.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from typing import Optional

from app.models.types import (
    BaselineComparison,
    ComputeNode,
    GroundStation,
    Hop,
    Job,
    LinkConfig,
    LinkKind,
    NodeKind,
    Plan,
    Reservation,
)
from app.orbit.propagate import OrbitEngine, elevation_deg, geodetic_to_ecef, range_m

OBJECTIVE_DOC = (
    "Prefer feasible-by-deadline then lower cost; "
    "else earlier completion then cost (OBJECTIVE_TIEBREAK)."
)


@dataclass
class ContactWindow:
    link_id: str
    a: str
    b: str
    start: float
    end: float
    bandwidth_bps: float
    price_per_bit: float


class PlacementPlanner:
    def __init__(
        self,
        nodes: list[ComputeNode],
        stations: list[GroundStation],
        links: list[LinkConfig],
        orbit: OrbitEngine,
        node_by_id: dict[str, ComputeNode],
        station_by_id: dict[str, GroundStation],
        link_by_id: dict[str, LinkConfig],
        reservations: list[Reservation],
        link_reservations: dict[str, list[tuple[float, float, int]]],  # link -> [(t0,t1,bytes)]
        disrupted: dict[str, dict],
        sim_step_s: float,
        plan_horizon_s: float,
    ):
        self.nodes = nodes
        self.stations = stations
        self.links = links
        self.orbit = orbit
        self.node_by_id = node_by_id
        self.station_by_id = station_by_id
        self.link_by_id = link_by_id
        self.reservations = reservations
        self.link_reservations = link_reservations
        self.disrupted = disrupted
        self.sim_step_s = sim_step_s
        self.plan_horizon_s = plan_horizon_s
        self.endpoints = set(node_by_id) | set(station_by_id)

    def plan_job(self, job: Job, t_now: float) -> tuple[Optional[Plan], Optional[BaselineComparison], str]:
        candidates: list[Plan] = []
        errors: list[str] = []
        for node in self.nodes:
            plan = self._plan_for_node(job, node, t_now)
            if plan is None:
                errors.append(f"{node.id}:infeasible")
            else:
                candidates.append(plan)

        cheapest = min(self.nodes, key=lambda n: n.price_per_work)
        baseline_plan = self._plan_for_node(job, cheapest, t_now)

        if not candidates:
            # Still attach baseline info when possible
            baseline = self._baseline_cmp(None, baseline_plan, cheapest)
            return None, baseline, "; ".join(errors) or "no feasible plan"

        chosen = self._select(candidates, job)
        baseline = self._baseline_cmp(chosen, baseline_plan, cheapest)
        chosen.baseline_comparison = baseline
        return chosen, baseline, ""

    def _select(self, candidates: list[Plan], job: Job) -> Plan:
        if job.deadline_at is not None:
            feasible = [p for p in candidates if p.estimated_completion <= job.deadline_at]
            if feasible:
                return min(feasible, key=lambda p: (p.estimated_cost, p.estimated_completion))
        return min(candidates, key=lambda p: (p.estimated_completion, p.estimated_cost))

    def _baseline_cmp(
        self, chosen: Optional[Plan], baseline_plan: Optional[Plan], cheapest: ComputeNode
    ) -> BaselineComparison:
        reason: list[str] = []
        if baseline_plan is None:
            reason.append("baseline_infeasible")
            b_cost = float("inf")
            b_comp = float("inf")
            b_ok = False
        else:
            b_cost = baseline_plan.estimated_cost
            b_comp = baseline_plan.estimated_completion
            b_ok = True

        if chosen is None:
            return BaselineComparison(
                baseline_node_id=cheapest.id,
                baseline_cost=b_cost if math.isfinite(b_cost) else -1,
                baseline_completion=b_comp if math.isfinite(b_comp) else -1,
                baseline_feasible=b_ok,
                chosen_node_id="",
                chosen_cost=-1,
                chosen_completion=-1,
                reason_codes=reason + ["chosen_infeasible"],
            )

        if not b_ok:
            reason.append("baseline_infeasible")
        elif chosen.compute_node_id != cheapest.id:
            if chosen.baseline_comparison:  # unused
                pass
            # Infer why we didn't pick cheapest
            if baseline_plan and chosen.job_id:
                # deadline context filled by caller via job — use completion comparison
                pass
            reason.append("chose_non_cheapest")
            if baseline_plan and chosen.estimated_completion < baseline_plan.estimated_completion:
                reason.append("baseline_later_completion")
            if baseline_plan and chosen.estimated_cost < baseline_plan.estimated_cost:
                reason.append("chosen_lower_cost")
        else:
            reason.append("chose_cheapest_node")

        # Refine with deadline if baseline misses and chosen meets — set by enrich below
        return BaselineComparison(
            baseline_node_id=cheapest.id,
            baseline_cost=b_cost if math.isfinite(b_cost) else -1.0,
            baseline_completion=b_comp if math.isfinite(b_comp) else -1.0,
            baseline_feasible=b_ok,
            chosen_node_id=chosen.compute_node_id,
            chosen_cost=chosen.estimated_cost,
            chosen_completion=chosen.estimated_completion,
            reason_codes=reason,
        )

    def enrich_reasons(self, plan: Plan, job: Job) -> None:
        bc = plan.baseline_comparison
        if not bc:
            return
        reasons = list(bc.reason_codes)
        if job.deadline_at is not None and bc.baseline_feasible:
            if bc.baseline_completion > job.deadline_at:
                if "baseline_misses_deadline" not in reasons:
                    reasons.append("baseline_misses_deadline")
            if plan.estimated_completion <= job.deadline_at and bc.baseline_completion > job.deadline_at:
                if "chosen_meets_deadline" not in reasons:
                    reasons.append("chosen_meets_deadline")
        if bc.chosen_node_id != bc.baseline_node_id and bc.chosen_cost <= bc.baseline_cost:
            if "chosen_lower_or_equal_cost" not in reasons:
                reasons.append("chosen_lower_or_equal_cost")
        if bc.chosen_node_id == bc.baseline_node_id:
            if "chose_cheapest_node" not in reasons:
                reasons.append("chose_cheapest_node")
        bc.reason_codes = reasons

    def _plan_for_node(self, job: Job, node: ComputeNode, t_now: float) -> Optional[Plan]:
        exec_duration = job.work / node.compute_rate
        # Optimistic filter
        if job.deadline_at is not None and t_now + exec_duration > job.deadline_at:
            # still might fail later; allow routing attempt if transfer could be fast
            pass

        input_route, input_arrival = self._earliest_delivery(
            job.source_id, node.id, job.input_bytes, t_now
        )
        if input_route is None:
            return None

        compute_start = self._earliest_slot(node.id, input_arrival, exec_duration)
        compute_end = compute_start + exec_duration

        output_route, output_arrival = self._earliest_delivery(
            node.id, job.destination_id, job.output_bytes, compute_end
        )
        if output_route is None:
            return None

        if job.deadline_at is not None and output_arrival > job.deadline_at + 1e-6:
            # Still return plan; selection filters by deadline preference
            pass

        compute_cost = job.work * node.price_per_work
        transfer_cost = self._route_cost(input_route) + self._route_cost(output_route)
        return Plan(
            id=f"plan-{uuid.uuid4().hex[:10]}",
            job_id=job.id,
            compute_node_id=node.id,
            input_route=input_route,
            output_route=output_route,
            compute_start=compute_start,
            compute_end=compute_end,
            estimated_cost=compute_cost + transfer_cost,
            estimated_completion=output_arrival,
            transfer_cost=transfer_cost,
            compute_cost=compute_cost,
        )

    def _node_available_at(self, node_id: str) -> float:
        ends = [r.end for r in self.reservations if r.node_id == node_id]
        node = self.node_by_id[node_id]
        return max([node.available_at] + ends) if ends else node.available_at

    def _earliest_slot(self, node_id: str, after: float, duration: float) -> float:
        intervals = sorted(
            [(r.start, r.end) for r in self.reservations if r.node_id == node_id],
            key=lambda x: x[0],
        )
        t = max(after, self._node_available_at(node_id))
        for start, end in intervals:
            if t + duration <= start + 1e-9:
                return t
            if t < end:
                t = end
        return t

    def _route_cost(self, hops: list[Hop]) -> float:
        total = 0.0
        for h in hops:
            if not h.link_id:
                continue
            link = self.link_by_id[h.link_id]
            total += h.bytes * 8 * link.price_per_bit
        return total

    def _earliest_delivery(
        self, src: str, dst: str, nbytes: int, t_start: float
    ) -> tuple[Optional[list[Hop]], float]:
        if src == dst:
            return [], t_start

        step = self.sim_step_s
        horizon = t_start + self.plan_horizon_s
        n_steps = int(math.ceil(self.plan_horizon_s / step)) + 1

        # Precompute link up bitmap per step
        link_up = self._contact_matrix(t_start, n_steps, step)

        # Dijkstra on time-expanded graph: state = (endpoint, step_index)
        # Cost key: arrival time
        INF = 10**18
        start_i = 0
        dist: dict[tuple[str, int], float] = {(src, start_i): t_start}
        prev: dict[tuple[str, int], tuple[tuple[str, int], Optional[str], int]] = {}
        # bytes remaining when arriving — for multi-step transfers we track separately

        # Better approach: for store-and-forward of a whole payload on exclusive link,
        # model edges as "can transfer full nbytes during continuous up window".
        windows = self._build_windows(t_start, horizon, step, link_up)

        # Graph search over endpoints with time
        import heapq

        # state: (arrival_time, endpoint, bytes_at_endpoint) — bytes always full after hop for MVP
        pq: list[tuple[float, str]] = [(t_start, src)]
        best: dict[str, float] = {src: t_start}
        parent: dict[str, tuple[str, str, float, float]] = {}  # ep -> (prev, link_id, w_start, w_end)

        while pq:
            t_arr, ep = heapq.heappop(pq)
            if t_arr > best.get(ep, INF) + 1e-9:
                continue
            if ep == dst:
                break
            # Wait + transfer over each outgoing window that starts at/after t_arr
            for w in windows:
                if ep not in (w.a, w.b):
                    continue
                other = w.b if ep == w.a else w.a
                if w.end <= t_arr:
                    continue
                # Disruption
                if self._is_disrupted(w.link_id, max(t_arr, w.start)):
                    continue
                start_tx = max(t_arr, w.start)
                # Exclusive bandwidth; subtract reserved bytes overlapping window (approx)
                bw = w.bandwidth_bps
                if bw <= 0:
                    continue
                # Available duration in this window from start_tx
                avail_s = w.end - start_tx
                need_s = (nbytes * 8) / bw
                if need_s > avail_s + 1e-9:
                    continue
                arrive = start_tx + need_s
                if arrive > horizon:
                    continue
                if arrive + 1e-9 < best.get(other, INF):
                    best[other] = arrive
                    parent[other] = (ep, w.link_id, start_tx, arrive)
                    heapq.heappush(pq, (arrive, other))

        if dst not in best:
            return None, INF

        # Reconstruct hops
        hops: list[Hop] = []
        cur = dst
        while cur != src:
            prev_ep, link_id, w_start, w_end = parent[cur]
            hops.append(
                Hop(
                    from_id=prev_ep,
                    to_id=cur,
                    link_id=link_id,
                    window_start=w_start,
                    window_end=w_end,
                    bytes=nbytes,
                )
            )
            cur = prev_ep
        hops.reverse()
        return hops, best[dst]

    def _is_disrupted(self, link_id: str, t: float) -> bool:
        d = self.disrupted.get(link_id)
        if not d:
            return False
        if d.get("down"):
            until = d.get("until")
            if until is None or t < until:
                return True
        factor = d.get("bandwidth_factor")
        if factor is not None and factor <= 0:
            return True
        return False

    def _bandwidth_factor(self, link_id: str) -> float:
        d = self.disrupted.get(link_id) or {}
        return float(d.get("bandwidth_factor", 1.0))

    def _contact_matrix(self, t_start: float, n_steps: int, step: float) -> dict[str, list[bool]]:
        up: dict[str, list[bool]] = {L.id: [False] * n_steps for L in self.links}
        for i in range(n_steps):
            t = t_start + i * step
            for L in self.links:
                up[L.id][i] = self._link_up_at(L, t) and not self._is_disrupted(L.id, t)
        return up

    def _link_up_at(self, link: LinkConfig, t: float) -> bool:
        if link.kind == LinkKind.terrestrial:
            return True
        if link.kind == LinkKind.ground_space:
            gs_id, orb_id = self._gs_and_orb(link)
            if gs_id is None:
                return False
            gs = self.station_by_id[gs_id]
            orb = self.node_by_id[orb_id]
            assert orb.orbital_record_id
            ecef = self.orbit.position_ecef_m(orb.orbital_record_id, t)
            if ecef is None:
                return False
            el = elevation_deg(gs.lat, gs.lon, gs.alt_m, ecef)
            min_el = link.rules.get("min_elevation_deg", gs.min_elevation_deg)
            if el < min_el:
                return False
            max_range = link.rules.get("max_range_km", gs.max_range_km)
            if max_range is not None:
                s_ecef = geodetic_to_ecef(gs.lat, gs.lon, gs.alt_m)
                if range_m(s_ecef, ecef) > max_range * 1000.0:
                    return False
            return True
        if link.kind == LinkKind.isl:
            a = self.node_by_id[link.endpoint_a]
            b = self.node_by_id[link.endpoint_b]
            if a.kind != NodeKind.orbital or b.kind != NodeKind.orbital:
                return False
            assert a.orbital_record_id and b.orbital_record_id
            ea = self.orbit.position_ecef_m(a.orbital_record_id, t)
            eb = self.orbit.position_ecef_m(b.orbital_record_id, t)
            if ea is None or eb is None:
                return False
            max_km = link.rules.get("max_range_km", 4000.0)
            return range_m(ea, eb) <= max_km * 1000.0
        return False

    def _gs_and_orb(self, link: LinkConfig) -> tuple[Optional[str], Optional[str]]:
        a, b = link.endpoint_a, link.endpoint_b
        if a in self.station_by_id and b in self.node_by_id:
            return a, b
        if b in self.station_by_id and a in self.node_by_id:
            return b, a
        return None, None

    def _build_windows(
        self, t_start: float, horizon: float, step: float, link_up: dict[str, list[bool]]
    ) -> list[ContactWindow]:
        windows: list[ContactWindow] = []
        for link in self.links:
            ups = link_up[link.id]
            i = 0
            while i < len(ups):
                if not ups[i]:
                    i += 1
                    continue
                j = i
                while j < len(ups) and ups[j]:
                    j += 1
                w_start = t_start + i * step
                w_end = t_start + j * step
                if w_start < horizon:
                    factor = self._bandwidth_factor(link.id)
                    windows.append(
                        ContactWindow(
                            link_id=link.id,
                            a=link.endpoint_a,
                            b=link.endpoint_b,
                            start=w_start,
                            end=min(w_end, horizon),
                            bandwidth_bps=link.bandwidth_bps * factor,
                            price_per_bit=link.price_per_bit,
                        )
                    )
                i = j
        windows.sort(key=lambda w: w.start)
        return windows

    def replan_routes(
        self, job: Job, plan: Plan, data_at: str, phase: str, t_now: float
    ) -> Optional[Plan]:
        """Replan input or output routes keeping assigned_node_id fixed."""
        node = self.node_by_id[plan.compute_node_id]
        if phase == "input":
            route, arrival = self._earliest_delivery(data_at, node.id, job.input_bytes, t_now)
            if route is None:
                return None
            exec_duration = plan.compute_end - plan.compute_start
            compute_start = self._earliest_slot(node.id, arrival, exec_duration)
            compute_end = compute_start + exec_duration
            out_route, out_arr = self._earliest_delivery(
                node.id, job.destination_id, job.output_bytes, compute_end
            )
            if out_route is None:
                return None
            compute_cost = job.work * node.price_per_work
            transfer_cost = self._route_cost(route) + self._route_cost(out_route)
            return Plan(
                id=plan.id,
                job_id=job.id,
                compute_node_id=node.id,
                input_route=route,
                output_route=out_route,
                compute_start=compute_start,
                compute_end=compute_end,
                estimated_cost=compute_cost + transfer_cost,
                estimated_completion=out_arr,
                baseline_comparison=plan.baseline_comparison,
                transfer_cost=transfer_cost,
                compute_cost=compute_cost,
            )
        else:
            route, arrival = self._earliest_delivery(
                data_at, job.destination_id, job.output_bytes, t_now
            )
            if route is None:
                return None
            transfer_cost = self._route_cost(plan.input_route) + self._route_cost(route)
            return Plan(
                id=plan.id,
                job_id=job.id,
                compute_node_id=node.id,
                input_route=plan.input_route,
                output_route=route,
                compute_start=plan.compute_start,
                compute_end=plan.compute_end,
                estimated_cost=plan.compute_cost + transfer_cost,
                estimated_completion=arrival,
                baseline_comparison=plan.baseline_comparison,
                transfer_cost=transfer_cost,
                compute_cost=plan.compute_cost,
            )
