# AgentTrust Gig Board (U4)

A federated gig board and service provider directory that proves federation works across different domains.

**Key Difference from Marketplace (U3):** This app is a service provider directory where users can register as providers and be hired for gigs, rather than posting tasks for negotiation.

## Architecture

- **Backend:** Flask-based HTTP server (Python)
- **Frontend:** React with TypeScript
- **Storage:** In-memory (service definitions and gigs)
- **Reputation:** Integrated with shared registry

## Running the App

### Backend

```bash
python -m apps.gig_board.server.app --port 8002 --registry-url http://localhost:8090
```

### Frontend (requires Node.js)

```bash
cd apps/gig-board
npm install
npm run dev  # Development server
npm run build  # Production build
```

Frontend will be available at `http://localhost:5173`

## API Endpoints

### Services (Provider Registration)

- `POST /api/services` - Register as a service provider
- `GET /api/services` - List all services
- `GET /api/services/{service_id}` - Get service details

### Gigs (Bookings)

- `POST /api/gigs` - Create a booking (hire a provider)
- `GET /api/gigs?principal_id=...` - List my gigs
- `POST /api/gigs/{gig_id}/complete` - Mark gig complete → records reputation

## Data Models

### Service

```json
{
  "id": "uuid",
  "provider_principal": "ed25519_...",
  "service_name": "Web Development",
  "description": "Full-stack services",
  "created_at": "2026-07-18T...",
  "gigs_completed": 0,
  "rating": null
}
```

### Gig

```json
{
  "id": "uuid",
  "service_id": "uuid",
  "provider_principal": "ed25519_...",
  "buyer_principal": "ed25519_...",
  "description": "Project details",
  "status": "active|completed",
  "created_at": "2026-07-18T...",
  "completed_at": null,
  "outcome": null
}
```

## Federation

Same as Marketplace (U3):
- Users log in with Principal (ed25519 key)
- Reputation flows from this app to shared registry
- Cross-app reputation visible (same Principal works everywhere)

## Testing

```bash
pytest tests/gig-board/test_gig_board_app.py -v
```

Tests verify:
- Service registration and listing
- Gig creation and completion
- Authorization (only buyer can complete)
- Self-hire prevention
- Full lifecycle flows
- Pagination and error cases
