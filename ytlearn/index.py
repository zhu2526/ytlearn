"""零依赖检索：中英混排分词 + BM25 + 邻域扩展。

为什么不用向量库：视频字幕量级很小（单集几千字，几十集也就几十万字），
BM25 加一点同义扩展已经够用，而且不需要 API、不需要额外依赖、结果可解释
（能直接告诉你这个答案出自第几秒）。
"""

from __future__ import annotations

import math
import re
from collections import Counter

_CJK = re.compile(r"[\u4e00-\u9fff]")
_WORD = re.compile(r"[a-zA-Z0-9_]+")

STOP = set(
    """的 了 是 在 我 有 和 就 不 人 都 一 一个 上 也 很 到 说 要 去 你 会 着 没有 看 好 自己 这
那 他 她 它 们 个 我们 这个 那个 什么 怎么 为什么 因为 所以 但是 如果 然后 还是 可以 就是
the a an and or but if then of to in on for with is are was were be been it this that these those
i you he she we they not no yes do does did so as at by from""".split()
)


def tokenize(text: str) -> list[str]:
    text = text.lower()
    tokens: list[str] = []
    for w in _WORD.findall(text):
        if w not in STOP and len(w) > 1:
            tokens.append(w)
    cjk = "".join(_CJK.findall(text))
    for ch in cjk:
        if ch not in STOP:
            tokens.append(ch)
    for i in range(len(cjk) - 1):
        tokens.append(cjk[i : i + 2])
    return tokens


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.docs = docs
        self.n = len(docs)
        self.avgdl = (sum(len(d) for d in docs) / self.n) if self.n else 0.0
        self.freqs = [Counter(d) for d in docs]
        df: Counter = Counter()
        for d in docs:
            df.update(set(d))
        self.idf = {
            t: math.log(1 + (self.n - c + 0.5) / (c + 0.5)) for t, c in df.items()
        }

    def score(self, query: list[str], i: int) -> float:
        f, dl = self.freqs[i], len(self.docs[i])
        s = 0.0
        for t in query:
            if t not in f:
                continue
            idf = self.idf.get(t, 0.0)
            tf = f[t]
            s += idf * (tf * (self.k1 + 1)) / (tf + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
        return s

    def search(self, query: list[str], top_k: int = 6) -> list[tuple[int, float]]:
        scored = [(i, self.score(query, i)) for i in range(self.n)]
        scored = [x for x in scored if x[1] > 0]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]


def normalize(scores: list[tuple[int, float]]) -> list[tuple[int, float]]:
    """把原始分压到 0~1，方便判断"这次是不是没检索到东西"。"""
    if not scores:
        return []
    top = max(s for _, s in scores) or 1.0
    return [(i, s / top) for i, s in scores]
