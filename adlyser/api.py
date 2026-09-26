"""FastAPI app: serves output folders only, runs jobs with progress, uploads, thumbnails and brands.

Only these are ever served: a video by file name, an ad creative, and ``vmap.xml`` / ``debug.json`` of a
job folder. Nothing else under ``data/`` (cache, uploads, catalogue, logs) is reachable.
"""

import asyncio
import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, ValidationError

from adlyser.agents.catalogue import normalise_catalogue, read_catalogue, slug
from adlyser.cache import DiskCache
from adlyser.config import Settings, get_settings
from adlyser.errors import CatalogueError, PerceptionError
from adlyser.graph import run_pipeline
from adlyser.llm.client import make_clients
from adlyser.llm.embed import Embedder
from adlyser.log import get_logger
from adlyser.perception.audio import probe_duration
from adlyser.perception.keyframes import extract_frames
from adlyser.schemas import Brand, DebugReport

log = get_logger(__name__)
NAME = re.compile(r"^[A-Za-z0-9_-]+$")
JOB_FILES = {"vmap.xml": "application/xml", "debug.json": "application/json"}
CHUNK = 1024 * 1024
FRAME_CACHE_CONTROL = "public, max-age=86400"


@dataclass
class Job:
    """One pipeline run: its progress events and how it ended."""

    status: str = "running"
    events: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""
    task: asyncio.Task[None] | None = None


class BrandText(BaseModel):
    """Body of the add-brand calls: free text or one JSON object."""

    text: str


class AddedBrand(BaseModel):
    """A brand added from the UI: its raw record is kept so a run can normalise it like any other."""

    id: str
    name: str
    record: dict[str, Any]


def reserved_names(settings: Settings) -> set[str]:
    """Folder names under ``data/`` that are not jobs, so no video may take them."""
    return {
        "creatives",
        settings.cache_dir.name,
        settings.api.uploads_dir.name,
        settings.catalogue.added_path.parent.name,
    }


def list_videos(settings: Settings) -> dict[str, Path]:
    """Every playable video by job name: the sample folder first, then uploads.

    :param settings: loaded settings.
    :return: name (file stem) to path. Files with other suffixes or unusable names are left out.
    """
    found: dict[str, Path] = {}
    skip = reserved_names(settings)
    for folder in (settings.videos_dir, settings.api.uploads_dir):
        if not folder.is_dir():
            continue
        for path in sorted(folder.iterdir()):
            ok = path.is_file() and path.suffix.lower() in settings.api.upload_suffixes
            if ok and NAME.match(path.stem) and path.stem not in skip:
                found.setdefault(path.stem, path)
    return found


def video_by_filename(settings: Settings, filename: str) -> Path | None:
    """Find a served video by its exact file name.

    :param settings: loaded settings.
    :param filename: e.g. ``feluda.mp4``.
    :return: its path, or None if no known video has that file name.
    """
    return next((p for p in list_videos(settings).values() if p.name == filename), None)


def read_report(job_dir: Path) -> DebugReport | None:
    """Read a job's debug.json, or None if it is missing or does not match the schema."""
    try:
        text = (job_dir / "debug.json").read_text()
    except OSError:
        return None
    try:
        return DebugReport.model_validate_json(text)
    except ValidationError:
        log.warning("debug_unreadable", extra={"job": job_dir.name})
        return None


def _catalogue_records(raw: str) -> list[dict[str, Any]] | None:
    """The catalogue's records if it is a JSON list of objects, else None (CSV or free text)."""
    try:
        records = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if isinstance(records, list) and all(isinstance(r, dict) for r in records):
        return records
    return None


def read_added(settings: Settings) -> list[AddedBrand]:
    """Brands added from the UI, oldest first."""
    try:
        return [AddedBrand.model_validate(x) for x in json.loads(settings.catalogue.added_path.read_text())]
    except (OSError, json.JSONDecodeError, ValidationError):
        return []


def write_added(settings: Settings, added: list[AddedBrand]) -> None:
    """Save the UI-added brands."""
    path = settings.catalogue.added_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([a.model_dump() for a in added], ensure_ascii=False, indent=1))


def working_settings(settings: Settings) -> Settings:
    """Write the catalogue a run reads (seed plus added brands) and point the settings at it.

    :param settings: loaded settings.
    :return: settings whose ``catalogue.path`` is the merged file.
    :raises CatalogueError: if the seed catalogue cannot be read.
    """
    cfg = settings.catalogue
    seed = read_catalogue(cfg.path)
    added = [a.record for a in read_added(settings)]
    records = _catalogue_records(seed)
    if records is not None:
        merged = json.dumps([*records, *added], ensure_ascii=False, indent=1)
    else:  # CSV or free text: keep it as it is and append the added records as JSON lines
        merged = "\n".join([seed.rstrip(), *(json.dumps(r, ensure_ascii=False) for r in added)])
    cfg.working_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.working_path.write_text(merged)
    return settings.model_copy(update={"catalogue": cfg.model_copy(update={"path": cfg.working_path})})


def brand_record(text: str) -> dict[str, Any]:
    """Turn what the user typed into a catalogue record: a JSON object as it is, anything else as a brief."""
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    return parsed if isinstance(parsed, dict) else {"brief": text.strip()}


async def _job_events(job: Job, poll_s: float) -> AsyncIterator[str]:
    """Server-sent events for one job: every progress event, then one ``end`` event."""
    sent = 0
    while True:
        while sent < len(job.events):
            yield f"data: {json.dumps(job.events[sent])}\n\n"
            sent += 1
        if job.status != "running":
            break
        await asyncio.sleep(poll_s)
    yield f"data: {json.dumps({'type': 'end', 'status': job.status, 'error': job.error})}\n\n"


def create_app(settings: Settings | None = None, embedder: Embedder | None = None) -> FastAPI:
    """Build the app.

    :param settings: settings to use (defaults to the loaded config).
    :param embedder: the embedder to share with every run (defaults to one built from the config).
    :return: the FastAPI app. bge-m3 is loaded once, when the app starts.
    """
    settings = settings or get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    shared = embedder or Embedder(settings.matcher.embed_model, DiskCache(settings.cache_dir / "embeddings"))
    jobs: dict[str, Job] = {}
    durations: dict[Path, float] = {}
    clients: dict[str, Any] = {}

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        """Load the embedding model once, and stop any running job on shutdown."""
        await shared.preload()
        yield
        for job in jobs.values():
            if job.task and not job.task.done():
                job.task.cancel()

    app = FastAPI(title="ADlyser", lifespan=lifespan)

    def busy() -> bool:
        return any(j.status == "running" for j in jobs.values())

    def start_job(name: str, video: Path) -> None:
        """Run the pipeline for one video in the background."""
        job = Job()
        jobs[name] = job

        def on_event(node: str, elapsed_s: float) -> None:
            job.events.append({"type": "node", "node": node, "elapsed_s": elapsed_s})

        async def run() -> None:
            try:
                await run_pipeline(
                    video, working_settings(settings), settings.data_dir / name,
                    on_event=on_event, embedder=shared,
                )  # fmt: skip
                job.status = "done"
            except asyncio.CancelledError:
                job.status, job.error = "error", "cancelled"
                raise
            except Exception as exc:  # the job is a boundary: report the failure, never crash the server
                log.exception("job_failed", extra={"job": name})
                job.status, job.error = "error", str(exc) or type(exc).__name__

        job.task = asyncio.create_task(run())

    # --- files -------------------------------------------------------------------------------------

    @app.get("/videos/{filename}")
    async def get_video(filename: str) -> FileResponse:
        path = video_by_filename(settings, filename)
        if path is None:
            raise HTTPException(404)
        return FileResponse(path)

    @app.get("/data/creatives/{filename}")
    async def get_creative(filename: str) -> FileResponse:
        path = settings.data_dir / "creatives" / filename
        if Path(filename).name != filename or path.suffix != ".mp4" or not path.is_file():
            raise HTTPException(404)
        return FileResponse(path)

    @app.get("/data/{job}/{filename}")
    async def get_job_file(job: str, filename: str) -> FileResponse:
        path = settings.data_dir / job / filename
        if not NAME.match(job) or filename not in JOB_FILES or not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, media_type=JOB_FILES[filename])

    # --- library, jobs, progress -------------------------------------------------------------------

    @app.get("/api/library")
    async def library() -> list[dict[str, Any]]:
        items = []
        for name, path in list_videos(settings).items():
            report = read_report(settings.data_dir / name)
            items.append(
                {
                    "name": name,
                    "video": path.name,
                    "video_url": f"/videos/{path.name}",
                    "processed": report is not None,
                    "duration_s": report.duration_s if report else None,
                    "breaks": sum(b.outcome != "dropped" for b in report.breaks) if report else 0,
                    "candidates": len(report.candidates) if report else 0,
                    "wall_s": report.wall_s if report else None,
                    "uploaded": path.parent == settings.api.uploads_dir,
                }
            )
        return items

    @app.get("/api/jobs/{name}")
    async def job_status(name: str) -> dict[str, Any]:
        job = jobs.get(name)
        if job is None:
            return {"status": "idle", "events": [], "error": ""}
        return {"status": job.status, "events": job.events, "error": job.error}

    @app.get("/api/jobs/{name}/events")
    async def job_events(name: str) -> StreamingResponse:
        job = jobs.get(name) or Job(status="idle")
        return StreamingResponse(
            _job_events(job, settings.api.events_poll_s),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/jobs/{name}/run", status_code=202)
    async def run_job(name: str) -> dict[str, str]:
        video = list_videos(settings).get(name)
        if video is None:
            raise HTTPException(404, "unknown video")
        if busy():
            raise HTTPException(409, "another job is running")
        start_job(name, video)
        return {"status": "running"}

    @app.get("/api/jobs/{name}/frame")
    async def job_frame(name: str, t: float, size: Literal["thumb", "large"] = "thumb") -> Response:
        video = list_videos(settings).get(name)
        if video is None:
            raise HTTPException(404, "unknown video")
        try:
            if video not in durations:
                durations[video] = await asyncio.to_thread(probe_duration, video)
            step = settings.api.frame_step_s
            at = min(max(round(t / step) * step, 0.0), max(durations[video] - 0.5, 0.0))
            frames_cfg = settings.frames
            if size == "large":
                frames_cfg = frames_cfg.model_copy(update={"width": settings.api.large_frame_width})
            frame = await asyncio.to_thread(
                extract_frames, video, [at], frames_cfg, settings.data_dir / name / "thumbs"
            )
        except PerceptionError as exc:
            raise HTTPException(404, str(exc)) from exc
        return Response(frame[0], media_type="image/jpeg", headers={"Cache-Control": FRAME_CACHE_CONTROL})

    # --- upload ------------------------------------------------------------------------------------

    @app.post("/api/upload", status_code=202)
    async def upload(file: UploadFile) -> dict[str, str]:
        cfg = settings.api
        original = Path(file.filename or "")
        suffix = original.suffix.lower()
        if suffix not in cfg.upload_suffixes:
            raise HTTPException(400, f"only {', '.join(cfg.upload_suffixes)} files are accepted")
        if busy():
            raise HTTPException(409, "another job is running")
        taken = {*list_videos(settings), *reserved_names(settings)}
        if settings.data_dir.is_dir():
            taken |= {p.name for p in settings.data_dir.iterdir()}
        base = slug(original.stem) or "video"
        name, n = base, 2
        while name in taken:
            name, n = f"{base}-{n}", n + 1
        cfg.uploads_dir.mkdir(parents=True, exist_ok=True)
        path = cfg.uploads_dir / f"{name}{suffix}"
        size, limit = 0, cfg.upload_max_mb * CHUNK
        with path.open("wb") as out:
            while chunk := await file.read(CHUNK):
                size += len(chunk)
                if size > limit:
                    break
                out.write(chunk)
        if size > limit:
            path.unlink(missing_ok=True)
            raise HTTPException(413, f"the file is over {cfg.upload_max_mb} MB")
        start_job(name, path)
        return {"name": name}

    # --- brands ------------------------------------------------------------------------------------

    async def normalise_one(text: str) -> tuple[Brand, dict[str, Any]]:
        """Normalise what the user typed into exactly one brand (one cached text call)."""
        if not text.strip():
            raise HTTPException(422, "type or paste a brand")
        if "text" not in clients:
            clients["text"] = make_clients(settings)[1]
        record = brand_record(text)
        try:
            brands = await normalise_catalogue(
                clients["text"],
                json.dumps([record], ensure_ascii=False),
                settings.catalogue.default_negative_tags,
            )
        except CatalogueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if len(brands) != 1:
            raise HTTPException(
                422, "add one brand at a time" if brands else "could not read a brand from that"
            )
        return brands[0], record

    @app.post("/api/brands/preview")
    async def preview_brand(body: BrandText) -> Brand:
        return (await normalise_one(body.text))[0]

    @app.get("/api/brands/added")
    async def added_brands() -> list[AddedBrand]:
        return read_added(settings)

    @app.post("/api/brands", status_code=201)
    async def add_brand(body: BrandText) -> AddedBrand:
        brand, record = await normalise_one(body.text)
        added = read_added(settings)
        entry = AddedBrand(id=brand.id, name=brand.name, record=record)
        write_added(settings, [a for a in added if a.id != entry.id] + [entry])
        return entry

    @app.delete("/api/brands/{brand_id}", status_code=204)
    async def remove_brand(brand_id: str) -> Response:
        added = read_added(settings)
        kept = [a for a in added if a.id != brand_id]
        if len(kept) == len(added):
            raise HTTPException(404, "not an added brand")
        write_added(settings, kept)
        return Response(status_code=204)

    return app


app = create_app()
