import React, { useState } from 'react';
import { useGigs } from '../hooks/useGigs';

interface Props {
  currentPrincipal: string;
  refresh: number;
  onReputationUpdated: () => void;
}

export default function MyGigs({ currentPrincipal, refresh, onReputationUpdated }: Props) {
  const { gigs, loading, error, completeGig } = useGigs(currentPrincipal, refresh);
  const [expandedGigId, setExpandedGigId] = useState<string | null>(null);
  const [outcome, setOutcome] = useState('');
  const [completing, setCompleting] = useState(false);
  const [message, setMessage] = useState<{ type: 'error' | 'success'; text: string } | null>(null);

  const handleCompleteGig = async (gigId: string) => {
    if (!outcome.trim()) {
      setMessage({ type: 'error', text: 'Please provide completion outcome' });
      return;
    }
    setCompleting(true);
    const completed = await completeGig(gigId, currentPrincipal, outcome);
    setCompleting(false);

    if (completed) {
      setMessage({ type: 'success', text: 'Gig completed! Reputation recorded.' });
      setOutcome('');
      setExpandedGigId(null);
      onReputationUpdated();
    } else {
      setMessage({ type: 'error', text: 'Failed to complete gig' });
    }
  };

  if (loading) {
    return <div className="loading-screen">Loading your gigs...</div>;
  }

  if (error) {
    return <div className="error-message">Error: {error}</div>;
  }

  const myGigs = gigs.filter(g => g.buyer_principal === currentPrincipal || g.provider_principal === currentPrincipal);
  const activeGigs = myGigs.filter(g => g.status === 'active');
  const completedGigs = myGigs.filter(g => g.status === 'completed');

  if (myGigs.length === 0) {
    return (
      <div className="empty-state">
        <p>You don't have any gigs yet. Browse services to hire someone!</p>
      </div>
    );
  }

  return (
    <div>
      <h2>My Gigs</h2>
      {message && (
        <div className={`${message.type}-message`}>{message.text}</div>
      )}

      {activeGigs.length > 0 && (
        <>
          <h3>Active Gigs ({activeGigs.length})</h3>
          <div className="list-container">
            {activeGigs.map((gig) => (
              <div key={gig.id} className="gig-card">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start' }}>
                  <div>
                    <div className="gig-status active">Active</div>
                    <div style={{ marginTop: '0.5rem' }}>
                      <strong>
                        {gig.buyer_principal === currentPrincipal ? 'You hired' : 'Hired by'}
                      </strong>
                      <div style={{ fontSize: '0.85rem', color: '#999' }}>
                        {gig.buyer_principal === currentPrincipal
                          ? gig.provider_principal.slice(0, 20)
                          : gig.buyer_principal.slice(0, 20)}...
                      </div>
                    </div>
                  </div>
                </div>
                <div style={{ marginTop: '0.75rem' }}>
                  <p>{gig.description}</p>
                </div>

                {expandedGigId === gig.id ? (
                  <div style={{ marginTop: '1rem', padding: '1rem', background: '#f9f9f9', borderRadius: '4px' }}>
                    <div className="form-group">
                      <label>Outcome/Notes:</label>
                      <textarea
                        value={outcome}
                        onChange={(e) => setOutcome(e.target.value)}
                        placeholder="Describe the outcome of this gig..."
                      />
                    </div>
                    <div style={{ display: 'flex', gap: '0.5rem' }}>
                      <button
                        className="btn btn-primary"
                        onClick={() => handleCompleteGig(gig.id)}
                        disabled={completing}
                      >
                        {completing ? 'Completing...' : 'Mark Complete'}
                      </button>
                      <button
                        className="btn btn-ghost"
                        onClick={() => {
                          setExpandedGigId(null);
                          setOutcome('');
                        }}
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <button
                    className="btn btn-primary"
                    onClick={() => setExpandedGigId(gig.id)}
                    disabled={gig.buyer_principal !== currentPrincipal}
                    style={{ marginTop: '1rem' }}
                  >
                    {gig.buyer_principal !== currentPrincipal
                      ? 'Awaiting buyer to complete'
                      : 'Complete This Gig'}
                  </button>
                )}
              </div>
            ))}
          </div>
        </>
      )}

      {completedGigs.length > 0 && (
        <>
          <h3 style={{ marginTop: '2rem' }}>Completed Gigs ({completedGigs.length})</h3>
          <div className="list-container">
            {completedGigs.map((gig) => (
              <div key={gig.id} className="gig-card" style={{ opacity: 0.7 }}>
                <div className="gig-status completed">Completed</div>
                <div style={{ marginTop: '0.5rem' }}>
                  <p>{gig.description}</p>
                  {gig.outcome && (
                    <div style={{ marginTop: '0.5rem', fontSize: '0.9rem', color: '#666' }}>
                      <strong>Outcome:</strong> {gig.outcome}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
