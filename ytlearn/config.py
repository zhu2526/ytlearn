"""运行时配置。全部走环境变量，可选 .env 文件。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    """极简 .env 读取，不引第三方依赖。"""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)


@dataclass
class Config:
    data_dir: Path
    llm_base: str | None = None
    llm_key: str | None = None
    llm_model: str = "gpt-4o-mini"
    vision_model: str | None = None
    whisper_model: str = "small"
    max_height: int = 1080
    sub_langs: list[str] = field(default_factory=lambda: ["zh-Hans", "zh-CN", "zh", "en"])

    @property
    def llm_ready(self) -> bool:
        return bool(self.llm_key and self.llm_base)

    @property
    def vision_ready(self) -> bool:
        return self.llm_ready and bool(self.vision_model)


def load_config(data_dir: str | None = None) -> Config:
    root = Path(__file__).resolve().parent.parent
    _load_dotenv(root / ".env")
    _load_dotenv(Path.cwd() / ".env")

    d = data_dir or os.environ.get("YTL_DATA_DIR") or str(root / "data")
    cfg = Config(
        data_dir=Path(d).expanduser().resolve(),
        llm_base=os.environ.get("YTL_LLM_BASE"),
        llm_key=os.environ.get("YTL_LLM_KEY"),
        llm_model=os.environ.get("YTL_LLM_MODEL", "gpt-4o-mini"),
        vision_model=os.environ.get("YTL_VISION_MODEL") or None,
        whisper_model=os.environ.get("YTL_WHISPER_MODEL", "small"),
    )
    if h := os.environ.get("YTL_MAX_HEIGHT"):
        try:
            cfg.max_height = int(h)
        except ValueError:
            pass
    if langs := os.environ.get("YTL_SUB_LANGS"):
        cfg.sub_langs = [x.strip() for x in langs.split(",") if x.strip()]
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    return cfg
