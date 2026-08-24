from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.api.routes import router as api_router

app = FastAPI(
    title="Mission Ops Scheduling Copilot",
    description="API for ground-station/antenna conflict resolution and what-if scenarios.",
    version="1.0.0"
)

# Allow Frontend (Person 5) to hit your API from localhost
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Update for production/demo deployment
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount your routes
app.include_router(api_router, prefix="/api/v1")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)