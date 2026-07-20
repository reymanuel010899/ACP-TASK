import React, { useState } from 'react';
import { useUserSession } from '../../hooks/useUserSession';

export default function RegisterPrincipal({ onRegisterSuccess }: { onRegisterSuccess: () => void }) {
  const [principalId, setPrincipalId] = useState('');
  const { register, error } = useUserSession();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const success = await register(principalId);
    if (success) {
      onRegisterSuccess();
    }
  };

  return (
    <form onSubmit={handleSubmit}>
      <h2>Register</h2>
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
      <p style={{ fontSize: '0.85rem', color: '#999' }}>
        Your Principal ID is your unique identity. Keep it safe!
      </p>
      <button type="submit" className="btn btn-primary">
        Register
      </button>
    </form>
  );
}
