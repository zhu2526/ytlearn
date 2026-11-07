"""极简 OpenAI 兼容客户端（不引 sdk，方便换任何家的接口）。"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from pathlib import Path

from .config import Config


def _post(cfg: Config, payload: dict, timeout: int = 180) -> dict | None:
    if not cfg.llm_ready:
        return None
    url = cfg.llm_base.rstrip("/") + "/chat/completions"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg.llm_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")[:400]
        print(f"  x LLM 请求失败 {e.code}: {body}")
    except Exception as e:
        print(f"  x LLM 请求失败: {e}")
    return None


def chat(cfg: Config, system: str, user: str, model: str | None = None, temperature: float = 0.2) -> str | None:
    payload = {
        "model": model or cfg.llm_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
    }
    resp = _post(cfg, payload)
    if not resp:
        return None
    try:
        return resp["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError):
        return None


def _b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def describe_frames(cfg: Config, frames: list[Path], prompt: str, model: str | None = None) -> str | None:
    """把回看抽出来的帧交给视觉模型，描述画面里在讲什么。"""
    if not cfg.vision_ready or not frames:
        return None
    content: list[dict] = [{"type": "text", "text": prompt}]
    for f in frames[:4]:
        content.append(
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{_b64(f)}"}}
        )
    payload = {
        "model": model or cfg.vision_model,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0.1,
    }
    resp = _post(cfg, payload, timeout=240)
    if not resp:
        return None
    try:
        return resp["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError):
        return None
