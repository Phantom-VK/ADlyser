"""FastAPI app. Phase 1b: only serves the content videos and generated data (VMAP, creatives)."""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from adlyser.config import get_settings

settings = get_settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="ADlyser")
app.mount("/videos", StaticFiles(directory=settings.videos_dir), name="videos")
app.mount("/data", StaticFiles(directory=settings.data_dir), name="data")
