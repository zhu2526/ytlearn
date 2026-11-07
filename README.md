# ytlearn

给一个 YouTube 链接，它把视频下载下来、转写、提炼成结构化笔记，存进本地知识库——**答不上来的时候，会回去看视频**。

> 大多数"视频总结"工具给你一份文字摘要就结束了。问题是文字会丢失视频里最关键的
> 那部分信息：板书、代码、图表、演示操作、语气和停顿。
> ytlearn 保留原片，索引带时间戳，检索命中度不足时自动抽帧回看、切片段重听，
> 把看到的东西再写回知识库。**它会第二次学习。**

## 它是怎么想的

```
youtube 链接
   │
   ├─ 下载原片（最高 1080p）+ 官方/自动字幕
   ├─ 没有字幕 → 本地语音识别
   ├─ 字幕切成带时间戳的检索块
   ├─ LLM 精读 → 结构化笔记（结论/观点/时间线/概念/待查点）
   └─ 入库
          │
   你提问 ──┤
          ├─ BM25 召回 + 邻域扩展
          ├─ 命中度够 → 直接答，带 [mm:ss] 出处
          └─ 命中度不足 → 回看：ffmpeg 抽帧 + 片段重听
                          → 视觉模型读画面（板书/代码/图表）
                          → 结果回写知识库，再答一次
```

## 安装

需要 Python 3.10+。

```bash
git clone https://github.com/zhu2526/ytlearn.git
cd ytlearn
pip install -r requirements.txt
pip install -e .
```

`ffmpeg` 由 `imageio-ffmpeg` 自带，不用单独装。

可选（没有字幕的视频才需要）：

```bash
pip install faster-whisper      # 本地转写，small 模型约 500MB
```

## 用

```bash
# 学一个视频
ytlearn add "https://www.youtube.com/watch?v=xxxx"

# 播放列表 / 频道，一次全学
ytlearn add "https://www.youtube.com/playlist?list=xxxx"

# 提问
ytlearn ask "作者为什么反对用向量库"

# 交互式追问，可以一直聊
ytlearn chat

# 回看某一段：抽出画面帧 + 切一个 30 秒片段
ytlearn relook dQw4w9WgXcQ --at 12:30 --window 30

# 看笔记 / 看知识库 / 环境自检
ytlearn show dQw4w9WgXcQ
ytlearn list
ytlearn doctor
```

平时最常用的是 `chat`：

```
你 > 视频里说的切块长度是多少
    不能超过 300 字，太长会稀释关键词权重 [06:34]

你 > /relook dQw4w9WgXcQ 21:05
    片段：data/videos/.../relook/01265/clip_01265.mp4
    画面内容：讲师在白板上画出两阶段检索的结构，左边标 BM25，右边标 rerank…
```

## 配置（可选，不配也能跑）

不配 LLM 时走抽取式大纲 + 原文检索，功能完整但没有"读懂"这一步。要真正的提炼和作答，写个 `.env`：

```bash
YTL_LLM_BASE=https://api.openai.com/v1      # 任何 OpenAI 兼容接口都行
YTL_LLM_KEY=sk-...
YTL_LLM_MODEL=gpt-4o-mini

# 可选：回看时让模型读画面
YTL_VISION_MODEL=gpt-4o-mini

# 可选
YTL_DATA_DIR=./data
YTL_MAX_HEIGHT=1080
YTL_SUB_LANGS=zh-Hans,zh,en
YTL_WHISPER_MODEL=small
```

DeepSeek、通义、Moonshot、本地 Ollama 都支持，改 base 和 model 即可。

## 为什么检索用 BM25 而不是向量库

单集视频几千字，几十集也就几十万字。这个量级下 BM25 足够准，而且：

- 不用调 embedding 接口，不用花钱，不用等
- 完全可解释——能直接告诉你答案出自第几秒
- 没有索引同步问题，加视频就是加文件

规模真正上去（十万条以上）再换向量召回 + 重排，接口已经留好了（`ytlearn/index.py` 里替换 `BM25` 即可）。

## 数据长什么样

```
data/
├── index.json                     # 书目
└── videos/<video_id>/
    ├── meta.json                  # 标题/作者/时长/章节
    ├── video.mp4                  # 原片，回看靠它
    ├── subs/*.vtt                 # 原始字幕
    ├── transcript.jsonl           # 逐句时间戳
    ├── chunks.json                # 检索块（含回看补学的新块）
    ├── notes.md                   # 结构化笔记
    └── relook/                    # 回看抽的帧、切片、重听音频
```

全是纯文件，可以直接用 Obsidian、grep、git 管理。

## 已知限制

- **网络**：需要能访问 YouTube。受限网络下请自行配置代理，或加 `--cookies chrome` 处理登录/年龄限制。
- **无字幕视频**：必须装 `faster-whisper`，CPU 上 small 模型大约 1:3 实时速度。
- **画面理解**：需要视觉模型。不配的话只导出帧，得自己看。
- **检索**：BM25 不懂同义词，"手机"和"电话"是两个词。中文靠字符二元组缓解了一部分，但不彻底。
- **版权**：仅供个人学习研究。下载和二次分发受 YouTube 服务条款及当地法律约束，请自行判断使用场景。

## License

MIT
