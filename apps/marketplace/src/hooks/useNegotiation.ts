/**
 * Hook for managing task negotiations
 */

import { useState, useCallback } from 'react';
import { apiClient, NegotiationMessage } from '../services/api';
import { Task } from '../types/marketplace';

export interface UseNegotiationReturn {
  negotiations: NegotiationMessage[];
  loading: boolean;
  error: string | null;
  sendMessage: (
    task_id: string,
    from_principal: string,
    message: string
  ) => Promise<boolean>;
  getNegotiations: (task_id: string) => Promise<void>;
  completeTask: (
    task_id: string,
    author_principal: string,
    outcome: string
  ) => Promise<Task | null>;
}

export function useNegotiation(): UseNegotiationReturn {
  const [negotiations, setNegotiations] = useState<NegotiationMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const getNegotiations = useCallback(async (task_id: string) => {
    try {
      setLoading(true);
      setError(null);
      const messages = await apiClient.getNegotiations(task_id);
      setNegotiations(messages);
    } catch (e) {
      const msg = String(e);
      setError(msg);
      console.error('Failed to get negotiations:', e);
    } finally {
      setLoading(false);
    }
  }, []);

  const sendMessage = useCallback(
    async (
      task_id: string,
      from_principal: string,
      message: string
    ): Promise<boolean> => {
      try {
        setLoading(true);
        setError(null);
        const msg = await apiClient.sendMessage(
          task_id,
          from_principal,
          message
        );
        setNegotiations((prev) => [...prev, msg]);
        return true;
      } catch (e) {
        const msg = String(e);
        setError(msg);
        console.error('Failed to send message:', e);
        return false;
      } finally {
        setLoading(false);
      }
    },
    []
  );

  const completeTask = useCallback(
    async (
      task_id: string,
      author_principal: string,
      outcome: string
    ): Promise<Task | null> => {
      try {
        setLoading(true);
        setError(null);
        const task = await apiClient.completeTask(
          task_id,
          author_principal,
          outcome
        );
        return task;
      } catch (e) {
        const msg = String(e);
        setError(msg);
        console.error('Failed to complete task:', e);
        return null;
      } finally {
        setLoading(false);
      }
    },
    []
  );

  return {
    negotiations,
    loading,
    error,
    sendMessage,
    getNegotiations,
    completeTask,
  };
}
