"""回看素材：抽帧、切片段。这是"不只是文字库"的关键。

文字索引告诉你答案在第 2 分 13 秒；这里负责把那一秒的画面真的调出来。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .downloader import ffmpeg_path


def _run(cmd: list[str]) -> bool:
    try:
        subprocess.run(
            cmd, check=True, capture_output=True, env={**os.environ, "PYTHONIOENCODING": "utf-8"}
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def extract_frames(video: Path, at: float, outdir: Path, count: int = 3, spread: float = 4.0) -> list[Path]:
    """在 at 秒附近抽 count 帧，间隔 spread 秒。"""
    ff = ffmpeg_path()
    if not ff or not Path(video).exists():
        return []
    outdir.mkdir(parents=True, exist_ok=True)
    frames: list[Path] = []
    start = max(0.0, at - (count - 1) * spread / 2)
    for i in range(count):
        t = start + i * spread
        out = outdir / f"frame_{int(t):05d}.jpg"
        if out.exists():
            frames.append(out)
            continue
        ok = _run(
            [ff, "-y", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", str(video),
             "-frames:v", "1", "-vf", "scale=960:-2", "-q:v", "3", str(out)]
        )
        if ok and out.exists():
            frames.append(out)
    return frames


def cut_clip(video: Path, start: float, out: Path, duration: float = 30.0) -> Path | None:
    ff = ffmpeg_path()
    if not ff or not Path(video).exists():
        return None
    out.parent.mkdir(parents=True, exist_ok=True)
    ok = _run(
        [ff, "-y", "-loglevel", "error", "-ss", f"{max(0.0, start):.3f}",
         "-i", str(video), "-t", f"{duration:.3f}", "-c", "copy", "-avoid_negative_ts", "make_zero", str(out)]
    )
    return out if ok and out.exists() else None
