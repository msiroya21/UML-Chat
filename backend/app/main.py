from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import get_settings
from app.api import auth, sessions, diagrams, feedback, ws

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schema is owned by Alembic (`alembic upgrade head`); the app does not create tables.
    yield
    # Shutdown: close the shared PlantUML HTTP client.
    from app.services.renderer import close_client
    await close_client()


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    description="AI-powered UML diagram generation from natural language prompts",
    lifespan=lifespan,
)

# CORS — allow frontend dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(sessions.router, prefix="/api/v1")
app.include_router(diagrams.router, prefix="/api/v1")
app.include_router(feedback.router, prefix="/api/v1")
app.include_router(ws.router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "app": settings.APP_NAME}
