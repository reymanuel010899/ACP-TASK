/**
 * React hook for user session management (U2, U3, U4).
 *
 * Provides:
 * - Session loading from localStorage
 * - Session persistence
 * - Reputation fetching from registry
 * - Login/logout operations
 * - Session context for all apps
 *
 * Usage:
 * ```tsx
 * const { session, reputation, login, logout, loading } = useUserSession();
 * if (loading) return <div>Loading...</div>;
 * if (!session) return <LoginForm onLogin={login} />;
 * return <Dashboard principal={session.principal_id} reputation={reputation} />;
 * ```
 */

import { useState, useEffect, useCallback } from 'react';

const SESSION_STORAGE_KEY = 'agentTrust_session';
const REGISTRY_URL = (import.meta.env.VITE_REGISTRY_URL || 'http://localhost:8090') as string;
const CONSOLE_API_URL = (import.meta.env.VITE_CONSOLE_URL || 'http://localhost:8000') as string;

export interface UserSession {
  principal_id: string;
  token?: string;
}

export interface UserReputation {
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

export interface UseUserSessionReturn {
  session: UserSession | null;
  reputation: UserReputation | null;
  loading: boolean;
  error: string | null;
  login: (principalId: string) => Promise<boolean>;
  register: (principalId: string) => Promise<boolean>;
  logout: () => void;
  loadReputation: () => Promise<void>;
}

export function useUserSession(): UseUserSessionReturn {
  const [session, setSession] = useState<UserSession | null>(null);
  const [reputation, setReputation] = useState<UserReputation | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Load session from localStorage on mount
  useEffect(() => {
    const loadSessionFromStorage = () => {
      try {
        const saved = localStorage.getItem(SESSION_STORAGE_KEY);
        if (saved) {
          const session = JSON.parse(saved) as UserSession;
          setSession(session);
          // Load reputation after loading session
          loadReputationForPrincipal(session.principal_id);
        }
      } catch (e) {
        console.error('Failed to load session from storage:', e);
      } finally {
        setLoading(false);
      }
    };

    loadSessionFromStorage();
  }, []);

  const loadReputationForPrincipal = useCallback(async (principalId: string) => {
    try {
      setLoading(true);
      setError(null);

      // First try console API (which is more likely in all apps)
      const apiUrl = `/api/reputation/${encodeURIComponent(principalId)}`;
      const resp = await fetch(apiUrl);

      if (!resp.ok) {
        setReputation(null);
        return;
      }

      const data = await resp.json();
      setReputation({
        principal_id: principalId,
        tasks_verified: data.reputation?.tasks_verified || 0,
        tasks_rejected: data.reputation?.tasks_rejected || 0,
        verification_rate: data.reputation?.verification_rate || null,
        reputation_records: data.reputation_records || [],
      });
    } catch (e) {
      console.error('Failed to load reputation:', e);
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  const loadReputation = useCallback(async () => {
    if (session?.principal_id) {
      await loadReputationForPrincipal(session.principal_id);
    }
  }, [session, loadReputationForPrincipal]);

  const register = useCallback(
    async (principalId: string): Promise<boolean> => {
      try {
        setLoading(true);
        setError(null);

        const resp = await fetch('/api/auth/register', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ principal_id: principalId }),
        });

        if (!resp.ok) {
          const data = await resp.json();
          setError(data.error || 'Registration failed');
          return false;
        }

        const data = await resp.json();
        const newSession: UserSession = { principal_id: data.principal_id };
        localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(newSession));
        setSession(newSession);
        setReputation({
          principal_id: data.principal_id,
          tasks_verified: data.reputation?.tasks_verified || 0,
          tasks_rejected: data.reputation?.tasks_rejected || 0,
          verification_rate: data.reputation?.verification_rate || null,
        });
        return true;
      } catch (e) {
        const msg = String(e);
        setError(msg);
        console.error('Registration error:', e);
        return false;
      } finally {
        setLoading(false);
      }
    },
    []
  );

  const login = useCallback(
    async (principalId: string): Promise<boolean> => {
      try {
        setLoading(true);
        setError(null);

        const resp = await fetch('/api/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ principal_id: principalId }),
        });

        if (!resp.ok) {
          const data = await resp.json();
          setError(data.error || 'Login failed');
          return false;
        }

        const data = await resp.json();
        const newSession: UserSession = { principal_id: data.principal_id };
        localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(newSession));
        setSession(newSession);
        setReputation({
          principal_id: data.principal_id,
          tasks_verified: data.reputation?.tasks_verified || 0,
          tasks_rejected: data.reputation?.tasks_rejected || 0,
          verification_rate: data.reputation?.verification_rate || null,
        });
        return true;
      } catch (e) {
        const msg = String(e);
        setError(msg);
        console.error('Login error:', e);
        return false;
      } finally {
        setLoading(false);
      }
    },
    []
  );

  const logout = useCallback(() => {
    localStorage.removeItem(SESSION_STORAGE_KEY);
    setSession(null);
    setReputation(null);
    setError(null);
  }, []);

  return {
    session,
    reputation,
    loading,
    error,
    login,
    register,
    logout,
    loadReputation,
  };
}
