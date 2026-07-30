# AgentTrust Registry: Quick Start Guide

This guide gets the independent registry running in 30 seconds.

## Prerequisite: Postgres + Redis

Unit U10: the registry persists through Postgres unconditionally now --
there is no in-memory or JSON-file fallback. Bring these up once, from the
repo root, before any of the options below:

```bash
docker compose -f ../infra/docker-compose.yml up -d   # Postgres 16 + Redis 7
psql "$DATABASE_URL" -f ../infra/roles.sql             # least-privilege roles (idempotent)
python -m tools.migrate                                # apply pending migrations (idempotent)
```

## Option 1: Docker Compose (Recommended for Phase A)

```bash
cd registry/
docker-compose up
```

Done! Registry is running on `http://localhost:8090`

Test it:
```bash
curl http://localhost:8090/healthz
```

## Option 2: Local Python (Development)

```bash
pip install -r requirements.txt
python -m registry.app
```

Registry starts on `http://localhost:8090` (default)

## Option 3: Docker Direct

```bash
docker build -f registry/Dockerfile -t registry:latest .
docker run -p 8090:8090 registry:latest
```

## Quick API Test

### 1. Get an API key
```bash
API_KEY=$(curl -s -X POST http://localhost:8090/admin/api-keys | jq -r '.api_key')
echo "API Key: $API_KEY"
```

### 2. Register a user
```bash
curl -X POST http://localhost:8090/auth/register \
  -H "Content-Type: application/json" \
  -d '{"principal_id": "user_alice", "username": "alice"}'
```

### 3. Record reputation
```bash
curl -X POST http://localhost:8090/users/user_alice/reputation \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "task_1",
    "capability_id": "code_review",
    "verified": true
  }'
```

### 4. Query user
```bash
curl http://localhost:8090/users/user_alice | jq .
```

## Multi-App Demo

Start three simulated apps:

```bash
# Terminal 1: Start registry
cd registry/
docker-compose up

# Terminal 2: Simulate Console app
python3 << 'EOF'
import requests
import time

time.sleep(2)  # Wait for registry

api_key = requests.post("http://localhost:8090/admin/api-keys").json()["api_key"]
print("[Console] API Key:", api_key)

user = requests.post("http://localhost:8090/auth/register",
    json={"principal_id": "user_bob", "username": "bob"}).json()
print("[Console] Registered user:", user["principal_id"])

rep = requests.post("http://localhost:8090/users/user_bob/reputation",
    json={"task_id": "task_1", "capability_id": "code_review", "verified": True}).json()
print("[Console] Recorded reputation: verified=True")
EOF

# Terminal 3: Simulate Marketplace app
python3 << 'EOF'
import requests
import time

time.sleep(4)  # Wait for Console to register user

rep = requests.post("http://localhost:8090/users/user_bob/reputation",
    json={"task_id": "task_2", "capability_id": "code_review", "verified": True}).json()
print("[Marketplace] Recorded reputation: verified=True")

user = requests.get("http://localhost:8090/users/user_bob").json()
print("[Marketplace] Queried user, reputation records:")
for record in user["reputation_records"]:
    print(f"  - {record['capability_id']}: {record['tasks_verified']} verified, {record['tasks_rejected']} rejected")
EOF

# Terminal 4: Simulate Gig Board app
python3 << 'EOF'
import requests
import time

time.sleep(6)  # Wait for Marketplace to record reputation

rep = requests.post("http://localhost:8090/users/user_bob/reputation",
    json={"task_id": "task_3", "capability_id": "code_review", "verified": False}).json()
print("[Gig Board] Recorded reputation: verified=False")

user = requests.get("http://localhost:8090/users/user_bob").json()
print("[Gig Board] Queried user, final reputation:")
for record in user["reputation_records"]:
    print(f"  - {record['capability_id']}: {record['tasks_verified']} verified, {record['tasks_rejected']} rejected (rate: {record['verification_rate']})")
EOF
```

Expected output:
```
[Console] API Key: atk_XXX...
[Console] Registered user: user_bob
[Console] Recorded reputation: verified=True

[Marketplace] Recorded reputation: verified=True
[Marketplace] Queried user, reputation records:
  - code_review: 1 verified, 0 rejected

[Gig Board] Recorded reputation: verified=False
[Gig Board] Queried user, final reputation:
  - code_review: 2 verified, 1 rejected (rate: 0.67)
```

This demonstrates:
- Multiple apps can connect to a single independent registry
- Apps can write reputation concurrently
- Registry correctly aggregates reputation data
- No app corrupts another's data

## Configuration

See `DEPLOYMENT.md` for:
- All command-line options
- Environment variables
- Persistence options
- Networking setup
- Troubleshooting

See `PRODUCTION_READY.md` for:
- Phase B production requirements
- Security hardening
- Monitoring & observability
- Database migration planning

## API Reference

| Endpoint | Method | Description |
| --- | --- | --- |
| `/healthz` | GET | Health check |
| `/admin/api-keys` | POST | Mint API key |
| `/auth/register` | POST | Register user |
| `/auth/login` | POST | Log in user |
| `/users/{principal_id}` | GET | Get user & reputation |
| `/users/{principal_id}/reputation` | POST | Record reputation event |
| `/register` | POST | Register agent (existing) |
| `/search` | GET | Search capabilities (existing) |

## Next Steps

1. **Phase A:** Verify multi-app scenarios work
2. **Phase B:** Implement production requirements from `PRODUCTION_READY.md`
3. **Scale:** Use load balancing and database replication

## Support

- **Logs:** `docker logs agenttrust-registry`
- **Docs:** See `DEPLOYMENT.md`
- **Tests:** `python3 -m pytest tests/integration/ -v`
- **Issues:** Check troubleshooting section in `DEPLOYMENT.md`
