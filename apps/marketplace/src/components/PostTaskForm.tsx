/**
 * PostTaskForm.tsx - Form to create a new task
 *
 * Allows users to post new tasks to the marketplace.
 */

import React, { useState } from 'react';
import { useTasks } from '../hooks/useTasks';
import { Task } from '../types/marketplace';

interface PostTaskFormProps {
  currentPrincipal: string | null;
  onTaskCreated?: (task: Task) => void;
}

export default function PostTaskForm({
  currentPrincipal,
  onTaskCreated,
}: PostTaskFormProps) {
  const [description, setDescription] = useState('');
  const { createTask, loading, error } = useTasks();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!description.trim()) {
      alert('Please enter a task description');
      return;
    }

    if (!currentPrincipal) {
      alert('Please log in first');
      return;
    }

    const task = await createTask(description.trim(), currentPrincipal);
    if (task) {
      setDescription('');
      onTaskCreated?.(task);
    }
  };

  return (
    <div className="post-task-form">
      <h2>Post a New Task</h2>
      <form onSubmit={handleSubmit}>
        <div className="form-group">
          <label htmlFor="description">Task Description</label>
          <textarea
            id="description"
            className="form-textarea"
            placeholder="Describe what you need done..."
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            disabled={loading || !currentPrincipal}
            rows={5}
          />
          <p className="hint">
            Be clear and specific about what you need. Include any relevant details.
          </p>
        </div>

        {error && <div className="error-message">{error}</div>}

        <button
          type="submit"
          className={`btn btn-primary ${loading ? 'btn-loading' : ''}`}
          disabled={loading || !currentPrincipal || !description.trim()}
        >
          {loading ? 'Posting...' : 'Post Task'}
        </button>
      </form>
    </div>
  );
}
