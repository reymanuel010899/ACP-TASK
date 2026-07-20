import React, { useState } from 'react';
import { useUserSession } from '../../hooks/useUserSession';

export default function LoginPrincipal({ onLoginSuccess }: { onLoginSuccess: () => void }) {
  const [principalId, setPrincipalId] = useState('');
  const { login, error } = useUserSession();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const success = await login(principalId);
    if (success) {
      onLoginSuccess();
    }
  };

  return (
    <form onSubmit={handleSubmit}>
      <h2>Log In</h2>
      {error && <div className="error-message">{error}</div>}
      <div className="form-group">
        <label>Principal ID (ed25519)</label>
        <input
          type="text"
          value={principalId}
          onChange={(e) => setPrincipalId(e.target.value)}
          placeholder="e.g., ed25519_..."
          required
        />
      </div>
      <button type="submit" className="btn btn-primary">
        Log In
      </button>
    </form>
  );
}
