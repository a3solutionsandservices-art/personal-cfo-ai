from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.api import accounts

app = FastAPI(
    title="Personal CFO AI",
    description="Brutal financial analysis system",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(accounts.router)

@app.get("/")
async def root():
    return {
        "status": "ok",
        "message": "Personal CFO AI is running!",
        "version": "1.0.0"
    }

@app.get("/api/health")
async def health():
    return {"status": "healthy", "database": "connected"}
