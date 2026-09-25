"""Deterministic, schedule-aware human transfer routing."""

from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Route:
    route_id: str
    department: str
    language: str
    timezone: str
    start_hour: int
    end_hour: int
    ring_seconds: int
    total_budget_seconds: int
    priority: int

    def available(self, dial_time):
        hour = dial_time.astimezone(ZoneInfo(self.timezone)).hour
        if self.start_hour == self.end_hour:
            return True
        if self.start_hour < self.end_hour:
            return self.start_hour <= hour < self.end_hour
        return hour >= self.start_hour or hour < self.end_hour


class TransferRouter:
    def __init__(self, routes):
        self.routes = tuple(routes)

    def candidates(self, department, language, dial_time):
        def rank(route):
            if route.department == department and route.language == language:
                specificity = 0
            elif route.department == department and route.language == "*":
                specificity = 1
            elif route.department == "*" and route.language == language:
                specificity = 2
            elif route.department == "*" and route.language == "*":
                specificity = 3
            else:
                specificity = 99
            return specificity, route.priority, route.route_id
        return tuple(route for route in sorted(self.routes, key=rank)
                     if rank(route)[0] < 99 and route.available(dial_time))

    @staticmethod
    def leg_deadline(route, elapsed_seconds):
        remaining = max(0, route.total_budget_seconds - elapsed_seconds)
        return min(route.ring_seconds, remaining)


class TransferRoutingRepository:
    def __init__(self, connection):
        self.connection = connection

    def routes(self, tenant_id):
        rows = self.connection.execute(
            "SELECT route_id,department,language,timezone,start_hour,end_hour,ring_seconds,total_budget_seconds,priority "
            "FROM voice_transfer_routes WHERE tenant_id=? AND enabled=1 ORDER BY priority,route_id", (tenant_id,)
        ).fetchall()
        return tuple(Route(*row) for row in rows)

