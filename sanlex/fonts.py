"""Regional font preferences for shared Han code points (no spelling conversion)."""
from PySide6.QtGui import QFont


FONT_FAMILIES = {
    'cn': ('Microsoft YaHei UI', 'Microsoft YaHei', 'PingFang SC',
           'Noto Sans CJK SC', 'Noto Sans SC', 'SimSun'),
    'jp': ('Yu Gothic UI', 'Yu Gothic', 'Meiryo', 'Hiragino Sans',
           'Noto Sans CJK JP', 'Noto Sans JP'),
    'hant': ('Microsoft JhengHei UI', 'Microsoft JhengHei', 'PingFang TC',
             'Noto Sans CJK TC', 'Noto Sans TC'),
    'en': ('Segoe UI', 'Arial'),
}


def font_language(language):
    language = {'ja': 'jp', 'hans': 'cn'}.get(language, language)
    return language if language in FONT_FAMILIES else 'en'


def font_families(language):
    return FONT_FAMILIES[font_language(language)]


def font_style(language):
    return 'font-family:' + ','.join(f"'{name}'" for name in font_families(language)) + ';'


def language_html(markup, language):
    """Wrap already escaped/generated markup with its own regional font."""
    return f'<span class="font-{font_language(language)}" style="{font_style(language)}">{markup}</span>'


# Qt reapplies inherited body styles to anchors. Target descendants explicitly
# so links inside a regional span retain that span's font as well.
REGIONAL_FONT_CSS = '\n'.join(
    f'.font-{lang}, .font-{lang} a, .font-{lang} span {{{font_style(lang)}}}'
    for lang in FONT_FAMILIES)


def entry_font(language, base):
    font = QFont(base)
    font.setFamilies(list(font_families(language)))
    return font
