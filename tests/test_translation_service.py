import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from translation_service import TranslationStore


class TranslationTests(unittest.TestCase):
    def test_cache_and_chinese_passthrough(self):
        with tempfile.TemporaryDirectory() as folder:
            store=TranslationStore(Path(folder)/'translation.sqlite3')
            self.assertEqual(store.get('中文新闻'),'中文新闻')
            self.assertIsNone(store.get('Oracle earnings'))
            store.save('Oracle earnings','甲骨文财报')
            self.assertEqual(store.get('Oracle earnings'),'甲骨文财报')

    def test_missing_texts_are_translated_once(self):
        with tempfile.TemporaryDirectory() as folder:
            store=TranslationStore(Path(folder)/'translation.sqlite3')
            with patch.object(store,'translate_group',return_value=['甲骨文财报']) as mocked:
                store.translate_missing(['Oracle earnings','Oracle earnings'],{})
                store.translate_missing(['Oracle earnings'],{})
            mocked.assert_called_once()


if __name__=='__main__':unittest.main()
