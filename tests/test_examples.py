import bz2
import gzip
import json
from pathlib import Path
import tempfile
import threading
import unittest

from sanlex.db import Dictionary
from sanlex.examples import FILES, corpus_examples, dictionary_examples
from sanlex.importers import Cancelled, install_source


class ExampleTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.root=Path(self.directory.name)
        self.db=Dictionary(self.root/'dictionary.sqlite3')
        self.db.initialize()
        folder=self.root/'tatoeba'
        folder.mkdir()
        records={
            FILES[0]:'1\tjpn\t学校に行く。\tJapaneseAuthor\tdate\tdate\n4\tjpn\t学校は大きい。\tAuthor2\tdate\tdate\n',
            FILES[1]:'2\tcmn\t我去学校。\tChineseAuthor\tdate\tdate\n',
            FILES[2]:'3\teng\tI go to school.\tEnglishAuthor\tdate\tdate\n5\teng\tHe goes.\tOtherAuthor\tdate\tdate\n6\teng\tThe school is big.\tOtherAuthor\tdate\tdate\n7\teng\tUnlinked English.\tOtherAuthor\tdate\tdate\n',
            FILES[3]:'1\t3\n4\t6\n1\t5\n',FILES[4]:'2\t3\n',FILES[5]:'1\t2\n'}
        for name,content in records.items():
            (folder/Path(name).name).write_bytes(bz2.compress(content.encode('utf-8')))
        self.manifest=self.root/'manifest.json'
        self.manifest.write_text(json.dumps({'files':FILES}),encoding='utf-8')
        self.entry={'id':'test:school','headword':'学校','forms':['学校','學校'], 'reading':'がっこう',
                    'lang':'jp','definition_lang':'en','source':'jmdict','glosses':['school'],'senses':[{'glosses':['school']}]}
        with self.db.conn:
            self.db.add_entry(self.entry)

    def tearDown(self):
        self.db.close()
        self.directory.cleanup()

    def install(self):
        install_source(self.db,'tatoeba',self.manifest,lambda _:None)

    def test_translations_authors_languages_and_word_boundaries(self):
        self.install()
        examples,_=corpus_examples(self.db,self.entry)
        self.assertTrue(examples)
        first=next(e for e in examples if e['text']=='学校に行く。')
        self.assertEqual(first['author'],'JapaneseAuthor')
        self.assertEqual({t['lang'] for t in first['translations']},{'en','cn'})
        self.assertTrue(all(t['author'] and t['url'].startswith('https://tatoeba.org/') for t in first['translations']))
        english={**self.entry,'headword':'he','forms':['he'],'lang':'en','reading':''}
        found,_=corpus_examples(self.db,english)
        self.assertEqual([e['text'] for e in found],['He goes.'])
        self.assertFalse(self.db.conn.execute("SELECT 1 FROM sentences WHERE text='Unlinked English.'").fetchone())
        japanese,_=corpus_examples(self.db,self.entry,directions=(('jp','en'),))
        self.assertTrue(all(t['lang']=='en' for e in japanese for t in e['translations']))
        self.assertEqual(corpus_examples(self.db,self.entry,directions=()),([],False))

    def test_shared_english_translation_does_not_invent_japanese_chinese_link(self):
        self.install()
        with self.db.conn:
            self.db.conn.execute('DELETE FROM sentence_links WHERE sentence_id=1 AND translation_id=2')
        found,_=corpus_examples(self.db,self.entry)
        first=next(e for e in found if e['text']=='学校に行く。')
        self.assertEqual({t['lang'] for t in first['translations']},{'en'})

    def test_reimport_and_cancel_are_transactional(self):
        self.install()
        count=self.db.conn.execute('SELECT count(*) FROM sentences').fetchone()[0]
        self.install()
        self.assertEqual(self.db.conn.execute('SELECT count(*) FROM sentences').fetchone()[0],count)
        # Fail after replacement has started to verify actual rollback, not just an early cancellation.
        path=self.root/'tatoeba'/Path(FILES[1]).name
        path.write_bytes(b'not bzip2')
        with self.assertRaises(OSError):
            self.install()
        self.assertEqual(self.db.conn.execute('SELECT count(*) FROM sentences').fetchone()[0],count)
        self.assertTrue(corpus_examples(self.db,self.entry)[0])
        cancel=threading.Event(); cancel.set()
        with self.assertRaises(Cancelled):
            install_source(self.db,'tatoeba',self.manifest,lambda _:None,cancel)

    def test_jmdict_examples_preserve_sense_and_stable_bookmarks(self):
        path=self.root/'jmdict.gz'
        xml='''<JMdict><entry><ent_seq>42</ent_seq><k_ele><keb>学校</keb></k_ele>
            <r_ele><reb>がっこう</reb></r_ele><sense><gloss>school</gloss><example>
            <ex_srce exsrc_type="tat">1</ex_srce><ex_text>学校</ex_text>
            <ex_sent xml:lang="jpn">学校に行く。</ex_sent><ex_sent xml:lang="eng">I go to school.</ex_sent>
            </example></sense><sense><gloss>another sense</gloss></sense></entry></JMdict>'''
        with gzip.open(path,'wt',encoding='utf-8') as stream: stream.write(xml)
        install_source(self.db,'jmdict',path,lambda _:None)
        self.db.toggle_favorite('jmdict:42')
        self.install()
        install_source(self.db,'jmdict',path,lambda _:None)
        entry=self.db.entry('jmdict:42')
        own,_,_=dictionary_examples(self.db,entry)
        self.assertEqual(own[0]['sense'],'school')
        self.assertEqual(own[0]['author'],'JapaneseAuthor')
        self.assertEqual(own[0]['translations'][0]['author'],'EnglishAuthor')
        self.assertEqual(entry['senses'][1]['examples'],[])
        self.assertTrue(self.db.is_favorite('jmdict:42'))

    def test_related_wiktionary_examples_follow_filters_and_are_deduplicated(self):
        with self.db.conn:
            for source,language in [('wiktionary-ja','jp'),('wiktionary-zh','cn')]:
                self.db.add_entry({**self.entry,'id':source+':school','source':source,'definition_lang':language,
                    'senses':[{'glosses':['meaning from another dictionary'],'source_url':'https://example.org/entry',
                               'examples':[{'text':'学校に行く。','translation':'translation'}]}]})
        own,related,_=dictionary_examples(self.db,self.entry)
        self.assertEqual(own,[])
        self.assertEqual(len(related),1)
        self.assertEqual(related[0]['sense'],'meaning from another dictionary')
        self.assertEqual(dictionary_examples(self.db,self.entry,sources=('jmdict',))[1],[])
        self.assertEqual(dictionary_examples(self.db,self.entry,directions=(('jp','en'),))[1],[])


if __name__=='__main__':
    unittest.main()
