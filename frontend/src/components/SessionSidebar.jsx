import { useEffect, useState, useRef } from 'react';
import { getSessions, createSession, patchSession } from '../services/api';

export default function SessionSidebar({ token, currentSessionId, onSelectSession, onLogout, refreshKey }) {
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [editTitle, setEditTitle] = useState('');
  const inputRef = useRef(null);

  async function fetchSessions() {
    try {
      const data = await getSessions(token);
      setSessions(data.sessions || []);
    } catch (e) {
      console.error('Failed to load sessions', e);
    }
  }

  useEffect(() => { fetchSessions(); }, [token, refreshKey]);

  useEffect(() => {
    if (editingId && inputRef.current) inputRef.current.focus();
  }, [editingId]);

  async function handleNewSession() {
    setLoading(true);
    try {
      const s = await createSession(token);
      await fetchSessions();
      onSelectSession(s.session_id);
    } catch (e) {
      alert('Could not create session: ' + e.message);
    } finally {
      setLoading(false);
    }
  }

  function startEdit(e, session) {
    e.stopPropagation();
    setEditingId(session.session_id);
    setEditTitle(session.title);
  }

  async function commitRename(sessionId) {
    const trimmed = editTitle.trim();
    if (trimmed) {
      try {
        await patchSession(token, sessionId, trimmed);
        await fetchSessions();
      } catch (e) {
        console.error('Rename failed', e);
      }
    }
    setEditingId(null);
  }

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <span className="sidebar-title">UML Chatbot</span>
        <button className="btn-ghost" onClick={onLogout} title="Logout">↩</button>
      </div>

      <button className="btn-primary btn-full" onClick={handleNewSession} disabled={loading}>
        {loading ? 'Creating…' : '+ New Session'}
      </button>

      <nav className="session-list">
        {sessions.length === 0 && <p className="empty-hint">No sessions yet</p>}
        {sessions.map(s => (
          <div
            key={s.session_id}
            className={`session-item ${s.session_id === currentSessionId ? 'active' : ''}`}
            onClick={() => editingId !== s.session_id && onSelectSession(s.session_id)}
          >
            {editingId === s.session_id ? (
              <input
                ref={inputRef}
                className="session-rename-input"
                value={editTitle}
                onChange={e => setEditTitle(e.target.value)}
                onBlur={() => commitRename(s.session_id)}
                onKeyDown={e => {
                  if (e.key === 'Enter') commitRename(s.session_id);
                  if (e.key === 'Escape') setEditingId(null);
                }}
                onClick={e => e.stopPropagation()}
              />
            ) : (
              <>
                <span className="session-name">{s.title}</span>
                <div className="session-item-footer">
                  <span className="session-date">{new Date(s.created_at).toLocaleDateString()}</span>
                  <button
                    className="session-rename-btn"
                    onClick={e => startEdit(e, s)}
                    title="Rename"
                  >✎</button>
                </div>
              </>
            )}
          </div>
        ))}
      </nav>
    </aside>
  );
}
