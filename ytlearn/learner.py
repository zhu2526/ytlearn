"""学习层：切块入库、生成笔记、检索作答、回看补学。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from . import llm, media
from .config import Config
from .index import BM25, normalize, tokenize
from .store import append_jsonl, read_json, read_jsonl, video_dir, write_json
from .transcript import fmt_ts


# ---------------------------------------------------------------- 建库

def load_chunks(cfg: Config, vid: str) -> list[dict]:
    return read_json(video_dir(cfg, vid) / "chunks.json", default=[]) or []


def all_chunks(cfg: Config) -> list[dict]:
    out: list[dict] = []
    for chunks_file in (cfg.data_dir / "videos").glob("*/chunks.json"):
        vid = chunks_file.parent.name
        meta = read_json(chunks_file.parent / "meta.json", default={}) or {}
        for i, c in enumerate(read_json(chunks_file, default=[]) or []):
            out.append(
                {
                    "vid": vid,
                    "title": meta.get("title", vid),
                    "i": i,
                    "start": c["start"],
                    "end": c["end"],
                    "text": c["text"],
                    "kind": c.get("kind", "sub"),
                }
            )
    return out


@dataclass
class Hit:
    vid: str
    title: str
    start: float
    end: float
    text: str
    score: float
    kind: str = "sub"

    @property
    def ref(self) -> str:
        return f"[{self.title} @ {fmt_ts(self.start)}]"


class Retriever:
    def __init__(self, docs: list[dict]):
        self.docs = docs
        self.bm25 = BM25([tokenize(d["text"]) for d in docs]) if docs else None

    def search(self, question: str, k: int = 6) -> tuple[list[Hit], float]:
        if not self.bm25:
            return [], 0.0
        q = tokenize(question)
        if not q:
            return [], 0.0
        raw = self.bm25.search(q, top_k=k)
        scored = normalize(raw)
        hits = [
            Hit(
                vid=self.docs[i]["vid"],
                title=self.docs[i]["title"],
                start=self.docs[i]["start"],
                end=self.docs[i]["end"],
                text=self.docs[i]["text"],
                score=s,
                kind=self.docs[i].get("kind", "sub"),
            )
            for i, s in scored
        ]
        coverage = self._coverage(q, hits)
        return hits, coverage

    @staticmethod
    def _coverage(q: list[str], hits: list[Hit]) -> float:
        """查询词有多少被命中——比 BM25 分数更适合判断"是不是没讲到"。"""
        if not hits:
            return 0.0
        joined = tokenize(" ".join(h.text for h in hits[:3]))
        seen = set(joined)
        uniq = list(dict.fromkeys(q))
        if not uniq:
            return 0.0
        return sum(1 for t in uniq if t in seen) / len(uniq)


# ---------------------------------------------------------------- 笔记

SYS_NOTES = """你是把视频内容转成可复用知识的学习助手。只依据给定的字幕内容作答，不要补充视频里没说的东西。
输出 Markdown，结构固定：
## 一句话结论
## 核心观点（3-6 条，每条一行，结尾标出出处时间如 [12:30]）
## 时间线（按讲解顺序分段，每段：`mm:ss` 讲了什么，一句话）
## 关键概念（术语 → 视频里的定义，没解释就写"未展开"）
## 可以直接拿来用的东西（步骤/清单/代码/方法，没有就写"无"）
## 视频没讲清楚的地方（2-3 条，这是后续要回看或查资料的点）"""


def make_notes(cfg: Config, meta: dict, chunks: list[dict]) -> str:
    body = _transcript_with_ts(chunks)
    if cfg.llm_ready:
        text = llm.chat(
            cfg,
            SYS_NOTES,
            f"标题：{meta.get('title')}\n作者：{meta.get('uploader')}\n时长：{fmt_ts(meta.get('duration') or 0)}\n\n字幕：\n{body}",
            temperature=0.3,
        )
        if text:
            return _ensure_header(meta, text, method="LLM 精读")
    return _ensure_header(meta, _extractive_notes(chunks), method="抽取式大纲")


def _transcript_with_ts(chunks: list[dict], limit: int = 26000) -> str:
    lines, total = [], 0
    for c in chunks:
        line = f"[{fmt_ts(c['start'])}] {c['text']}"
        total += len(line)
        if total > limit:
            lines.append("…（字幕过长，已截断，可分段用 ask 追问细节）")
            break
        lines.append(line)
    return "\n".join(lines)


def _ensure_header(meta: dict, body: str, method: str = "") -> str:
    head = (
        f"# {meta.get('title', '未命名')}\n\n"
        f"- 作者：{meta.get('uploader', '')}\n"
        f"- 时长：{fmt_ts(meta.get('duration') or 0)}\n"
        f"- 来源：{meta.get('webpage_url', '')}\n"
        f"- 生成方式：{method}\n\n---\n\n"
    )
    return head + body.strip() + "\n"


def _extractive_notes(chunks: list[dict]) -> str:
    """没有 LLM 时的兜底：抽取式大纲，仍然可用。"""
    if not chunks:
        return "（无字幕内容）"
    df: dict[str, int] = {}
    for c in chunks:
        for t in set(tokenize(c["text"])):
            df[t] = df.get(t, 0) + 1
    n = len(chunks)
    scored = []
    for c in chunks:
        toks = tokenize(c["text"])
        if not toks:
            continue
        s = sum(df.get(t, 1) / n for t in toks) / (len(toks) ** 0.5)
        scored.append((s, c))
    top = sorted(scored, key=lambda x: x[0], reverse=True)[:6]
    top.sort(key=lambda x: x[1]["start"])

    keywords = sorted(df.items(), key=lambda kv: kv[1], reverse=True)
    kw = "、".join(k for k, v in keywords if len(k) > 1 and v < n)[:200]

    out = ["## 一句话结论", "（未配置 LLM，以下为抽取式大纲）", "", "## 核心观点"]
    for _s, c in top:
        out.append(f"- [{fmt_ts(c['start'])}] {c['text'][:120]}")
    out += ["", "## 时间线"]
    for c in chunks[:: max(1, len(chunks) // 12)][:14]:
        out.append(f"- `{fmt_ts(c['start'])}` {c['text'][:60]}")
    out += ["", "## 关键概念", f"高频词：{kw}", "", "## 视频没讲清楚的地方", "（需要 LLM 才能判断，可配置后重跑）"]
    return "\n".join(out)


# ---------------------------------------------------------------- 作答

SYS_ANSWER = """你是用户的知识代理人，只能基于给出的字幕片段回答。
规则：
1. 每个结论后面必须带时间戳引用，格式 `[mm:ss]`，能对应到片段里的时间。
2. 片段里没有的信息，直接说"视频里没有讲到"，不要编。
3. 如果片段只是擦边相关，明确提示"这块讲得不深，建议回看 mm:ss"。
4. 中文回答，简洁，先给结论再给依据。"""


def answer(cfg: Config, question: str, k: int = 6, deep: bool = False) -> dict:
    docs = all_chunks(cfg)
    retr = Retriever(docs)
    hits, coverage = retr.search(question, k=k)

    if not hits:
        return {
            "text": "知识库里没有相关内容。先 `ytlearn add <链接>` 把视频学进来。",
            "hits": [],
            "coverage": 0.0,
            "relook": None,
        }

    relook_info = None
    extra_context = ""
    if deep or coverage < 0.45:
        relook_info = relook(cfg, hits[0].vid, hits[0].start, window=hits[0].end - hits[0].start + 20)
        if relook_info.get("vision"):
            extra_context = f"\n\n【回看画面描述】{relook_info['vision']}"
        if relook_info.get("respeech"):
            extra_context += f"\n\n【回看该段语音】{relook_info['respeech']}"

    ctx = "\n\n".join(f"[{h.title} @ {fmt_ts(h.start)}] {h.text}" for h in hits)

    if cfg.llm_ready:
        text = llm.chat(
            cfg,
            SYS_ANSWER,
            f"问题：{question}\n\n字幕片段：\n{ctx}{extra_context}",
            temperature=0.2,
        )
    else:
        text = None

    if not text:
        text = _fallback_answer(question, hits, coverage)
        fallback = True
    else:
        fallback = False

    return {
        "text": text,
        "hits": hits,
        "coverage": coverage,
        "relook": relook_info,
        "fallback": fallback,
    }


def _fallback_answer(question: str, hits: list[Hit], coverage: float) -> str:
    head = f"（未配置 LLM，直接给原文 · 命中度 {coverage:.0%}）"
    if coverage < 0.3:
        head += "\n⚠️ 命中度偏低，可能视频没讲这个，用 `relook` 回看确认。"
    lines = [head]
    for h in hits[:3]:
        lines.append(f"\n**{fmt_ts(h.start)}** {h.text[:220]}")
    return "\n".join(lines)


# ---------------------------------------------------------------- 回看

def relook(cfg: Config, vid: str, start: float, window: float = 45.0, frames: int = 3) -> dict:
    """回看一段：抽帧（+ 视觉描述）+ 可选重听该段语音，并把新信息回写知识库。"""
    vdir = video_dir(cfg, vid)
    meta = read_json(vdir / "meta.json", default={}) or {}
    video = next((p for p in vdir.glob("video.*") if p.suffix in {".mp4", ".mkv", ".webm"}), None)

    info: dict = {"vid": vid, "start": start, "window": window, "frames": [], "clip": None,
                  "vision": None, "respeech": None}

    if not video:
        info["error"] = "本地没有视频文件，无法回看画面"
        return info

    stamp = f"{int(start):05d}"
    outdir = vdir / "relook" / stamp
    info["frames"] = [str(p) for p in media.extract_frames(video, start, outdir, count=frames)]
    clip = media.cut_clip(video, max(0.0, start - 2), outdir / f"clip_{stamp}.mp4", duration=window)
    info["clip"] = str(clip) if clip else None

    if cfg.vision_ready and info["frames"]:
        prompt = (
            f"这是一个视频在 {fmt_ts(start)} 附近的画面，来自《{meta.get('title','')}》。"
            "请描述画面里有什么：是人在讲话、板书、代码、图表还是演示界面？"
            "如果是文字/代码/图表，尽量把内容读出来。只描述看到的，不要推测。"
        )
        info["vision"] = llm.describe_frames(cfg, [Path(p) for p in info["frames"]], prompt)

    info["respeech"] = _respeech(cfg, video, start, window)

    new_text = " ".join(filter(None, [info.get("vision"), info.get("respeech")]))
    if new_text:
        append_jsonl(
            vdir / "relook_chunks.jsonl",
            [{"start": start, "end": start + window, "text": new_text, "kind": "relook"}],
        )
        _merge_relook_into_chunks(cfg, vid)
    return info


def _respeech(cfg: Config, video: Path, start: float, window: float) -> str | None:
    """把这一段单独切出来重新转写，拿到比自动字幕更准的文本。"""
    try:
        from .downloader import extract_audio
        from .transcript import transcribe_with_whisper

        wav = video.parent / "relook" / f"seg_{int(start):05d}.wav"
        wav.parent.mkdir(parents=True, exist_ok=True)
        if not extract_audio(video, wav, start=max(0.0, start - 2), duration=window):
            return None
        cues = transcribe_with_whisper(wav, cfg.whisper_model)
        return " ".join(c.text for c in cues).strip() or None
    except Exception:
        return None


def _merge_relook_into_chunks(cfg: Config, vid: str) -> None:
    vdir = video_dir(cfg, vid)
    base = read_json(vdir / "chunks.json", default=[]) or []
    extra = read_jsonl(vdir / "relook_chunks.jsonl")
    seen = {(round(c["start"]), c["text"][:40]) for c in base}
    for e in extra:
        key = (round(e["start"]), e["text"][:40])
        if key not in seen:
            base.append({"start": e["start"], "end": e["end"], "text": e["text"], "kind": "relook"})
            seen.add(key)
    base.sort(key=lambda c: c["start"])
    write_json(vdir / "chunks.json", base)


# ---------------------------------------------------------------- 入库

def save_chunks(cfg: Config, vid: str, chunks: list[dict], meta: dict) -> Path:
    vdir = video_dir(cfg, vid)
    write_json(vdir / "chunks.json", chunks)
    notes = make_notes(cfg, meta, chunks)
    (vdir / "notes.md").write_text(notes, encoding="utf-8")
    return vdir / "notes.md"


def stats(cfg: Config) -> dict:
    idx = read_json(cfg.data_dir / "index.json", default={"videos": {}}) or {"videos": {}}
    vids = idx.get("videos", {})
    return {
        "videos": len(vids),
        "chunks": len(all_chunks(cfg)),
        "titles": [(v, d.get("title", v)) for v, d in vids.items()],
    }
