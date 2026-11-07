"""Cached Chinese translations of public headlines and summaries."""
import hashlib
import json
import re
import sqlite3
import threading
from contextlib import closing
from queue import Queue, Empty

import requests

from data_service import configured_proxy

SEPARATOR='\n@@@\n'


class TranslationStore:
    def __init__(self, path):
        self.path=path
        self.lock=threading.Lock()
        with closing(sqlite3.connect(self.path)) as con:
            con.execute('CREATE TABLE IF NOT EXISTS translations (key TEXT PRIMARY KEY, original TEXT NOT NULL, chinese TEXT NOT NULL)')

    @staticmethod
    def key(text):
        return hashlib.sha256(text.encode('utf-8')).hexdigest()

    def get(self,text):
        if not text:return ''
        if re.search(r'[\u4e00-\u9fff]',text):return text
        with self.lock,closing(sqlite3.connect(self.path)) as con:
            row=con.execute('SELECT chinese FROM translations WHERE key=?',(self.key(text),)).fetchone()
        return row[0] if row else None

    def get_many(self,texts):
        unique=list(dict.fromkeys(text for text in texts if text))
        result={text:text for text in unique if re.search(r'[\u4e00-\u9fff]',text)}
        pending=[text for text in unique if text not in result]
        with self.lock,closing(sqlite3.connect(self.path)) as con:
            for text in pending:
                row=con.execute('SELECT chinese FROM translations WHERE key=?',(self.key(text),)).fetchone()
                if row:result[text]=row[0]
        return result

    def save(self,original,chinese):
        if not chinese or chinese==original:return
        with self.lock,closing(sqlite3.connect(self.path)) as con:
            con.execute('INSERT OR REPLACE INTO translations VALUES (?,?,?)',(self.key(original),original,chinese))
            con.commit()

    def translate_group(self,texts,config):
        if not texts:return []
        query=SEPARATOR.join(texts)
        response=requests.get('https://translate.googleapis.com/translate_a/single',
                              params={'client':'gtx','sl':'auto','tl':'zh-CN','dt':'t','q':query},
                              proxies=configured_proxy(config,for_google=True),timeout=(5,18))
        response.raise_for_status()
        payload=json.loads(response.content.decode('utf-8'))
        translated=''.join(part[0] for part in payload[0] if part and part[0])
        parts=translated.split(SEPARATOR)
        if len(parts)!=len(texts):
            raise ValueError('翻译批次边界发生变化')
        return [part.strip() for part in parts]

    def translate_missing(self,texts,config,progress=None):
        unique=list(dict.fromkeys(text for text in texts if text))
        known=self.get_many(unique)
        pending=[text for text in unique if text not in known]
        done=0
        groups=[pending[start:start+5] for start in range(0,len(pending),5)]
        def process(group):
            try:
                return group,self.translate_group(group,config)
            except ValueError:
                translations=[]
                for text in group:
                    try:translations.extend(self.translate_group([text],config))
                    except (requests.RequestException,ValueError,KeyError,TypeError):translations.append('')
                return group,translations
            except (requests.RequestException,KeyError,TypeError):
                return group,['']*len(group)
        jobs=Queue();results=Queue()
        for group in groups:jobs.put(group)
        def worker():
            while True:
                try:group=jobs.get_nowait()
                except Empty:return
                results.put(process(group))
        for _ in range(min(5,len(groups))):
            threading.Thread(target=worker,daemon=True).start()
        for _ in groups:
            group,translations=results.get()
            for original,chinese in zip(group,translations):
                self.save(original,chinese)
                if chinese:done+=1
            if progress:progress(done,len(pending))
        return done,len(pending)

    def translate_one(self,text,config):
        cached=self.get(text)
        if cached is not None:return cached
        try:
            translated=self.translate_group([text],config)[0]
            self.save(text,translated)
            return translated or text
        except (requests.RequestException,ValueError,KeyError,TypeError):
            return text
