# AgentTrust Task Marketplace (U3)

A federated task marketplace where users can post tasks, discover available work, negotiate outcomes, and earn reputation.

## Features

- **Post Tasks**: Create new marketplace tasks with detailed descriptions
- **Discover Tasks**: Browse available tasks posted by other users
- **Accept Tasks**: Workers can accept open tasks to earn reputation
- **Negotiation**: Real-time message exchange between task authors and workers
- **Reputation System**: Completed tasks automatically record reputation in the federated registry
- **Portable Identity**: Use your Principal across all federated apps (Console, Marketplace, Gig Board)

## Architecture

### Backend (`apps/marketplace/server/app.py`)

Python Flask-based HTTP server with 7 endpoints:

- `POST /api/tasks` - Create a new task
- `GET /api/tasks` - List all tasks with pagination
- `GET /api/tasks/{task_id}` - Get task details
- `POST /api/tasks/{task_id}/accept` - Accept a task as worker
- `POST /api/negotiations/{task_id}` - Send negotiation message
- `GET /api/negotiations/{task_id}` - Get negotiation thread
- `POST /api/negotiations/{task_id}/complete` - Complete task and record reputation

**Data Model:**
```python
{
  "id": "uuid",
  "author_principal": "ed25519_...",
  "description": "What needs to be done",
  "status": "open|accepted|completed",
  "created_at": "2026-07-18T...",
  "worker_principal": None or "ed25519_...",
  "negotiations": [
    {"from": "principal", "message": "text", "timestamp": "..."}
  ],
  "outcome": None or "completion description"
}
```

### Frontend (`apps/marketplace/src/`)

React + TypeScript app with:

- **Hooks**: 
  - `useUserSession` - Session & reputation management
  - `useTasks` - Task CRUD operations
  - `useNegotiation` - Negotiation messaging
  
- **Components**:
  - `LoginPrincipal` / `RegisterPrincipal` - Auth flows
  - `TaskList` - Browse tasks
  - `TaskDetail` - View task + accept
  - `PostTaskForm` - Create new task
  - `NegotiationThread` - Chat + completion
  - `ReputationDisplay` - User reputation

- **Services**:
  - `api.ts` - HTTP client for marketplace backend
  - `marketplace.ts` - TypeScript types

## Getting Started

### Backend

```bash
# Start the marketplace server
python3 -m apps.marketplace.server.app --port 8001 --registry-url http://localhost:8090

# Or run tests
python3 -m pytest tests/marketplace/test_marketplace_app.py -v
```

### Frontend

```bash
cd apps/marketplace

# Install dependencies
npm install

# Development server (port 3000, proxies /api to localhost:8001)
npm run dev

# Build for production
npm run build

# Preview production build
npm run preview
```

## Usage Flow

### For Task Authors:
1. Register/Login with your Principal
2. Navigate to "Post Task"
3. Describe what you need done
4. View incoming offers on "Browse Tasks"
5. When worker accepts: discuss in "My Negotiations"
6. When satisfied: mark task complete and record reputation

### For Workers:
1. Register/Login with your Principal
2. Browse available tasks on "Browse Tasks"
3. Find interesting work and click "Accept Task"
4. Discuss details in "My Negotiations" tab
5. Complete the work - author marks it done
6. Reputation recorded in federated registry

## Federation

The marketplace integrates with the registry to:
- Store and retrieve user reputation
- Record completed tasks as reputation events
- Query aggregated reputation across capabilities

All principals are portable - the same Principal works across Console, Marketplace, and any other federated app.

## Testing

Run comprehensive tests:
```bash
python3 -m pytest tests/marketplace/ -v
```

Tests cover:
- Endpoint CRUD operations
- Pagination and filtering
- Authorization checks (only author can complete)
- End-to-end flow (post → accept → negotiate → complete → reputation)
- Error handling and validation

## Environment Variables

Create `.env` file in `apps/marketplace/`:

```
REACT_APP_MARKETPLACE_URL=http://localhost:8001/api
REACT_APP_REGISTRY_URL=http://localhost:8090
REACT_APP_CONSOLE_URL=http://localhost:8000
```

## Database

Uses in-memory storage for MVP. No database required. Tasks are stored in a thread-safe dictionary and lost on restart.

For production, integrate with a persistent store (PostgreSQL, etc).

## Security Notes

- All endpoints validate authorization (e.g., only task author can mark complete)
- Messages can only be sent by author or worker
- No API key auth for MVP (secure with bearer tokens in production)
- Reputation records only created when task completion is marked

## Future Enhancements

- Task search and filtering by category/price
- Reputation-based worker ranking
- Dispute resolution for completed tasks
- Escrow payment system
- Rating and reviews
- Task deadline tracking
- Automatic reputation updates based on outcome feedback
