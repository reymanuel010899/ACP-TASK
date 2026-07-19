import React, { useState } from 'react';
import { useServices } from '../hooks/useServices';
import { useGigs } from '../hooks/useGigs';

interface Props {
  currentPrincipal: string;
  onGigCreated: () => void;
}

export default function ServiceList({ currentPrincipal, onGigCreated }: Props) {
  const { services, loading, error } = useServices();
  const { createGig } = useGigs(currentPrincipal);
  const [selectedServiceId, setSelectedServiceId] = useState<string | null>(null);
  const [gigDescription, setGigDescription] = useState('');
  const [message, setMessage] = useState<{ type: 'error' | 'success'; text: string } | null>(null);

  const handleHireProvider = async (serviceId: string) => {
    if (!gigDescription.trim()) {
      setMessage({ type: 'error', text: 'Please describe the gig' });
      return;
    }
    const gig = await createGig(serviceId, currentPrincipal, gigDescription);
    if (gig) {
      setMessage({ type: 'success', text: 'Gig created! Check "My Gigs" to see it.' });
      setGigDescription('');
      setSelectedServiceId(null);
      setTimeout(() => onGigCreated(), 1000);
    } else {
      setMessage({ type: 'error', text: 'Failed to create gig' });
    }
  };

  if (loading) {
    return <div className="loading-screen">Loading services...</div>;
  }

  if (error) {
    return <div className="error-message">Error: {error}</div>;
  }

  if (services.length === 0) {
    return (
      <div className="empty-state">
        <p>No services available yet. Be the first to offer one!</p>
      </div>
    );
  }

  return (
    <div>
      <h2>Available Services</h2>
      {message && (
        <div className={`${message.type}-message`}>{message.text}</div>
      )}
      <div className="list-container">
        {services.map((service) => (
          <div key={service.id} className="service-card">
            <div className="service-header">
              <div>
                <div className="service-name">{service.service_name}</div>
                <div className="service-provider">
                  by {service.provider_principal.slice(0, 20)}...
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
            {selectedServiceId === service.id ? (
              <div style={{ marginTop: '1rem', padding: '1rem', background: '#f9f9f9', borderRadius: '4px' }}>
                <div className="form-group">
                  <label>Describe the gig:</label>
                  <textarea
                    value={gigDescription}
                    onChange={(e) => setGigDescription(e.target.value)}
                    placeholder="What do you need help with?"
                  />
                </div>
                <div style={{ display: 'flex', gap: '0.5rem' }}>
                  <button
                    className="btn btn-primary"
                    onClick={() => handleHireProvider(service.id)}
                  >
                    Hire Now
                  </button>
                  <button
                    className="btn btn-ghost"
                    onClick={() => {
                      setSelectedServiceId(null);
                      setGigDescription('');
                    }}
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <button
                className="btn btn-primary"
                onClick={() => setSelectedServiceId(service.id)}
                disabled={service.provider_principal === currentPrincipal}
              >
                {service.provider_principal === currentPrincipal ? 'This is your service' : 'Hire this provider'}
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
