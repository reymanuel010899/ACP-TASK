import React, { useState } from 'react';
import { useUserSession } from './hooks/useUserSession';
import LoginPrincipal from './components/Auth/LoginPrincipal';
import RegisterPrincipal from './components/Auth/RegisterPrincipal';
import ReputationDisplay from './components/ReputationDisplay';
import ServiceList from './components/ServiceList';
import PostServiceForm from './components/PostServiceForm';
import MyGigs from './components/MyGigs';
import './index.css';

type ViewType = 'browse' | 'post' | 'my-gigs' | 'auth';

export default function App() {
  const { session, reputation, login, register, logout, loading } = useUserSession();
  const [currentView, setCurrentView] = useState<ViewType>('browse');
  const [showRegister, setShowRegister] = useState(false);
  const [refreshGigs, setRefreshGigs] = useState(0);

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
          <h1>AgentTrust Gig Board</h1>
          <p className="tagline">Browse service providers, hire talent, build reputation</p>
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
          <h1>AgentTrust Gig Board</h1>
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
          className={`nav-item ${currentView === 'browse' ? 'active' : ''}`}
          onClick={() => setCurrentView('browse')}
        >
          Browse Services
        </button>
        <button
          className={`nav-item ${currentView === 'post' ? 'active' : ''}`}
          onClick={() => setCurrentView('post')}
        >
          Offer Service
        </button>
        <button
          className={`nav-item ${currentView === 'my-gigs' ? 'active' : ''}`}
          onClick={() => setCurrentView('my-gigs')}
        >
          My Gigs
        </button>
      </nav>

      <main className="app-main">
        {currentView === 'browse' && (
          <ServiceList
            currentPrincipal={session.principal_id}
            onGigCreated={() => {
              setRefreshGigs(refreshGigs + 1);
              setCurrentView('my-gigs');
            }}
          />
        )}

        {currentView === 'post' && (
          <PostServiceForm
            currentPrincipal={session.principal_id}
            onServiceCreated={() => setCurrentView('browse')}
          />
        )}

        {currentView === 'my-gigs' && (
          <MyGigs
            currentPrincipal={session.principal_id}
            refresh={refreshGigs}
            onReputationUpdated={() => {
              // Reload reputation from server
            }}
          />
        )}
      </main>

      <footer className="app-footer">
        <p>AgentTrust Gig Board - Federated Service Provider Directory (U4)</p>
      </footer>
    </div>
  );
}
