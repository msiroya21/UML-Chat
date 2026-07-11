import { useState } from 'react';
import useWebSocket from '../hooks/useWebSocket';
import FeedbackWidget from './FeedbackWidget';
import { buildWsUrl } from '../services/api';

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

function DiagramCard({ diagram, token }) {
  const [showCode, setShowCode] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [showFeedback, setShowFeedback] = useState(false);

  return (
    <div className="diagram-card">
      <div className="diagram-card-header">
        <div className="diagram-card-title">
          <span className="diagram-type-badge">{diagram.diagram_type}</span>
          {diagram.is_fallback && (
            <span className="fallback-badge" title="LLM generation failed — showing example diagram">⚠ Fallback</span>
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

      <div className="svg-container">
        <div
          style={{ transform: `scale(${zoom})`, transformOrigin: 'top left', display: 'inline-block' }}
          dangerouslySetInnerHTML={{ __html: diagram.svg }}
        />
      </div>

      {showCode && (
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

export default function DiagramPanel({ wsPath, token }) {
  const wsUrl = wsPath ? buildWsUrl(wsPath) : null;
  const { isConnected, isComplete, progress, diagrams, errors } = useWebSocket(wsUrl);

  const inProgress = Object.entries(progress);

  if (!wsPath) {
    return (
      <div className="diagram-panel diagram-empty">
        <p>Submit a prompt to generate diagrams</p>
      </div>
    );
  }

  return (
    <div className="diagram-panel">
      {isConnected && (
        <div className="status-bar connecting">Generating diagrams…</div>
      )}
      {isComplete && (
        <div className="status-bar complete">
          Done — {diagrams.length} diagram{diagrams.length !== 1 ? 's' : ''} generated
        </div>
      )}

      {inProgress.map(([type, { stage, percent }]) => (
        <ProgressBar key={type} stage={stage} percent={percent} />
      ))}

      {errors.map((err, i) => (
        <div key={i} className="error-card">
          <strong>{err.diagram_type}</strong>: {err.message}
        </div>
      ))}

      {diagrams.map((d, i) => (
        <DiagramCard key={i} diagram={d} token={token} />
      ))}
    </div>
  );
}
