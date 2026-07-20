import React, { useState } from 'react';
import { useServices } from '../hooks/useServices';

interface Props {
  currentPrincipal: string;
  onServiceCreated: () => void;
}

export default function PostServiceForm({ currentPrincipal, onServiceCreated }: Props) {
  const [serviceName, setServiceName] = useState('');
  const [description, setDescription] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { registerService } = useServices();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    const service = await registerService(currentPrincipal, serviceName, description);
    setLoading(false);

    if (service) {
      setServiceName('');
      setDescription('');
      onServiceCreated();
    } else {
      setError('Failed to create service. Try again.');
    }
  };

  return (
    <div style={{ maxWidth: '600px', margin: '0 auto' }}>
      <h2>Offer Your Service</h2>
      {error && <div className="error-message">{error}</div>}
      <form onSubmit={handleSubmit}>
        <div className="form-group">
          <label>Service Name *</label>
          <input
            type="text"
            value={serviceName}
            onChange={(e) => setServiceName(e.target.value)}
            placeholder="e.g., Web Development, Logo Design, Consulting"
            required
          />
        </div>
        <div className="form-group">
          <label>Description *</label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Describe what you offer, your expertise, and what clients can expect"
            required
          />
        </div>
        <button type="submit" className="btn btn-primary" disabled={loading}>
          {loading ? 'Publishing...' : 'Publish Service'}
        </button>
      </form>
    </div>
  );
}
