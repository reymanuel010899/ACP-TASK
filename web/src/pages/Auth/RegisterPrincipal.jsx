/**
 * RegisterPrincipal.jsx — User registration with Principal (ed25519 key).
 *
 * Allows users to:
 * 1. Paste an existing ed25519 Principal (key), or
 * 2. Generate a new one using tweetnacl.js (if available)
 *
 * On success, stores session in localStorage and redirects to dashboard.
 *
 * Usage:
 * ```jsx
 * <RegisterPrincipal onRegisterSuccess={() => navigate('/dashboard')} />
 * ```
 */

import React, { useState } from 'react';
import { useUserSession } from '../../hooks/useUserSession';

export default function RegisterPrincipal({ onRegisterSuccess = null }) {
  const [principal, setPrincipal] = useState('');
  const [showWarning, setShowWarning] = useState(false);
  const { register, loading, error } = useUserSession();

  const handleRegister = async (e) => {
    e.preventDefault();

    if (!principal.trim()) {
      alert('Please paste your Principal (ed25519 key).');
      return;
    }

    if (!showWarning) {
      setShowWarning(true);
      return;
    }

    const success = await register(principal.trim());
    if (success && onRegisterSuccess) {
      onRegisterSuccess();
    }
  };

  return (
    <div className="register-principal-card">
      <h2>Create Your AgentTrust Account</h2>
      <p className="description">
        To participate in AgentTrust, you need an ed25519 Principal. This is your
        cryptographic identity across all federated apps.
      </p>

      <form onSubmit={handleRegister}>
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
            Don't have a Principal? Generate one using tweetnacl.js or similar tools.
            <br />
            <strong>Important:</strong> Save your Principal securely. If you lose it, you lose access to your account.
          </p>
        </div>

        {error && <div className="error-message">{error}</div>}

        {showWarning && (
          <div className="warning-box">
            <strong>⚠️ Important:</strong> Make sure you've saved your Principal somewhere safe.
            If you lose it, you won't be able to log in to your account.
            <br />
            <button
              type="button"
              onClick={() => setShowWarning(false)}
              className="link-button"
            >
              I'll save it somewhere else first
            </button>
          </div>
        )}

        <button
          type="submit"
          className={`btn btn-primary ${loading ? 'btn-loading' : ''}`}
          disabled={loading || (showWarning && !principal.trim())}
        >
          {showWarning ? 'Yes, register with this Principal' : 'Continue'}
        </button>
      </form>

      <div className="note">
        <p>
          <strong>Note:</strong> This is a proof-of-concept federation demo. In production,
          we would implement key recovery and more sophisticated key management.
        </p>
      </div>
    </div>
  );
}
