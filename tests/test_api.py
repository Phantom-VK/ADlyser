"""API behaviour: what is served, jobs and progress, uploads, thumbnails, brands. No paid calls."""

import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from adlyser import api
from adlyser.config import ApiConfig, CatalogueConfig, get_settings
from adlyser.errors import AdlyserError
from adlyser.schemas import Brand, DebugReport, Funnel

VMAP = "<vmap/>"


def report(video: str = "ep1.mp4", breaks: int = 0) -> DebugReport:
    """A minimal valid debug report with ``breaks`` placed breaks."""
    placed = [
        {
            "break_id": f"break-{i}", "t": 100.0 * i, "break_score": 0.9, "outcome": "brand",
            "brand_id": "b", "brand_name": "B", "before_scene": 0, "after_scene": 1, "shortlist": [],
            "blocked": [], "sweep_added": {}, "review": None, "review_trace": [], "history": [], "reason": "r",
        }
        for i in range(1, breaks + 1)
    ]  # fmt: skip
    return DebugReport.model_validate(
        {
            "video": video, "duration_s": 600.0, "funnel": Funnel(silences=9, long_enough=8, with_cut=7,
                                                                  in_window=6, after_spacing_cap=5),
            "candidates": [], "stretches": [], "scenes": [], "breaks": placed, "brands": [],
            "llm_stats": {}, "loops": 0, "wall_s": 12.5,
        }
    )  # fmt: skip


class FakeEmbedder:
    def __init__(self) -> None:
        self.preloads = 0

    async def preload(self) -> None:
        self.preloads += 1


@pytest.fixture
def env(tmp_path: Path):
    """Settings on a temp tree: videos, data (one finished job, cache, creatives) and uploads."""
    videos, data = tmp_path / "videos", tmp_path / "data"
    (videos / "sub").mkdir(parents=True)
    (videos / "ep1.mp4").write_bytes(b"0123456789" * 10)
    (videos / "ep2.mp4").write_bytes(b"x" * 20)
    (videos / "notes.txt").write_text("not a video")
    (videos / "sub" / "hidden.mp4").write_bytes(b"x")
    job = data / "ep1"
    job.mkdir(parents=True)
    (job / "vmap.xml").write_text(VMAP)
    (job / "debug.json").write_text(report(breaks=2).model_dump_json())
    (job / "perception.json").write_text("{}")
    (data / "cache" / "llm").mkdir(parents=True)
    (data / "cache" / "llm" / "secret.json").write_text("{}")
    (data / "creatives").mkdir()
    (data / "creatives" / "ad.mp4").write_bytes(b"ad")
    (data / "creatives" / "notes.txt").write_text("no")
    base = get_settings()
    return base.model_copy(
        update={
            "videos_dir": videos,
            "data_dir": data,
            "cache_dir": data / "cache",
            "api": ApiConfig(uploads_dir=data / "uploads", upload_max_mb=1, upload_suffixes=[".mp4"],
                             frame_step_s=0.5, large_frame_width=800, events_poll_s=0.01),
            "catalogue": CatalogueConfig(path=Path("catalogue/brands.json"), added_path=data / "cat" / "added.json",
                                         working_path=data / "cat" / "working.json"),
        }
    )  # fmt: skip


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture
def client(env, embedder):
    with TestClient(api.create_app(env, embedder)) as c:
        yield c


def brand(name: str) -> Brand:
    return Brand(id=api.slug(name), name=name, category="c", tagline="t", description="d")


# --- what is served ---------------------------------------------------------------------------------


def test_job_outputs_are_served(client):
    assert client.get("/data/ep1/vmap.xml").text == VMAP
    assert client.get("/data/ep1/debug.json").json()["video"] == "ep1.mp4"


def test_other_files_in_data_are_not_served(client):
    assert client.get("/data/ep1/perception.json").status_code == 404
    assert client.get("/data/cache/llm/secret.json").status_code == 404
    assert client.get("/data/cache/debug.json").status_code == 404
    assert client.get("/data/nojob/vmap.xml").status_code == 404
    assert client.get("/data/ep1").status_code == 404
    assert client.get("/data/").status_code == 404


def test_path_tricks_are_not_served(client):
    for url in ["/data/%2e%2e/videos/ep1.mp4", "/data/ep1/..%2fperception.json", "/data/..%2fcache/vmap.xml",
                "/data/creatives/..%2f..%2fep1%2fdebug.json", "/videos/..%2fep1.mp4", "/videos/sub%2fhidden.mp4"]:  # fmt: skip
        assert client.get(url).status_code == 404, url


def test_creatives_are_served_but_only_videos(client):
    assert client.get("/data/creatives/ad.mp4").content == b"ad"
    assert client.get("/data/creatives/notes.txt").status_code == 404
    assert client.get("/data/creatives/missing.mp4").status_code == 404


def test_videos_are_served_by_name_and_support_ranges(client):
    assert client.get("/videos/ep1.mp4").status_code == 200
    part = client.get("/videos/ep1.mp4", headers={"Range": "bytes=0-3"})
    assert part.status_code == 206 and part.content == b"0123"
    assert client.get("/videos/notes.txt").status_code == 404
    assert client.get("/videos/missing.mp4").status_code == 404


# --- startup ---------------------------------------------------------------------------------------


def test_embedder_is_loaded_once_at_startup(env, embedder):
    with TestClient(api.create_app(env, embedder)) as c:
        c.get("/api/library")
        c.get("/api/library")
        assert embedder.preloads == 1


# --- library ---------------------------------------------------------------------------------------


def test_library_lists_videos_with_their_summary(client):
    items = {i["name"]: i for i in client.get("/api/library").json()}
    assert set(items) == {"ep1", "ep2"}
    assert items["ep1"]["processed"] is True and items["ep1"]["breaks"] == 2
    assert items["ep1"]["duration_s"] == 600.0 and items["ep1"]["video_url"] == "/videos/ep1.mp4"
    assert items["ep2"]["processed"] is False and items["ep2"]["breaks"] == 0


def test_an_unreadable_debug_json_counts_as_not_processed(client, env):
    (env.data_dir / "ep1" / "debug.json").write_text("{not json")
    items = {i["name"]: i for i in client.get("/api/library").json()}
    assert items["ep1"]["processed"] is False


# --- jobs and progress -----------------------------------------------------------------------------


def fake_pipeline(monkeypatch, *, fail: bool = False):
    """Replace run_pipeline: emits two node events, then writes a vmap (or fails)."""
    calls: list[dict] = []

    async def run(video, settings, out_dir, base_url="", on_event=None, embedder=None):
        calls.append(
            {"video": video, "out": out_dir, "catalogue": settings.catalogue.path, "embedder": embedder}
        )
        on_event("measure", 1.0)
        on_event("analyse", 2.0)
        if fail:
            raise AdlyserError("boom")
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "vmap.xml").write_text("<new/>")
        (out_dir / "debug.json").write_text(report(video.name, breaks=1).model_dump_json())
        return report(video.name, breaks=1)

    monkeypatch.setattr(api, "run_pipeline", run)
    return calls


def read_stream(client, url) -> list[dict]:
    with client.stream("GET", url) as resp:
        return [json.loads(line[6:]) for line in resp.iter_lines() if line.startswith("data: ")]


def test_idle_job_has_no_events(client):
    assert client.get("/api/jobs/ep2").json()["status"] == "idle"
    assert read_stream(client, "/api/jobs/ep2/events") == [{"type": "end", "status": "idle", "error": ""}]


def test_run_streams_progress_then_ends(client, monkeypatch, embedder):
    calls = fake_pipeline(monkeypatch)
    assert client.post("/api/jobs/ep2/run").status_code == 202
    events = read_stream(client, "/api/jobs/ep2/events")
    assert [e.get("node") for e in events[:-1]] == ["measure", "analyse"]
    assert events[-1] == {"type": "end", "status": "done", "error": ""}
    assert calls[0]["embedder"] is embedder and calls[0]["out"].name == "ep2"
    assert client.get("/data/ep2/vmap.xml").text == "<new/>"
    assert client.get("/api/jobs/ep2").json()["status"] == "done"


def test_a_failed_run_reports_the_error_and_frees_the_slot(client, monkeypatch):
    fake_pipeline(monkeypatch, fail=True)
    client.post("/api/jobs/ep2/run")
    end = read_stream(client, "/api/jobs/ep2/events")[-1]
    assert end["status"] == "error" and "boom" in end["error"]
    fake_pipeline(monkeypatch)
    assert client.post("/api/jobs/ep2/run").status_code == 202


def test_unknown_video_cannot_run(client):
    assert client.post("/api/jobs/nope/run").status_code == 404
    assert client.post("/api/jobs/..%2fep1/run").status_code == 404


def test_only_one_job_runs_at_a_time(client, monkeypatch):
    import asyncio

    gate = asyncio.Event()

    async def slow(video, settings, out_dir, base_url="", on_event=None, embedder=None):
        await gate.wait()

    monkeypatch.setattr(api, "run_pipeline", slow)
    assert client.post("/api/jobs/ep1/run").status_code == 202
    assert client.post("/api/jobs/ep2/run").status_code == 409
    assert client.post("/api/jobs/ep1/run").status_code == 409


# --- upload ----------------------------------------------------------------------------------------


def upload(client, name="My Clip.mp4", data=b"video-bytes"):
    return client.post("/api/upload", files={"file": (name, data, "video/mp4")})


def test_upload_saves_the_video_and_starts_a_job(client, env, monkeypatch):
    calls = fake_pipeline(monkeypatch)
    resp = upload(client)
    assert resp.status_code == 202 and resp.json()["name"] == "my-clip"
    assert (env.api.uploads_dir / "my-clip.mp4").read_bytes() == b"video-bytes"
    read_stream(client, "/api/jobs/my-clip/events")
    assert calls[0]["video"] == env.api.uploads_dir / "my-clip.mp4"
    names = {i["name"] for i in client.get("/api/library").json()}
    assert "my-clip" in names
    assert client.get("/videos/my-clip.mp4").content == b"video-bytes"


def test_upload_rejects_other_file_types(client, env):
    assert upload(client, name="script.sh").status_code == 400
    assert not env.api.uploads_dir.exists() or not list(env.api.uploads_dir.iterdir())


def test_upload_rejects_files_over_the_size_cap(client, env):
    assert upload(client, data=b"x" * (1024 * 1024 + 1)).status_code == 413
    assert not list(env.api.uploads_dir.iterdir())


def test_upload_never_overwrites_an_existing_video(client, env, monkeypatch):
    fake_pipeline(monkeypatch)
    first = upload(client, name="ep1.mp4").json()["name"]
    read_stream(client, f"/api/jobs/{first}/events")
    assert first == "ep1-2"
    assert (env.videos_dir / "ep1.mp4").read_bytes() == b"0123456789" * 10


def test_upload_is_refused_while_a_job_runs(client, monkeypatch):
    import asyncio

    gate = asyncio.Event()

    async def slow(video, settings, out_dir, base_url="", on_event=None, embedder=None):
        await gate.wait()

    monkeypatch.setattr(api, "run_pipeline", slow)
    assert upload(client).status_code == 202
    assert upload(client, name="other.mp4").status_code == 409


# --- thumbnails ------------------------------------------------------------------------------------


@pytest.fixture
def real_video(env) -> Path:
    path = env.videos_dir / "real.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10:duration=4",
         "-pix_fmt", "yuv420p", "-y", str(path)],
        check=True,
    )  # fmt: skip
    return path


def test_frame_endpoint_returns_a_jpeg_and_caches_it(client, env, real_video):
    resp = client.get("/api/jobs/real/frame", params={"t": 1.26})
    assert resp.status_code == 200 and resp.headers["content-type"] == "image/jpeg"
    assert resp.content[:2] == b"\xff\xd8"
    thumbs = list((env.data_dir / "real" / "thumbs").iterdir())
    assert len(thumbs) == 1
    client.get("/api/jobs/real/frame", params={"t": 1.3})  # same 0.5 s step
    assert len(list((env.data_dir / "real" / "thumbs").iterdir())) == 1


def jpeg_width(data: bytes) -> int:
    """Width from the JPEG's start-of-frame marker."""
    i = 2
    while i < len(data):
        marker, length = data[i + 1], int.from_bytes(data[i + 2 : i + 4], "big")
        if marker in (0xC0, 0xC1, 0xC2):
            return int.from_bytes(data[i + 7 : i + 9], "big")
        i += 2 + length
    raise AssertionError("no frame header")


def test_large_frames_use_the_configured_width(client, env, real_video):
    small = client.get("/api/jobs/real/frame", params={"t": 1}).content
    large = client.get("/api/jobs/real/frame", params={"t": 1, "size": "large"}).content
    assert jpeg_width(small) == env.frames.width
    assert jpeg_width(large) == env.api.large_frame_width
    assert client.get("/api/jobs/real/frame", params={"t": 1, "size": "huge"}).status_code == 422


def test_frame_time_is_clamped_and_unknown_videos_are_404(client, real_video):
    assert client.get("/api/jobs/real/frame", params={"t": 9999}).status_code == 200
    assert client.get("/api/jobs/real/frame", params={"t": -5}).status_code == 200
    assert client.get("/api/jobs/nope/frame", params={"t": 1}).status_code == 404
    assert client.get("/api/jobs/real/frame").status_code == 422


# --- brands ----------------------------------------------------------------------------------------


@pytest.fixture
def normaliser(monkeypatch):
    """Replace the CatalogueNormaliser: the brand name is the record's first value."""
    seen: list[str] = []

    async def normalise(client, raw):
        seen.append(raw)
        records = json.loads(raw)
        return [brand(str(next(iter(r.values())))) for r in records]

    monkeypatch.setattr(api, "normalise_catalogue", normalise)
    monkeypatch.setattr(api, "make_clients", lambda settings: (None, None))
    return seen


def test_added_brands_start_empty(client):
    assert client.get("/api/brands/added").json() == []


def test_preview_normalises_free_text_without_saving(client, env, normaliser):
    resp = client.post("/api/brands/preview", json={"text": "Lotus Lassi, cold yoghurt drinks"})
    assert resp.status_code == 200 and resp.json()["name"] == "Lotus Lassi, cold yoghurt drinks"
    assert json.loads(normaliser[0]) == [{"brief": "Lotus Lassi, cold yoghurt drinks"}]
    assert not env.catalogue.added_path.exists()


def test_json_input_is_kept_as_a_record(client, normaliser):
    client.post("/api/brands/preview", json={"text": '{"brand": "Lotus Lassi", "sector": "drinks"}'})
    assert json.loads(normaliser[0]) == [{"brand": "Lotus Lassi", "sector": "drinks"}]


def test_adding_saves_the_raw_record_and_lists_it(client, env, normaliser):
    resp = client.post("/api/brands", json={"text": "Lotus Lassi"})
    assert resp.status_code == 201 and resp.json()["id"] == "lotus-lassi"
    added = client.get("/api/brands/added").json()
    assert added == [{"id": "lotus-lassi", "name": "Lotus Lassi", "record": {"brief": "Lotus Lassi"}}]
    assert json.loads(env.catalogue.added_path.read_text()) == added


def test_a_brand_that_cannot_be_read_is_rejected(client, monkeypatch):
    async def nothing(client, raw):
        return []

    monkeypatch.setattr(api, "normalise_catalogue", nothing)
    monkeypatch.setattr(api, "make_clients", lambda settings: (None, None))
    assert client.post("/api/brands", json={"text": "???"}).status_code == 422
    assert client.post("/api/brands", json={"text": "   "}).status_code == 422


def test_text_with_two_brands_is_rejected(client, monkeypatch):
    async def two(client, raw):
        return [brand("A"), brand("B")]

    monkeypatch.setattr(api, "normalise_catalogue", two)
    monkeypatch.setattr(api, "make_clients", lambda settings: (None, None))
    assert client.post("/api/brands", json={"text": "A and B"}).status_code == 422


def test_a_brand_can_be_removed(client, normaliser):
    client.post("/api/brands", json={"text": "Lotus Lassi"})
    assert client.delete("/api/brands/lotus-lassi").status_code == 204
    assert client.get("/api/brands/added").json() == []
    assert client.delete("/api/brands/lotus-lassi").status_code == 404


def test_a_run_reads_the_seed_plus_the_added_brands(client, env, normaliser, monkeypatch):
    calls = fake_pipeline(monkeypatch)
    client.post("/api/brands", json={"text": "Lotus Lassi"})
    client.post("/api/jobs/ep2/run")
    read_stream(client, "/api/jobs/ep2/events")
    assert calls[0]["catalogue"] == env.catalogue.working_path
    merged = json.loads(env.catalogue.working_path.read_text())
    seed = json.loads(Path("catalogue/brands.json").read_text())
    assert merged == [*seed, {"brief": "Lotus Lassi"}]


def test_a_run_without_added_brands_reads_the_seed_as_is(client, env, monkeypatch):
    calls = fake_pipeline(monkeypatch)
    client.post("/api/jobs/ep2/run")
    read_stream(client, "/api/jobs/ep2/events")
    assert json.loads(env.catalogue.working_path.read_text()) == json.loads(
        Path("catalogue/brands.json").read_text()
    )
    assert calls[0]["catalogue"] == env.catalogue.working_path
