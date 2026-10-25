"""Transactional, streaming importers for original upstream dictionary formats."""
from __future__ import annotations

import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import threading
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from urllib.parse import quote

from .db import Dictionary
from .text import hiragana, normalize

SOURCES = {
    "jmdict": {"name": "JMdict · Japanese ↔ English with examples", "filename": "JMdict_e_examp.gz",
                "url": "https://www.edrdg.org/pub/Nihongo/JMdict_e_examp.gz",
                "homepage": "https://www.edrdg.org/wiki/index.php/JMdict-EDICT_Dictionary_Project",
                "license": "CC BY-SA 4.0 · EDRDG; examples CC BY 2.0 FR · Tatoeba", "about": "Japanese vocabulary and senses, with Japanese / English example pairs embedded in selected meanings."},
    "cedict": {"name": "CC-CEDICT · Chinese ↔ English", "filename": "cedict.txt.gz",
                "url": "https://www.mdbg.net/chinese/export/cedict/cedict_1_0_ts_utf-8_mdbg.txt.gz",
                "homepage": "https://www.mdbg.net/chinese/dictionary?page=cedict",
                "license": "CC BY-SA 4.0 · MDBG and CC-CEDICT contributors",
                "about": "Simplified / traditional headwords, Mandarin pinyin and English definitions."},
    "kanjidic": {"name": "KANJIDIC2 · Japanese characters", "filename": "kanjidic2.xml.gz",
                  "url": "https://www.edrdg.org/pub/Nihongo/kanjidic2.xml.gz",
                  "homepage": "https://www.edrdg.org/wiki/index.php/KANJIDIC_Project",
                  "license": "CC BY-SA 4.0 · EDRDG", "about": "On / kun readings, names, radicals, stroke counts and school grades."},
    "unihan": {"name": "Unicode Unihan 17.0 · Han characters", "filename": "Unihan-17.0.zip",
                "url": "https://www.unicode.org/Public/17.0.0/ucd/Unihan.zip",
                "homepage": "https://www.unicode.org/reports/tr38/", "license": "Unicode License v3 · Unicode, Inc.",
                "about": "Mandarin, Cantonese, definitions, radical / stroke indices and character variants."},
    "ids": {"name": "CJKVI / CHISE · Character structures", "filename": "ids.txt",
             "url": "https://raw.githubusercontent.com/cjkvi/cjkvi-ids/master/ids.txt",
             "homepage": "https://github.com/cjkvi/cjkvi-ids", "license": "GPL-2.0-or-later · CHISE / CJKVI",
             "about": "Ideographic description sequences and the reverse ‘Part of’ component index."},
    "wiktionary-ja": {"name": "Wiktionary · Japanese definitions & translations", "filename": "jawiktionary.jsonl.gz",
                      "url": "https://kaikki.org/jawiktionary/raw-wiktextract-data.jsonl.gz",
                      "homepage": "https://kaikki.org/jawiktionary/rawdata.html", "license": "CC BY-SA 4.0 · Wiktionary contributors / Kaikki",
                      "about": "Japanese-language definitions and source-linked JP / CN / EN translations."},
    "wiktionary-zh": {"name": "Wiktionary · Chinese definitions & translations", "filename": "zhwiktionary.jsonl.gz",
                      "url": "https://kaikki.org/zhwiktionary/raw-wiktextract-data.jsonl.gz",
                      "homepage": "https://kaikki.org/zhwiktionary/rawdata.html", "license": "CC BY-SA 4.0 · Wiktionary contributors / Kaikki",
                      "about": "Chinese-language definitions and source-linked JP / CN / EN translations."},
    "tatoeba": {"name":"Tatoeba · Example sentences", "filename":"tatoeba-manifest.json",
                "url":"https://tatoeba.org/en/downloads", "homepage":"https://tatoeba.org/en/downloads",
                "license":"CC BY 2.0 FR · Tatoeba contributors",
                "about":"Offline Japanese, Mandarin and linked English sentences, with direct translations and contributor attribution. Corpus matches use spelling; check the intended meaning."},
}


class Cancelled(Exception):
    pass


def check_cancel(cancel: threading.Event | None):
    if cancel and cancel.is_set():
        raise Cancelled("Cancelled. Existing installed data was preserved.")


def download(source: str, cache: Path, progress=print, cancel=None, refresh=False) -> Path:
    if source=='tatoeba':
        from .examples import FILES
        cache.mkdir(parents=True,exist_ok=True)
        hashes={}
        for name in FILES:
            check_cancel(cancel)
            file = download_file({'filename':Path(name).name,'url':'https://downloads.tatoeba.org/exports/'+name},
                                 cache/'tatoeba',progress,cancel,refresh)
            hashes[name]=hashlib.sha256(file.read_bytes()).hexdigest()
        manifest=cache/SOURCES[source]['filename']
        temporary=manifest.with_suffix('.json.part')
        temporary.write_text(json.dumps({'files':FILES,'sha256':hashes},indent=2),encoding='utf-8')
        temporary.replace(manifest)
        return manifest
    return download_file(SOURCES[source],cache,progress,cancel,refresh)


def download_file(spec, cache: Path, progress=print, cancel=None, refresh=False) -> Path:
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / spec["filename"]
    if target.exists() and not refresh:
        progress(f"Using cached {spec['filename']}")
        return target
    partial = target.with_suffix(target.suffix + ".part")
    request = urllib.request.Request(spec["url"], headers={"User-Agent": "SanLex/0.1 (offline dictionary data download)"})
    try:
        with urllib.request.urlopen(request, timeout=45) as response, partial.open("wb") as output:
            total = int(response.headers.get("Content-Length", 0))
            received = 0
            last_report = -1
            while True:
                check_cancel(cancel)
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                received += len(chunk)
                if received > 256 * 1024 * 1024:
                    raise ValueError("Download exceeded the 256 MB source limit")
                output.write(chunk)
                if received // (1024 * 1024) != last_report:
                    last_report = received // (1024 * 1024)
                    suffix = f" / {total / 1048576:.1f} MB" if total else " MB"
                    progress(f"Downloading {spec['filename']}: {received / 1048576:.1f}{suffix}")
            if total and received != total:
                raise ValueError("Incomplete download; please retry")
        if not received:
            raise ValueError("Empty download")
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
    return target


def import_jmdict(db: Dictionary, path: Path, progress, cancel) -> int:
    db.delete_source_entries("jmdict")
    count = 0
    with gzip.open(path, "rb") as stream:
        for _, element in ET.iterparse(stream, events=("end",)):
            if element.tag != "entry":
                continue
            if count % 1000 == 0:
                check_cancel(cancel)
                progress(f"Indexing Japanese words: {count:,}")
            spellings = [k.text for k in element.findall("k_ele/keb")]
            readings = [r.text for r in element.findall("r_ele/reb")]
            senses, inherited_pos = [], []
            for sense in element.findall("sense"):
                glosses = [g.text for g in sense.findall("gloss") if g.get("{http://www.w3.org/XML/1998/namespace}lang", "eng") == "eng" and g.text]
                if not glosses:
                    continue
                inherited_pos = [p.text for p in sense.findall("pos")] or inherited_pos
                examples=[]
                for example in sense.findall('example'):
                    texts={node.get('{http://www.w3.org/XML/1998/namespace}lang'):node.text for node in example.findall('ex_sent')}
                    if texts.get('jpn'):
                        identifier=example.findtext('ex_srce')
                        examples.append({'text':texts['jpn'],'translation':texts.get('eng',''),
                            'translation_lang':'en','match':example.findtext('ex_text') or '',
                            'tatoeba_id':int(identifier) if identifier and identifier.isdigit() else None})
                senses.append({"glosses": glosses, "pos": inherited_pos[:],
                               "examples":examples,
                               "tags": [p.text for tag in ("field", "misc", "dial") for p in sense.findall(tag)],
                               "spellings": [p.text for p in sense.findall("stagk")],
                               "readings": [p.text for p in sense.findall("stagr")],
                               "note": "; ".join(p.text for p in sense.findall("s_inf")),
                               "xref": [p.text for p in sense.findall("xref")]})
            if senses and readings:
                restrictions = [{"reading": r.findtext("reb"), "spellings": [x.text for x in r.findall("re_restr")],
                                 "no_kanji": r.find("re_nokanji") is not None} for r in element.findall("r_ele")]
                senses[0]["reading_restrictions"] = restrictions
                db.add_entry({"id": "jmdict:" + element.findtext("ent_seq"), "lang": "jp",
                              "headword": (spellings or readings)[0], "forms": spellings + readings,
                              "reading": readings[0], "readings": readings,
                              "glosses": [g for s in senses for g in s["glosses"]], "senses": senses,
                              "common": int(bool(element.findall("k_ele/ke_pri") or element.findall("r_ele/re_pri"))),
                              "source": "jmdict"})
                count += 1
            element.clear()
    return count


CEDICT_RE = re.compile(r"^(\S+) (\S+) \[(.+?)\] /(.+)/$")


def import_cedict(db: Dictionary, path: Path, progress, cancel) -> int:
    db.delete_source_entries("cedict")
    count = 0
    with gzip.open(path, "rt", encoding="utf-8-sig") as stream:
        for line in stream:
            match = CEDICT_RE.match(line.strip())
            if not match:
                continue
            traditional, simplified, reading, meanings = match.groups()
            # IDs are content-derived and stable across source updates; no line-number bookmarks.
            entry_id = hashlib.sha256(f"{traditional}\t{simplified}\t{reading}".encode()).hexdigest()[:24]
            glosses = [g for g in meanings.split("/") if g]
            if db.conn.execute("SELECT 1 FROM entries WHERE id=?", ("cedict:" + entry_id,)).fetchone():
                continue
            db.add_entry({"id": "cedict:" + entry_id, "lang": "cn", "headword": simplified,
                          "forms": [simplified, traditional], "reading": reading,
                          "glosses": glosses, "senses": [{"glosses": glosses}], "source": "cedict"})
            count += 1
            if count % 1000 == 0:
                check_cancel(cancel)
                progress(f"Indexing Chinese words: {count:,}")
    return count


def import_kanjidic(db: Dictionary, path: Path, progress, cancel) -> int:
    db.conn.execute("UPDATE characters SET kanjidic='{}'")
    count = 0
    with gzip.open(path, "rb") as stream:
        for _, element in ET.iterparse(stream, events=("end",)):
            if element.tag != "character":
                continue
            props = {"on": [], "kun": [], "meanings": [], "nanori": [],
                     "strokes": [s.text for s in element.findall("misc/stroke_count")],
                     "radicals": [r.text for r in element.findall("radical/rad_value") if r.get("rad_type") == "classical"],
                     "grade": element.findtext("misc/grade"), "frequency": element.findtext("misc/freq")}
            for reading in element.findall("reading_meaning/rmgroup/reading"):
                key = {"ja_on": "on", "ja_kun": "kun"}.get(reading.get("r_type"))
                if key:
                    props[key].append(reading.text)
            props["meanings"] = [m.text for m in element.findall("reading_meaning/rmgroup/meaning") if not m.get("m_lang")]
            props["nanori"] = [m.text for m in element.findall("reading_meaning/nanori")]
            db.conn.execute("INSERT INTO characters(char,kanjidic) VALUES(?,?) ON CONFLICT(char) DO UPDATE SET kanjidic=excluded.kanjidic",
                            (element.findtext("literal"), json.dumps(props, ensure_ascii=False)))
            count += 1
            if count % 1000 == 0:
                check_cancel(cancel)
                progress(f"Indexing kanji: {count:,}")
            element.clear()
    return count


UNIHAN_FIELDS = {"kDefinition", "kMandarin", "kCantonese", "kJapaneseOn", "kJapaneseKun", "kTotalStrokes", "kRSUnicode",
                 "kSimplifiedVariant", "kTraditionalVariant", "kSemanticVariant", "kCompatibilityVariant"}


def import_unihan(db: Dictionary, path: Path, progress, cancel) -> int:
    characters = {}
    with zipfile.ZipFile(path) as archive:
        for filename in archive.namelist():
            if not filename.endswith(".txt"):
                continue
            check_cancel(cancel)
            progress(f"Reading {filename}")
            with archive.open(filename) as raw:
                for line in io.TextIOWrapper(raw, encoding="utf-8-sig"):
                    if not line.startswith("U+"):
                        continue
                    code, prop, value = line.rstrip("\r\n").split("\t", 2)
                    if prop in UNIHAN_FIELDS:
                        char = chr(int(code[2:], 16))
                        characters.setdefault(char, {})[prop] = value
    db.conn.execute("UPDATE characters SET unihan='{}'")
    for i, (char, props) in enumerate(characters.items()):
        if i % 2000 == 0:
            check_cancel(cancel)
            progress(f"Indexing Han characters: {i:,}")
        db.conn.execute("INSERT INTO characters(char,unihan) VALUES(?,?) ON CONFLICT(char) DO UPDATE SET unihan=excluded.unihan",
                        (char, json.dumps(props, ensure_ascii=False)))
    return len(characters)


def import_ids(db: Dictionary, path: Path, progress, cancel) -> int:
    db.conn.execute("DELETE FROM decompositions WHERE source='ids'")
    db.conn.execute("DELETE FROM components WHERE source='ids'")
    count = 0
    with path.open(encoding="utf-8-sig") as stream:
        for line in stream:
            if not line.startswith("U+"):
                continue
            fields = line.rstrip("\r\n").split("\t")
            if len(fields) < 3 or len(fields[1]) != 1:
                continue
            char = fields[1]
            db.conn.execute("INSERT OR IGNORE INTO characters(char) VALUES(?)", (char,))
            for expression in fields[2:]:
                if expression != char:
                    db.add_decomposition(char, expression, "ids")
            count += 1
            if count % 2000 == 0:
                check_cancel(cancel)
                progress(f"Indexing character structures: {count:,}")
    return count


IMPORTERS = {"jmdict": import_jmdict, "cedict": import_cedict, "kanjidic": import_kanjidic,
             "unihan": import_unihan, "ids": import_ids}


def import_wiktionary(db: Dictionary, path: Path, progress, cancel, edition="ja", links_only=False) -> int:
    source = 'wiktionary-' + edition
    if not links_only:
        db.delete_source_entries(source)
    db.conn.execute('DELETE FROM lexical_links WHERE source=?', (source,))
    language_codes = {'ja': 'jp', 'zh': 'cn', 'cmn': 'cn', 'en': 'en'}
    count = 0
    seen = {}
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        for i, line in enumerate(stream):
            if i % 2000 == 0:
                check_cancel(cancel)
                progress(f"Reading {edition.upper()} Wiktionary: {i:,} records; {count:,} indexed")
            item = json.loads(line)
            lang = language_codes.get(item.get('lang_code'))
            word = item.get('word', '')
            if not lang or not word or len(word) > 300:
                continue
            senses = [{'glosses': s.get('glosses', []), 'pos': [item.get('pos', '')],
                       'tags': s.get('tags', []), 'examples': s.get('examples', [])}
                      for s in item.get('senses', []) if s.get('glosses')]
            url = f'https://{edition}.wiktionary.org/wiki/' + quote(word, safe='')
            reading = ''
            for sound in item.get('sounds', []):
                reading = sound.get('zh_pron') or sound.get('roman') or ''
                if reading:
                    break
            forms = [f['form'] for f in item.get('forms', []) if f.get('form')]
            if lang == 'jp':
                kana_forms = [f for f in forms if re.fullmatch(r'[ぁ-ゖァ-ヶー・ ]+', f)]
                if kana_forms:
                    reading = kana_forms[0]
            base = json.dumps([word, lang, item.get('pos'), item.get('etymology_number', 0)], ensure_ascii=False)
            occurrence = seen.get(base, 0)
            seen[base] = occurrence + 1
            identifier = source + ':' + hashlib.sha256(f'{base}:{occurrence}'.encode()).hexdigest()[:24]
            if senses:
                senses[0]['source_url'] = url
                if not links_only:
                    db.add_entry({'id': identifier, 'lang': lang, 'headword': word, 'reading': reading,
                              'forms': forms, 'readings': kana_forms if lang == 'jp' and kana_forms else [reading],
                              'glosses': [g for s in senses for g in s['glosses']],
                                  'senses': senses, 'source': source, 'definition_lang': 'jp' if edition == 'ja' else 'cn'})
                count += 1
            for translation in item.get('translations', []):
                target_lang = language_codes.get(translation.get('lang_code') or translation.get('code'))
                target_word = translation.get('word', '')
                if not target_lang or target_lang == lang or not target_word:
                    continue
                sense = translation.get('sense', '')
                db.conn.execute('INSERT OR IGNORE INTO lexical_links VALUES(?,?,?,?,?,?,?,?)',
                                (lang, normalize(word), target_lang, target_word, translation.get('roman', ''), sense, source, url))
                db.conn.execute('INSERT OR IGNORE INTO lexical_links VALUES(?,?,?,?,?,?,?,?)',
                                (target_lang, normalize(target_word), lang, word, reading, sense, source, url))
    return count


IMPORTERS['wiktionary-ja'] = lambda db, p, progress, cancel: import_wiktionary(db, p, progress, cancel, 'ja')
IMPORTERS['wiktionary-zh'] = lambda db, p, progress, cancel: import_wiktionary(db, p, progress, cancel, 'zh')
from .examples import import_tatoeba
IMPORTERS['tatoeba'] = import_tatoeba


def install_source(db: Dictionary, source: str, path: Path, progress=print, cancel=None):
    check_cancel(cancel)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    with db.conn:
        count = IMPORTERS[source](db, path, progress, cancel)
        if count < 1:
            raise ValueError("No records found: source format may have changed. Previous data was preserved.")
        check_cancel(cancel)
        metadata={**SOURCES[source], "entries": count, "sha256": digest.hexdigest()}
        if source=='tatoeba':
            manifest=json.loads(path.read_text(encoding='utf-8'))
            metadata.update({'files':manifest['files'],'file_sha256':manifest.get('sha256',{}),
                'selection':'Japanese and Mandarin sentences up to 1000 characters; English sentences directly linked to those languages. Only direct translation links are displayed.'})
        db.set_source(source, metadata)
    progress(f"Installed {SOURCES[source]['name']}: {count:,} records")
    return count
