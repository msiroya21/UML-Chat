import { useState } from 'react';
import { submitFeedback } from '../services/api';

export default function FeedbackWidget({ token, diagramId, onClose }) {
  const [rating, setRating] = useState(0);
  const [hovered, setHovered] = useState(0);
  const [feedbackType, setFeedbackType] = useState('praise');
  const [feedbackText, setFeedbackText] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!rating) return alert('Please select a star rating.');
    setLoading(true);
    try {
      await submitFeedback(token, diagramId, rating, feedbackType, feedbackText || 'No comment.');
      setSubmitted(true);
    } catch (err) {
      alert('Failed to submit feedback: ' + err.message);
    } finally {
      setLoading(false);
    }
  }

  if (submitted) {
    return (
      <div className="feedback-modal">
        <p className="feedback-thanks">Thanks for your feedback!</p>
        <button className="btn-ghost" onClick={onClose}>Close</button>
      </div>
    );
  }

  return (
    <div className="feedback-modal">
      <div className="feedback-header">
        <span>Rate this diagram</span>
        <button className="btn-ghost" onClick={onClose}>✕</button>
      </div>
      <form onSubmit={handleSubmit}>
        <div className="stars">
          {[1, 2, 3, 4, 5].map(n => (
            <button
              key={n}
              type="button"
              className={`star ${n <= (hovered || rating) ? 'filled' : ''}`}
              onMouseEnter={() => setHovered(n)}
              onMouseLeave={() => setHovered(0)}
              onClick={() => setRating(n)}
            >★</button>
          ))}
        </div>

        <select
          className="feedback-select"
          value={feedbackType}
          onChange={e => setFeedbackType(e.target.value)}
        >
          <option value="praise">Praise</option>
          <option value="correction">Correction</option>
          <option value="suggestion">Suggestion</option>
        </select>

        <textarea
          className="feedback-text"
          placeholder="Optional comment…"
          value={feedbackText}
          onChange={e => setFeedbackText(e.target.value)}
          rows={3}
        />

        <button className="btn-primary" type="submit" disabled={loading || !rating}>
          {loading ? 'Submitting…' : 'Submit'}
        </button>
      </form>
    </div>
  );
}
