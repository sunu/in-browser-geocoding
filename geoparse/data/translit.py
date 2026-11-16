"""Latin keys for names in Cyrillic, Greek and Chinese script (plan-013 section 3). Used by the build only.

A user types the Latin form of a name, so the query side needs no transliteration.
"""
from __future__ import annotations

import re
import unicodedata

from pypinyin import lazy_pinyin

from geoparse.execute.data import norm_name

CYRILLIC = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z", "и": "i", "й": "y",
    "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f",
    "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    # Ukrainian, Belarusian, Kazakh, Serbian, Macedonian
    "і": "i", "ї": "yi", "є": "ye", "ґ": "g", "ў": "u", "ә": "a", "ғ": "gh", "қ": "q", "ң": "ng", "ө": "o", "ұ": "u",
    "ү": "u", "һ": "h", "ђ": "dj", "ј": "j", "љ": "lj", "њ": "nj", "ћ": "c", "џ": "dz", "ѓ": "gj", "ќ": "kj", "ѕ": "dz",
}
GREEK = {
    "α": "a", "β": "v", "γ": "g", "δ": "d", "ε": "e", "ζ": "z", "η": "i", "θ": "th", "ι": "i", "κ": "k", "λ": "l",
    "μ": "m", "ν": "n", "ξ": "x", "ο": "o", "π": "p", "ρ": "r", "σ": "s", "ς": "s", "τ": "t", "υ": "y", "φ": "f",
    "χ": "ch", "ψ": "ps", "ω": "o",
}
TABLE = CYRILLIC | GREEK
# Ukrainian national transliteration (2010), word-internal forms.
COUNTRY_TABLE = {"UA": TABLE | {"г": "h", "и": "y", "ї": "i", "є": "ie", "й": "i"}}
# Countries where a Han character is Chinese (for Japanese names, pinyin is wrong).
PINYIN_COUNTRIES = {"CN", "TW", "HK", "MO", "SG"}
# Administrative suffixes of Chinese names. The key without the suffix is also added ("厦门市" also gives "xiamen").
HAN_SUFFIXES = ("自治区", "自治州", "自治县", "特别行政区", "街道", "地区", "省", "市", "县", "区", "镇", "乡", "村", "盟", "旗")
_HAN = re.compile(r"[㐀-鿿豈-﫿]")
_CYR_GREEK = re.compile(r"[Ͱ-Ͽἀ-῿Ѐ-ӿ]")


def _table(s: str, country: str | None) -> str:
    table = COUNTRY_TABLE.get(country or "", TABLE)
    out = []
    for c in s.lower():
        if c in table:
            out.append(table[c])
            continue
        base = unicodedata.normalize("NFKD", c)[:1]
        out.append(table.get(base, c))
    return "".join(out)


def _pinyin(s: str) -> str:
    return " ".join("".join(lazy_pinyin(w)) for w in s.split())


def translit_keys(name: str | None, country: str | None) -> list[str]:
    """Latin name keys (norm_name form) for a name in Cyrillic, Greek or Chinese script."""
    if not name:
        return []
    out: list[str] = []
    if _CYR_GREEK.search(name):
        out.append(norm_name(_table(name, country)))
    if country in PINYIN_COUNTRIES and _HAN.search(name):
        out.append(norm_name(_pinyin(name)))
        for suf in HAN_SUFFIXES:
            if name.endswith(suf) and len(name) > len(suf) + 1:
                out.append(norm_name(_pinyin(name[: -len(suf)])))
                break
    own = norm_name(name)
    return [k for k in dict.fromkeys(out) if k and k != own and _HAN.search(k) is None]
