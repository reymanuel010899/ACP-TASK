# AgentTrust Registry Deployment Guide

This document describes how to deploy and run the AgentTrust Reference Registry as an independent, isolated service that multiple applications can connect to.

## Quick Start

### Prerequisites

- Docker and Docker Compose installed (or Python 3.11+)
- Port 8090 available on your system

### Option 1: Docker Compose (Recommended)

```bash
cd registry/
docker-compose up
```

The registry will:
- Build the Docker image from `Dockerfile`
- Start on `http://localhost:8090`
- Expose the data volume at `/data` for persistence
- Auto-restart on failure (unless-stopped)

Verify it's running:

```bash
curl http://localhost:8090/healthz
# Expected: {"status": "ok"}
```

Stop the registry:

```bash
docker-compose down
```

### Option 2: Docker (Direct)

```bash
# Build
docker build -f registry/Dockerfile -t agenttrust-registry:latest .

# Run
docker run -p 8090:8090 \
  -e REGISTRY_HOST=0.0.0.0 \
  -e REGISTRY_PORT=8090 \
  -v registry_data:/data \
  --restart unless-stopped \
  --name agenttrust-registry \
  agenttrust-registry:latest
```

### Option 3: Local Python (Development)

```bash
# From project root
pip install -r requirements.txt

# Start registry with defaults
python -m registry.app

# Or with custom options
python -m registry.app --port 8090 --host 0.0.0.0
```

## Environment Variables

When using Docker, configure via `docker-compose.yml` environment block:

| Variable | Default | Description |
| --- | --- | --- |
| `REGISTRY_HOST` | `0.0.0.0` | Bind address (0.0.0.0 for all interfaces) |
| `REGISTRY_PORT` | `8090` | Listening port |

## Command-Line Options

When running with `python -m registry.app`:

```
--port <int>              Listening port (default: 8090)
--host <str>              Bind address (default: 127.0.0.1)
--verification-url <url>  Base URL of verification service for lazy reputation fetches
--api-keys-file <path>    JSON file with initial valid API keys (array of strings)
--index-path <path>       JSON file for persisting agent registrations
--admin-token <token>     Bearer token required for POST /admin/api-keys (if set)
--rate-limit <int>        Max requests per IP per 60s (0 = off, default: 0)
```

### Example: With Verification Service

```bash
python -m registry.app \
  --port 8090 \
  --host 0.0.0.0 \
  --verification-url http://verification-service:8091 \
  --api-keys-file ./api_keys.json \
  --index-path ./data/registrations.json \
  --admin-token secret_admin_token_here
```

## Data Persistence

### Docker Compose (Recommended)

The `registry_data` volume persists files in `/data` inside the container:

```yaml
volumes:
  - registry_data:/data
```

To use file-based persistence when running the registry, pass these flags:

```bash
# In docker-compose.yml, modify the service command:
python -m registry.app \
  --index-path /data/registrations.json \
  --api-keys-file /data/api_keys.json
```

### Local Development

For local testing, you can pass `--index-path` to persist registrations:

```bash
python -m registry.app \
  --index-path ./registry_data.json \
  --api-keys-file ./api_keys.json
```

## API Endpoints

Once the registry is running, apps can use these endpoints:

### Health Check

```bash
curl http://localhost:8090/healthz
```

### Agent Registration

```bash
# First, get an API key
curl -X POST http://localhost:8090/admin/api-keys

# Then register an agent
curl -X POST http://localhost:8090/register \
  -H "Content-Type: application/json" \
  -d '{
    "principal_id": "agent_alice",
    "api_key": "atk_...",
    "agent_card": {
      "capabilities": {
        "extensions": [{
          "uri": "https://agenttrust.example/extensions/trust/v1"
        }]
      },
      "skills": [{"id": "code_review"}]
    }
  }'
```

### Agent Search

```bash
curl "http://localhost:8090/search?capability=code_review"
```

### User Registration

```bash
curl -X POST http://localhost:8090/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "principal_id": "user_bob",
    "username": "bob"
  }'
```

### User Login

```bash
curl -X POST http://localhost:8090/auth/login \
  -H "Content-Type: application/json" \
  -d '{"principal_id": "user_bob"}'
```

### Record User Reputation

```bash
curl -X POST http://localhost:8090/users/user_bob/reputation \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "task_123",
    "capability_id": "code_review",
    "verified": true
  }'
```

## Networking

### Docker Compose Network

Services in `docker-compose.yml` communicate via the default bridge network. The registry service name is `registry`, so other services would connect to:

```
http://registry:8090
```

### Multi-Container Setup

To extend the compose file with other services (Console, Marketplace, Gig Board):

```yaml
services:
  registry:
    # ... existing config ...

  console:
    build: ./console
    depends_on:
      - registry
    environment:
      REGISTRY_URL: http://registry:8090

  marketplace:
    build: ./marketplace
    depends_on:
      - registry
    environment:
      REGISTRY_URL: http://registry:8090

  gig-board:
    build: ./gig-board
    depends_on:
      - registry
    environment:
      REGISTRY_URL: http://registry:8090
```

## Monitoring & Observability

### Health Check

Docker automatically monitors the HEALTHCHECK directive:

```bash
docker ps  # Look for "healthy" status
docker logs agenttrust-registry  # View logs
```

### Manual Verification

```bash
# Registry is up
curl -s http://localhost:8090/healthz | jq .

# Register a test agent
curl -s -X POST http://localhost:8090/admin/api-keys | jq .

# Search for capabilities
curl -s "http://localhost:8090/search?capability=test" | jq .
```

## Troubleshooting

### Port Already in Use

```bash
# Find what's using port 8090
lsof -i :8090

# Kill it (if safe)
kill -9 <PID>

# Or run on a different port
python -m registry.app --port 8091
```

### Container Won't Start

```bash
# Check logs
docker logs agenttrust-registry

# Rebuild without cache
docker-compose up --build
```

### Data Not Persisting

Ensure `--index-path` is passed to the registry and volume is mounted:

```yaml
volumes:
  - registry_data:/data

# Then in command: --index-path /data/registrations.json
```

### Verification Service Integration

If `--verification-url` is set and the verification service is down, reputation will be treated as neutral (no error). To debug:

```bash
curl http://verification-service:8091/reputation/principal_id?capability_id=test
```

## Security Considerations for Phase B

Before production deployment:

1. **Admin Token** — Always set `--admin-token` in production; never leave `/admin/api-keys` open
2. **Rate Limiting** — Enable `--rate-limit` to prevent abuse
3. **TLS/HTTPS** — Add a reverse proxy (nginx/Caddy) in front of the registry for encryption
4. **API Key Rotation** — Implement key rotation policy
5. **Audit Logging** — Add structured logging to track registrations and searches
6. **Database Migration** — Migrate from JSON files to PostgreSQL for scale
7. **Access Control** — Gate access by IP, API key tier, or OAuth2

See `PRODUCTION_READY.md` for the full Phase B checklist.

## Running Multiple Registries

Each registry is independent. To run multiple instances (for high availability):

```yaml
services:
  registry-1:
    build:
      context: ..
      dockerfile: registry/Dockerfile
    ports:
      - "8090:8090"
    environment:
      REGISTRY_HOST: 0.0.0.0
      REGISTRY_PORT: 8090

  registry-2:
    build:
      context: ..
      dockerfile: registry/Dockerfile
    ports:
      - "8091:8090"
    environment:
      REGISTRY_HOST: 0.0.0.0
      REGISTRY_PORT: 8090

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
```

## Support

For issues or questions:
- Check logs: `docker logs agenttrust-registry`
- Review this guide's Troubleshooting section
- File an issue in the project repository
