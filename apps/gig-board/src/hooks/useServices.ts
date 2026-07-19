import { useState, useEffect, useCallback } from 'react';

export interface Service {
  id: string;
  provider_principal: string;
  service_name: string;
  description: string;
  created_at: string;
  gigs_completed: number;
  rating: number | null;
}

export function useServices() {
  const [services, setServices] = useState<Service[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadServices = useCallback(async (skip = 0, limit = 50) => {
    try {
      setLoading(true);
      setError(null);
      const resp = await fetch(`/api/services?skip=${skip}&limit=${limit}`);
      if (!resp.ok) {
        setError('Failed to load services');
        return;
      }
      const data = await resp.json();
      setServices(data.services || []);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  const registerService = useCallback(async (
    principalId: string,
    serviceName: string,
    description: string
  ): Promise<Service | null> => {
    try {
      const resp = await fetch('/api/services', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          principal_id: principalId,
          service_name: serviceName,
          description,
        }),
      });
      if (!resp.ok) {
        const data = await resp.json();
        setError(data.error || 'Failed to register service');
        return null;
      }
      const data = await resp.json();
      setServices([data.service, ...services]);
      return data.service;
    } catch (e) {
      setError(String(e));
      return null;
    }
  }, [services]);

  useEffect(() => {
    loadServices();
  }, [loadServices]);

  return { services, loading, error, registerService, reload: loadServices };
}
