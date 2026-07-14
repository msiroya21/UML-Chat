import { useState, useEffect, useRef } from 'react';
import useWebSocket from '../hooks/useWebSocket';
import FeedbackWidget from './FeedbackWidget';
import { buildWsUrl, getDiagrams } from '../services/api';

const STAGE_LABELS = {
  selecting_diagrams: 'Selecting types',
  generating_ir: 'Generating IR',
  validating_ir: 'Validating IR',
  generating_plantuml: 'Generating PlantUML',
  rendering_svg: 'Rendering SVG',
};

function ProgressBar({ stage, percent }) {
  return (
    <div className="progress-wrap">
      <div className="progress-label">{STAGE_LABELS[stage] || stage} — {percent}%</div>
      <div className="progress-bar">
        <div className="progress-fill" style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}

function svgDataUri(svg) {
  // Render server SVG as an <img> data URI rather than injecting it into the DOM —
  // avoids the XSS surface of dangerouslySetInnerHTML on prompt-derived labels.
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
}

function DiagramCard({ diagram, token }) {
  const [showCode, setShowCode] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [showFeedback, setShowFeedback] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const [fsZoom, setFsZoom] = useState(1); // 1 = fit-to-screen

  const isInvalid = diagram.validation ? !diagram.validation.is_valid : diagram.is_valid === false;
  const errorMsg = diagram.validation?.errors?.[0] || (diagram.ir && diagram.ir._error);

  // Close fullscreen on Escape.
  useEffect(() => {
    if (!fullscreen) return;
    const onKey = e => { if (e.key === 'Escape') setFullscreen(false); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [fullscreen]);

  return (
    <div className="diagram-card">
      <div className="diagram-card-header">
        <div className="diagram-card-title">
          <span className="diagram-type-badge">{diagram.diagram_type}</span>
          {diagram.is_fallback && (
            <span className="fallback-badge" title="Generation failed — showing the model's attempted code">⚠ Fallback</span>
          )}
        </div>
        <div className="diagram-actions">
          <button className="btn-ghost" onClick={() => setZoom(z => Math.max(0.3, z - 0.2))} title="Zoom out">−</button>
          <button className="btn-ghost" onClick={() => setZoom(1)} title="Reset zoom">⊙</button>
          <button className="btn-ghost" onClick={() => setZoom(z => Math.min(3, z + 0.2))} title="Zoom in">+</button>
          <button className="btn-ghost" onClick={() => setShowCode(v => !v)}>
            {showCode ? 'Hide Code' : 'Show Code'}
          </button>
          <button className="btn-ghost" onClick={() => setShowFeedback(true)}>Rate</button>
        </div>
      </div>

      {isInvalid && (
        <div className="error-card" style={{ margin: '10px 14px' }}>
          {errorMsg || 'This diagram failed validation — showing the attempted PlantUML below.'}
        </div>
      )}

      {diagram.svg && !isInvalid && (
        <div className="svg-container">
          <img
            src={svgDataUri(diagram.svg)}
            alt={`${diagram.diagram_type} diagram`}
            style={{ transform: `scale(${zoom})`, transformOrigin: 'top left', maxWidth: '100%' }}
          />
          <div className="svg-toolbar">
            <button
              className="fullscreen-btn"
              onClick={() => { setFsZoom(1); setFullscreen(true); }}
              title="View fullscreen"
              aria-label="View fullscreen"
            >⛶ Fullscreen</button>
          </div>
        </div>
      )}

      {fullscreen && diagram.svg && (
        <div className="diagram-fullscreen" onClick={() => setFullscreen(false)}>
          <div className="diagram-fullscreen-bar" onClick={e => e.stopPropagation()}>
            <span className="diagram-type-badge">{diagram.diagram_type}</span>
            <div className="diagram-fullscreen-controls">
              <button className="btn-ghost" onClick={() => setFsZoom(z => Math.max(0.2, +(z - 0.2).toFixed(2)))} title="Zoom out">−</button>
              <span className="zoom-readout">{Math.round(fsZoom * 100)}%</span>
              <button className="btn-ghost" onClick={() => setFsZoom(z => Math.min(5, +(z + 0.2).toFixed(2)))} title="Zoom in">+</button>
              <button className="btn-ghost" onClick={() => setFsZoom(1)} title="Fit to screen">⊙ Fit</button>
              <button className="btn-ghost" onClick={() => setFullscreen(false)} title="Close (Esc)">✕ Close</button>
            </div>
          </div>
          <div className="diagram-fullscreen-body" onClick={e => e.stopPropagation()}>
            <img
              src={svgDataUri(diagram.svg)}
              alt={`${diagram.diagram_type} diagram, fullscreen`}
              style={{ maxWidth: `${fsZoom * 100}%`, maxHeight: `${fsZoom * 100}%` }}
            />
          </div>
        </div>
      )}

      {(showCode || isInvalid) && (
        <pre className="plantuml-code">{diagram.plantuml_code}</pre>
      )}

      {showFeedback && (
        <div className="feedback-overlay">
          <FeedbackWidget
            token={token}
            diagramId={diagram.diagram_id}
            onClose={() => setShowFeedback(false)}
          />
        </div>
      )}
    </div>
  );
}

export default function DiagramPanel({ view, token, onComplete }) {
  const isLive = view?.mode === 'live';
  const wsUrl = isLive ? buildWsUrl(view.wsPath) : null;
  const { isConnected, isComplete, progress, diagrams: liveDiagrams, errors } = useWebSocket(wsUrl);

  const [histDiagrams, setHistDiagrams] = useState([]);
  const completedRef = useRef(false);

  // History mode: re-hydrate a past turn's diagrams from the DB (SVG re-rendered server-side).
  useEffect(() => {
    if (view?.mode === 'history' && view.messageId) {
      getDiagrams(token, view.sessionId, view.messageId)
        .then(data => setHistDiagrams(Array.isArray(data) ? data : []))
        .catch(() => setHistDiagrams([]));
    } else {
      setHistDiagrams([]);
    }
  }, [view, token]);

  // Notify parent once when a live generation finishes (picks up title + status).
  useEffect(() => { completedRef.current = false; }, [wsUrl]);
  useEffect(() => {
    if (isLive && isComplete && !completedRef.current) {
      completedRef.current = true;
      onComplete && onComplete();
    }
  }, [isLive, isComplete, onComplete]);

  if (!view) {
    return (
      <div className="diagram-panel diagram-empty">
        <p>Submit a prompt to generate diagrams</p>
      </div>
    );
  }

  const inProgress = Object.entries(progress);
  const diagrams = isLive ? liveDiagrams : histDiagrams;

  return (
    <div className="diagram-panel">
      {isLive && isConnected && <div className="status-bar connecting">Generating diagrams…</div>}
      {isLive && isComplete && (
        <div className="status-bar complete">
          Done — {diagrams.length} diagram{diagrams.length !== 1 ? 's' : ''} generated
        </div>
      )}

      {isLive && inProgress.map(([type, { stage, percent }]) => (
        <ProgressBar key={type} stage={stage} percent={percent} />
      ))}

      {isLive && errors.map(err => (
        <div key={`err-${err.diagram_type}`} className="error-card">
          <strong>{(err.diagram_type || '').replace(/_/g, ' ')}</strong>
          {' — '}
          {err.message || 'Something went wrong generating this diagram. Please try again.'}
        </div>
      ))}

      {diagrams.map(d => (
        <DiagramCard key={d.diagram_type || d.diagram_id} diagram={d} token={token} />
      ))}

      {!isLive && diagrams.length === 0 && (
        <p className="empty-hint">No diagrams for this session yet</p>
      )}
    </div>
  );
}
