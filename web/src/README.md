# Web Console React Components (U2)

This directory contains reusable React components for user authentication and session management. These components are designed to be shared across all three federated apps: Web Console (U2), Marketplace (U3), and Gig Board (U4).

## Shared Components & Hooks

### `hooks/useUserSession.ts`

Core React hook for session management. Used by all apps.

**Features:**
- Load session from localStorage
- Login with Principal (ed25519 key)
- Register new user with Principal
- Load user reputation
- Logout
- Error handling

**Usage:**
```jsx
const { session, reputation, login, logout, loading, error } = useUserSession();

if (loading) return <div>Loading...</div>;
if (!session) return <LoginForm onLogin={login} />;

return (
  <Dashboard 
    principal={session.principal_id}
    reputation={reputation}
    onLogout={logout}
  />
);
```

### `pages/Auth/LoginPrincipal.jsx`

Login form component. Users paste their Principal to log in.

**Props:**
- `onLoginSuccess: () => void` — callback when login succeeds

**Usage:**
```jsx
import LoginPrincipal from './pages/Auth/LoginPrincipal';

<LoginPrincipal onLoginSuccess={() => navigate('/dashboard')} />
```

### `pages/Auth/RegisterPrincipal.jsx`

Registration form component. Users paste or generate a Principal to create an account.

**Props:**
- `onRegisterSuccess: () => void` — callback when registration succeeds

**Usage:**
```jsx
import RegisterPrincipal from './pages/Auth/RegisterPrincipal';

<RegisterPrincipal onRegisterSuccess={() => navigate('/dashboard')} />
```

### `components/ReputationDisplay.jsx`

Display user reputation with stats and breakdown by capability.

**Props:**
- `principal: string` — user's Principal ID
- `reputation: UserReputation | null` — reputation data from API

**Usage:**
```jsx
import ReputationDisplay from './components/ReputationDisplay';

<ReputationDisplay 
  principal={session.principal_id}
  reputation={reputation}
/>
```

## API Contract

All components assume the following API endpoints exist on the app server:

### POST `/api/auth/register`

Register a new user.

**Request:**
```json
{
  "principal_id": "AwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=="
}
```

**Response (200):**
```json
{
  "status": "registered",
  "principal_id": "AwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA==",
  "reputation": {
    "tasks_verified": 0,
    "tasks_rejected": 0,
    "verification_rate": null
  },
  "user": { ... }
}
```

**Error (409):**
```json
{
  "error": "principal already registered"
}
```

### POST `/api/auth/login`

Log in a user.

**Request:**
```json
{
  "principal_id": "AwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=="
}
```

**Response (200):**
```json
{
  "status": "ok",
  "principal_id": "AwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA==",
  "reputation": {
    "tasks_verified": 0,
    "tasks_rejected": 0,
    "verification_rate": null
  },
  "user": { ... }
}
```

**Error (404):**
```json
{
  "error": "principal not found"
}
```

### GET `/api/reputation/{principal_id}`

Fetch user reputation.

**Response (200):**
```json
{
  "principal_id": "...",
  "reputation_records": [
    {
      "capability_id": "terraform.generate",
      "tasks_verified": 5,
      "tasks_rejected": 1,
      "verification_rate": 0.833
    }
  ],
  "created_at": "2026-07-18T...",
  "last_active": "2026-07-18T..."
}
```

**Error (404):**
```json
{
  "error": "principal not found"
}
```

## Integration Guide for U3 (Marketplace) and U4 (Gig Board)

1. **Copy these components** into your app's `src/` directory
2. **Implement the API endpoints** that match the contract above in your backend
3. **Use `useUserSession`** hook in your page components:
   ```jsx
   const { session, reputation, login, logout } = useUserSession();
   ```
4. **Guard protected routes** with session check:
   ```jsx
   if (!session) return <LoginPrincipal onLoginSuccess={...} />;
   ```
5. **Display reputation** using ReputationDisplay component
6. **Call logout** when user clicks logout button

## Session Storage

Sessions are stored in browser `localStorage` with key:
```
agentTrust_session
```

Data structure:
```json
{
  "principal_id": "AwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=="
}
```

Session persists across page reloads and app restarts.

## Environment Variables

Optional environment variables for configuration:

```bash
REACT_APP_REGISTRY_URL=http://localhost:8090  # Registry URL (if direct access needed)
REACT_APP_CONSOLE_URL=http://localhost:8000    # Console URL (if cross-app calls needed)
```

## Type Definitions

### UserSession
```typescript
interface UserSession {
  principal_id: string;
  token?: string;
}
```

### UserReputation
```typescript
interface UserReputation {
  principal_id: string;
  tasks_verified: number;
  tasks_rejected: number;
  verification_rate: number | null;
  reputation_records?: Array<{
    capability_id: string;
    tasks_verified: number;
    tasks_rejected: number;
    verification_rate: number | null;
  }>;
}
```

## Notes for Developers

- **Principal Format:** ed25519 keys, typically 44 characters (base64) or 64 characters (hex)
- **No Server-Side Sessions:** Sessions are managed client-side via localStorage. The backend only validates Principals against the registry
- **Reputation Fetching:** `useUserSession` automatically loads reputation when session is loaded or set
- **Error Handling:** All hooks include error states. Components should display `error` message to user
- **TypeScript:** `useUserSession.ts` is written in TypeScript but components are JSX for simplicity. You can convert components to .tsx if needed
- **Styling:** Components don't include CSS. Style them with your app's design system (see Material 3 tokens in `app_typography.dart`)

## Testing

Example integration test:
```python
def test_user_flow():
    # Register
    resp = requests.post('/api/auth/register', 
        json={'principal_id': 'AwAAAAAAAAA...'})
    assert resp.status_code == 200
    
    # Login
    resp = requests.post('/api/auth/login',
        json={'principal_id': 'AwAAAAAAAAA...'})
    assert resp.status_code == 200
    
    # Fetch reputation
    resp = requests.get('/api/reputation/AwAAAAAAAAA...')
    assert resp.status_code == 200
```

See `tests/web/test_user_auth.py` for complete test examples.
