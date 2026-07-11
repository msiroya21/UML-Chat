const BASE_URL = 'http://localhost:8000/api/v1';

function authHeaders(token) {
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

async function request(method, path, body, token) {
  const res = await fetch(`${BASE_URL}${path}`, {
    method,
    headers: authHeaders(token),
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

export function register(email, password, name) {
  return request('POST', '/auth/register', { email, password, name });
}

export function login(email, password) {
  return request('POST', '/auth/login', { email, password });
}

export function createSession(token, title) {
  return request('POST', '/sessions', { title: title || 'New Session' }, token);
}

export function getSessions(token, page = 1) {
  return request('GET', `/sessions?page=${page}&per_page=50`, null, token);
}

export function getMessages(token, sessionId) {
  return request('GET', `/sessions/${sessionId}/messages`, null, token);
}

export function submitMessage(token, sessionId, prompt, diagramTypes) {
  return request('POST', `/sessions/${sessionId}/messages`, { prompt, diagram_types: diagramTypes }, token);
}

export function updateMessage(token, sessionId, messageId, prompt, diagramTypes) {
  return request('PUT', `/sessions/${sessionId}/messages/${messageId}`, { prompt, diagram_types: diagramTypes }, token);
}

export function getDiagrams(token, sessionId, messageId) {
  return request('GET', `/sessions/${sessionId}/messages/${messageId}/diagrams`, null, token);
}

export function submitFeedback(token, diagramId, rating, feedbackType, feedbackText, corrections) {
  return request('POST', '/feedback', { diagram_id: diagramId, rating, feedback_type: feedbackType, feedback_text: feedbackText, corrections: corrections || null }, token);
}

export function patchSession(token, sessionId, title) {
  return request('PATCH', `/sessions/${sessionId}`, { title }, token);
}

export function submitMessageFeedback(token, messageId, feedbackType, feedbackText) {
  return request('POST', '/feedback', {
    message_id: messageId,
    feedback_type: feedbackType,
    feedback_text: feedbackText,
  }, token);
}

export function buildWsUrl(wsPath) {
  return `ws://localhost:8000${wsPath}`;
}
