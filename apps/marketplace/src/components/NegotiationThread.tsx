/**
 * NegotiationThread.tsx - Task negotiation conversation UI
 *
 * Allows author and worker to exchange messages and complete the task.
 */

import React, { useEffect, useState } from 'react';
import { useTasks } from '../hooks/useTasks';
import { useNegotiation } from '../hooks/useNegotiation';
import { Task } from '../types/marketplace';

interface NegotiationThreadProps {
  taskId: string;
  currentPrincipal: string | null;
  onTaskCompleted?: (task: Task) => void;
}

export default function NegotiationThread({
  taskId,
  currentPrincipal,
  onTaskCompleted,
}: NegotiationThreadProps) {
  const [task, setTask] = useState<Task | null>(null);
  const [messageText, setMessageText] = useState('');
  const [completionOutcome, setCompletionOutcome] = useState('');
  const [showCompleteForm, setShowCompleteForm] = useState(false);

  const { getTask, loading: taskLoading } = useTasks();
  const {
    negotiations,
    loading: negLoading,
    error,
    sendMessage,
    getNegotiations,
    completeTask,
  } = useNegotiation();

  useEffect(() => {
    const loadTaskAndNegotiations = async () => {
      const loadedTask = await getTask(taskId);
      if (loadedTask) {
        setTask(loadedTask);
        await getNegotiations(taskId);
      }
    };
    loadTaskAndNegotiations();
  }, [taskId, getTask, getNegotiations]);

  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!messageText.trim()) {
      alert('Please enter a message');
      return;
    }

    if (!currentPrincipal) {
      alert('Please log in first');
      return;
    }

    if (!task) {
      alert('Task not found');
      return;
    }

    const success = await sendMessage(taskId, currentPrincipal, messageText.trim());
    if (success) {
      setMessageText('');
    }
  };

  const handleCompleteTask = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!completionOutcome.trim()) {
      alert('Please describe the completion outcome');
      return;
    }

    if (!currentPrincipal || !task) {
      alert('Invalid state');
      return;
    }

    const completedTask = await completeTask(
      taskId,
      currentPrincipal,
      completionOutcome.trim()
    );
    if (completedTask) {
      setTask(completedTask);
      setCompletionOutcome('');
      setShowCompleteForm(false);
      onTaskCompleted?.(completedTask);
    }
  };

  if (taskLoading) {
    return <div className="negotiation-loading">Loading negotiations...</div>;
  }

  if (!task) {
    return <div className="error-message">Task not found</div>;
  }

  if (task.status !== 'accepted') {
    return (
      <div className="negotiation-empty">
        <p>Negotiations are only available for accepted tasks.</p>
        <p className="hint">The task must be accepted before negotiating.</p>
      </div>
    );
  }

  const isAuthor = task.author_principal === currentPrincipal;
  const isWorker = task.worker_principal === currentPrincipal;
  const canParticipate = isAuthor || isWorker;
  const canComplete = isAuthor;

  return (
    <div className="negotiation-thread">
      <h2>Negotiation Thread</h2>

      {error && <div className="error-message">{error}</div>}

      <div className="negotiation-container">
        {negotiations.length === 0 ? (
          <div className="negotiation-empty">
            <p>No messages yet. Start a conversation!</p>
          </div>
        ) : (
          <div className="messages-list">
            {negotiations.map((msg, idx) => (
              <div
                key={idx}
                className={`message ${
                  msg.from === currentPrincipal ? 'from-you' : 'from-other'
                }`}
              >
                <div className="message-header">
                  <span className="message-from">
                    {msg.from === currentPrincipal ? 'You' : msg.from.substring(0, 20)}
                  </span>
                  <span className="message-time">
                    {new Date(msg.timestamp).toLocaleTimeString()}
                  </span>
                </div>
                <div className="message-body">{msg.message}</div>
              </div>
            ))}
          </div>
        )}

        {canParticipate && (
          <form onSubmit={handleSendMessage} className="message-form">
            <div className="form-group">
              <textarea
                className="form-textarea"
                placeholder="Type your message..."
                value={messageText}
                onChange={(e) => setMessageText(e.target.value)}
                disabled={negLoading}
                rows={3}
              />
            </div>
            <button
              type="submit"
              className={`btn btn-primary ${negLoading ? 'btn-loading' : ''}`}
              disabled={negLoading || !messageText.trim()}
            >
              {negLoading ? 'Sending...' : 'Send Message'}
            </button>
          </form>
        )}

        {canComplete && (
          <div className="completion-section">
            {!showCompleteForm ? (
              <button
                className="btn btn-success"
                onClick={() => setShowCompleteForm(true)}
              >
                Mark Task as Complete
              </button>
            ) : (
              <form onSubmit={handleCompleteTask} className="completion-form">
                <div className="form-group">
                  <label htmlFor="outcome">Completion Outcome</label>
                  <textarea
                    id="outcome"
                    className="form-textarea"
                    placeholder="Describe how the task was completed..."
                    value={completionOutcome}
                    onChange={(e) => setCompletionOutcome(e.target.value)}
                    disabled={negLoading}
                    rows={4}
                  />
                  <p className="hint">
                    This will record reputation for the worker on the registry.
                  </p>
                </div>

                <div className="form-actions">
                  <button
                    type="submit"
                    className={`btn btn-success ${
                      negLoading ? 'btn-loading' : ''
                    }`}
                    disabled={negLoading || !completionOutcome.trim()}
                  >
                    {negLoading ? 'Completing...' : 'Complete Task'}
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost"
                    onClick={() => setShowCompleteForm(false)}
                    disabled={negLoading}
                  >
                    Cancel
                  </button>
                </div>
              </form>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
