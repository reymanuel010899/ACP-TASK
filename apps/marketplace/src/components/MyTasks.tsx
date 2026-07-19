import React from 'react';
import apiClient from '../services/api';

interface Props {
  currentPrincipal: string;
}

interface Task {
  id: string;
  description: string;
  status: string;
  created_at: string;
  worker_principal: string | null;
}

export default function MyTasks({ currentPrincipal }: Props) {
  const [myTasks, setMyTasks] = React.useState<Task[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    loadMyTasks();
  }, [currentPrincipal]);

  const loadMyTasks = async () => {
    try {
      setLoading(true);
      const response = await apiClient.listTasks(0, 100);
      const filtered = response.tasks.filter(t => (t as any).author_principal === currentPrincipal);
      setMyTasks(filtered);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load tasks');
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return <div className="loading-screen">Loading your tasks...</div>;
  }

  if (error) {
    return <div className="error-message">Error: {error}</div>;
  }

  if (myTasks.length === 0) {
    return (
      <div className="empty-state">
        <p>You haven't created any tasks yet.</p>
        <p>Go to "Post Task" to create your first task!</p>
      </div>
    );
  }

  const getStatusBadge = (status: string) => {
    const colors: { [key: string]: string } = {
      'open': '#4CAF50',
      'accepted': '#2196F3',
      'completed': '#9C27B0',
    };
    return (
      <span style={{
        display: 'inline-block',
        padding: '0.25rem 0.75rem',
        background: colors[status] || '#999',
        color: 'white',
        borderRadius: '4px',
        fontSize: '0.85rem',
        fontWeight: 'bold'
      }}>
        {status.toUpperCase()}
      </span>
    );
  };

  return (
    <div>
      <h2>My Tasks ({myTasks.length})</h2>
      <div className="list-container">
        {myTasks.map((task) => (
          <div key={task.id} className="task-card" style={{ padding: '1rem', border: '1px solid #ddd', borderRadius: '4px', marginBottom: '1rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start', marginBottom: '0.5rem' }}>
              <h3 style={{ margin: 0 }}>{task.description.slice(0, 50)}{task.description.length > 50 ? '...' : ''}</h3>
              {getStatusBadge(task.status)}
            </div>
            <div style={{ fontSize: '0.9rem', color: '#666', marginBottom: '0.5rem' }}>
              ID: {task.id.slice(0, 8)}...
            </div>
            {task.worker_principal && (
              <div style={{ fontSize: '0.9rem', color: '#666' }}>
                Worker: {task.worker_principal.slice(0, 20)}...
              </div>
            )}
            <div style={{ marginTop: '0.75rem', fontSize: '0.85rem', color: '#999' }}>
              Created: {new Date(task.created_at).toLocaleDateString()}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
