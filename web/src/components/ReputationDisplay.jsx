/**
 * ReputationDisplay.jsx — Display user reputation summary.
 *
 * Shows:
 * - Principal ID (truncated)
 * - Total tasks verified
 * - Total tasks rejected
 * - Verification rate (percentage)
 * - Breakdown by capability (if available)
 *
 * If no reputation records exist, shows "No reputation yet" message.
 *
 * Usage:
 * ```jsx
 * <ReputationDisplay
 *   principal={session.principal_id}
 *   reputation={reputation}
 * />
 * ```
 */

import React from 'react';

export default function ReputationDisplay({ principal, reputation }) {
  if (!principal) {
    return (
      <div className="reputation-display">
        <p className="muted">Log in to view your reputation.</p>
      </div>
    );
  }

  if (!reputation) {
    return (
      <div className="reputation-display">
        <p className="muted">Loading reputation...</p>
      </div>
    );
  }

  const totalTasks =
    reputation.tasks_verified + reputation.tasks_rejected;
  const hasReputation = totalTasks > 0;
  const verificationRate = reputation.verification_rate;

  return (
    <div className="reputation-display">
      <div className="reputation-header">
        <h3>Your Reputation</h3>
        <p className="principal-display">
          Principal:{' '}
          <code title={principal}>
            {principal.substring(0, 20)}...
          </code>
        </p>
      </div>

      {!hasReputation ? (
        <div className="reputation-empty">
          <p>No reputation yet.</p>
          <p className="hint">
            Your reputation will appear here as you complete tasks
            across AgentTrust apps.
          </p>
        </div>
      ) : (
        <>
          <div className="reputation-stats">
            <div className="stat">
              <div className="stat-label">Tasks Verified</div>
              <div className="stat-value">{reputation.tasks_verified}</div>
            </div>
            <div className="stat">
              <div className="stat-label">Tasks Rejected</div>
              <div className="stat-value error">
                {reputation.tasks_rejected}
              </div>
            </div>
            {verificationRate !== null && (
              <div className="stat">
                <div className="stat-label">Verification Rate</div>
                <div className="stat-value success">
                  {(verificationRate * 100).toFixed(1)}%
                </div>
              </div>
            )}
          </div>

          {reputation.reputation_records &&
            reputation.reputation_records.length > 0 && (
              <div className="reputation-breakdown">
                <h4>By Capability</h4>
                <div className="records-list">
                  {reputation.reputation_records.map(
                    (record, idx) => (
                      <div
                        key={idx}
                        className="reputation-record"
                      >
                        <div className="record-capability">
                          {record.capability_id}
                        </div>
                        <div className="record-stats">
                          <span>
                            {record.tasks_verified} verified
                          </span>
                          <span className="separator">•</span>
                          <span>
                            {record.tasks_rejected} rejected
                          </span>
                          {record.verification_rate !== null && (
                            <>
                              <span className="separator">•</span>
                              <span>
                                {(
                                  record.verification_rate *
                                  100
                                ).toFixed(1)}
                                %
                              </span>
                            </>
                          )}
                        </div>
                      </div>
                    )
                  )}
                </div>
              </div>
            )}
        </>
      )}

      <div className="reputation-note">
        <p>
          Your reputation is stored in the shared registry and visible
          across all federated apps.
        </p>
      </div>
    </div>
  );
}
