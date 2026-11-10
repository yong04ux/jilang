"""文本工具：字符/字节计数、截断、分句、词频与大小写判断。

平台限制有的是"字符数"，有的是"字节数"（如 Search Terms 的 250 bytes），
因此计数必须显式区分，避免用 len() 混淆。
"""

from __future__ import annotations

import re

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z\-']+")
_SENTENCE_RE = re.compile(r"(?<=[.!?。！？])\s+")

STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "have", "has", "had",
    "was", "were", "are", "but", "not", "you", "your", "our", "its", "it's",
    "they", "them", "their", "there", "here", "what", "when", "which", "who",
    "will", "would", "could", "should", "can", "cant", "can't", "just", "very",
    "too", "also", "into", "out", "about", "after", "before", "than", "then",
    "some", "any", "all", "more", "most", "much", "many", "one", "two", "get",
    "got", "did", "does", "done", "use", "used", "using", "like", "really",
    "even", "still", "only", "other", "same", "such", "been", "being", "because",
    "while", "where", "how", "why", "all", "would", "these", "those", "im",
    "i'm", "ive", "i've", "dont", "don't", "didnt", "didn't", "doesnt", "doesn't",
}

# 中性词，不能反映产品问题，统计高频词时排除
NEUTRAL_WORDS = {
    "product", "item", "good", "great", "nice", "okay", "ok", "works", "work",
    "working", "bought", "buy", "purchase", "amazon", "review", "price", "money",
}


def char_len(text: str) -> int:
    """字符数（按 Unicode 码点计，与卖家后台的字符计数一致）。"""
    return len(text)


def byte_len_utf8(text: str) -> int:
    """UTF-8 字节数，用于 Search Terms 之类以 bytes 计的限制。"""
    return len(text.encode("utf-8"))


def truncate(text: str, limit: int, suffix: str = "…") -> str:
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if len(suffix) >= limit:
        return text[:limit]
    return text[: limit - len(suffix)].rstrip() + suffix


def quote(text: str, limit: int = 160) -> str:
    """把评论文本压缩成适合作为证据引用的短句。"""
    cleaned = re.sub(r"\s+", " ", text).strip()
    return truncate(cleaned, limit, "…")


def split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENTENCE_RE.split(text or "") if p.strip()]
    return parts or ([text.strip()] if text and text.strip() else [])


def tokenize(text: str) -> list[str]:
    return [m.group(0).lower() for m in _WORD_RE.finditer(text or "")]


def top_terms(texts: list[str], limit: int = 10, min_count: int = 2) -> list[tuple[str, int]]:
    """英文词频统计（中文不做分词，避免引入额外依赖与错误切分）。"""
    counts: dict[str, int] = {}
    for text in texts:
        for word in tokenize(text):
            if len(word) < 3 or word in STOPWORDS or word in NEUTRAL_WORDS:
                continue
            counts[word] = counts.get(word, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [(w, c) for w, c in ranked if c >= min_count][:limit]


def is_all_caps(text: str, min_letters: int = 3) -> bool:
    """判断文本是否整体大写（忽略数字与符号）。"""
    letters = [c for c in text if c.isalpha()]
    return len(letters) >= min_letters and all(c.isupper() for c in letters)


def contains_emoji(text: str) -> bool:
    ranges = (
        (0x1F300, 0x1FAFF),
        (0x2600, 0x27BF),
        (0x2190, 0x21FF),
        (0x2B00, 0x2BFF),
    )
    return any(any(lo <= ord(ch) <= hi for lo, hi in ranges) for ch in text)


def contains_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


__all__ = [
    "NEUTRAL_WORDS",
    "STOPWORDS",
    "byte_len_utf8",
    "char_len",
    "contains_cjk",
    "contains_emoji",
    "is_all_caps",
    "quote",
    "split_sentences",
    "tokenize",
    "top_terms",
    "truncate",
]
