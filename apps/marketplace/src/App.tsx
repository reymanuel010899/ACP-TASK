/**
 * App.tsx - Main Marketplace App Component
 *
 * Routes and manages the overall marketplace experience.
 * Shows auth when not logged in, otherwise shows the marketplace UI.
 */

import React, { useState } from 'react';
import { useUserSession } from './hooks/useUserSession';
import LoginPrincipal from './components/Auth/LoginPrincipal';
import RegisterPrincipal from './components/Auth/RegisterPrincipal';
import ReputationDisplay from './components/ReputationDisplay';
import TaskList from './components/TaskList';
import PostTaskForm from './components/PostTaskForm';
import TaskDetail from './components/TaskDetail';
import NegotiationThread from './components/NegotiationThread';
import MyTasks from './components/MyTasks';
import { Task } from './types/marketplace';
import './App.css';

type ViewType = 'discover' | 'my-tasks' | 'post' | 'negotiations' | 'auth';

export default function App() {
  const { session, reputation, login, register, logout, loading } = useUserSession();
  const [currentView, setCurrentView] = useState<ViewType>('discover');
  const [selectedTask, setSelectedTask] = useState<Task | null>(null);
  const [showRegister, setShowRegister] = useState(false);

  if (loading) {
    return (
      <div className="app-container">
        <div className="loading-screen">Loading...</div>
      </div>
    );
  }

  if (!session) {
    return (
      <div className="app-container">
        <header className="app-header">
          <h1>AgentTrust Marketplace</h1>
          <p className="tagline">Post tasks, negotiate outcomes, earn reputation</p>
        </header>

        <div className="auth-container">
          {!showRegister ? (
            <>
              <LoginPrincipal onLoginSuccess={() => {}} />
              <button
                className="btn btn-link"
                onClick={() => setShowRegister(true)}
              >
                Don't have an account? Register here
              </button>
            </>
          ) : (
            <>
              <RegisterPrincipal onRegisterSuccess={() => {}} />
              <button
                className="btn btn-link"
                onClick={() => setShowRegister(false)}
              >
                Already have an account? Log in
              </button>
            </>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="app-container">
      <header className="app-header">
        <div className="header-left">
          <h1>AgentTrust Marketplace</h1>
        </div>
        <div className="header-right">
          <ReputationDisplay
            principal={session.principal_id}
            reputation={reputation}
          />
          <button className="btn btn-ghost" onClick={logout}>
            Logout
          </button>
        </div>
      </header>

      <nav className="app-nav">
        <button
          className={`nav-item ${currentView === 'discover' ? 'active' : ''}`}
          onClick={() => {
            setCurrentView('discover');
            setSelectedTask(null);
          }}
        >
          Browse Tasks
        </button>
        <button
          className={`nav-item ${currentView === 'my-tasks' ? 'active' : ''}`}
          onClick={() => setCurrentView('my-tasks')}
        >
          My Tasks
        </button>
        <button
          className={`nav-item ${currentView === 'post' ? 'active' : ''}`}
          onClick={() => setCurrentView('post')}
        >
          Post Task
        </button>
        <button
          className={`nav-item ${
            currentView === 'negotiations' ? 'active' : ''
          }`}
          onClick={() => setCurrentView('negotiations')}
        >
          My Negotiations
        </button>
      </nav>

      <main className="app-main">
        {currentView === 'discover' && !selectedTask && (
          <TaskList
            currentPrincipal={session.principal_id}
            onSelectTask={(task) => {
              setSelectedTask(task);
            }}
            onAcceptTask={(task) => {
              setSelectedTask(task);
            }}
          />
        )}

        {currentView === 'discover' && selectedTask && (
          <TaskDetail
            taskId={selectedTask.id}
            currentPrincipal={session.principal_id}
            onAcceptSuccess={(task) => {
              setSelectedTask(task);
              setCurrentView('negotiations');
            }}
            onGoBack={() => {
              setSelectedTask(null);
            }}
          />
        )}

        {currentView === 'my-tasks' && (
          <MyTasks currentPrincipal={session.principal_id} />
        )}

        {currentView === 'post' && (
          <PostTaskForm
            currentPrincipal={session.principal_id}
            onTaskCreated={(task) => {
              setCurrentView('my-tasks');
              setSelectedTask(task);
            }}
          />
        )}

        {currentView === 'negotiations' && selectedTask && (
          <div className="negotiations-view">
            <button
              className="btn btn-ghost"
              onClick={() => setSelectedTask(null)}
            >
              Back to Browse
            </button>
            <NegotiationThread
              taskId={selectedTask.id}
              currentPrincipal={session.principal_id}
              onTaskCompleted={(task) => {
                setSelectedTask(task);
              }}
            />
          </div>
        )}

        {currentView === 'negotiations' && !selectedTask && (
          <div className="negotiations-view-empty">
            <p>Select a task to view negotiations.</p>
            <button
              className="btn btn-primary"
              onClick={() => {
                setCurrentView('discover');
              }}
            >
              Browse Available Tasks
            </button>
          </div>
        )}
      </main>

      <footer className="app-footer">
        <p>AgentTrust Marketplace - Federated Task Marketplace (U3)</p>
      </footer>
    </div>
  );
}
