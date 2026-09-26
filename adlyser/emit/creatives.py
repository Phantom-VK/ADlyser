"""Ad creatives: 10 s title-card slates made with ffmpeg (no real ad assets needed)."""

import subprocess
import tempfile
from pathlib import Path

from adlyser.config import CreativesConfig
from adlyser.errors import EmitError


def slate_command(title_file: Path, subtitle_file: Path, out: Path, cfg: CreativesConfig) -> list[str]:
    """Build the ffmpeg command for a slate. Text comes from files, so it needs no escaping.

    :param title_file: text file holding the big line.
    :param subtitle_file: text file holding the small line.
    :param out: output mp4 path.
    :param cfg: slate settings.
    :return: the argument list.
    """
    common = f"font='{cfg.font}':fontcolor=white:x=(w-text_w)/2"
    vf = (
        f"drawtext=textfile={title_file}:{common}:fontsize=h/12:y=(h-text_h)/2-h/16,"
        f"drawtext=textfile={subtitle_file}:{common}:fontcolor=0xa0a4ab:fontsize=h/22:y=(h/2)+h/12"
    )
    return [
        "ffmpeg", "-v", "error", "-y",
        "-f", "lavfi", "-i", f"color=c=0x101216:s={cfg.width}x{cfg.height}:d={cfg.duration_s}:r=25",
        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
        "-t", f"{cfg.duration_s}", "-vf", vf,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
        "-movflags", "+faststart", "-f", "mp4", str(out),
    ]  # fmt: skip


def make_slate(title: str, subtitle: str, out: Path, cfg: CreativesConfig) -> Path:
    """Render a slate mp4 (written to a temp file, then renamed).

    :param title: the big line of text.
    :param subtitle: the small line of text.
    :param out: destination mp4 (parent is created).
    :param cfg: slate settings.
    :return: ``out``.
    :raises EmitError: if ffmpeg fails.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp_out = out.with_name(out.name + ".tmp")
    with tempfile.TemporaryDirectory() as tmp:
        title_file, subtitle_file = Path(tmp) / "title.txt", Path(tmp) / "subtitle.txt"
        title_file.write_text(title, encoding="utf-8")
        subtitle_file.write_text(subtitle, encoding="utf-8")
        try:
            subprocess.run(
                slate_command(title_file, subtitle_file, tmp_out, cfg),
                capture_output=True,
                text=True,
                check=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            tmp_out.unlink(missing_ok=True)
            detail = getattr(exc, "stderr", "") or ""
            raise EmitError(f"slate creation failed: {detail[:200]}") from exc
    tmp_out.replace(out)
    return out
