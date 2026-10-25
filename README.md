# SanLex · 三言辞典

A Windows desktop dictionary for Japanese, English and Chinese, built with Python, Qt / PySide6, and SQLite. It also runs from source on macOS and Linux. Searches stay on your device; no account or API key is needed.

## Run on Windows

Open **`dist/SanLex/SanLex.exe`**. Keep the whole `SanLex` folder together: the executable depends on its `_internal` folder. The full build includes an offline dictionary snapshot. On first launch, SanLex copies that snapshot to `%LOCALAPPDATA%\SanLex\dictionary.sqlite3`; this can take a few seconds. Bookmarks and history live separately in `user.sqlite3`, and survive dictionary updates. The application is a portable folder, not an installer, and the executable is unsigned.

Windows builds isolate DLL discovery from other programs on `PATH` and then launch the actual packaged executable against a temporary empty database to check that Qt loads and renders a window. A failed launch makes the build fail. Run this check separately with `.venv\Scripts\python.exe scripts\smoke_build.py dist\SanLex\SanLex.exe`.

For development, double-click `Start SanLex.cmd`, or run:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m sanlex
```

Python 3.11+ is required when running from source. Without a bundled full database, install dictionaries through **Dictionaries & sources → Download / update selected**. You can import original downloaded `.gz`, `.zip`, and IDS `.txt` files from the same dialog.

## Why it works before downloading dictionaries

The full Windows build already includes the prepared dictionaries. Its first launch copies the bundled database to your local data folder; it does not download it from the internet. All dictionary searches use that installed local database. There is no online lookup fallback or automatic update.

**Dictionaries & sources** shows the number installed at the top and an explicit **INSTALLED · Ready offline** or **NOT INSTALLED** status for each source, with record counts. The checkboxes only select which dictionaries to download or update; an unchecked box does not mean a dictionary is missing. **Cached download** refers to an optional original archive retained after a manual download. A dictionary can be installed and fully usable without any cached archive. The window also shows the database location and an **Open data folder** button.

Internet access happens when you explicitly request a download / update, or follow an external source link. Local file imports use the file you choose. **Download latest files** forces a fresh download; with it unchecked, the updater reuses cached source files when available and downloads any missing files after you request the update.

## What to explore

- Search Japanese, English or Chinese, including kana, basic Hepburn romaji, numeric / tone-marked / unmarked pinyin, and supplied simplified / traditional spellings. Use the language dropdown to filter entry language; English searches also find meanings in Japanese and Chinese dictionaries.
- As you type, up to ten suggestions show matching words and readings with a brief definition. Click one, or use **Up / Down** then **Enter / Tab**, to open it. **Esc** hides suggestions; **Enter** with no suggestion selected, or **Search**, searches your original text. Suggestions match spelling / reading prefixes, respect the language, dictionary and direction filters, and wait until IME composition finishes. Full meaning searches and example loading run after you submit or select a word, keeping typing lightweight.
- Select a word for definitions and mappings. **JP → EN** identifies a Japanese entry with English definitions; **JP → CN** identifies one with Chinese definitions. Source-linked Wiktionary translations appear alongside labelled shared-English suggestions. Click a translation to inspect its entry or search for it.
- Entries use regional fonts so shared Han characters have Chinese glyphs in CN entries and Japanese glyphs in JP entries. Translations and examples use their own language's font. Windows prefers Microsoft YaHei UI for Chinese and Yu Gothic UI for Japanese; other platforms use available regional fonts from the fallback lists.
- In the character analyser, the Japanese tab follows recorded simplified/traditional links when the input has no Japanese data, choosing forms with installed Japanese readings or stroke data (for example, 务 → 務). Shared Japanese forms such as 学 stay unchanged; ambiguous matches remain selectable.
- Click any kanji / hanzi in a word to open the **Character explorer**. It shows Japanese on / kun / name readings, Mandarin / Cantonese readings, stroke counts, indexing radicals, glyph decompositions, and simplified / traditional / semantic variants when supplied by the source.
- **Part of** is a reverse component index: explore **弟** to find **梯**, then follow **木** into other characters. Toggle **Include nested parts** to include transitive relationships. Example: 木 is directly in 林 and nested inside 森. Radicals and visual components are separate sections.
- Save entries with **☆ Save word**, revisit recent searches, and export saved words as an Excel-friendly UTF-8 CSV. **Ctrl+L** focuses the search box. Selecting a recent search puts that query in the search box, searches again using the current filters, and opens the dictionary entry you last selected for that query. If that entry is unavailable, the first matching entry opens; a single kanji / hanzi with no matching entries opens its Character explorer. Older history without a saved entry follows the same fallback. Recent searches do not restore an unrelated search or an old explorer navigation state.
- Broad searches have a **Show more results** button. Character parent lists and containing-word lists also have controls to reveal more matches.
- Use **← Back** / **Forward →**, or **Alt+Left** / **Alt+Right**, to retrace entry links, translations and character details. Navigation restores your scroll position, search results, language filter and character options. Opening a new page after going Back replaces the Forward path. Navigation history is kept for the current app session.

## Example sentences

Each word entry has an **Example sentences** section below its primary definitions. It shows examples embedded in the current entry, Tatoeba sentences containing the spelling, and examples from matching Wiktionary entries. Each dictionary example retains its source meaning; related entries can use a different sense. Examples can be short phrases as well as full sentences. **Show more examples** expands the groups, and kanji / hanzi inside examples remain clickable for character analysis.

The Japanese source is now **JMdict_e_examp.gz**, preserving the same stable entry IDs and bookmarks while adding Japanese / English example pairs to 28,930 entries in the bundled snapshot. Existing Wiktionary examples are surfaced alongside JMdict and CC-CEDICT entries, respecting the selected dictionaries and definition directions.

The bundled **Tatoeba** corpus contains **613,083 sentences**: 248,939 Japanese, 89,190 Mandarin Chinese and 274,954 English. Japanese and Mandarin exports are imported up to 1,000 characters per sentence; English is limited to sentences directly linked to those languages. The index matches literal spellings, with English word boundaries, and preserves supplied simplified / traditional text. Inflected Japanese forms may need another lookup; the corpus does not establish that a sentence uses the current dictionary meaning. Translation lines follow published direct links; a shared English translation does not create an inferred JP–CN pair. The original sentence and its translations link to Tatoeba with available contributor names. Coverage and translation quality vary.

The **Tatoeba example sentences** checkbox in Search filters controls corpus examples separately from word dictionaries; its state is remembered and restored by Back / Forward. Direction filters restrict the languages of corpus translations. **Dictionaries & sources** shows corpus installation status and cached source files. Download / update Tatoeba manually there, or import `tatoeba-manifest.json` with its adjacent `tatoeba/` folder containing all six listed `.bz2` exports. Updates are transactional and preserve the previous corpus on failure or cancellation. Searching and viewing examples uses local data exclusively.

## Character analysis and animated strokes

### Handwriting lookup

Click **✎ Handwriting** beside the example searches, or press **Ctrl+H**, when you know what a kanji / hanzi looks like but cannot type it. Draw one character with the mouse, pen or touch, lifting between strokes. Possible matches update after a short pause. **Undo stroke** removes the last stroke and **Clear** starts again. Select a match and choose **Look up character**, or double-click it, to search and open its character analysis. **Insert into search** inserts at the search cursor (replacing selected text) and clears the pad so you can build a word one character at a time; press **Search** when ready.

**All scripts** matches the combined Simplified Chinese, Traditional Chinese and Japanese kanji datasets and shows each codepoint once. Separate script modes restrict matching to that regional set; the selected mode is remembered. These modes control handwriting candidates independently of dictionary search filters. Candidate tooltips name the matching template's region; a shared character does not uniquely identify a language. The combined pack covers **10,870 distinct characters**, including components. Simplified mode has 8,244 templates, Japanese 7,336 and Traditional 1,513; use All scripts if a character is missing in a narrower mode. Kana recognition is not included in this pack.

Recognition is an approximate shape match against the bundled AnimCJK stroke medians, not a trained handwriting model. Write clearly and use usual stroke order where possible; cursive, unusual proportions, merged strokes and missing templates can prevent a good match. Suggestions are not confidence guarantees. Everything runs locally in a background thread, without network access, new language packs, accounts or API keys. The derived acceleration index is bundled in `assets/strokes/handwriting.json.zlib`; regenerate it with `.venv\Scripts\python.exe scripts\build_handwriting.py` after editing stroke data. `scripts/install_strokes.py` also rebuilds it when refreshing the pack.

### Character analysis

Click an individual kanji or hanzi in the large entry heading, other spellings, definitions or examples to open its analysis directly. You can also use **Inside the word**, the large character in the atlas, or **Character explorer → Stroke analysis ↗**. The resizable character window stays open while you browse the dictionary. **Simplified Chinese**, **Traditional Chinese**, and **Japanese** tabs select separate regional stroke and component data. Chinese tabs offer recorded Unicode simplified/traditional forms; when several forms are possible, use **Character form** to choose. Japanese keeps the selected codepoint, rather than assuming every traditional character has an interchangeable Japanese form.

Use **Play / Pause**, restart, previous / next stroke, **End**, the position slider and speed control to study the animation. Toggle grid, stroke numbers, outline guide and loop. The **Parts / Part of** tab shows **Parts** on the left and **Part of** on the right, with a draggable divider and independent scrolling. Both panes provide clickable character links. **Words containing this character** remains a separate tab. **Include nested parts** adds transitive relationships. The window has its own **Back / Forward** history and Alt+Left / Alt+Right shortcuts. **Copy** copies the displayed character; **Full explorer** shows the main atlas.

Japanese mode lists Japanese words. Chinese modes use their corresponding CC-CEDICT spelling; other Chinese headwords retain their source spelling, with recognisable opposite-script forms excluded. Your word dictionary and definition-direction filters apply to the word list. Character strokes, readings, radicals and structural relationships remain available independently.

The bundled AnimCJK pack provides **7,336 Japanese**, **8,244 Simplified Chinese** and **1,513 Traditional Chinese** glyph animations, including some components. Traditional mode uses the Taiwan dataset, Simplified mode the mainland dataset. No regional stroke data is substituted when missing; a grey font preview and an explicit message appear instead. Mainland, Taiwan, Hong Kong and Japanese conventions can differ. The interface shows the actual number of strokes in the selected animation, rather than assuming a shared Unicode stroke count. Components prefer the matching AnimCJK decomposition; other characters use region-matching IDS records or clearly labelled shared / unspecified records. Coverage and source analyses differ; glyph structure is not etymology.

The pack is entirely offline, lives in `assets/strokes/` (under `_internal` in Windows builds), and is updated with the application. **Dictionaries & sources** lists its installed coverage. Rebuild it explicitly with `.venv\Scripts\python.exe scripts\install_strokes.py`; pinned upstream revision, original files, hashes, provenance and licences are included. It does not require Qt WebEngine, browser access or an online API.

## Filter by dictionary and translation direction

The **Search filters** panel selects individual dictionary files and translation directions. Use the **Filters** button beside the search box to show or hide it. Each dictionary lists its actual filename and word-entry count; unavailable dictionaries are greyed out. Each group has **All** and **None**, and **Reset all filters** restores every word dictionary/direction and clears the language dropdown restriction.

Directions mean **headword language → definition language**: **EN → JP** finds English headwords with Japanese definitions, **JP → JP** finds Japanese headwords with Japanese definitions, and **JP → EN** finds Japanese headwords with English definitions. This follows the direction labels on result entries, regardless of which script you typed. Greyed-out directions have no entries in the selected dictionaries; hover for counts. JMdict's reverse English-meaning lookup still returns **JP → EN** entries.

Dictionary, direction and language restrictions apply together, before the result limit. They also apply when loading more results, to saved words and their CSV export, and to related definitions, translations and containing-word lists. Related translations use the current headword language → translation language. Following a link opens its entry normally. KANJIDIC2, Unihan and IDS are character-data files; their readings, radicals and structures remain available in the explorer. Selections are remembered across launches, and Back / Forward restores the filters belonging to each visited page.

## Dictionary coverage

The full snapshot is generated from:

| Source | Purpose |
| --- | --- |
| JMdict_e_examp | Japanese words, kana, English senses, reading / spelling restrictions and embedded examples |
| CC-CEDICT | Chinese words, simplified / traditional forms, Mandarin pinyin, English definitions |
| KANJIDIC2 | Japanese character readings, radicals, stroke counts and school grades |
| Unicode Unihan 17.0 | Han character definitions, readings, radical / stroke metadata and variants |
| CJKVI / CHISE IDS | Character structures and reverse component relationships |
| Japanese Wiktionary via Kaikki | Japanese-language definitions for JP / CN / EN and direct translations |
| Chinese Wiktionary via Kaikki | Chinese-language definitions for JP / CN / EN and direct translations |
| Tatoeba | Offline JP / CN / linked EN sentences, direct translations and contributor attribution |

Counts are **entries, not distinct words**: different sources, languages, parts of speech, and senses may create separate entries. There is no claim of exhaustive vocabulary or complete sense-aligned JP↔CN coverage. Not every word has definitions in all three languages. Direct translations, localized headword matches and automatic English-gloss suggestions are distinguished in the interface. Regional IDS alternatives are preserved; visual decomposition is not etymology. Rare Han glyphs require fonts that cover their Unicode ranges.

Source attribution, licence terms and limitations are available inside the app and in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Downloads are manual and go directly to their publishers; no search text is sent. A full first install downloads approximately 360 MB of compressed data. Allow at least 8 GB of free storage for the portable application, writable dictionary copy, download caches, and import transaction space. Exact sizes vary as sources change. Installation uses worker threads and each source imports transactionally; a failed or cancelled import preserves that source's previous installed data.

## Command line and development

```powershell
# Keep development data inside this project:
.\.venv\Scripts\python.exe -m sanlex --home .\local-data

# Download and index all sources (or select individual source IDs):
.\.venv\Scripts\python.exe -m sanlex --home .\local-data --install-data
.\.venv\Scripts\python.exe -m sanlex --home .\local-data --install-data --sources jmdict cedict ids --refresh

# Tests, including GUI interactions in Qt's offscreen mode:
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

# Build the portable Windows folder; include a full snapshot when available:
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe scripts\build.py --database local-data\dictionary.sqlite3

# Build a separate updated copy while the existing app remains open:
.\.venv\Scripts\python.exe scripts\build.py --database local-data\dictionary.sqlite3 --reuse-snapshot --dist-dir dist\updated

# Smaller build, dictionaries installed separately:
.\.venv\Scripts\python.exe scripts\build.py
```

Set `SANLEX_HOME` or pass `--home` to change the writable data folder. The portable executable also accepts these options. Database updates never replace `user.sqlite3`. Cached downloads live in `<home>/downloads/`; **Fetch fresh files** bypasses them. The source table records installed time, URL, record count and the source file's SHA-256 digest. The snapshot and its derived indexes can be regenerated with the included importers; no proprietary database is required. `scripts/reindex.py --home local-data` rebuilds search and Wiktionary translation indexes after changes to normalization rules, using cached Wiktionary files.

Implementation: `sanlex/db.py` owns SQLite queries, `sanlex/importers.py` handles upstream formats, `sanlex/text.py` handles normalization and IDS parsing, and `sanlex/ui.py` contains the Qt interface. GUI search and downloads run in background threads with separate SQLite connections. Stale search results are discarded. Code is MIT-licensed; dictionary data keeps its respective source licence.
