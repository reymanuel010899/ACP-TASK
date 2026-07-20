import { useState, useEffect, useCallback } from 'react';

export interface Gig {
  id: string;
  service_id: string;
  provider_principal: string;
  buyer_principal: string;
  description: string;
  status: 'active' | 'completed';
  created_at: string;
  completed_at: string | null;
  outcome: string | null;
}

export function useGigs(principalId: string, refresh: number = 0) {
  const [gigs, setGigs] = useState<Gig[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadGigs = useCallback(async (skip = 0, limit = 50) => {
    if (!principalId) return;
    try {
      setLoading(true);
      setError(null);
      const resp = await fetch(
        `/api/gigs?principal_id=${encodeURIComponent(principalId)}&skip=${skip}&limit=${limit}`
      );
      if (!resp.ok) {
        setError('Failed to load gigs');
        return;
      }
      const data = await resp.json();
      setGigs(data.gigs || []);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [principalId]);

  const createGig = useCallback(async (
    serviceId: string,
    buyerPrincipal: string,
    description: string
  ): Promise<Gig | null> => {
    try {
      const resp = await fetch('/api/gigs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          service_id: serviceId,
          buyer_principal: buyerPrincipal,
          description,
        }),
      });
      if (!resp.ok) {
        const data = await resp.json();
        setError(data.error || 'Failed to create gig');
        return null;
      }
      const data = await resp.json();
      setGigs([data.gig, ...gigs]);
      return data.gig;
    } catch (e) {
      setError(String(e));
      return null;
    }
  }, [gigs]);

  const completeGig = useCallback(async (
    gigId: string,
    buyerPrincipal: string,
    outcome: string
  ): Promise<Gig | null> => {
    try {
      const resp = await fetch(`/api/gigs/${gigId}/complete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          buyer_principal: buyerPrincipal,
          outcome,
        }),
      });
      if (!resp.ok) {
        const data = await resp.json();
        setError(data.error || 'Failed to complete gig');
        return null;
      }
      const data = await resp.json();
      setGigs(gigs.map(g => g.id === gigId ? data.gig : g));
      return data.gig;
    } catch (e) {
      setError(String(e));
      return null;
    }
  }, [gigs]);

  useEffect(() => {
    loadGigs();
  }, [principalId, refresh, loadGigs]);

  return { gigs, loading, error, createGig, completeGig, reload: loadGigs };
}
