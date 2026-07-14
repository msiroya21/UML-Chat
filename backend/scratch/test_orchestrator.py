import asyncio
import logging
import sys
import os

# Adjust path to import app modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.renderer import encode_plantuml, render_plantuml_to_svg
from app.services.cache import get_cached_diagram, set_cached_diagram
from app.services.orchestrator import run_orchestrator_background
from app.core.ws_manager import ws_manager
from app.models.db import Base, engine, SessionLocal, User, Session, Message, Diagram
from sqlalchemy.future import select

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_orchestrator")

async def test_plantuml_encoding():
    logger.info("--- Testing PlantUML Encoding ---")
    uml_code = "@startuml\nBob -> Alice : hello\n@enduml"
    encoded = encode_plantuml(uml_code)
    logger.info(f"UML: {repr(uml_code)}")
    logger.info(f"Encoded: {encoded}")
    # Standard check for Bob -> Alice
    assert encoded is not None
    logger.info("PlantUML Encoding test passed!")

async def test_plantuml_rendering():
    logger.info("--- Testing PlantUML Rendering ---")
    uml_code = "@startuml\ntitle Simple Flow\nBob -> Alice : hello\n@enduml"
    try:
        svg = await render_plantuml_to_svg(uml_code)
        logger.info(f"SVG received (len: {len(svg)})")
        assert "<svg" in svg
        logger.info("PlantUML Rendering test passed!")
    except Exception as e:
        logger.error(f"PlantUML Rendering failed: {e}")
        raise e

def test_cache():
    logger.info("--- Testing Cache ---")
    prompt = "Test prompt for caching"
    diagram_type = "sequence"
    data = {
        "ir": {"diagram_type": "sequence", "title": "Cache Test"},
        "plantuml_code": "@startuml\n@enduml",
        "svg": "<svg>Cache</svg>"
    }
    
    # Verify miss
    assert get_cached_diagram(prompt, diagram_type) is None
    
    # Store
    set_cached_diagram(prompt, diagram_type, data)
    
    # Verify hit
    cached = get_cached_diagram(prompt, diagram_type)
    assert cached is not None
    assert cached["ir"]["title"] == "Cache Test"
    logger.info("Cache test passed!")

# Mock WebSocket object for capturing broadcasted frames
class MockWebSocket:
    def __init__(self):
        self.sent_messages = []
        
    async def accept(self):
        pass
        
    async def send_json(self, data):
        self.sent_messages.append(data)
        logger.info(f"[MockWS Sent] {data.get('type')} - Stage: {data.get('stage')} - Diagram: {data.get('diagram_type')}")

async def test_orchestrator_pipeline():
    logger.info("--- Testing Orchestrator Pipeline ---")
    
    # 1. Initialize DB and create dummy user, session, message
    # (scratch harness creates its own tables; the app relies on Alembic)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    async with SessionLocal() as db:
        # Create a dummy user
        result = await db.execute(select(User).where(User.email == "test@example.com"))
        user = result.scalars().first()
        if not user:
            user = User(email="test@example.com", name="Test User", password_hash="hash")
            db.add(user)
            await db.commit()
            await db.refresh(user)
            
        # Create a session
        session = Session(user_id=user.id, title="Test Session")
        db.add(session)
        await db.commit()
        await db.refresh(session)
        
        # Create a message
        message = Message(
            session_id=session.id,
            role="user",
            prompt="Generate a sequence diagram of a scraper service storing records in a database",
            diagram_types=["sequence"],
            version=1
        )
        db.add(message)
        await db.commit()
        await db.refresh(message)
        
        message_id = message.id
        prompt_context = message.prompt
        diagram_types = message.diagram_types

    # 2. Setup mock WebSocket subscription
    mock_ws = MockWebSocket()
    # Direct access to connect without HTTP validation
    ws_manager.active_connections[message_id] = [mock_ws]

    # 3. Run orchestrator background task
    logger.info("Running orchestrator background task...")
    await run_orchestrator_background(message_id, prompt_context, diagram_types)
    
    # 4. Verify output in database
    async with SessionLocal() as db:
        diagrams_result = await db.execute(select(Diagram).where(Diagram.message_id == message_id))
        diagrams = diagrams_result.scalars().all()
        logger.info(f"Diagrams saved in DB: {len(diagrams)}")
        for d in diagrams:
            logger.info(f" - Saved Type: {d.diagram_type}, Valid: {d.is_valid}, SVG len: {len(d.svg)}")
            
        assert len(diagrams) > 0
        assert diagrams[0].diagram_type == "sequence"
        assert "<svg" in diagrams[0].svg

    # 5. Verify WebSocket frames
    logger.info(f"WS Frames count: {len(mock_ws.sent_messages)}")
    types_sent = [msg.get("type") for msg in mock_ws.sent_messages]
    logger.info(f"WS Event flow: {types_sent}")
    assert "progress" in types_sent
    assert "diagram_result" in types_sent or "error" in types_sent
    assert "complete" in types_sent

    logger.info("Orchestrator Pipeline test passed!")

async def main():
    await test_plantuml_encoding()
    await test_plantuml_rendering()
    test_cache()
    await test_orchestrator_pipeline()
    logger.info("ALL TESTS COMPLETED SUCCESSFULLY!")

if __name__ == "__main__":
    asyncio.run(main())
