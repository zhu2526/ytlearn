"""命令行入口。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import learner, pipeline
from .config import load_config
from .downloader import expand, ffmpeg_path
from .store import read_json, video_dir
from .transcript import fmt_ts


def _ts(s: str) -> float:
    s = s.strip()
    parts = s.split(":")
    try:
        nums = [float(x) for x in parts]
    except ValueError:
        raise argparse.ArgumentTypeError(f"时间格式不对：{s}（用 12:30 或 1:02:30）")
    if len(nums) == 1:
        return nums[0]
    if len(nums) == 2:
        return nums[0] * 60 + nums[1]
    return nums[0] * 3600 + nums[1] * 60 + nums[2]


def cmd_add(args, cfg) -> int:
    ok = 0
    urls = []
    for u in args.urls:
        urls.extend(expand(u, cfg, args.cookies))

    for n, u in enumerate(urls, 1):
        print(f"\n[{n}/{len(urls)}] {u}")
        try:
            r = pipeline.ingest(u, cfg, cookies=args.cookies, force_whisper=args.whisper)
        except Exception as e:
            print(f"  x 失败：{e}")
            continue
        if r["ok"]:
            ok += 1
            print(f"  √ {r['meta']['title']}")
            print(f"    {r['chunks']} 段 · 来源 {r['source']}")
            print(f"    笔记 {r['notes']}")
        else:
            print(f"  x {r.get('error')}")
    print(f"\n完成 {ok}/{len(urls)}")
    return 0 if ok else 1


def cmd_ask(args, cfg) -> int:
    r = learner.answer(cfg, args.question, k=args.k, deep=args.deep)
    print(r["text"])
    if r["hits"] and not r.get("fallback"):
        print(f"\n--- 命中 {r['coverage']:.0%} · 出处 ---")
        for h in r["hits"][:4]:
            print(f"{h.ref}  {h.text[:70]}…")
    if r.get("relook"):
        rl = r["relook"]
        if rl.get("clip"):
            print(f"\n回看片段：{rl['clip']}")
        if rl.get("frames"):
            print(f"回看画面：{rl['frames'][0]}")
    return 0


def cmd_relook(args, cfg) -> int:
    info = learner.relook(cfg, args.vid, args.at, window=args.window, frames=args.frames)
    if info.get("error"):
        print(f"x {info['error']}")
        return 1
    print(f"回看 {args.vid} @ {fmt_ts(args.at)}")
    if info.get("clip"):
        print(f"  片段：{info['clip']}")
    for f in info.get("frames") or []:
        print(f"  帧：{f}")
    if info.get("vision"):
        print(f"\n画面内容：\n{info['vision']}")
    if info.get("respeech"):
        print(f"\n该段语音（重新转写）：\n{info['respeech']}")
    if not info.get("vision") and not info.get("respeech"):
        print("\n（未配置视觉/语音模型，已导出帧和片段，可直接打开看）")
    return 0


def cmd_list(args, cfg) -> int:
    st = learner.stats(cfg)
    if not st["videos"]:
        print("知识库还是空的。`ytlearn add <youtube链接>`")
        return 0
    print(f"{st['videos']} 个视频 · {st['chunks']} 个片段\n")
    for vid, title in st["titles"]:
        print(f"  {vid}  {title}")
    return 0


def cmd_show(args, cfg) -> int:
    p = video_dir(cfg, args.vid) / "notes.md"
    if not p.exists():
        print("没有这个视频的笔记")
        return 1
    print(p.read_text(encoding="utf-8"))
    return 0


def cmd_chat(args, cfg) -> int:
    st = learner.stats(cfg)
    print(f"知识库：{st['videos']} 个视频 / {st['chunks']} 个片段")
    print("直接提问；/relook <vid> <mm:ss> 回看；/list；/q 退出\n")
    while True:
        try:
            q = input("你 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not q:
            continue
        if q in {"/q", "/quit", "exit"}:
            break
        if q == "/list":
            cmd_list(args, cfg)
            continue
        if q.startswith("/relook"):
            parts = q.split()
            if len(parts) >= 3:
                args.vid, args.at, args.window, args.frames = parts[1], _ts(parts[2]), 45.0, 3
                cmd_relook(args, cfg)
            continue
        r = learner.answer(cfg, q, k=args.k, deep=args.deep)
        print(f"\n{r['text']}\n")
        if r["hits"] and not r.get("fallback"):
            print("出处：" + "  ".join(h.ref for h in r["hits"][:3]))
        if r.get("relook") and r["relook"].get("clip"):
            print(f"已回看并切片：{r['relook']['clip']}")
        print()
    return 0


def cmd_doctor(args, cfg) -> int:
    import importlib.util

    print(f"数据目录：{cfg.data_dir}")
    print(f"ffmpeg  ：{ffmpeg_path() or '未找到（pip install imageio-ffmpeg）'}")
    print(f"yt-dlp  ：{'已安装' if importlib.util.find_spec('yt_dlp') else '未安装'}")
    print(f"whisper ：{'已安装' if importlib.util.find_spec('faster_whisper') else '未安装（可选）'}")
    print(f"LLM     ：{'已配置 ' + cfg.llm_model if cfg.llm_ready else '未配置（走抽取式兜底）'}")
    print(f"视觉    ：{cfg.vision_model if cfg.vision_ready else '未配置（回看只导出帧）'}")
    st = learner.stats(cfg)
    print(f"知识库  ：{st['videos']} 视频 / {st['chunks']} 片段")
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    p = argparse.ArgumentParser(prog="ytlearn", description="YouTube → 可追问、可回看的个人知识库")
    p.add_argument("--data", help="数据目录", default=None)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--data", help="数据目录", default=argparse.SUPPRESS)
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", parents=[common], help="学习一个或多个视频")
    a.add_argument("urls", nargs="+")
    a.add_argument("--cookies", help="从浏览器取 cookie，如 chrome / edge")
    a.add_argument("--whisper", action="store_true", help="强制用本地语音识别，不用官方字幕")
    a.set_defaults(func=cmd_add)

    b = sub.add_parser("ask", parents=[common], help="提问")
    b.add_argument("question")
    b.add_argument("-k", type=int, default=6)
    b.add_argument("--deep", action="store_true", help="不管命中度如何，强制回看画面")
    b.set_defaults(func=cmd_ask)

    c = sub.add_parser("relook", parents=[common], help="回看某一段")
    c.add_argument("vid")
    c.add_argument("--at", type=_ts, required=True)
    c.add_argument("--window", type=float, default=45.0)
    c.add_argument("--frames", type=int, default=3)
    c.set_defaults(func=cmd_relook)

    d = sub.add_parser("list", parents=[common], help="看知识库")
    d.set_defaults(func=cmd_list)

    e = sub.add_parser("show", parents=[common], help="看笔记")
    e.add_argument("vid")
    e.set_defaults(func=cmd_show)

    f = sub.add_parser("chat", parents=[common], help="交互式追问")
    f.add_argument("-k", type=int, default=6)
    f.add_argument("--deep", action="store_true")
    f.set_defaults(func=cmd_chat)

    g = sub.add_parser("doctor", parents=[common], help="环境自检")
    g.set_defaults(func=cmd_doctor)

    args = p.parse_args(argv)
    cfg = load_config(args.data)
    return args.func(args, cfg)


if __name__ == "__main__":
    raise SystemExit(main())
