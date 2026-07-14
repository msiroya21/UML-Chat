import { useState, useEffect, useRef, useCallback } from 'react';

export default function useWebSocket(wsUrl) {
  const [isConnected, setIsConnected] = useState(false);
  const [isComplete, setIsComplete] = useState(false);
  const [progress, setProgress] = useState({}); // { diagram_type: { stage, percent } }
  const [diagrams, setDiagrams] = useState([]); // array of diagram_result frames
  const [errors, setErrors] = useState([]);     // array of error frames
  const wsRef = useRef(null);

  const reset = useCallback(() => {
    setIsConnected(false);
    setIsComplete(false);
    setProgress({});
    setDiagrams([]);
    setErrors([]);
  }, []);

  useEffect(() => {
    if (!wsUrl) return;

    reset();

    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => setIsConnected(true);

    ws.onmessage = (event) => {
      let frame;
      try { frame = JSON.parse(event.data); } catch { return; }

      if (frame.type === 'progress') {
        setProgress(prev => ({
          ...prev,
          [frame.diagram_type || 'global']: { stage: frame.stage, percent: frame.percent },
        }));
      } else if (frame.type === 'diagram_result') {
        setDiagrams(prev => [...prev, frame]);
        // Clear this type's bar and the global "selecting types" bar once real work lands.
        setProgress(prev => {
          const next = { ...prev };
          delete next[frame.diagram_type];
          delete next.all;
          return next;
        });
      } else if (frame.type === 'complete') {
        setIsComplete(true);
        setIsConnected(false);
        setProgress({}); // no lingering bars after the run finishes
      } else if (frame.type === 'error') {
        setErrors(prev => [...prev, frame]);
        setProgress(prev => {
          const next = { ...prev };
          delete next[frame.diagram_type];
          delete next.all;
          return next;
        });
      }
    };

    ws.onerror = () => setIsConnected(false);
    ws.onclose = () => setIsConnected(false);

    return () => {
      ws.close();
      wsRef.current = null;
    };
  }, [wsUrl, reset]);

  return { isConnected, isComplete, progress, diagrams, errors };
}
