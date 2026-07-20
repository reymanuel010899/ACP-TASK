/**
 * LoginPrincipal.jsx — User login with Principal (ed25519 key).
 *
 * Allows users to log in by pasting their Principal. This Principal is portable
 * across all federated apps (Web Console, Marketplace, Gig Board, etc).
 *
 * Session is stored in localStorage with key 'agentTrust_session'.
 *
 * Usage:
 * ```jsx
 * <LoginPrincipal onLoginSuccess={() => navigate('/dashboard')} />
 * ```
 */

import React, { useState } from 'react';
import { useUserSession } from '../../hooks/useUserSession';

export default function LoginPrincipal({ onLoginSuccess = null }) {
  const [principal, setPrincipal] = useState('');
  const { login, loading, error } = useUserSession();

  const handleLogin = async (e) => {
    e.preventDefault();

    if (!principal.trim()) {
      alert('Please paste your Principal.');
      return;
    }

    const success = await login(principal.trim());
    if (success && onLoginSuccess) {
      onLoginSuccess();
    }
  };

  return (
    <div className="login-principal-card">
      <h2>Log In to AgentTrust</h2>
      <p className="description">
        Enter your Principal to access all three federated apps with a single identity.
      </p>

      <form onSubmit={handleLogin}>
        <div className="form-group">
          <label htmlFor="principal-input">
            Your Principal (ed25519 key)
          </label>
          <textarea
            id="principal-input"
            className="principal-textarea"
            placeholder="Paste your ed25519 key here (base64 or hex encoded)&#10;Example: AwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=="
            value={principal}
            onChange={(e) => setPrincipal(e.target.value)}
            disabled={loading}
            rows={6}
          />
          <p className="hint">
            Your Principal is your portable identity across Console, Marketplace, and Gig Board.
          </p>
        </div>

        {error && <div className="error-message">{error}</div>}

        <button
          type="submit"
          className={`btn btn-primary ${loading ? 'btn-loading' : ''}`}
          disabled={loading || !principal.trim()}
        >
          {loading ? 'Logging in...' : 'Log In'}
        </button>
      </form>

      <div className="divider">or</div>

      <div className="signup-prompt">
        <p>Don't have an account yet?</p>
        <button type="button" className="btn btn-secondary">
          Create One
        </button>
      </div>
    </div>
  );
}
