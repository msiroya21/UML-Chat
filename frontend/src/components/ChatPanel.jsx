import { useState, useEffect, useRef } from 'react';
import { getMessages, submitMessage, updateMessage, submitMessageFeedback } from '../services/api';

// Types with a full structured-IR pipeline (validation + auto-repair).
// The rest are best-effort "direct PlantUML" and shown with a β tag.
const SUPPORTED = new Set([
  'sequence', 'class', 'component',
  'activity', 'usecase', 'state', 'deployment',
]);

const DIAGRAM_TYPES = [
  'sequence', 'class', 'component',
  'activity', 'usecase', 'state', 'object',
  'deployment', 'package', 'composite_structure',
  'communication', 'interaction_overview', 'timing', 'profile',
];

export default function ChatPanel({ token, sessionId, onLive, onHistory, onRefreshSessions }) {
  const [messages, setMessages] = useState([]);
  const [prompt, setPrompt] = useState('');
  const [selectedTypes, setSelectedTypes] = useState(['sequence', 'class']);
  const [loading, setLoading] = useState(false);
  const [lastMessageId, setLastMessageId] = useState(null);
  const [mode, setMode] = useState('generate'); // 'generate' | 'feedback'
  const [feedbackDone, setFeedbackDone] = useState(false);
  const textareaRef = useRef(null);

  // On session open/switch: load messages, restore lastMessageId from history (so the
  // next prompt is an UPDATE, not a new v1), and re-hydrate that turn's diagrams.
  useEffect(() => {
    if (!sessionId) { setMessages([]); setLastMessageId(null); setMode('generate'); return; }
    setMode('generate');
    getMessages(token, sessionId)
      .then(data => {
        const msgs = data.messages || [];
        setMessages(msgs);
        if (msgs.length > 0) {
          const latest = msgs[msgs.length - 1].message_id;
          setLastMessageId(latest);
          onHistory && onHistory(sessionId, latest);
        } else {
          setLastMessageId(null);
        }
      })
      .catch(console.error);
    // onHistory intentionally omitted from deps to avoid a reload loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, token]);

  function handlePromptChange(e) {
    setPrompt(e.target.value);
    const el = e.target;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 200) + 'px';
  }

  function toggleType(t) {
    setSelectedTypes(prev =>
      prev.includes(t) ? prev.filter(x => x !== t) : [...prev, t]
    );
  }

  function selectAll() { setSelectedTypes([...DIAGRAM_TYPES]); }
  function clearAll() { setSelectedTypes([]); }

  async function handleSubmit(e) {
    e.preventDefault();
    if (!prompt.trim() || !sessionId) return;
    setLoading(true);
    setFeedbackDone(false);

    try {
      if (mode === 'feedback') {
        await submitMessageFeedback(token, lastMessageId, 'suggestion', prompt.trim());
        setFeedbackDone(true);
        setPrompt('');
        if (textareaRef.current) textareaRef.current.style.height = 'auto';
        return;
      }

      let res;
      const isFirstMessage = !lastMessageId;
      if (lastMessageId) {
        res = await updateMessage(token, sessionId, lastMessageId, prompt.trim(), selectedTypes);
      } else {
        res = await submitMessage(token, sessionId, prompt.trim(), selectedTypes);
      }

      const newMsg = {
        message_id: res.message_id,
        prompt: prompt.trim(),
        diagram_types: selectedTypes,
        version: res.version || 1,
      };
      setMessages(prev => [...prev, newMsg]);
      setLastMessageId(res.message_id);
      onLive(res.ws_url);
      setPrompt('');
      if (textareaRef.current) textareaRef.current.style.height = 'auto';

      if (isFirstMessage && onRefreshSessions) onRefreshSessions();
      // The auto-generated title is picked up when generation completes:
      // DiagramPanel calls onComplete -> App bumps refreshKey (no fixed timer).
    } catch (err) {
      alert('Error: ' + err.message);
    } finally {
      setLoading(false);
    }
  }

  const isUpdateMode = !!lastMessageId;

  return (
    <div className="chat-panel">
      <div className="message-list">
        {!sessionId && <p className="empty-hint">Select or create a session to start</p>}
        {messages.map(m => (
          <div key={m.message_id} className="message message-user">
            <div className="message-bubble">
              <p className="message-text">{m.prompt}</p>
              {m.diagram_types?.length > 0 && (
                <div className="message-tags">
                  {m.diagram_types.map(t => <span key={t} className="tag">{t}</span>)}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>

      <form className="chat-form" onSubmit={handleSubmit}>
        {isUpdateMode && (
          <div className="mode-toggle">
            <button
              type="button"
              className={`mode-btn ${mode === 'generate' ? 'active' : ''}`}
              onClick={() => { setMode('generate'); setFeedbackDone(false); }}
            >↻ Update</button>
            <button
              type="button"
              className={`mode-btn ${mode === 'feedback' ? 'active' : ''}`}
              onClick={() => { setMode('feedback'); setFeedbackDone(false); }}
            >✦ Feedback</button>
          </div>
        )}

        {feedbackDone && (
          <p className="feedback-thanks">Feedback submitted — thank you!</p>
        )}

        {mode === 'generate' && (
          <>
            <div className="type-selector-label">
              Diagram types <span className="type-hint">(empty = auto-select)</span>
              <span className="type-selector-actions">
                <button type="button" className="type-action-btn" onClick={selectAll}>Select all</button>
                <button type="button" className="type-action-btn" onClick={clearAll}>Clear</button>
              </span>
            </div>
            <div className="type-selector">
              {DIAGRAM_TYPES.map(t => (
                <label key={t} className={`type-chip ${selectedTypes.includes(t) ? 'selected' : ''} ${!SUPPORTED.has(t) ? 'beta' : ''}`}>
                  <input type="checkbox" checked={selectedTypes.includes(t)} onChange={() => toggleType(t)} style={{ display: 'none' }} />
                  {t}{!SUPPORTED.has(t) && <span className="beta-tag"> β</span>}
                </label>
              ))}
            </div>
          </>
        )}

        <div className="chat-input-row">
          <textarea
            ref={textareaRef}
            className="chat-input"
            placeholder={
              !sessionId ? 'Select a session first' :
              mode === 'feedback' ? 'Describe what could be improved in these diagrams…' :
              'Describe your software design…'
            }
            value={prompt}
            onChange={handlePromptChange}
            disabled={!sessionId || loading}
            rows={5}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSubmit(e); }
            }}
          />
          <button
            className="btn-primary btn-send"
            type="submit"
            disabled={!sessionId || !prompt.trim() || loading}
          >
            {loading ? '…' : mode === 'feedback' ? 'Send' : lastMessageId ? 'Update' : 'Generate'}
          </button>
        </div>

        {isUpdateMode && mode === 'generate' && (
          <button type="button" className="btn-ghost btn-new-prompt" onClick={() => { setLastMessageId(null); setPrompt(''); setMode('generate'); }}>
            Start new prompt
          </button>
        )}
      </form>
    </div>
  );
}
