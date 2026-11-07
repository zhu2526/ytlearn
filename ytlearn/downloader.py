"""下载：优先拿原片 + 官方字幕，拿不到字幕再走本地转写。"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .config import Config
from .store import video_dir, write_json


def ffmpeg_path() -> str | None:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg")


class _Quiet:
    def debug(self, msg: str) -> None: ...

    def info(self, msg: str) -> None: ...

    def warning(self, msg: str) -> None:
        if msg.strip():
            print(f"  ! {msg}")

    def error(self, msg: str) -> None:
        print(f"  x {msg}")


def _base_opts(cfg: Config, cookies_from_browser: str | None = None) -> dict:
    opts: dict = {
        "quiet": True,
        "noprogress": True,
        "no_warnings": False,
        "logger": _Quiet(),
        "retries": 5,
        "fragment_retries": 5,
        "concurrent_fragment_downloads": 4,
        "ignoreerrors": False,
        "nocheckcertificate": True,
        "socket_timeout": 30,
    }
    ff = ffmpeg_path()
    if ff:
        opts["ffmpeg_location"] = str(Path(ff).parent)
    if cookies_from_browser:
        opts["cookiesfrombrowser"] = (cookies_from_browser,)
    return opts


def expand(url: str, cfg: Config, cookies: str | None = None) -> list[str]:
    """把一个链接展开成一串视频链接（支持播放列表 / 频道）。"""
    import yt_dlp

    if "list=" not in url and "/playlist" not in url and "/@" not in url:
        return [url]

    opts = _base_opts(cfg, cookies)
    opts.update({"extract_flat": "in_playlist", "skip_download": True})
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info:
        return [url]
    if info.get("_type") != "playlist":
        return [info.get("webpage_url") or url]
    urls = []
    for e in info.get("entries") or []:
        if not e:
            continue
        urls.append(e.get("url") or e.get("webpage_url") or f"https://www.youtube.com/watch?v={e.get('id')}")
    print(f"  播放列表《{info.get('title')}》共 {len(urls)} 个视频")
    return urls


def download(url: str, cfg: Config, cookies: str | None = None) -> dict:
    """下载单个视频，返回元数据。已存在则直接复用。"""
    import yt_dlp

    opts = _base_opts(cfg, cookies)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    vid = info["id"]
    vdir = video_dir(cfg, vid)

    meta = {
        "id": vid,
        "title": info.get("title") or vid,
        "uploader": info.get("uploader") or info.get("channel") or "",
        "duration": info.get("duration") or 0,
        "upload_date": info.get("upload_date") or "",
        "webpage_url": info.get("webpage_url") or url,
        "description": (info.get("description") or "")[:4000],
        "chapters": info.get("chapters") or [],
        "thumbnail": info.get("thumbnail") or "",
        "has_subtitles": bool(info.get("subtitles")),
        "auto_captions": bool(info.get("automatic_captions")),
    }
    write_json(vdir / "meta.json", meta)

    target = vdir / "video.mp4"
    if target.exists() and target.stat().st_size > 10_000:
        print(f"  视频已存在，跳过下载：{target.name}")
        return {**meta, "video_path": str(target), "skipped": True}

    dl = _base_opts(cfg, cookies)
    max_h = cfg.max_height
    dl.update(
        {
            "format": (
                f"bv*[height<={max_h}][ext=mp4]+ba[ext=m4a]/"
                f"bv*[height<={max_h}]+ba/b[height<={max_h}]/bv*+ba/b"
            ),
            "merge_output_format": "mp4",
            "outtmpl": str(vdir / "video.%(ext)s"),
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": cfg.sub_langs,
            "subtitlesformat": "vtt",
            "overwrites": False,
        }
    )
    print(f"  下载中：{meta['title']}")
    with yt_dlp.YoutubeDL(dl) as ydl:
        ydl.download([url])

    for p in vdir.glob("video.*"):
        if p.suffix in {".mp4", ".mkv", ".webm", ".m4a"} and p.stat().st_size > 10_000:
            target = p
            break
    return {**meta, "video_path": str(target), "skipped": False}


def pick_subtitle(vdir: Path, prefer: list[str]) -> Path | None:
    """手动字幕优先，其次自动字幕；语言按 prefer 顺序匹配。"""
    subs = list((vdir / "subs").glob("*.vtt")) + list(vdir.glob("*.vtt"))
    if not subs:
        return None

    def rank(p: Path) -> tuple[int, int]:
        name = p.name.lower()
        auto = 1 if ".auto." in name or name.count(".") > 2 else 0
        for i, lang in enumerate(prefer):
            if lang.lower() in name:
                return (auto, i)
        return (auto, len(prefer) + 1)

    subs.sort(key=rank)
    return subs[0]


def extract_audio(video: Path, out: Path, start: float | None = None, duration: float | None = None) -> Path | None:
    ff = ffmpeg_path()
    if not ff:
        return None
    cmd = [ff, "-y", "-loglevel", "error"]
    if start is not None:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", str(video)]
    if duration is not None:
        cmd += ["-t", f"{duration:.3f}"]
    cmd += ["-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(out)]
    subprocess.run(cmd, check=True, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    return out if out.exists() else None
