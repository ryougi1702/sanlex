"""Search normalization and structural IDS parsing (no GUI dependencies)."""
from __future__ import annotations

import re
import unicodedata as ud
from dataclasses import dataclass


def is_han(char: str) -> bool:
    return len(char) == 1 and (0x3400 <= ord(char) <= 0x9FFF or
                              0xF900 <= ord(char) <= 0xFAFF or
                              0x20000 <= ord(char) <= 0x3347F)


def parse_components(value) -> list[str]:
    """Distinct component codepoints; compatibility radicals use their Han form.

    Visual variants such as 水 and 氵 remain separate. IDS entities with no
    Unicode glyph cannot be entered or presented as selectable characters.
    """
    text = ud.normalize('NFKC', value if isinstance(value, str) else ''.join(value))
    result = []
    for char in text:
        if char.isspace() or char in '+,、;/':
            continue
        if not (is_han(char) or 0x2E80 <= ord(char) <= 0x2FDF or 0x31C0 <= ord(char) <= 0x31EF):
            raise ValueError('Use kanji / hanzi components, separated by spaces or +.')
        if char not in result:
            result.append(char)
        if len(result) > 8:
            raise ValueError('Select up to 8 different components.')
    return result


def normalize(value: str) -> str:
    value = ud.normalize("NFKC", value).casefold().replace("u:", "v")
    value = re.sub("u\u0308", "v", ud.normalize('NFD', value))
    output = []
    latin = False
    for char in value:
        if ud.combining(char):
            if not latin:
                output.append(char)
        else:
            latin = ud.name(char, '').startswith('LATIN ')
            output.append(char)
    return " ".join(ud.normalize('NFC', ''.join(output)).split())


def hiragana(value: str) -> str:
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in value)


_KANA = dict(zip(
    "あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをんがぎぐげござじずぜぞだぢづでどばびぶべぼぱぴぷぺぽゔ",
    "a i u e o ka ki ku ke ko sa shi su se so ta chi tsu te to na ni nu ne no ha hi fu he ho ma mi mu me mo ya yu yo ra ri ru re ro wa o n ga gi gu ge go za ji zu ze zo da ji zu de do ba bi bu be bo pa pi pu pe po vu".split()))


def romaji(value: str) -> str:
    """Basic Hepburn search alias; original kana is always retained."""
    value = hiragana(value)
    output, i = "", 0
    while i < len(value):
        c = value[i]
        syllable = _KANA.get(c, c)
        if i + 1 < len(value) and value[i + 1] in "ゃゅょ" and syllable.endswith("i"):
            stem = syllable[:-1]
            if stem in ("sh", "ch", "j"):
                syllable = stem + {"ゃ": "a", "ゅ": "u", "ょ": "o"}[value[i + 1]]
            else:
                syllable = stem + {"ゃ": "ya", "ゅ": "yu", "ょ": "yo"}[value[i + 1]]
            i += 1
        if c == "っ" and i + 1 < len(value):
            nxt = _KANA.get(value[i + 1], "")
            syllable = "t" if nxt.startswith("ch") else nxt[:1]
        elif c == "ー":
            syllable = output[-1:] if output[-1:] in "aeiou" else ""
        output += syllable
        i += 1
    return output


def reading_aliases(value: str, lang: str) -> set[str]:
    result = {normalize(value)}
    if lang == "jp":
        result.update((hiragana(value), normalize(romaji(value))))
    else:
        # Both numeric tones and unmarked pinyin, with and without spaces.
        plain = re.sub(r"[0-5]", "", normalize(value))
        result.update((plain, plain.replace(" ", ""), normalize(value).replace(" ", "")))
    return {v for v in result if v}


IDS_ARITY = {c: 2 for c in "⿰⿱⿴⿵⿶⿷⿸⿹⿺⿻⿼⿽㇯"}
IDS_ARITY.update({"⿲": 3, "⿳": 3, "⿾": 1, "⿿": 1})
IDS_LABELS = dict(zip("⿰⿱⿲⿳⿴⿵⿶⿷⿸⿹⿺⿻",
                      ["left + right", "above + below", "three across", "three stacked",
                       "surround", "surround from above", "surround from below",
                       "surround from left", "upper-left surround", "upper-right surround",
                       "lower-left surround", "overlap"]))


@dataclass
class IDSNode:
    value: str
    children: list[IDSNode]

    def leaves(self) -> list[str]:
        if not self.children:
            return [self.value]
        return [v for child in self.children for v in child.leaves()]


def parse_ids(expression: str) -> IDSNode:
    # Bracketed region annotations are metadata, never components.
    expression = re.sub(r"\[[^\]]*\]", "", expression).strip()
    tokens = re.findall(r"&[^;]+;|.", expression)
    position = 0

    def parse() -> IDSNode:
        nonlocal position
        if position >= len(tokens):
            raise ValueError(f"Incomplete IDS: {expression}")
        token = tokens[position]
        position += 1
        return IDSNode(token, [parse() for _ in range(IDS_ARITY.get(token, 0))])

    node = parse()
    if position != len(tokens):
        raise ValueError(f"Trailing IDS content: {expression}")
    return node


def gloss_key(value: str) -> str:
    # Qualifiers distinguish senses: ‘school (of fish)’ must not become ‘school’.
    return re.sub(r"^(?:to |an? |the )", "", normalize(value).strip(" .;"))


def radical_label(number: str | int) -> str:
    try:
        n = int(str(number).split(".")[0].replace("'", ""))
        if not 1 <= n <= 214:
            return str(number)
        symbol = chr(0x2F00 + n - 1)
        name = ud.name(symbol).replace("KANGXI RADICAL ", "").lower()
        return f"{ud.normalize('NFKC', symbol)} · {name} · #{n}"
    except ValueError:
        return str(number)
