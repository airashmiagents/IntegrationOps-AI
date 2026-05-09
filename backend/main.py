"""
IntegrationOps-AI — FastAPI entrypoint.

backend/
--------
Python API for CPI monitoring hooks and AI-assisted incident analysis.

Run locally:  uvicorn main:app --reload --port 8000
API docs:      http://localhost:8000/docs
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes import api_router
from services.settings import settings

app = FastAPI(title=settings.app_name, debug=settings.debug)

# Allow the Vite dev server to call the API during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "IntegrationOps-AI API — see /docs for endpoints"}
