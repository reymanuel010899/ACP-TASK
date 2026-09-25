from datetime import datetime, timezone

from libs.transfer_routing import Route, TransferRouter


def test_routing_precedence_and_leg_time_schedule():
    routes = [
        Route("fallback", "*", "*", "America/Los_Angeles", 0, 24, 30, 90, 30),
        Route("spanish-sales", "sales", "es", "America/Los_Angeles", 9, 17, 10, 90, 10),
        Route("english-sales", "sales", "en", "America/Los_Angeles", 9, 17, 20, 90, 20),
    ]
    router = TransferRouter(routes)
    now = datetime(2026, 8, 6, 18, 0, tzinfo=timezone.utc)  # 11:00 PDT
    assert [r.route_id for r in router.candidates("sales", "es", now)] == ["spanish-sales", "fallback"]


def test_total_budget_bounds_each_leg():
    route = Route("one", "sales", "es", "UTC", 0, 24, 60, 45, 1)
    assert TransferRouter([route]).leg_deadline(route, elapsed_seconds=20) == 25
    assert TransferRouter([route]).leg_deadline(route, elapsed_seconds=46) == 0

