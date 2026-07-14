from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.core.ws_manager import ws_manager

router = APIRouter(tags=["WebSocket"])


@router.websocket("/ws/stream/{message_id}")
async def websocket_stream(message_id: str, websocket: WebSocket):
    await ws_manager.connect(message_id, websocket)
    try:
        # Keep connection alive; orchestrator pushes frames via ws_manager
        while True:
            # Wait for any client message (ping/close); we don't use client messages
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(message_id, websocket)
