import logging
from collections import OrderedDict
from typing import Dict, List
from fastapi import WebSocket

logger = logging.getLogger(__name__)

# Cap buffered frames per message so a client that never connects can't grow
# memory without bound.
_MAX_BUFFER = 200
# Cap the number of message buffers retained (incl. completed runs waiting for a
# late-connecting client). Bounds total memory; oldest buffers are evicted first.
_MAX_PENDING_MESSAGES = 128


class ConnectionManager:
    def __init__(self):
        # Maps message_id -> list of active WebSocket connections
        self.active_connections: Dict[str, List[WebSocket]] = {}
        # Frames broadcast before any socket connected, replayed on connect.
        # Retained (bounded) even after 'complete' so a client that connects AFTER a
        # fast/cache-hit run finished still replays the results instead of hanging.
        self.pending_frames: "OrderedDict[str, List[dict]]" = OrderedDict()

    async def connect(self, message_id: str, websocket: WebSocket):
        await websocket.accept()
        if message_id not in self.active_connections:
            self.active_connections[message_id] = []
        self.active_connections[message_id].append(websocket)
        logger.info(f"WebSocket connected for message_id: {message_id}")

        # Replay any frames that were produced before this socket connected
        # (background orchestration starts before the browser opens the socket).
        buffered = self.pending_frames.pop(message_id, [])
        for frame in buffered:
            try:
                await websocket.send_json(frame)
            except Exception as e:
                logger.warning(f"Failed to replay buffered WS frame: {e}")
                break

    def disconnect(self, message_id: str, websocket: WebSocket):
        if message_id in self.active_connections:
            try:
                self.active_connections[message_id].remove(websocket)
            except ValueError:
                pass
            if not self.active_connections[message_id]:
                del self.active_connections[message_id]
        logger.info(f"WebSocket disconnected for message_id: {message_id}")

    async def broadcast_to_message(self, message_id: str, message: dict):
        connections = self.active_connections.get(message_id)

        # No socket connected yet — buffer so early frames aren't lost. Keep the buffer
        # even on 'complete': a client may still connect afterwards (fast/cache-hit runs
        # can finish before the browser opens the socket) and needs the full replay.
        if not connections:
            buf = self.pending_frames.setdefault(message_id, [])
            if len(buf) < _MAX_BUFFER:
                buf.append(message)
            self.pending_frames.move_to_end(message_id)  # most-recently-written
            # Bound total retained buffers; evict the oldest (LRU by last write).
            while len(self.pending_frames) > _MAX_PENDING_MESSAGES:
                evicted, _ = self.pending_frames.popitem(last=False)
                logger.debug("Evicted pending WS buffer for message %s", evicted)
            return

        stale_connections = []
        # Copy the list to avoid mutation during iteration.
        for connection in list(connections):
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.warning(f"Failed to send WS message to connection: {e}")
                stale_connections.append(connection)

        # Clean up any failed connections
        for conn in stale_connections:
            self.disconnect(message_id, conn)


# Global singleton instance
ws_manager = ConnectionManager()
