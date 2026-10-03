from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


@dataclass(frozen=True)
class CountryLocation:
    country: str
    latitude: float
    longitude: float
    precision: str = "country"
    method: str = "explicit_country_name"


# Country-level label anchors are not event locations. They are used only when
# the source text explicitly names a country and no precise coordinates exist.
_COUNTRY_LABEL_ANCHORS: dict[str, tuple[tuple[str, ...], float, float]] = {
    "Iran": (("iran", "伊朗"), 32.4279, 53.6880),
    "Poland": (("poland", "波兰"), 51.9194, 19.1451),
    "Ukraine": (("ukraine", "乌克兰"), 48.3794, 31.1656),
    "Russia": (("russia", "俄罗斯"), 61.5240, 105.3188),
    "China": (("china", "中国"), 35.8617, 104.1954),
    "India": (("india", "印度"), 22.9734, 78.6569),
    "Nepal": (("nepal", "尼泊尔"), 28.3949, 84.1240),
    "Turkey": (("turkey", "土耳其"), 38.9637, 35.2433),
    "South Korea": (("south korea", "republic of korea", "韩国", "南韩"), 35.9078, 127.7669),
    "Yemen": (("yemen", "也门"), 15.5527, 48.5164),
    "Saudi Arabia": (("saudi arabia", "沙特", "沙特阿拉伯"), 23.8859, 45.0792),
    "Canada": (("canada", "加拿大"), 56.1304, -106.3468),
    "Mexico": (("mexico", "墨西哥"), 23.6345, -102.5528),
    "Nigeria": (("nigeria", "尼日利亚"), 9.0820, 8.6753),
    "South Africa": (("south africa", "南非"), -30.5595, 22.9375),
    "Fiji": (("fiji", "斐济"), -17.7134, 178.0650),
    "France": (("france", "法国"), 46.2276, 2.2137),
    "Bangladesh": (("bangladesh", "孟加拉国"), 23.6850, 90.3563),
    "Pakistan": (("pakistan", "巴基斯坦"), 30.3753, 69.3451),
    "Sweden": (("sweden", "瑞典"), 60.1282, 18.6435),
    "Hungary": (("hungary", "匈牙利"), 47.1625, 19.5033),
    "Colombia": (("colombia", "哥伦比亚"), 4.5709, -74.2973),
    "Brazil": (("brazil", "巴西"), -14.2350, -51.9253),
    "United Kingdom": (("united kingdom", "uk", "u.k.", "英国"), 55.3781, -3.4360),
    "United States": (("united states", "u.s.", "usa", "美国"), 37.0902, -95.7129),
    "Israel": (("israel", "以色列"), 31.0461, 34.8516),
    "Japan": (("japan", "日本"), 36.2048, 138.2529),
    "Australia": (("australia", "澳大利亚"), -25.2744, 133.7751),
    "Germany": (("germany", "德国"), 51.1657, 10.4515),
}


def _normalise_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def resolve_explicit_country_location(text: str) -> CountryLocation | None:
    """Resolve an explicitly named country to a country-level map label."""
    haystack = _normalise_text(text)
    if not haystack:
        return None
    aliases: list[tuple[int, str, str, float, float]] = []
    for country, (names, latitude, longitude) in _COUNTRY_LABEL_ANCHORS.items():
        for name in names:
            aliases.append((len(name), country, name, latitude, longitude))
    matches = [
        (country, latitude, longitude)
        for _, country, name, latitude, longitude in sorted(aliases, reverse=True)
        if re.search(rf"(?<![a-z]){re.escape(name)}(?![a-z])", haystack)
    ]
    unique = {country: (latitude, longitude) for country, latitude, longitude in matches}
    if len(unique) != 1:
        return None
    country, (latitude, longitude) = next(iter(unique.items()))
    return CountryLocation(country, latitude, longitude)


def verified_location(
    latitude: Any,
    longitude: Any,
    location_name: str = "",
    precision_hint: str = "",
) -> tuple[float | None, float | None, str]:
    """Accept only explicit coordinates; never infer a capital or use 0,0."""
    try:
        lat = float(latitude)
        lon = float(longitude)
    except (TypeError, ValueError):
        return None, None, "country" if location_name else "unknown"
    if not -90 <= lat <= 90 or not -180 <= lon <= 180 or (lat == 0 and lon == 0):
        return None, None, "country" if location_name else "unknown"
    return lat, lon, precision_hint or "city"
