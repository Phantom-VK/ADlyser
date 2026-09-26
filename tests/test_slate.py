from pathlib import Path

from adlyser.config import CreativesConfig
from adlyser.emit.creatives import slate_command


def test_slate_command_reads_text_from_files_and_uses_configured_size_and_duration():
    cfg = CreativesConfig(
        duration_s=10, width=960, height=540, font="DejaVu Sans", promo_title="t", promo_subtitle="s"
    )
    cmd = slate_command(Path("/t/title.txt"), Path("/t/sub.txt"), Path("/o/out.mp4"), cfg)
    joined = " ".join(cmd)
    assert "textfile=/t/title.txt" in joined and "textfile=/t/sub.txt" in joined
    assert "s=960x540:d=10" in joined and cmd[-1] == "/o/out.mp4"
