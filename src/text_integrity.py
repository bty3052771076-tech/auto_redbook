from __future__ import annotations

"""Small, conservative guards for text that crosses terminal and API boundaries."""


# These are characteristic fragments produced when UTF-8 Chinese is decoded as
# GBK/GB18030.  A conversion is attempted only when one of these fragments is
# present and the reverse conversion is lossless.
_UTF8_AS_GBK_MARKERS = (
    "姣忔棩",
    "鏂伴椈",
    "璐㈢粡",
    "浜т笟",
    "鐢熸垚",
    "澶辫触",
    "璇风◢",
    "鍐呭",
    "璇勪环",
    "濮ｅ繑",
    "妫╅",
    "弬浼",
    "锛",
    "銆",
    "锟",
)


def _looks_like_utf8_as_gbk(text: str) -> bool:
    return any(marker in text for marker in _UTF8_AS_GBK_MARKERS)


def repair_utf8_as_gbk_mojibake(value: str, *, max_rounds: int = 2) -> str:
    """Restore a clearly reversible UTF-8-as-GBK decoding mistake.

    Normal Chinese text is left untouched.  The two-round limit handles text
    that passed through a Windows code page boundary more than once.
    """
    text = str(value or "")
    for _ in range(max(0, max_rounds)):
        if not _looks_like_utf8_as_gbk(text):
            break
        try:
            repaired = text.encode("gb18030").decode("utf-8")
        except (LookupError, UnicodeDecodeError, UnicodeEncodeError):
            break
        if not repaired or repaired == text:
            break
        text = repaired
    return text


def contains_recoverable_utf8_as_gbk_mojibake(value: str) -> bool:
    text = str(value or "")
    return repair_utf8_as_gbk_mojibake(text) != text


_COMMON_TRADITIONAL_TO_SIMPLIFIED = str.maketrans(
    {
        "騰": "腾",
        "訊": "讯",
        "發": "发",
        "躋": "跻",
        "陸": "陆",
        "頂": "顶",
        "陣": "阵",
        "營": "营",
        "開": "开",
        "關": "关",
        "進": "进",
        "對": "对",
        "體": "体",
        "與": "与",
        "這": "这",
        "項": "项",
        "規": "规",
        "則": "则",
        "後": "后",
        "續": "续",
        "觀": "观",
        "權": "权",
        "護": "护",
        "數": "数",
        "據": "据",
        "報": "报",
        "導": "导",
        "選": "选",
        "證": "证",
        "華": "华",
        "區": "区",
        "風": "风",
        "險": "险",
        "響": "响",
        "應": "应",
        "監": "监",
        "測": "测",
        "檢": "检",
        "機": "机",
        "構": "构",
        "專": "专",
        "屬": "属",
        "園": "园",
        "時": "时",
        "兩": "两",
        "種": "种",
        "極": "极",
        "銷": "销",
        "廣": "广",
        "東": "东",
    }
)


def simplify_common_chinese(value: str) -> str:
    """Convert a conservative set of frequent traditional characters."""
    return str(value or "").translate(_COMMON_TRADITIONAL_TO_SIMPLIFIED)
