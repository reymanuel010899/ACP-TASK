import React from 'react';
import { UserReputation } from '../hooks/useUserSession';

interface Props {
  principal: string;
  reputation: UserReputation | null;
}

export default function ReputationDisplay({ principal, reputation }: Props) {
  if (!reputation) {
    return (
      <div className="reputation-display">
        <div className="reputation-score">--</div>
        <div className="reputation-label">Loading reputation...</div>
      </div>
    );
  }

  return (
    <div className="reputation-display">
      <div className="reputation-score">{reputation.tasks_verified}</div>
      <div className="reputation-label">Verified Gigs</div>
      {reputation.verification_rate !== null && (
        <div style={{ fontSize: '0.8rem', marginTop: '0.5rem' }}>
          Rate: {(reputation.verification_rate * 100).toFixed(0)}%
        </div>
      )}
    </div>
  );
}
