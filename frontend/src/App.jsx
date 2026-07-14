import { useState } from 'react';
import { login, register } from './services/api';
import SessionSidebar from './components/SessionSidebar';
import ChatPanel from './components/ChatPanel';
import DiagramPanel from './components/DiagramPanel';

function AuthPage({ onAuth }) {
  const [mode, setMode] = useState('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const res = mode === 'login'
        ? await login(email, password)
        : await register(email, password, name);
      localStorage.setItem('token', res.token);
      localStorage.setItem('user_id', res.user_id);
      onAuth(res.token);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <h1 className="auth-title">UML Chatbot</h1>
        <p className="auth-subtitle">Generate UML diagrams from natural language</p>

        <div className="auth-tabs">
          <button className={`auth-tab ${mode === 'login' ? 'active' : ''}`} onClick={() => setMode('login')}>Login</button>
          <button className={`auth-tab ${mode === 'register' ? 'active' : ''}`} onClick={() => setMode('register')}>Register</button>
        </div>

        <form onSubmit={handleSubmit} className="auth-form">
          {mode === 'register' && (
            <input className="input" type="text" placeholder="Name" value={name} onChange={e => setName(e.target.value)} required />
          )}
          <input className="input" type="text" placeholder="Email" value={email} onChange={e => setEmail(e.target.value)} required />
          <input className="input" type="password" placeholder="Password" value={password} onChange={e => setPassword(e.target.value)} required />
          {error && <p className="auth-error">{error}</p>}
          <button className="btn-primary btn-full" type="submit" disabled={loading}>
            {loading ? 'Please wait…' : mode === 'login' ? 'Login' : 'Register'}
          </button>
        </form>
      </div>
    </div>
  );
}

export default function App() {
  const [token, setToken] = useState(() => localStorage.getItem('token') || '');
  const [currentSessionId, setCurrentSessionId] = useState(null);
  // view drives the diagram panel: live generation (WS) or historical (REST re-hydration).
  const [view, setView] = useState(null); // { mode: 'live', wsPath } | { mode: 'history', sessionId, messageId }
  const [refreshKey, setRefreshKey] = useState(0);

  function handleAuth(newToken) { setToken(newToken); }

  function handleLogout() {
    localStorage.removeItem('token');
    localStorage.removeItem('user_id');
    setToken('');
    setCurrentSessionId(null);
    setView(null);
  }

  function handleSelectSession(sessionId) {
    setCurrentSessionId(sessionId);
    setView(null); // ChatPanel sets a history view once it has loaded the session's messages
  }

  if (!token) return <AuthPage onAuth={handleAuth} />;

  return (
    <div className="app-layout">
      <SessionSidebar
        token={token}
        currentSessionId={currentSessionId}
        onSelectSession={handleSelectSession}
        onLogout={handleLogout}
        refreshKey={refreshKey}
      />
      <div className="main-area">
        <ChatPanel
          token={token}
          sessionId={currentSessionId}
          onLive={(wsPath) => setView({ mode: 'live', wsPath })}
          onHistory={(sessionId, messageId) => setView({ mode: 'history', sessionId, messageId })}
          onRefreshSessions={() => setRefreshKey(k => k + 1)}
        />
        <DiagramPanel
          view={view}
          token={token}
          onComplete={() => setRefreshKey(k => k + 1)}
        />
      </div>
    </div>
  );
}
