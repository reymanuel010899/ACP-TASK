/**
 * TaskList.tsx - Display list of available tasks
 *
 * Shows all open tasks from the marketplace with basic details.
 * Users can click to view details or accept a task.
 */

import React, { useEffect } from 'react';
import { Task } from '../types/marketplace';
import { useTasks } from '../hooks/useTasks';

interface TaskListProps {
  onSelectTask?: (task: Task) => void;
  onAcceptTask?: (task: Task) => void;
  currentPrincipal?: string | null;
}

export default function TaskList({
  onSelectTask,
  onAcceptTask,
  currentPrincipal,
}: TaskListProps) {
  const { tasks, loading, error, listTasks } = useTasks();

  useEffect(() => {
    listTasks();
  }, []);

  if (loading && tasks.length === 0) {
    return <div className="task-list-loading">Loading tasks...</div>;
  }

  if (error) {
    return <div className="error-message">Error loading tasks: {error}</div>;
  }

  if (tasks.length === 0) {
    return (
      <div className="task-list-empty">
        <p>No tasks available yet.</p>
        <p className="hint">Be the first to post a task!</p>
      </div>
    );
  }

  return (
    <div className="task-list">
      <h2>Available Tasks</h2>
      <div className="tasks-container">
        {tasks.map((task) => (
          <div
            key={task.id}
            className={`task-card status-${task.status}`}
          >
            <div className="task-header">
              <div className="task-title-section">
                <h3>{task.description}</h3>
                <span className={`status-badge ${task.status}`}>
                  {task.status === 'open'
                    ? 'Open'
                    : task.status === 'accepted'
                      ? 'Accepted'
                      : 'Completed'}
                </span>
              </div>
              <div className="task-meta">
                <small>Posted: {new Date(task.created_at).toLocaleDateString()}</small>
              </div>
            </div>

            <div className="task-body">
              <p className="author">
                Author: <code>{task.author_principal.substring(0, 20)}...</code>
              </p>

              {task.worker_principal && (
                <p className="worker">
                  Worker: <code>{task.worker_principal.substring(0, 20)}...</code>
                </p>
              )}

              {task.status === 'completed' && task.outcome && (
                <div className="task-outcome">
                  <strong>Outcome:</strong>
                  <p>{task.outcome}</p>
                </div>
              )}
            </div>

            <div className="task-actions">
              <button
                className="btn btn-secondary"
                onClick={() => onSelectTask?.(task)}
              >
                View Details
              </button>

              {task.status === 'open' &&
                currentPrincipal &&
                task.author_principal !== currentPrincipal && (
                  <button
                    className="btn btn-primary"
                    onClick={() => onAcceptTask?.(task)}
                  >
                    Accept Task
                  </button>
                )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
