"""离线冒烟测试：不需要网络，验证 解析 → 切块 → 入库 → 检索。

    python tests/smoke.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ytlearn import learner  # noqa: E402
from ytlearn.config import load_config  # noqa: E402
from ytlearn.store import upsert_index, video_dir, write_json  # noqa: E402
from ytlearn.transcript import chunk_cues, parse_vtt  # noqa: E402


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="ytlearn-test-"))
    try:
        cfg = load_config(str(tmp))
        cues = parse_vtt(ROOT / "tests" / "sample.vtt")
        assert cues, "字幕解析失败"
        chunks = chunk_cues(cues, target_chars=120)
        assert chunks, "切块失败"

        vid = "smoke001"
        vdir = video_dir(cfg, vid)
        meta = {
            "id": vid,
            "title": "测试视频",
            "uploader": "smoke",
            "duration": 41,
            "webpage_url": "https://example.com",
        }
        write_json(vdir / "meta.json", meta)
        notes = learner.save_chunks(cfg, vid, chunks, meta)
        upsert_index(cfg, vid, {"title": meta["title"], "chunks": len(chunks)})
        assert notes.exists() and notes.stat().st_size > 50, "笔记没有生成"

        r = learner.answer(cfg, "BM25 有什么缺点", k=4)
        assert r["hits"], "检索没命中"
        top = r["hits"][0].text
        assert "同义词" in top or "缺点" in top, f"命中内容不对：{top[:60]}"

        r2 = learner.answer(cfg, "怎么养多肉植物", k=4)
        assert r2["coverage"] < 0.5, "无关问题不该高命中"

        print("OK")
        print(f"  chunks      : {len(chunks)}")
        print(f"  命中        : {r['hits'][0].ref}  覆盖 {r['coverage']:.0%}")
        print(f"  无关问题覆盖 : {r2['coverage']:.0%}")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
