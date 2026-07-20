/**
 * Home.jsx — Main dashboard for the Web Console (U2).
 *
 * Shows:
 * - Login/register forms if not authenticated
 * - Task submission form if authenticated
 * - User reputation if authenticated
 * - Logout button if authenticated
 *
 * This is the entry point for the web console UI. It integrates:
 * - useUserSession hook (from U2)
 * - Auth pages (RegisterPrincipal, LoginPrincipal)
 * - ReputationDisplay component
 * - Task submission (existing console feature)
 *
 * Usage:
 * ```jsx
 * <Home />
 * ```
 */

import React, { useState } from 'react';
import { useUserSession } from '../hooks/useUserSession';
import RegisterPrincipal from './Auth/RegisterPrincipal';
import LoginPrincipal from './Auth/LoginPrincipal';
import ReputationDisplay from '../components/ReputationDisplay';

export default function Home() {
  const { session, reputation, logout, loading } = useUserSession();
  const [authMode, setAuthMode] = useState(null); // 'login' | 'register' | null
  const [taskText, setTaskText] = useState('');
  const [taskResult, setTaskResult] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmitTask = async (e) => {
    e.preventDefault();

    if (!taskText.trim()) {
      alert('Please describe what you need.');
      return;
    }

    setSubmitting(true);
    try {
      const resp = await fetch('/api/task', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: taskText.trim() }),
      });

      if (!resp.ok) {
        const error = await resp.json();
        setTaskResult({
          error: error.error || 'Request failed',
        });
        return;
      }

      const result = await resp.json();
      setTaskResult(result);
      setTaskText('');
    } catch (e) {
      setTaskResult({
        error: `Error: ${String(e)}`,
      });
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return <div className="container">Loading...</div>;
  }

  // Show auth forms if not logged in
  if (!session) {
    return (
      <div className="container">
        <h1>AgentTrust</h1>
        <p className="subtitle">
          Your agent discovers providers, negotiates competitively,
          and brings verified results — all on a federated network.
        </p>

        {authMode === 'register' ? (
          <>
            <RegisterPrincipal
              onRegisterSuccess={() => setAuthMode(null)}
            />
            <button
              onClick={() => setAuthMode('login')}
              className="link-button"
            >
              Already have an account? Log in
            </button>
          </>
        ) : authMode === 'login' ? (
          <>
            <LoginPrincipal
              onLoginSuccess={() => setAuthMode(null)}
            />
            <button
              onClick={() => setAuthMode('register')}
              className="link-button"
            >
              Don't have an account? Create one
            </button>
          </>
        ) : (
          <div className="auth-options">
            <button
              onClick={() => setAuthMode('login')}
              className="btn btn-primary"
            >
              Log In
            </button>
            <button
              onClick={() => setAuthMode('register')}
              className="btn btn-secondary"
            >
              Create Account
            </button>
          </div>
        )}
      </div>
    );
  }

  // Show dashboard if logged in
  return (
    <div className="container">
      <div className="header">
        <h1>AgentTrust Console</h1>
        <button onClick={logout} className="btn btn-outline">
          Log Out
        </button>
      </div>

      {/* User reputation */}
      <ReputationDisplay
        principal={session.principal_id}
        reputation={reputation}
      />

      {/* Task submission */}
      <div className="task-card">
        <h2>Submit a Task</h2>
        <p className="description">
          Describe what you need. Your agent will search for providers,
          negotiate price, and bring verified results.
        </p>

        <form onSubmit={handleSubmitTask}>
          <div className="form-group">
            <label htmlFor="task-input">What do you need?</label>
            <input
              id="task-input"
              type="text"
              placeholder="E.g., I need Terraform infrastructure for a web app with 3 containers"
              value={taskText}
              onChange={(e) => setTaskText(e.target.value)}
              disabled={submitting}
            />
          </div>

          <button
            type="submit"
            className={`btn btn-primary ${submitting ? 'btn-loading' : ''}`}
            disabled={submitting || !taskText.trim()}
          >
            {submitting
              ? 'Searching and negotiating…'
              : 'Submit to My Agent'}
          </button>
        </form>

        {taskResult && (
          <div
            className={`task-result ${
              taskResult.error ? 'error' : 'success'
            }`}
          >
            {taskResult.error ? (
              <div>
                <p className="error-label">Error</p>
                <p>{taskResult.error}</p>
              </div>
            ) : (
              <div>
                <p className="success-label">✓ Verified</p>
                {taskResult.provider_name && (
                  <p>
                    Provider: <strong>{taskResult.provider_name}</strong>
                  </p>
                )}
                {taskResult.price_paid && (
                  <p>
                    Price:{' '}
                    <strong>
                      {taskResult.price_paid}{' '}
                      {taskResult.currency || ''}
                    </strong>
                  </p>
                )}
                {taskResult.artifacts?.['main.tf'] && (
                  <pre>{taskResult.artifacts['main.tf']}</pre>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
