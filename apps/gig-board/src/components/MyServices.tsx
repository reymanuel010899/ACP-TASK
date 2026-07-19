import React from 'react';
import { useServices } from '../hooks/useServices';

interface Props {
  currentPrincipal: string;
}

export default function MyServices({ currentPrincipal }: Props) {
  const { services, loading, error } = useServices();

  const myServices = services.filter(s => s.provider_principal === currentPrincipal);

  if (loading) {
    return <div className="loading-screen">Loading your services...</div>;
  }

  if (error) {
    return <div className="error-message">Error: {error}</div>;
  }

  if (myServices.length === 0) {
    return (
      <div className="empty-state">
        <p>You haven't created any services yet.</p>
        <p>Go to "Offer Service" to create your first service!</p>
      </div>
    );
  }

  return (
    <div>
      <h2>My Services ({myServices.length})</h2>
      <div className="list-container">
        {myServices.map((service) => (
          <div key={service.id} className="service-card">
            <div className="service-header">
              <div>
                <div className="service-name">{service.service_name}</div>
                <div style={{ fontSize: '0.85rem', color: '#666' }}>
                  ID: {service.id.slice(0, 8)}...
                </div>
              </div>
              {service.gigs_completed > 0 && (
                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontSize: '0.9rem', fontWeight: 'bold' }}>
                    {service.gigs_completed} gigs completed
                  </div>
                </div>
              )}
            </div>
            <div className="service-description">{service.description}</div>
            <div style={{ marginTop: '1rem', padding: '0.75rem', background: '#f0f0f0', borderRadius: '4px', fontSize: '0.9rem' }}>
              <div>Created: {new Date(service.created_at).toLocaleDateString()}</div>
              {service.rating && <div>Rating: {service.rating}</div>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
