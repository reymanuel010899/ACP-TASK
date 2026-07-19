/**
 * Hook for managing marketplace tasks
 */

import { useState, useCallback } from 'react';
import { apiClient } from '../services/api';
import { Task } from '../types/marketplace';

export interface UseTasksReturn {
  tasks: Task[];
  loading: boolean;
  error: string | null;
  listTasks: (skip?: number, limit?: number) => Promise<void>;
  createTask: (description: string, principalId: string) => Promise<Task | null>;
  getTask: (task_id: string) => Promise<Task | null>;
  acceptTask: (task_id: string, workerPrincipal: string) => Promise<Task | null>;
}

export function useTasks(): UseTasksReturn {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const listTasks = useCallback(async (skip = 0, limit = 50) => {
    try {
      setLoading(true);
      setError(null);
      const result = await apiClient.listTasks(skip, limit);
      setTasks(result.tasks);
    } catch (e) {
      setError(String(e));
      console.error('Failed to list tasks:', e);
    } finally {
      setLoading(false);
    }
  }, []);

  const createTask = useCallback(
    async (description: string, principalId: string): Promise<Task | null> => {
      try {
        setLoading(true);
        setError(null);
        const task = await apiClient.createTask(principalId, description);
        setTasks((prev) => [task, ...prev]);
        return task;
      } catch (e) {
        const msg = String(e);
        setError(msg);
        console.error('Failed to create task:', e);
        return null;
      } finally {
        setLoading(false);
      }
    },
    []
  );

  const getTask = useCallback(
    async (task_id: string): Promise<Task | null> => {
      try {
        setLoading(true);
        setError(null);
        return await apiClient.getTask(task_id);
      } catch (e) {
        const msg = String(e);
        setError(msg);
        console.error('Failed to get task:', e);
        return null;
      } finally {
        setLoading(false);
      }
    },
    []
  );

  const acceptTask = useCallback(
    async (task_id: string, workerPrincipal: string): Promise<Task | null> => {
      try {
        setLoading(true);
        setError(null);
        const task = await apiClient.acceptTask(task_id, workerPrincipal);
        // Update the task in the list
        setTasks((prev) =>
          prev.map((t) => (t.id === task_id ? task : t))
        );
        return task;
      } catch (e) {
        const msg = String(e);
        setError(msg);
        console.error('Failed to accept task:', e);
        return null;
      } finally {
        setLoading(false);
      }
    },
    []
  );

  return {
    tasks,
    loading,
    error,
    listTasks,
    createTask,
    getTask,
    acceptTask,
  };
}
