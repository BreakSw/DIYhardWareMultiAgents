from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import compatibility, hardware, health, recommendations, requirements


app = FastAPI(
    title="DIY Multi-Agents API",
    description="Local-first computer build recommendation service",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api/v1")
app.include_router(requirements.router, prefix="/api/v1")
app.include_router(recommendations.router, prefix="/api/v1")
app.include_router(compatibility.router, prefix="/api/v1")
app.include_router(hardware.router, prefix="/api/v1")
