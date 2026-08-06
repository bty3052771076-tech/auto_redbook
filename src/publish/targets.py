from __future__ import annotations


PUBLISH_PLATFORM_OPTIONS = ("xhs", "toutiao", "both")
PUBLISH_PLATFORM_LABELS = {
    "xhs": "小红书",
    "toutiao": "今日头条",
    "both": "小红书 + 今日头条",
}
_PUBLISH_PLATFORM_ALIASES = {
    "": "xhs",
    "xhs": "xhs",
    "xiaohongshu": "xhs",
    "小红书": "xhs",
    "toutiao": "toutiao",
    "头条": "toutiao",
    "头条号": "toutiao",
    "今日头条": "toutiao",
    "both": "both",
    "all": "both",
    "两个平台": "both",
    "小红书+今日头条": "both",
    "小红书 + 今日头条": "both",
}


def normalize_publish_platform(value: str) -> str:
    normalized = str(value or "").strip().lower()
    compact = normalized.replace(" ", "")
    platform = _PUBLISH_PLATFORM_ALIASES.get(normalized) or _PUBLISH_PLATFORM_ALIASES.get(compact)
    if platform is None:
        supported = ", ".join(PUBLISH_PLATFORM_OPTIONS)
        raise ValueError(f"unsupported publish platform: {value!r}; choose one of {supported}")
    return platform


def publish_targets(value: str) -> tuple[str, ...]:
    platform = normalize_publish_platform(value)
    if platform == "both":
        return ("xhs", "toutiao")
    return (platform,)
