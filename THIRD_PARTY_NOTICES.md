# SanLex data sources, attribution and licences

SanLex combines independent dictionaries. Coverage and accuracy vary by source. No publisher listed here endorses SanLex. Dictionary data is kept separate from the application code and retains its original copyright and licence.

## JMdict and KANJIDIC2

These files are the property of the Electronic Dictionary Research and Development Group (EDRDG), and are used in conformance with the [EDRDG General Dictionary Licence](https://www.edrdg.org/edrdg/licence.html), under **Creative Commons Attribution-ShareAlike 4.0 International**. Copyright James William Breen and EDRDG. English definitions and Japanese word data are imported from JMdict_e_examp. Its embedded sentence pairs come from the Tatoeba / Tanaka corpus and retain their sentence-source terms below.

Documentation: [JMdict / EDICT](https://www.edrdg.org/wiki/index.php/JMdict-EDICT_Dictionary_Project), [KANJIDIC project](https://www.edrdg.org/wiki/index.php/KANJIDIC_Project). Copies of the licence and documentation are in `licenses/`. Use Dictionaries & sources → Download / update selected to update data. Cached source files can also be reimported. Upstream source URLs and SHA-256 digests are stored in the database's `sources` table.

## CC-CEDICT

Copyright MDBG and CC-CEDICT contributors, continuing the CEDICT project founded by Paul Andrew Denisowski. Distributed under **Creative Commons Attribution-ShareAlike 4.0 International**, as stated by the current [MDBG download page](https://www.mdbg.net/chinese/dictionary?page=cedict). Source: [CC-CEDICT](https://cc-cedict.org/). Both traditional and simplified spellings, numeric pinyin, and English definitions are preserved.

## Unicode Unihan 17.0.0

Copyright © Unicode, Inc. Distributed under the **Unicode License v3** (local copy: `licenses/Unicode-license.txt`). [Unihan documentation](https://www.unicode.org/reports/tr38/), [versioned source archive](https://www.unicode.org/Public/17.0.0/ucd/Unihan.zip). Unicode is a registered trademark of Unicode, Inc. Only selected properties are imported. A radical index is a dictionary classification, distinct from visual components.

## CJKVI / CHISE IDS

Copyright © 2014–2017 CJKVI Database; based on the CHISE IDS Database. [Original repository and licence notes](https://github.com/cjkvi/cjkvi-ids), [CHISE project](https://www.chise.org/). The `ids.txt` data follows the CHISE licensing terms, **GNU General Public License version 2 or later**. See local `licenses/GPL-2.0.txt` and `licenses/CJKVI-README.md`. The original UTF-8 source can be downloaded using the URL recorded in the `sources` table and retained in the downloads folder. SanLex's decomposition and reverse component tables derived from this file are distributed under the same terms. The importer source code is supplied with this project.

IDS structures describe glyphs; they are not etymological claims. Regional alternatives are retained. Nested relationship results can combine different regional descriptions; their presence does not imply one universal glyph form. Unknown or missing decompositions are left unknown.

## Wiktionary / Kaikki / Wiktextract

Japanese and Chinese Wiktionary text and translations are by **Wiktionary contributors**, available under **CC BY-SA 4.0** (legacy material may also be available under GFDL). Attribution includes the originating Wiktionary page and its contributor history, linked from each imported entry and direct translation. See [Wikimedia Terms of Use](https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use) and the [Wiktionary copyright information](https://en.wiktionary.org/wiki/Wiktionary:Copyrights).

The machine-readable datasets are provided by Tatu Ylonen and contributors at [Kaikki.org](https://kaikki.org/), extracted with [Wiktextract](https://github.com/tatuylonen/wiktextract). Data editions: [Japanese](https://kaikki.org/jawiktionary/rawdata.html), [Chinese](https://kaikki.org/zhwiktionary/rawdata.html). Reference: Tatu Ylonen, “Wiktextract: Wiktionary as Machine-Readable Structured Data,” LREC 2022, pp. 1317–1325. Only JP, CN (zh/cmn), and EN word records and translation links are imported. Other languages, media files, and most editorial fields are omitted. Definitions, examples, and translation sense labels are preserved; dictionary entries are indexed and linked by headword. Extraction errors and omissions are possible.

## Tatoeba / Tanaka example sentences

Sentence text is by **Tatoeba contributors**, distributed under **[Creative Commons Attribution 2.0 France](https://creativecommons.org/licenses/by/2.0/fr/)**; a subset is also available under CC0. See [Tatoeba downloads](https://tatoeba.org/en/downloads) and [reuse guidance](https://en.wiki.tatoeba.org/articles/show/using-the-tatoeba-corpus). Contributor names, sentence IDs and original sentence links are retained and displayed for the source and each available translation. Sentences whose contributor field is empty link to the original attribution page. JMdict embedded examples retain their Tatoeba ID; contributor information is resolved against the installed corpus where available. Dictionary examples from Wiktionary retain their source page, source meaning and supplied citation.

The import uses Japanese (`jpn`) and Mandarin (`cmn`) detailed sentence exports, English (`eng`) detailed sentences directly linked to those languages, and the `jpn-eng`, `cmn-eng`, `jpn-cmn` direct link exports. Original URLs are under `https://downloads.tatoeba.org/exports/per_language/`. The six cached files, their SHA-256 hashes and selection details are recorded in `tatoeba-manifest.json` and installed source metadata. Sentences longer than 1,000 characters are excluded. The bundled snapshot contains 613,083 sentences. The SQLite text index and translation-link tables are derived from these exports; `sanlex/examples.py` supplies the importer and lookup implementation.

Sentences are matched by spelling and English word boundaries; those matches do not establish the intended dictionary sense. English sentences are a selected linked subset, not the entire English export. Translations follow direct contributor links, without inferred translations through a third language. Source examples, wording, original scripts and available translations are preserved; corpus quality and coverage vary. All lookups are offline; updates are explicitly requested through the source manager.

## Derived search data

Derived SQLite search tables follow the respective source-data licences. These notices must accompany redistributed data. Search indexes are generated by the included importer code, which is available under the application's MIT licence; this does not change source-data licences.

## AnimCJK regional stroke and character data

[AnimCJK](https://github.com/parsimonhi/animCJK), copyright 2016–2026 FM&SH, supplies separate Japanese, mainland Simplified Chinese and Taiwan Traditional Chinese glyph records. The bundled revision is `3e1253b341cc7be14c3540bb3c045e6163557777`. Graphics derive from the Arphic PL KaitiM GB and Big5 fonts (Arphic Technology Co., Ltd., copyright 1999) and [Make Me a Hanzi](https://github.com/skishore/makemeahanzi). Character metadata also derives from Unicode Unihan. Upstream copyright notices are in `licenses/AnimCJK-COPYING.txt`.

The `graphics*.txt` stroke outlines and medians, and their compressed records in `assets/strokes/characters.sqlite3`, are redistributed under the **Arphic Public License**, included unaltered at `licenses/AnimCJK-Arphic-Public-License.txt`. The `dictionary*.txt` metadata and derived regional component index are under **LGPL v3 or later**, included at `licenses/LGPL-3.0.txt`. This separate dataset retains these terms independently of the application's MIT code. It is provided without warranty and may be redistributed under the included licences.

SanLex converts the original records into a compressed SQLite container and indexes component leaves from their decompositions. The original text files are included unmodified in `assets/strokes/originals/`; revision, SHA-256 hashes, modification date and changes are recorded in `assets/strokes/manifest.json` and the SQLite `provenance` table. The build script is `scripts/install_strokes.py`. The native Qt renderer reads those paths, flips their coordinate system for display, and progressively reveals strokes along their medians. Stroke data is bundled for offline use and updated with the application.

The derived `assets/strokes/handwriting.json.zlib` index contains normalized, resampled stroke medians and shape features for offline handwriting matching, under the same **Arphic Public License** as its source medians. Its embedded metadata records the source SQLite file's SHA-256 digest. Regenerate it with `scripts/build_handwriting.py`; the transformation is implemented in `sanlex/handwriting.py`. No external recognizer code or trained model is bundled. Matching is approximate and does not establish a character's language or guarantee handwriting accuracy.

Coverage is 7,336 Japanese, 8,244 Simplified Chinese and 1,513 Traditional Chinese glyphs, including components. Traditional Chinese coverage is incomplete and represents Taiwan conventions; it does not claim to cover every traditional-writing region. Missing regional animations are explicitly identified, with a labelled font preview. No animation from another regional set is silently substituted. IDS fallback relationships are labelled as regional or shared / unspecified.

## Runtime dependencies

- **Qt / PySide6 / Shiboken6**: The Qt Company and contributors; used under LGPL v3. The desktop distribution uses separate dynamic Qt libraries. [Qt for Python licensing](https://doc.qt.io/qtforpython-6/licenses.html). Local LGPL v3 and GPL v3 texts are in `licenses/`. The application source and build instructions are supplied so users can modify the application and use compatible replacement libraries. Do not remove dependency copyright and licence files from the distribution.
- **Python**: Python Software Foundation Licence. [Python licence](https://docs.python.org/3/license.html).
- **SQLite**: public domain. [SQLite copyright](https://www.sqlite.org/copyright.html).
- **PyInstaller**: GPL v2 or later with the bootloader exception allowing bundled applications under other licences. [PyInstaller licence](https://pyinstaller.org/en/stable/license.html).

## Coverage and mapping limits

Direct Wiktionary translation links retain their sense labels; they are not guarantees that every sense of the source headword matches the target entry. Localized definitions are matched by spelling and language, and can represent different senses. Suggested JP↔CN matches use shared English glosses, not a translation model, and are visibly labelled. No complete Japanese–Chinese sense-aligned lexicon is claimed. English lookup searches English definitions and English Wiktionary headwords; romaji support is basic Hepburn, not Japanese morphological analysis. Pinyin accepts tone numbers and unmarked / tone-marked forms. Simplified and traditional forms are searched when the upstream entry supplies both; Japanese shinjitai is not globally treated as simplified Chinese. Missing data is never invented.
