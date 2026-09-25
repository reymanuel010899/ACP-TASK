from services.oauth.repository import OAuthRepository


def test_voice_routes_replace_atomically_and_stay_tenant_scoped(tmp_path):
    repository = OAuthRepository(tmp_path / "oauth.db")
    route = {
        "route_id": "support-es", "department": "support", "language": "es",
        "destination": "+15551234567", "timezone": "America/Los_Angeles",
        "start_hour": 9, "end_hour": 17, "ring_seconds": 20,
        "total_budget_seconds": 90, "priority": 10,
    }
    repository.replace_voice_routes("tenant-a", [route])
    assert repository.voice_routes("tenant-a") == [route]
    assert repository.voice_routes("tenant-b") == []
    repository.replace_voice_routes("tenant-a", [])
    assert repository.voice_routes("tenant-a") == []
