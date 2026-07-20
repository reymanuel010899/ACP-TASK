/**
 * TaskDetail.tsx - Display detailed task information
 *
 * Shows full task details and allows workers to accept tasks.
 */

import React, { useEffect, useState } from 'react';
import { Task } from '../types/marketplace';
import { useTasks } from '../hooks/useTasks';

interface TaskDetailProps {
  taskId: string;
  currentPrincipal: string | null;
  onAcceptSuccess?: (task: Task) => void;
  onGoBack?: () => void;
}

export default function TaskDetail({
  taskId,
  currentPrincipal,
  onAcceptSuccess,
  onGoBack,
}: TaskDetailProps) {
  const [task, setTask] = useState<Task | null>(null);
  const { getTask, acceptTask, loading, error } = useTasks();

  useEffect(() => {
    const loadTask = async () => {
      const loadedTask = await getTask(taskId);
      if (loadedTask) {
        setTask(loadedTask);
      }
    };
    loadTask();
  }, [taskId, getTask]);

  const handleAccept = async () => {
    if (!currentPrincipal) {
      alert('Please log in first');
      return;
    }

    const updatedTask = await acceptTask(taskId, currentPrincipal);
    if (updatedTask) {
      setTask(updatedTask);
      onAcceptSuccess?.(updatedTask);
    }
  };

  if (loading && !task) {
    return <div className="task-detail-loading">Loading task details...</div>;
  }

  if (error) {
    return <div className="error-message">Error loading task: {error}</div>;
  }

  if (!task) {
    return <div className="error-message">Task not found</div>;
  }

  const isAuthor = task.author_principal === currentPrincipal;
  const isWorker = task.worker_principal === currentPrincipal;
  const canAccept =
    task.status === 'open' &&
    currentPrincipal &&
    !isAuthor;

  return (
    <div className="task-detail">
      <button className="btn btn-ghost" onClick={onGoBack}>
        Back to Tasks
      </button>

      <div className="task-detail-card">
        <div className="task-detail-header">
          <h1>{task.description}</h1>
          <span className={`status-badge large ${task.status}`}>
            {task.status === 'open'
              ? 'Open'
              : task.status === 'accepted'
                ? 'Accepted'
                : 'Completed'}
          </span>
        </div>

        <div className="task-detail-meta">
          <div className="meta-item">
            <strong>Posted:</strong>
            <span>{new Date(task.created_at).toLocaleString()}</span>
          </div>

          <div className="meta-item">
            <strong>Author:</strong>
            <code title={task.author_principal}>
              {task.author_principal.substring(0, 30)}...
            </code>
            {isAuthor && <span className="badge-you">You</span>}
          </div>

          {task.worker_principal && (
            <div className="meta-item">
              <strong>Accepted by:</strong>
              <code title={task.worker_principal}>
                {task.worker_principal.substring(0, 30)}...
              </code>
              {isWorker && <span className="badge-you">You</span>}
            </div>
          )}
        </div>

        <div className="task-detail-content">
          <div className="section">
            <h3>Description</h3>
            <p className="full-description">{task.description}</p>
          </div>

          {task.status === 'completed' && task.outcome && (
            <div className="section">
              <h3>Completed Outcome</h3>
              <p className="outcome-text">{task.outcome}</p>
            </div>
          )}
        </div>

        {task.status === 'accepted' && (
          <div className="task-detail-note">
            <p>
              This task has been accepted. View negotiations to discuss details.
            </p>
          </div>
        )}

        {task.status === 'completed' && (
          <div className="task-detail-note success">
            <p>This task is completed.</p>
          </div>
        )}

        <div className="task-detail-actions">
          {canAccept && (
            <button
              className={`btn btn-primary ${loading ? 'btn-loading' : ''}`}
              onClick={handleAccept}
              disabled={loading}
            >
              {loading ? 'Accepting...' : 'Accept This Task'}
            </button>
          )}

          {isAuthor && task.status === 'open' && (
            <p className="info-message">
              Waiting for someone to accept your task...
            </p>
          )}

          {(isAuthor || isWorker) && task.status === 'accepted' && (
            <p className="info-message">
              You can discuss this task in the negotiations section.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
