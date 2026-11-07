"""字幕解析 / 语音转写 / 切块。"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

_TS = re.compile(
    r"(?P<h>\d{1,2}):(?P<m>\d{2}):(?P<s>\d{2})[.,](?P<ms>\d{3})\s*-->\s*"
    r"(?P<h2>\d{1,2}):(?P<m2>\d{2}):(?P<s2>\d{2})[.,](?P<ms2>\d{3})"
)
_TAG = re.compile(r"<[^>]+>")
_VTT_HEAD = re.compile(r"^(WEBVTT|Kind:|Language:|NOTE\b|\d+$)", re.I)


@dataclass
class Cue:
    start: float
    end: float
    text: str


def _secs(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def parse_vtt(path: Path) -> list[Cue]:
    cues: list[Cue] = []
    blocks = path.read_text(encoding="utf-8", errors="ignore").split("\n\n")
    for block in blocks:
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        ts_line = next((ln for ln in lines if "-->" in ln), None)
        if not ts_line:
            continue
        m = _TS.search(ts_line)
        if not m:
            continue
        g = m.groupdict()
        start = _secs(g["h"], g["m"], g["s"], g["ms"])
        end = _secs(g["h2"], g["m2"], g["s2"], g["ms2"])
        body = " ".join(ln for ln in lines if "-->" not in ln and not _VTT_HEAD.match(ln))
        body = _TAG.sub("", body).strip()
        if body:
            cues.append(Cue(start, end, body))
    return _dedupe(cues)


def _dedupe(cues: list[Cue]) -> list[Cue]:
    """YouTube 自动字幕经常滚动重复上一行，去掉紧邻重复。"""
    out: list[Cue] = []
    for c in cues:
        if out and c.text == out[-1].text:
            out[-1].end = c.end
            continue
        out.append(c)
    return out


def fmt_ts(sec: float, with_ms: bool = False) -> str:
    sec = max(0.0, sec)
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    if with_ms:
        ms = int(round((sec - int(sec)) * 1000))
        return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def chunk_cues(cues: list[Cue], target_chars: int = 320, max_seconds: float = 75.0) -> list[dict]:
    """把字幕合并成适合检索和引用的块。"""
    chunks: list[dict] = []
    buf: list[Cue] = []

    def flush() -> None:
        if not buf:
            return
        text = _join(buf)
        chunks.append(
            {
                "start": round(buf[0].start, 2),
                "end": round(buf[-1].end, 2),
                "text": re.sub(r"\s+", " ", text).strip(),
            }
        )
        buf.clear()

    for c in cues:
        buf.append(c)
        span = buf[-1].end - buf[0].start
        chars = sum(len(x.text) for x in buf)
        if chars >= target_chars or span >= max_seconds:
            flush()
    flush()
    return [c for c in chunks if len(c["text"]) > 8]


_PUNCT_END = tuple("，。！？；：、,.!?;:…）)》」\"'")
_PUNCT_START = tuple("，。！？；：、,.!?;:）)》」")


def _join(cues: list[Cue]) -> str:
    """中文按标点断句拼接，别把两句糊成一坨；西文用空格。"""
    if not _is_cjk_heavy(cues):
        return " ".join(c.text for c in cues)
    out = ""
    for c in cues:
        t = c.text.strip()
        if not t:
            continue
        if not out:
            out = t
            continue
        if out.endswith(_PUNCT_END) or t.startswith(_PUNCT_START):
            out += t
        else:
            out += "，" + t
    return out


def _is_cjk_heavy(cues: list[Cue]) -> bool:
    sample = "".join(c.text for c in cues)[:200]
    if not sample:
        return False
    cjk = sum(1 for ch in sample if "\u4e00" <= ch <= "\u9fff")
    return cjk / len(sample) > 0.4


def transcribe_with_whisper(media: Path, model_size: str = "small", language: str | None = None) -> list[Cue]:
    """本地转写兜底。需要 pip install faster-whisper。"""
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "没有字幕，且未安装本地转写器。执行：pip install faster-whisper\n"
            "（首次会下载模型，small 约 500MB）"
        ) from e

    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, _info = model.transcribe(str(media), language=language, vad_filter=True)
    return [Cue(float(s.start), float(s.end), s.text.strip()) for s in segments if s.text.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows),
        encoding="utf-8",
    )


def cue_to_dict(c: Cue) -> dict:
    return asdict(c)
