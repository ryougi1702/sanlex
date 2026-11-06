"""Bounded, offline Japanese deinflection, checked against dictionary POS data.

Rules are written here, with no external code or runtime language model. Each
reverse step carries the grammatical class required of the next step. This
allows e.g. past -> negative -> verb, but rejects arbitrary suffix stripping.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import re

from .text import hiragana, is_han, normalize


@dataclass(frozen=True)
class Rule:
    ending: str
    replacement: str
    surface: str
    base: str
    reason: str
    whole: bool = False


@dataclass(frozen=True)
class Candidate:
    term: str
    kind: str
    forms: tuple[str, ...]
    reasons: tuple[str, ...]


def _rules() -> tuple[Rule, ...]:
    rules = []

    def add(ending, replacement, surface, base, reason, whole=False):
        rules.append(Rule(ending, replacement, surface, base, reason, whole))

    # Surface classes: finite forms do not themselves take more inflections;
    # negative/desiderative forms behave as i-adjectives; derived verbs are
    # ichidan, so further tense, politeness and voice can be unwound safely.
    polite = (('ます', 'polite'), ('ました', 'polite past'),
              ('ません', 'polite negative'), ('ませんでした', 'polite negative past'),
              ('ましょう', 'polite volitional'))
    ichidan = (('た', 'finite', 'past'), ('て', 'te', 'te-form'),
               ('ない', 'adj-i', 'negative'), ('なければ', 'finite', 'negative conditional'),
               ('なくて', 'te', 'negative te-form'), ('ず', 'finite', 'negative (ず)'),
               ('れば', 'finite', 'conditional'), ('ろ', 'finite', 'imperative'),
               ('よ', 'finite', 'imperative'), ('よう', 'finite', 'volitional'),
               ('たい', 'adj-i', 'desire (たい)'),
               ('られる', 'v1', 'potential / passive'), ('させる', 'v1', 'causative'))
    for ending, reason in polite:
        add(ending, 'る', 'finite', 'v1', reason)
    for ending, surface, reason in ichidan:
        add(ending, 'る', surface, 'v1', reason)

    # dictionary ending, i/a/e/o-row stem, past, te-form, dictionary class
    godan = (('う', 'い', 'わ', 'え', 'お', 'った', 'って', 'v5u'),
             ('く', 'き', 'か', 'け', 'こ', 'いた', 'いて', 'v5k'),
             ('ぐ', 'ぎ', 'が', 'げ', 'ご', 'いだ', 'いで', 'v5g'),
             ('す', 'し', 'さ', 'せ', 'そ', 'した', 'して', 'v5s'),
             ('つ', 'ち', 'た', 'て', 'と', 'った', 'って', 'v5t'),
             ('ぬ', 'に', 'な', 'ね', 'の', 'んだ', 'んで', 'v5n'),
             ('ぶ', 'び', 'ば', 'べ', 'ぼ', 'んだ', 'んで', 'v5b'),
             ('む', 'み', 'ま', 'め', 'も', 'んだ', 'んで', 'v5m'),
             ('る', 'り', 'ら', 'れ', 'ろ', 'った', 'って', 'v5r'),
             ('く', 'き', 'か', 'け', 'こ', 'った', 'って', 'v5k-s'))
    for end, i, a, e, o, past, te, kind in godan:
        for suffix, reason in polite:
            add(i + suffix, end, 'finite', kind, reason)
        for ending, surface, reason in (
                (past, 'finite', 'past'), (te, 'te', 'te-form'),
                (a + 'ない', 'adj-i', 'negative'),
                (a + 'なければ', 'finite', 'negative conditional'),
                (a + 'なくて', 'te', 'negative te-form'), (a + 'ず', 'finite', 'negative (ず)'),
                (e + 'ば', 'finite', 'conditional'), (e, 'finite', 'imperative'),
                (o + 'う', 'finite', 'volitional'), (i + 'たい', 'adj-i', 'desire (たい)'),
                (e + 'る', 'v1', 'potential'), (a + 'れる', 'v1', 'passive'),
                (a + 'せる', 'v1', 'causative')):
            add(ending, end, surface, kind, reason)

    suru = [('し' + suffix, 'finite', reason) for suffix, reason in polite]
    suru += [('した', 'finite', 'past'), ('して', 'te', 'te-form'),
             ('しない', 'adj-i', 'negative'), ('しなければ', 'finite', 'negative conditional'),
             ('しなくて', 'te', 'negative te-form'), ('せず', 'finite', 'negative (ず)'),
             ('すれば', 'finite', 'conditional'), ('しろ', 'finite', 'imperative'),
             ('せよ', 'finite', 'imperative'), ('しよう', 'finite', 'volitional'),
             ('したい', 'adj-i', 'desire (たい)'), ('される', 'v1', 'passive'),
             ('させる', 'v1', 'causative'), ('できる', 'v1', 'potential')]
    for ending, surface, reason in suru:
        add(ending, 'する', surface, 'vs', reason)
        # JMdict often stores 勉強 rather than a separate 勉強する entry.
        add(ending, '', surface, 'vs-noun', reason + ' (する)')

    for spelling, ki, ko in (('くる', 'き', 'こ'), ('来る', '来', '来'), ('來る', '來', '來')):
        for suffix, reason in polite:
            add(ki + suffix, spelling, 'finite', 'vk', reason)
        for ending, surface, reason in (
                (ki + 'た', 'finite', 'past'), (ki + 'て', 'te', 'te-form'),
                (ko + 'ない', 'adj-i', 'negative'),
                (ko + 'なければ', 'finite', 'negative conditional'),
                (ko + 'なくて', 'te', 'negative te-form'), (ko + 'ず', 'finite', 'negative (ず)'),
                (ko + 'れば', 'finite', 'conditional'), (ko + 'い', 'finite', 'imperative'),
                (ko + 'よう', 'finite', 'volitional'), (ki + 'たい', 'adj-i', 'desire (たい)'),
                (ko + 'られる', 'v1', 'potential / passive'), (ko + 'させる', 'v1', 'causative')):
            add(ending, spelling, surface, 'vk', reason)

    for ending, surface, reason in (
            ('かった', 'finite', 'past'), ('かったです', 'finite', 'polite past'),
            ('くない', 'adj-i', 'negative'),
            ('くて', 'te', 'te-form'), ('ければ', 'finite', 'conditional'),
            ('くなければ', 'finite', 'negative conditional'),
            ('くありません', 'finite', 'polite negative'),
            ('くありませんでした', 'finite', 'polite negative past')):
        add(ending, 'い', surface, 'adj-i', reason)
        # いい conjugates with the よ- stem, including compounds like かっこいい.
        add('よ' + ending, 'いい', surface, 'adj-i', reason)
    add('です', '', 'finite', 'adj-i', 'polite')
    for ending, surface, reason in (
            ('だった', 'finite', 'past'), ('で', 'te', 'te-form'),
            ('ではない', 'adj-i', 'negative'), ('じゃない', 'adj-i', 'negative (じゃない)'),
            ('なら', 'finite', 'conditional'), ('です', 'finite', 'polite'),
            ('でした', 'finite', 'polite past'), ('ではありません', 'finite', 'polite negative'),
            ('じゃありません', 'finite', 'polite negative'),
            ('ではありませんでした', 'finite', 'polite negative past'),
            ('じゃありませんでした', 'finite', 'polite negative past')):
        add(ending, '', surface, 'adj-na', reason)

    for te in ('て', 'で'):
        add(te + 'いる', te, 'v1', 'te', 'progressive / continuing state')
        add(te + 'る', te, 'v1', 'te', 'progressive (contracted)')
    for past in ('た', 'だ'):
        add(past + 'ら', past, 'finite', 'finite', 'conditional (たら)')
        add(past + 'り', past, 'finite', 'finite', 'listing actions (たり)')
    add('ない', 'ある', 'adj-i', 'v5r', 'negative', whole=True)
    return tuple(rules)


RULES = _rules()
MAX_DEPTH = 6
MAX_CANDIDATES = 256


def deinflect(query: str) -> list[Candidate]:
    """Generate shortest analyses first; only exact dictionary hits are useful.

    Work is capped independently of input size. Romaji and sentences are left
    to the existing search; this is a word lookup, not a Japanese tokenizer.
    """
    term = hiragana(normalize(query.strip()))
    if not term or len(term) > 100 or not all(is_han(c) or 'ぁ' <= c <= 'ゖ' or c in 'ー々〆' for c in term):
        return []
    queue = deque([Candidate(term, '', (term,), ())])
    seen = {(term, '')}
    candidates = []
    while queue and len(candidates) < MAX_CANDIDATES:
        current = queue.popleft()
        if len(current.reasons) >= MAX_DEPTH:
            continue
        for rule in RULES:
            if current.kind and current.kind != rule.surface:
                continue
            if not current.term.endswith(rule.ending) or (rule.whole and current.term != rule.ending):
                continue
            base = current.term[:-len(rule.ending)] + rule.replacement
            key = (base, rule.base)
            if not base or base in current.forms or key in seen:
                continue
            seen.add(key)
            candidate = Candidate(base, rule.base, (*current.forms, base), (*current.reasons, rule.reason))
            candidates.append(candidate)
            queue.append(candidate)
            if len(candidates) >= MAX_CANDIDATES:
                break
    return candidates


def entry_kinds(entry: dict) -> set[str]:
    """Interpret JMdict classes and the broader POS labels used by Wiktionary.

    Explicit conjugation classes take precedence over inferred spelling. A
    broad 'verb' label can be ambiguous; the UI labels analyses as possible.
    Nouns with no suru annotation and entries with no POS are never accepted.
    """
    tags = {normalize(p) for s in entry['senses'] for p in (*s.get('pos', []), *s.get('tags', []))}
    kinds = set()
    codes = {'v1', 'vs', 'vs-i', 'vs-s', 'vk', 'adj-i', 'adj-ix', 'adj-na',
             'v5u', 'v5k', 'v5g', 'v5s', 'v5t', 'v5n', 'v5b', 'v5m', 'v5r', 'v5k-s', 'v5r-i'}
    for tag in tags:
        if tag in codes:
            kinds.add({'adj-ix': 'adj-i', 'vs-i': 'vs', 'vs-s': 'vs', 'v5r-i': 'v5r'}.get(tag, tag))
        if 'ichidan' in tag:
            kinds.add('v1')
        if 'godan' in tag:
            if 'iku/yuku' in tag:
                kinds.add('v5k-s')
            else:
                match = re.search(r"'([ukgstnbmr])u?' ending", tag)
                if match:
                    kinds.add('v5' + match[1])
        if 'kuru verb' in tag:
            kinds.add('vk')
        if 'suru' in tag:
            kinds.add('vs-noun' if 'noun or participle' in tag else 'vs')
        if 'adjective (keiyoushi)' in tag or tag == 'i-adjective':
            kinds.add('adj-i')
        if 'keiyodoshi' in tag or tag == 'na-adjective':
            kinds.add('adj-na')
    if 'vs' in tags:
        kinds.add('vs-noun')
    if kinds:
        return kinds
    word = hiragana(entry['headword'])
    if tags.intersection({'verb', 'auxiliary verb'}):
        if word.endswith(('する', 'ずる')):
            return {'vs'} if word.endswith('する') else set()
        if word.endswith(('来る', '來る', 'くる')):
            return {'vk'}
        if word.endswith(('行く', '往く', '逝く', 'いく', 'ゆく')):
            return {'v5k-s'}
        kind = dict(zip('うくぐすつぬぶむる', ('v5u', 'v5k', 'v5g', 'v5s', 'v5t', 'v5n', 'v5b', 'v5m', 'v5r'))).get(word[-1:])
        return ({kind} if kind else set()) | ({'v1'} if word.endswith('る') else set())
    if tags.intersection({'adj', 'adjective'}):
        return {'adj-i'} if word.endswith('い') else {'adj-na'}
    return set()
