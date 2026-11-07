"""一条龙：链接 → 下载 → 转写 → 切块 → 笔记 → 入库。"""

from __future__ import annotations

from pathlib import Path

from . import downloader, learner
from .config import Config
from .store import upsert_index, video_dir, write_json
from .transcript import chunk_cues, parse_vtt, transcribe_with_whisper


def ingest(url: str, cfg: Config, cookies: str | None = None, force_whisper: bool = False) -> dict:
    meta = downloader.download(url, cfg, cookies=cookies)
    vid = meta["id"]
    vdir = video_dir(cfg, vid)

    cues = []
    source = None

    if not force_whisper:
        sub = downloader.pick_subtitle(vdir, cfg.sub_langs)
        if sub:
            cues = parse_vtt(sub)
            if cues:
                source = f"字幕 {sub.name}"
                _stash(vdir, sub)

    if not cues:
        print("  没有可用字幕，转本地语音识别…")
        video = Path(meta["video_path"])
        try:
            cues = transcribe_with_whisper(video, cfg.whisper_model)
            source = "本地语音识别"
        except Exception as e:
            write_json(vdir / "error.json", {"error": str(e)})
            print(f"  x 转写失败：{e}")
            return {"ok": False, "error": str(e), "meta": meta}

    if not cues:
        return {"ok": False, "error": "转写结果为空", "meta": meta}

    chunks = chunk_cues(cues)
    notes_path = learner.save_chunks(cfg, vid, chunks, meta)

    upsert_index(
        cfg,
        vid,
        {
            "title": meta["title"],
            "uploader": meta.get("uploader", ""),
            "duration": meta.get("duration", 0),
            "url": meta.get("webpage_url", url),
            "chunks": len(chunks),
            "source": source,
            "notes": str(notes_path),
            "video": meta.get("video_path"),
            "learned_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        },
    )
    return {"ok": True, "meta": meta, "chunks": len(chunks), "source": source, "notes": notes_path}


def _stash(vdir: Path, sub: Path) -> None:
    try:
        dest = vdir / "subs" / sub.name
        if sub.parent != dest.parent and not dest.exists():
            dest.write_bytes(sub.read_bytes())
    except OSError:
        pass
