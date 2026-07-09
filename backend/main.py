"""StudySphere AI — application entry point.

Run:  uvicorn main:app --reload --port 8000
Then open http://localhost:8000 — the frontend is served by this same server.
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from db import init_db
from routes import router

app = FastAPI(title="StudySphere AI", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # tighten to your domain in production
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()
app.include_router(router)

FRONTEND = Path(__file__).parent.parent / "frontend"


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND), name="static")


@app.exception_handler(404)
async def spa_fallback(request, exc):
    """If a browser path isn't an API route, serve the app (and give a clear
    message if the frontend folder is missing)."""
    from fastapi.responses import JSONResponse
    if request.url.path.startswith("/api"):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    index = FRONTEND / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse(
        {"detail": "frontend/index.html not found — keep the 'backend' and "
                   "'frontend' folders side by side as in the zip."},
        status_code=500,
    )


if __name__ == "__main__":
    # Allows plain:  python main.py
    import uvicorn
    print("\n  StudySphere AI running →  http://localhost:8000\n")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
