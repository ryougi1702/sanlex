from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sqlite3
import sys
from datetime import datetime, timezone

from .text import gloss_key, hiragana, is_han, normalize, parse_components, reading_aliases
from .conjugation import deinflect, entry_kinds


def resource_path(name: str) -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)) / name


def default_home() -> Path:
    if os.environ.get("SANLEX_HOME"):
        return Path(os.environ["SANLEX_HOME"])
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "SanLex"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/SanLex"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "sanlex"


SCHEMA = """
CREATE TABLE IF NOT EXISTS entries(
 id TEXT PRIMARY KEY, lang TEXT NOT NULL, headword TEXT NOT NULL,
 reading TEXT NOT NULL, forms TEXT NOT NULL, glosses TEXT NOT NULL,
 senses TEXT NOT NULL, source TEXT NOT NULL, common INTEGER DEFAULT 0,
 definition_lang TEXT NOT NULL DEFAULT 'en');
CREATE INDEX IF NOT EXISTS entry_source ON entries(source);
CREATE INDEX IF NOT EXISTS entry_language ON entries(lang);
CREATE TABLE IF NOT EXISTS forms(term TEXT, entry_id TEXT, kind TEXT,
 PRIMARY KEY(term, entry_id, kind));
CREATE INDEX IF NOT EXISTS form_entry ON forms(entry_id);
CREATE VIRTUAL TABLE IF NOT EXISTS words_fts USING fts5(
 headword, readings, glosses, tokenize='unicode61 remove_diacritics 2');
CREATE TABLE IF NOT EXISTS gloss_index(key TEXT, entry_id TEXT, lang TEXT,
 PRIMARY KEY(key, entry_id));
CREATE INDEX IF NOT EXISTS gloss_entry ON gloss_index(entry_id);
CREATE TABLE IF NOT EXISTS characters(char TEXT PRIMARY KEY, unihan TEXT DEFAULT '{}',
 kanjidic TEXT DEFAULT '{}');
CREATE TABLE IF NOT EXISTS decompositions(parent TEXT, expression TEXT, source TEXT,
 PRIMARY KEY(parent, expression, source));
CREATE TABLE IF NOT EXISTS components(parent TEXT, component TEXT, source TEXT,
 PRIMARY KEY(parent, component, source));
CREATE INDEX IF NOT EXISTS component_reverse ON components(component);
CREATE TABLE IF NOT EXISTS word_chars(char TEXT, entry_id TEXT, PRIMARY KEY(char, entry_id));
CREATE INDEX IF NOT EXISTS char_entry ON word_chars(entry_id);
CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY, metadata TEXT);
CREATE TABLE IF NOT EXISTS favorites(entry_id TEXT PRIMARY KEY, added TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS history(query TEXT PRIMARY KEY, searched TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS lexical_links(from_lang TEXT, from_word TEXT, to_lang TEXT, to_word TEXT,
 reading TEXT, sense TEXT, source TEXT, url TEXT,
 PRIMARY KEY(from_lang,from_word,to_lang,to_word,sense,source));
CREATE INDEX IF NOT EXISTS lexical_lookup ON lexical_links(from_lang,from_word);
"""


class Dictionary:
    def __init__(self, path: Path | str, *, read_only=False):
        self.path = Path(path)
        if not read_only:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro',uri=True,timeout=0.15) if read_only else sqlite3.connect(str(path), timeout=60)
        self.conn.row_factory = sqlite3.Row
        if not read_only:
            self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute('PRAGMA busy_timeout='+('150' if read_only else '60000'))
        self.user = None

    def close(self):
        self.conn.close()
        if self.user:
            self.user.close()

    def user_connection(self):
        # A separate file keeps saving and history responsive during bulk imports.
        if self.user is None:
            self.user = sqlite3.connect(str(self.path.with_name('user.sqlite3')), timeout=5)
            self.user.execute('PRAGMA journal_mode=WAL')
            self.user.executescript('''CREATE TABLE IF NOT EXISTS favorites(entry_id TEXT PRIMARY KEY, added TEXT DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS history(query TEXT PRIMARY KEY,searched TEXT DEFAULT CURRENT_TIMESTAMP,entry_id TEXT);
                CREATE TABLE IF NOT EXISTS preferences(key TEXT PRIMARY KEY,value TEXT NOT NULL);''')
            if 'entry_id' not in {row[1] for row in self.user.execute('PRAGMA table_info(history)')}:
                self.user.execute('ALTER TABLE history ADD COLUMN entry_id TEXT')
        return self.user

    def preference(self, key: str, default=None):
        row = self.user_connection().execute('SELECT value FROM preferences WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_preference(self, key: str, value):
        user = self.user_connection()
        with user:
            user.execute('INSERT OR REPLACE INTO preferences VALUES(?,?)', (key, json.dumps(value)))

    def source_directions(self) -> list[dict]:
        return [dict(row) for row in self.conn.execute(
            'SELECT source,lang,definition_lang,count(*) entries FROM entries GROUP BY source,lang,definition_lang')]

    @staticmethod
    def entry_filters(sources=None, directions=None, alias='e') -> tuple[str, list]:
        clauses, args = [], []
        if sources is not None:
            if not sources:
                return ' AND 0', []
            clauses.append(f"{alias}.source IN ({','.join('?' for _ in sources)})")
            args.extend(sources)
        if directions is not None:
            if not directions:
                return ' AND 0', []
            clauses.append('(' + ' OR '.join(f'({alias}.lang=? AND {alias}.definition_lang=?)' for _ in directions) + ')')
            args.extend(value for pair in directions for value in pair)
        return ''.join(' AND ' + clause for clause in clauses), args

    def initialize(self):
        self.conn.executescript(SCHEMA)
        from .examples import SCHEMA as EXAMPLE_SCHEMA
        self.conn.executescript(EXAMPLE_SCHEMA)
        columns = {r[1] for r in self.conn.execute('PRAGMA table_info(entries)')}
        if 'definition_lang' not in columns:
            self.conn.execute("ALTER TABLE entries ADD COLUMN definition_lang TEXT NOT NULL DEFAULT 'en'")
            self.conn.commit()
        self.conn.execute('CREATE INDEX IF NOT EXISTS entry_source_direction ON entries(source,lang,definition_lang)')
        # Retire the old demo dictionary from existing installations as well.
        if self.conn.execute("SELECT 1 FROM sources WHERE id='starter'").fetchone():
            with self.conn:
                self.delete_source_entries('starter')
                for table in ('components', 'decompositions', 'lexical_links'):
                    self.conn.execute(f"DELETE FROM {table} WHERE source='starter'")
                self.conn.execute("DELETE FROM sources WHERE id='starter'")
        if not self.conn.execute("SELECT 1 FROM settings WHERE key='gloss-index-v2'").fetchone():
            with self.conn:
                self.conn.execute('DELETE FROM gloss_index')
                for row in self.conn.execute("SELECT id,lang,glosses FROM entries WHERE definition_lang='en'").fetchall():
                    keys = {gloss_key(g) for g in json.loads(row['glosses'])}
                    self.conn.executemany('INSERT OR IGNORE INTO gloss_index VALUES(?,?,?)',
                                          [(g,row['id'],row['lang']) for g in keys if 2 <= len(g) <= 80])
                self.conn.execute("INSERT INTO settings VALUES('gloss-index-v2','1')")

    def add_entry(self, entry: dict):
        forms = list(dict.fromkeys([entry["headword"], *entry.get("forms", [])]))
        glosses = entry["glosses"]
        cursor = self.conn.execute(
            "INSERT INTO entries(id,lang,headword,reading,forms,glosses,senses,source,common,definition_lang) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (entry["id"], entry["lang"], entry["headword"], entry["reading"], json.dumps(forms, ensure_ascii=False),
             json.dumps(glosses, ensure_ascii=False), json.dumps(entry.get("senses", []), ensure_ascii=False),
             entry["source"], entry.get("common", 0), entry.get("definition_lang", "en")))
        aliases = {(normalize(f), "word") for f in forms}
        for reading in entry.get("readings", [entry["reading"]]):
            aliases.update((a, "reading") for a in reading_aliases(reading, entry["lang"]))
        self.conn.executemany("INSERT OR IGNORE INTO forms VALUES(?,?,?)",
                              [(term, entry["id"], kind) for term, kind in aliases])
        self.conn.execute("INSERT INTO words_fts(rowid,headword,readings,glosses) VALUES(?,?,?,?)",
                          (cursor.lastrowid, " ".join(forms), " ".join(a[0] for a in aliases), " ; ".join(glosses)))
        keys = {gloss_key(g) for g in glosses} if entry.get("definition_lang", "en") == "en" else set()
        self.conn.executemany("INSERT OR IGNORE INTO gloss_index VALUES(?,?,?)",
                              [(g, entry["id"], entry["lang"]) for g in keys if 2 <= len(g) <= 80])
        self.conn.executemany("INSERT OR IGNORE INTO word_chars VALUES(?,?)",
                              [(c, entry["id"]) for c in set("".join(forms)) if is_han(c)])

    def delete_source_entries(self, source: str):
        # Called inside the import transaction; FTS rowids must be removed before entries.
        self.conn.execute("DELETE FROM words_fts WHERE rowid IN (SELECT rowid FROM entries WHERE source=?)", (source,))
        for table in ("forms", "gloss_index", "word_chars"):
            self.conn.execute(f"DELETE FROM {table} WHERE entry_id IN (SELECT id FROM entries WHERE source=?)", (source,))
        self.conn.execute("DELETE FROM entries WHERE source=?", (source,))

    def add_decomposition(self, char: str, expression: str, source: str):
        from .text import parse_ids
        try:
            node = parse_ids(expression)
        except ValueError:
            return
        self.conn.execute("INSERT OR IGNORE INTO decompositions VALUES(?,?,?)", (char, expression, source))
        # Nested layout nodes have no codepoint, so store all explicitly named glyph leaves.
        self.conn.executemany("INSERT OR IGNORE INTO components VALUES(?,?,?)",
                              [(char, c, source) for c in set(node.leaves()) if c != char and len(c) == 1])

    def set_source(self, source: str, metadata: dict):
        metadata.setdefault("installed", datetime.now(timezone.utc).isoformat())
        self.conn.execute("INSERT OR REPLACE INTO sources VALUES(?,?)", (source, json.dumps(metadata)))

    def sources(self) -> dict:
        return {r["id"]: json.loads(r["metadata"]) for r in self.conn.execute("SELECT * FROM sources")}

    @staticmethod
    def decode(row) -> dict | None:
        if row is None:
            return None
        result = dict(row)
        for field in ("forms", "glosses", "senses"):
            result[field] = json.loads(result[field])
        return result

    def entry(self, entry_id: str) -> dict | None:
        return self.decode(self.conn.execute("SELECT * FROM entries WHERE id=?", (entry_id,)).fetchone())

    def autocomplete(self, query: str, lang='all', limit=10, *, sources=None, directions=None):
        """Small indexed prefix preview; never reads senses, examples or characters."""
        query=normalize(query.strip())
        if not query or limit<1:
            return []
        suffix,args=self.entry_filters(sources,directions)
        if lang!='all':
            suffix+=' AND e.lang=?'
            args.append(lang)
        fields="e.id,e.lang,e.headword,e.reading,e.source,e.definition_lang,e.common,json_extract(e.glosses,'$[0]') gloss"
        found={}
        queries=list(dict.fromkeys([query,normalize(hiragana(query))]))
        try:
            for term in queries:
                rows=self.conn.execute('SELECT '+fields+' FROM forms f CROSS JOIN entries e ON e.id=f.entry_id '
                    'WHERE f.term=?'+suffix+" ORDER BY e.common DESC,e.definition_lang='en' DESC LIMIT ?",
                    [term,*args,max(40,limit*4)])
                for row in rows:
                    found.setdefault(row['id'],{**dict(row),'exact':True,'matched':term})
            for term in queries:
                # Scan the ordered forms index; no global popularity sort over a broad prefix.
                rows=self.conn.execute('SELECT '+fields+',f.term matched FROM forms f CROSS JOIN entries e ON e.id=f.entry_id '
                    'WHERE f.term>=? AND f.term<?'+suffix+' ORDER BY f.term LIMIT ?',
                    [term,term+chr(0x10FFFF),*args,max(100,limit*12)])
                for row in rows:
                    found.setdefault(row['id'],{**dict(row),'exact':False})
        except sqlite3.OperationalError as error:
            if 'interrupted' not in str(error):
                raise
            # A cancelled/time-limited preview may still have useful rows. The UI
            # rejects superseded requests; full search has no preview time budget.
        ordered=sorted(found.values(),key=lambda e:(not e['exact'],normalize(e['headword'])!=query,
            -e['common'],e['definition_lang']!='en',len(e['matched']),len(e['headword']),e['headword']))
        seen,result=set(),[]
        for row in ordered:
            key=(row['lang'],row['headword'],row['reading'])
            if key in seen:
                continue
            seen.add(key)
            row['gloss']=(row['gloss'] or '').replace('\n',' ')[:85]
            result.append(row)
            if len(result)>=limit:
                break
        return result

    def search(self, query: str, lang: str = "all", limit: int = 80, *, sources=None, directions=None) -> list[dict]:
        original_query = query.strip()
        query = normalize(query.strip())
        if not query or limit <= 0:
            return []
        found: dict[str, dict] = {}
        fetch_limit = limit * 2  # Leave room for source duplicates before applying the display limit.
        lang_sql, args = ("", []) if lang == "all" else (" AND e.lang=?", [lang])
        extra_sql, extra_args = self.entry_filters(sources, directions)
        lang_sql += extra_sql
        args.extend(extra_args)

        def append(rows):
            for row in rows:
                if row["id"] not in found:
                    found[row["id"]] = self.decode(row)

        queries = list(dict.fromkeys([query, normalize(hiragana(query))]))
        marks = ','.join('?' * len(queries))
        # Keep the selective text index outermost. With source constraints,
        # SQLite may otherwise scan an entire dictionary before matching words.
        append(self.conn.execute("SELECT DISTINCT e.* FROM forms f CROSS JOIN entries e ON e.id=f.entry_id "
                                 f"WHERE f.term IN ({marks})" + lang_sql + " ORDER BY e.common DESC,e.definition_lang='en' DESC,e.lang='jp' DESC LIMIT ?",
                                 [*queries, *args, fetch_limit]))
        # Exact surface matches keep priority. Deinflected forms are exact,
        # POS-checked Japanese lookups, ahead of broad gloss/prefix matches.
        if lang in ('all', 'jp'):
            candidates = deinflect(query)
            terms = list(dict.fromkeys(c.term for c in candidates))
            if terms:
                marks = ','.join('?' * len(terms))
                rows = self.conn.execute(
                    'SELECT e.*,f.term AS matched_term FROM forms f CROSS JOIN entries e ON e.id=f.entry_id '
                    f"WHERE f.term IN ({marks}) AND e.lang='jp'" + lang_sql +
                    " ORDER BY e.common DESC,e.definition_lang='en' DESC,e.id", [*terms, *args])
                matches = {}
                for row in rows:
                    entry = self.decode(row)
                    term = entry.pop('matched_term')
                    matches.setdefault(term, []).append((entry, entry_kinds(entry)))
                # No SQL limit before POS validation: unrelated homographs must
                # not crowd a valid, filtered conjugation out of a small limit.
                for candidate in candidates:
                    for entry, kinds in matches.get(candidate.term, ()):
                        if entry['id'] not in found and candidate.kind in kinds:
                            entry = dict(entry)
                            entry['_conjugation'] = {
                                'query': original_query,
                                'forms': [original_query, *candidate.forms[1:]],
                                'reasons': list(reversed(candidate.reasons)),
                            }
                            found[entry['id']] = entry
        # FTS query is built from quoted tokens; user punctuation is never SQL/FTS syntax.
        tokens = re.findall(r"[^\W_]+", query, re.UNICODE)
        if tokens:
            expression = " AND ".join('"' + t.replace('"', '""') + '"' + ("*" if i == len(tokens)-1 else "")
                                      for i, t in enumerate(tokens))
            append(self.conn.execute("SELECT e.* FROM words_fts CROSS JOIN entries e ON e.rowid=words_fts.rowid "
                                     "WHERE words_fts MATCH ?" + lang_sql +
                                     " ORDER BY bm25(words_fts,8,6,1),e.common DESC LIMIT ?",
                                     [expression, *args, fetch_limit]))
        for prefix in queries:
            if len(found) >= limit:
                break
            upper = prefix + chr(0x10FFFF)
            append(self.conn.execute("SELECT DISTINCT e.* FROM forms f CROSS JOIN entries e ON e.id=f.entry_id "
                                     "WHERE f.term>=? AND f.term<?" + lang_sql +
                                     " ORDER BY length(e.headword),e.common DESC LIMIT ?", [prefix, upper, *args, fetch_limit]))
        # Deduplicate equivalent entries while keeping homonyms/readings.
        seen, result = set(), []
        for entry in found.values():
            key = (entry["lang"], entry['definition_lang'], entry["headword"], entry["reading"], tuple(entry["glosses"]))
            if key not in seen:
                seen.add(key)
                result.append(entry)
        return result[:limit]

    def mappings(self, entry: dict, limit: int = 12, *, sources=None, directions=None) -> list[tuple[dict, str]]:
        opposite = "cn" if entry["lang"] == "jp" else "jp"
        if sources is not None and not sources or directions is not None and not directions:
            return []
        target_languages = {target for origin, target in directions if origin == entry['lang']} if directions is not None else {'jp', 'cn', 'en'}
        mapped: dict[str, tuple[dict, str]] = {}
        # Direct Wiktionary translations retain their original sense labels and source page.
        forms = [normalize(f) for f in entry['forms'] if f and any(is_han(c) for c in f)] if any(is_han(c) for c in entry['headword']) else [normalize(entry['headword'])]
        if forms and target_languages:
            marks = ','.join('?' * len(forms))
            link_sql = ' AND to_lang IN (' + ','.join('?' for _ in target_languages) + ')'
            link_args = list(sorted(target_languages))
            if sources is not None:
                link_sql += ' AND source IN (' + ','.join('?' for _ in sources) + ')'
                link_args.extend(sources)
            rows = self.conn.execute(f"SELECT * FROM (SELECT *,row_number() OVER (PARTITION BY to_lang ORDER BY to_word) rn "
                                     f"FROM lexical_links WHERE from_lang=? AND from_word IN ({marks}){link_sql}) "
                                     "WHERE rn<=? ORDER BY rn,to_lang LIMIT ?", [entry['lang'], *forms, *link_args, max(3, limit // 2), limit * 2])
            for row in rows:
                target_sql, target_args = self.entry_filters(sources)
                target = self.conn.execute("SELECT e.* FROM forms f CROSS JOIN entries e ON e.id=f.entry_id "
                                           "WHERE f.term=? AND e.lang=?" + target_sql + " ORDER BY e.definition_lang='en' DESC,e.common DESC LIMIT 1",
                                           [normalize(row['to_word']), row['to_lang'], *target_args]).fetchone()
                candidate = self.decode(target) if target else {
                    'id': None, 'headword': row['to_word'], 'lang': row['to_lang'],
                    'reading': row['reading'], 'glosses': [], 'source': row['source']}
                candidate = {**candidate, '_translation_word': row['to_word'], '_source_url': row['url']}
                key = 'direct:' + row['to_lang'] + ':' + row['to_word'] + ':' + row['sense']
                mapped[key] = (candidate, 'Wiktionary translation · ' + (row['sense'] or 'sense not specified'))
                if len(mapped) >= limit:
                    break
        keys = [gloss_key(g) for g in entry["glosses"] if 2 <= len(gloss_key(g)) <= 80] if entry.get('definition_lang', 'en') == 'en' else []
        if keys and opposite in target_languages:
            marks = ",".join("?" * len(keys))
            target_sql, target_args = self.entry_filters(sources)
            rows = self.conn.execute(f"SELECT e.*,count(*) matches FROM gloss_index g CROSS JOIN entries e ON e.id=g.entry_id "
                                     f"WHERE g.key IN ({marks}) AND g.lang=?" + target_sql + " GROUP BY e.id "
                                     "ORDER BY matches DESC,e.common DESC,length(e.headword) LIMIT ?", [*keys, opposite, *target_args, limit])
            for row in rows:
                candidate = self.decode(row)
                mapped.setdefault(candidate["id"], (candidate, "Suggested · shared English gloss; check senses"))
        return list(mapped.values())[:limit]

    def localized_definitions(self, entry: dict, *, sources=None, directions=None) -> list[dict]:
        forms = [normalize(f) for f in entry['forms'] if any(is_han(c) for c in f)] if any(is_han(c) for c in entry['headword']) else [normalize(entry['headword'])]
        if not forms:
            return []
        marks = ','.join('?' * len(forms))
        filter_sql, args = self.entry_filters(sources, directions)
        return [self.decode(r) for r in self.conn.execute(
            f"WITH candidates AS (SELECT DISTINCT e.* FROM forms f CROSS JOIN entries e ON e.id=f.entry_id WHERE f.term IN ({marks}) "
            "AND e.lang=? AND e.definition_lang<>'en' AND e.id<>?" + filter_sql + "), "
            "ranked AS (SELECT *,row_number() OVER (PARTITION BY definition_lang ORDER BY length(glosses) DESC) native_rank FROM candidates) "
            "SELECT * FROM ranked WHERE native_rank<=4 ORDER BY definition_lang,native_rank",
            [*forms, entry['lang'], entry['id'], *args])]

    def character(self, char: str) -> dict:
        row = self.conn.execute("SELECT * FROM characters WHERE char=?", (char,)).fetchone()
        return {"char": char, "unihan": json.loads(row["unihan"]) if row else {},
                "kanjidic": json.loads(row["kanjidic"]) if row else {},
                "decompositions": [dict(r) for r in self.conn.execute(
                    "SELECT * FROM decompositions WHERE parent=? ORDER BY expression", (char,))]}

    def part_of(self, char: str, recursive: bool = True, limit: int = 200) -> tuple[list[dict], bool]:
        if recursive:
            sql = """WITH RECURSIVE relatives(parent) AS (
                SELECT parent FROM components WHERE component=? AND parent<>?
                UNION SELECT c.parent FROM components c JOIN relatives r ON c.component=r.parent WHERE c.parent<>?
            ) SELECT r.parent, EXISTS(SELECT 1 FROM components c WHERE c.parent=r.parent AND c.component=?) direct,
              ch.unihan, ch.kanjidic FROM relatives r LEFT JOIN characters ch ON ch.char=r.parent
              ORDER BY direct DESC,coalesce(cast(json_extract(ch.kanjidic,'$.frequency') AS INT),999999),r.parent LIMIT ?"""
            rows = self.conn.execute(sql, (char, char, char, char, limit + 1)).fetchall()
        else:
            rows = self.conn.execute("SELECT DISTINCT c.parent,1 direct,ch.unihan,ch.kanjidic FROM components c "
                                     "LEFT JOIN characters ch ON ch.char=c.parent WHERE c.component=? AND c.parent<>? "
                                     "ORDER BY coalesce(cast(json_extract(ch.kanjidic,'$.frequency') AS INT),999999),c.parent LIMIT ?", (char, char, limit + 1)).fetchall()
        return [dict(r) for r in rows[:limit]], len(rows) > limit

    def component_catalog(self) -> list[dict]:
        """Selectable Unicode parts in the installed shared IDS index."""
        rows = self.conn.execute(
            'SELECT c.component,COUNT(DISTINCT c.parent) uses,ch.unihan,ch.kanjidic '
            'FROM components c LEFT JOIN characters ch ON ch.char=c.component '
            'WHERE length(c.component)=1 AND c.parent<>c.component GROUP BY c.component')
        result = []
        for row in rows:
            char = row['component']
            try:
                # Keep the spelling actually indexed; NFKC is only an input aid.
                if parse_components(char) != [char]:
                    continue
            except ValueError:
                continue
            uni, kan = json.loads(row['unihan'] or '{}'), json.loads(row['kanjidic'] or '{}')
            strokes = (kan.get('strokes') or [uni.get('kTotalStrokes', '')])[0]
            match = re.search(r'\d+', str(strokes))
            result.append({'char': char, 'uses': row['uses'], 'strokes': int(match[0]) if match else None})
        return sorted(result, key=lambda r: (-r['uses'], r['strokes'] or 999, r['char']))

    def find_by_components(self, components, recursive=True, limit=80) -> tuple[list[dict], bool]:
        """Intersect proper ancestors of every selected part, before paging.

        UNION deduplicates each (selected part, ancestor) pair, so cycles and
        duplicate sources terminate. A character does not contain itself.
        Shared IDS alternatives are searched together, as in the atlas.
        """
        selected = parse_components(components)
        if not selected or limit <= 0:
            return [], False
        seeds = ','.join('(?)' for _ in selected)
        recursion = '''UNION SELECT r.component,c.parent FROM reached r
            JOIN components c ON c.component=r.parent WHERE c.parent<>r.component''' if recursive else ''
        rows = self.conn.execute(f'''WITH RECURSIVE wanted(component) AS (VALUES {seeds}),
            reached(component,parent) AS (
                SELECT w.component,c.parent FROM wanted w JOIN components c ON c.component=w.component
                WHERE c.parent<>w.component {recursion}
            ), matches AS (
                SELECT parent FROM reached GROUP BY parent HAVING COUNT(DISTINCT component)=?
            ) SELECT m.parent,ch.unihan,ch.kanjidic FROM matches m
            LEFT JOIN characters ch ON ch.char=m.parent WHERE length(m.parent)=1
            ORDER BY coalesce(nullif(cast(json_extract(ch.kanjidic,'$.frequency') AS INT),0),999999),
                coalesce(cast(json_extract(ch.kanjidic,'$.strokes[0]') AS INT),
                         cast(json_extract(ch.unihan,'$.kTotalStrokes') AS INT),999),m.parent LIMIT ?''',
            [*selected, len(selected), limit + 1]).fetchall()
        return [dict(row) for row in rows[:limit]], len(rows) > limit

    def containing(self, char: str, lang: str = "all", limit: int = 40, *, sources=None, directions=None) -> list[dict]:
        suffix, args = ("", []) if lang == "all" else (" AND e.lang=?", [lang])
        filter_sql, filter_args = self.entry_filters(sources, directions)
        suffix += filter_sql
        args.extend(filter_args)
        return [self.decode(r) for r in self.conn.execute(
            "SELECT e.* FROM word_chars wc CROSS JOIN entries e ON e.id=wc.entry_id WHERE wc.char=?" + suffix +
            " ORDER BY e.common DESC,length(e.headword),e.headword LIMIT ?", [char, *args, limit])]

    def toggle_favorite(self, entry_id: str) -> bool:
        user = self.user_connection()
        with user:
            if self.is_favorite(entry_id):
                user.execute("DELETE FROM favorites WHERE entry_id=?", (entry_id,))
                return False
            user.execute("INSERT INTO favorites(entry_id) VALUES(?)", (entry_id,))
            return True

    def is_favorite(self, entry_id: str) -> bool:
        return bool(self.user_connection().execute("SELECT 1 FROM favorites WHERE entry_id=?", (entry_id,)).fetchone())

    def favorites(self, *, sources=None, directions=None, lang='all') -> list[dict]:
        return [entry for row in self.user_connection().execute('SELECT entry_id FROM favorites ORDER BY added DESC')
                if (entry := self.entry(row[0])) and (sources is None or entry['source'] in sources)
                and (directions is None or (entry['lang'], entry['definition_lang']) in directions)
                and (lang == 'all' or entry['lang'] == lang)]

    def record_search(self, query: str):
        user = self.user_connection()
        with user:
            user.execute("INSERT OR REPLACE INTO history(query,searched,entry_id) "
                         "VALUES(?,strftime('%Y-%m-%d %H:%M:%f','now'),"
                         "(SELECT entry_id FROM history WHERE query=?))", (query, query))
            user.execute("DELETE FROM history WHERE query NOT IN (SELECT query FROM history ORDER BY searched DESC,rowid DESC LIMIT 100)")

    def history(self) -> list[str]:
        return [r[0] for r in self.user_connection().execute("SELECT query FROM history ORDER BY searched DESC,rowid DESC")]

    def history_entry(self, query: str):
        row = self.user_connection().execute('SELECT entry_id FROM history WHERE query=?', (query,)).fetchone()
        return row[0] if row else None

    def remember_search_entry(self, query: str, entry_id):
        # Update only submitted queries; browsing a saved word or editing the
        # search box must not create a new search-history association.
        user = self.user_connection()
        with user:
            user.execute('UPDATE history SET entry_id=? WHERE query=?', (entry_id, query))

    def counts(self) -> dict:
        result = {r[0]: r[1] for r in self.conn.execute("SELECT lang,count(*) FROM entries GROUP BY lang")}
        result["characters"] = self.conn.execute("SELECT count(*) FROM characters").fetchone()[0]
        result["structures"] = self.conn.execute("SELECT count(DISTINCT parent) FROM decompositions").fetchone()[0]
        return result

    def rebuild_search(self, progress=print):
        """Recreate derived indexes without changing stable entry IDs or user data."""
        with self.conn:
            self.conn.execute('DELETE FROM forms')
            self.conn.execute('DELETE FROM words_fts')
            self.conn.execute('DELETE FROM gloss_index')
            cursor = self.conn.execute('SELECT rowid,* FROM entries')
            count = 0
            while rows := cursor.fetchmany(1000):
                for row in rows:
                    entry = self.decode(row)
                    readings = [entry['reading']]
                    if entry['source'].startswith('wiktionary-') and entry['lang'] == 'jp':
                        kana = [f for f in entry['forms'] if re.fullmatch(r'[ぁ-ゖァ-ヶー・ ]+', f)]
                        if kana:
                            readings = kana
                            entry['reading'] = kana[0]
                            self.conn.execute('UPDATE entries SET reading=? WHERE id=?', (kana[0],entry['id']))
                    elif entry['source'] == 'jmdict':
                        restrictions = (entry['senses'] or [{}])[0].get('reading_restrictions', [])
                        readings = [r['reading'] for r in restrictions] or readings
                    aliases = {(normalize(f),'word') for f in entry['forms']}
                    for reading in readings:
                        aliases.update((a,'reading') for a in reading_aliases(reading, entry['lang']))
                    self.conn.executemany('INSERT OR IGNORE INTO forms VALUES(?,?,?)',
                                          [(term,entry['id'],kind) for term,kind in aliases])
                    self.conn.execute('INSERT INTO words_fts(rowid,headword,readings,glosses) VALUES(?,?,?,?)',
                                      (entry['rowid'],' '.join(entry['forms']),' '.join(a[0] for a in aliases),'; '.join(entry['glosses'])))
                    if entry.get('definition_lang','en') == 'en':
                        keys = {gloss_key(g) for g in entry['glosses']}
                        self.conn.executemany('INSERT OR IGNORE INTO gloss_index VALUES(?,?,?)',
                                              [(g,entry['id'],entry['lang']) for g in keys if 2 <= len(g) <= 80])
                    count += 1
                progress(f'Rebuilding search index: {count:,} entries')
            self.conn.execute("INSERT OR REPLACE INTO settings VALUES('search-normalization-v2','1')")
        self.conn.execute("INSERT INTO words_fts(words_fts) VALUES('optimize')")
        self.conn.commit()
