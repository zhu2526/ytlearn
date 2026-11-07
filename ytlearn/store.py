"""数据布局与读写。

data/
  index.json                 # 全局书目
  videos/<video_id>/
      meta.json
      transcript.jsonl       # 带时间戳的片段
      chunks.json            # 检索单元
      notes.md               # 结构化学习笔记
      video.mp4
      subs/*.vtt
      relook/                # 回看时抽的帧和切片
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .config import Config


def safe_name(s: str, limit: int = 60) -> str:
    s = re.sub(r"[\\/:*?\"<>|\r\n\t]+", "_", s).strip(" .")
    s = re.sub(r"\s+", " ", s)
    return (s[:limit] or "untitled").strip()


def video_dir(cfg: Config, vid: str) -> Path:
    p = cfg.data_dir / "videos" / vid
    p.mkdir(parents=True, exist_ok=True)
    (p / "relook").mkdir(exist_ok=True)
    (p / "subs").mkdir(exist_ok=True)
    return p


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def append_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def load_index(cfg: Config) -> dict:
    return read_json(cfg.data_dir / "index.json", default={"videos": {}}) or {"videos": {}}


def save_index(cfg: Config, idx: dict) -> None:
    write_json(cfg.data_dir / "index.json", idx)


def upsert_index(cfg: Config, vid: str, patch: dict) -> None:
    idx = load_index(cfg)
    entry = idx.setdefault("videos", {}).get(vid, {})
    entry.update(patch)
    idx["videos"][vid] = entry
    save_index(cfg, idx)
