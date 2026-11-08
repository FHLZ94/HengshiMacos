import threading, time, json, os, re, queue, sqlite3, webbrowser, logging, sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import quote

import requests
import data_service
import securities
import tempfile

APP_DIR = (Path(os.environ['HENGSHI_DATA_DIR']) if os.environ.get('HENGSHI_DATA_DIR') else
           Path.home() / 'Library' / 'Application Support' / '衡势' if sys.platform == 'darwin' else
           Path(os.getenv('APPDATA', str(Path.home()))) / 'AIMarketIntelligence')
APP_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(filename=str(APP_DIR / 'application.log'), level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(message)s', encoding='utf-8')
DB = APP_DIR / 'events.sqlite3'
APP_VERSION = '1.3.0'
CONFIG = APP_DIR / 'settings.json'
ICON = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / 'nexus.ico'
DEFAULT_WATCHLIST = list(securities.DEFAULT_TRACKING)
FEEDS = [
    ('Google News · World Markets', 'https://news.google.com/rss/search?q=global+markets+OR+Federal+Reserve+OR+Treasury+OR+tariffs&hl=en-US&gl=US&ceid=US:en'),
    ('Google News · AI Infrastructure', 'https://news.google.com/rss/search?q=AI+datacenter+capex+OR+cloud+compute+OR+semiconductor+orders&hl=en-US&gl=US&ceid=US:en'),
    ('Google News · Geopolitics', 'https://news.google.com/rss/search?q=US+China+trade+export+controls+OR+geopolitical+risk&hl=en-US&gl=US&ceid=US:en'),
    ('Federal Reserve · Press Releases', 'https://www.federalreserve.gov/feeds/press_all.xml'),
    ('SEC · Press Releases', 'https://www.sec.gov/news/pressreleases.rss'),
    ('Google News · Semiconductor Leaders', 'https://news.google.com/rss/search?q='+quote('NVIDIA OR AMD OR TSMC OR ASML earnings guidance export controls')+'&hl=en-US&gl=US&ceid=US:en'),
    ('Google News · AI Compute Leaders', 'https://news.google.com/rss/search?q='+quote('Broadcom OR Marvell OR Intel OR Micron AI chip datacenter guidance')+'&hl=en-US&gl=US&ceid=US:en'),
    ('Google News · Optical Interconnect', 'https://news.google.com/rss/search?q='+quote('Coherent OR Lumentum OR Arista optical interconnect datacenter')+'&hl=en-US&gl=US&ceid=US:en'),
    ('Google News · Memory Leaders', 'https://news.google.com/rss/search?q='+quote('SK Hynix OR Samsung OR Micron HBM memory AI')+'&hl=en-US&gl=US&ceid=US:en'),
    ('New York Times · Business', 'https://rss.nytimes.com/services/xml/rss/nyt/Business.xml'),
    ('Bloomberg · Markets', 'https://feeds.bloomberg.com/markets/news.rss'),
    ('Seeking Alpha · Market Currents', 'https://seekingalpha.com/market_currents.xml'),
    ('Investing · Markets', 'https://www.investing.com/rss/news_25.rss'),
    ('Google News · CNBC Tech', 'https://news.google.com/rss/search?q='+quote('site:cnbc.com/technology AI OR semiconductor OR data center')+'&hl=en-US&gl=US&ceid=US:en'),
    ('Google News · Reuters Markets', 'https://news.google.com/rss/search?q='+quote('site:reuters.com/markets AI chip OR Fed OR policy')+'&hl=en-US&gl=US&ceid=US:en'),
]

POS = {'beats','raise','raised','upgrade','surge','growth','record','strong','accelerate','demand','订单','增长','上调','突破','创新高','扩产','合作','获批','盈利'}
NEG = {'miss','cut','cuts','downgrade','delay','cancel','cancellation','lawsuit','probe','investigation','default','dilution','offering','selloff','warning','weak','decline','drop','暂停','取消','下调','调查','制裁','暴跌','减持','增发','融资','违约','裁员'}
HIGH = {'halt','cancel','cancellation','default','bankruptcy','sanction','export control','war','emergency','fraud','restatement','guidance cut','订单取消','出口管制','制裁','违约','破产'}
HIGH.update({'moratorium','ai development halt','ai pause','export ban'})
NEG.update({'moratorium','halt','ban','restriction'})
MED = {'earnings','guidance','capex','acquisition','merger','offering','dilution','regulation','fed','rate','cpi','就业','财报','指引','资本开支','收购','增发','利率'}


def init_db():
    with sqlite3.connect(DB) as con:
        con.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, title TEXT, link TEXT UNIQUE, source TEXT, published TEXT, summary TEXT, impact TEXT, sentiment INTEGER, label TEXT, tickers TEXT, first_seen TEXT)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_seen ON events(first_seen)")
        con.execute("CREATE TABLE IF NOT EXISTS quote_cache (ticker TEXT PRIMARY KEY, payload TEXT NOT NULL, fetched_at TEXT NOT NULL)")
        con.execute("CREATE TABLE IF NOT EXISTS source_health (source TEXT PRIMARY KEY, payload TEXT NOT NULL, checked_at TEXT NOT NULL)")
        con.execute("CREATE TABLE IF NOT EXISTS positions (ticker TEXT PRIMARY KEY, quantity REAL NOT NULL CHECK(quantity > 0), cost REAL NOT NULL CHECK(cost >= 0), updated_at TEXT NOT NULL)")
        con.execute("CREATE TABLE IF NOT EXISTS estimate_cache (ticker TEXT PRIMARY KEY, payload TEXT NOT NULL, fetched_at TEXT NOT NULL)")
        con.execute("CREATE TABLE IF NOT EXISTS valuation_history (ticker TEXT NOT NULL, period TEXT NOT NULL, observed_date TEXT NOT NULL, price REAL NOT NULL, eps REAL NOT NULL, pe REAL NOT NULL, PRIMARY KEY(ticker,period,observed_date))")
        con.execute("CREATE TABLE IF NOT EXISTS ntm_valuation_history (ticker TEXT NOT NULL, observed_date TEXT NOT NULL, price REAL NOT NULL, eps REAL NOT NULL, pe REAL NOT NULL, period TEXT NOT NULL, PRIMARY KEY(ticker,observed_date))")
        con.execute("CREATE TABLE IF NOT EXISTS neutral_multiples (ticker TEXT PRIMARY KEY, pe REAL NOT NULL CHECK(pe > 0), updated_at TEXT NOT NULL)")
        con.execute("CREATE TABLE IF NOT EXISTS management_guidance (ticker TEXT PRIMARY KEY, eps REAL NOT NULL CHECK(eps > 0), period TEXT NOT NULL, source_url TEXT NOT NULL, updated_at TEXT NOT NULL)")
        con.execute("CREATE TABLE IF NOT EXISTS history_cache (ticker TEXT PRIMARY KEY, payload TEXT NOT NULL, fetched_at TEXT NOT NULL)")
        con.execute("CREATE TABLE IF NOT EXISTS comparison_cache (ticker TEXT PRIMARY KEY, payload TEXT NOT NULL, fetched_at TEXT NOT NULL)")
        con.execute("CREATE TABLE IF NOT EXISTS event_analysis (link TEXT PRIMARY KEY, payload TEXT NOT NULL, analyzed_at TEXT NOT NULL)")
        con.execute("CREATE TABLE IF NOT EXISTS market_extras (name TEXT PRIMARY KEY, payload TEXT NOT NULL, fetched_at TEXT NOT NULL)")
        con.execute("CREATE TABLE IF NOT EXISTS holding_flags (ticker TEXT PRIMARY KEY, updated_at TEXT NOT NULL)")
        con.execute("CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        con.execute("CREATE TABLE IF NOT EXISTS research_observations (observed_at TEXT NOT NULL, hour_key TEXT NOT NULL, ticker TEXT NOT NULL, event_key TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(hour_key,ticker,event_key))")
        if not con.execute("SELECT 1 FROM app_meta WHERE key='holding_seed_v1'").fetchone():
            when=datetime.now(timezone.utc).isoformat(timespec='seconds')
            for ticker in ('ORCL','SMH','QQQM','MRVL','LITE','AVGO'):
                con.execute('INSERT OR IGNORE INTO holding_flags VALUES (?,?)',(ticker,when))
            con.execute("INSERT INTO app_meta VALUES ('holding_seed_v1','1')")
        columns={row[1] for row in con.execute('PRAGMA table_info(events)')}
        for name in ('grade','credibility','horizon'):
            if name not in columns:
                con.execute(f'ALTER TABLE events ADD COLUMN {name} TEXT')
        if 'publisher' not in columns:
            con.execute('ALTER TABLE events ADD COLUMN publisher TEXT')
        if 'independent_publishers' not in columns:
            con.execute('ALTER TABLE events ADD COLUMN independent_publishers TEXT')
        guidance_columns={r[1] for r in con.execute('PRAGMA table_info(management_guidance)')}
        if 'eps_basis' not in guidance_columns:
            con.execute("ALTER TABLE management_guidance ADD COLUMN eps_basis TEXT DEFAULT 'unspecified'")


def market_regime(quotes, news):
    q = {x['ticker']: x for x in quotes}
    vix = q.get('^VIX', {}).get('price')
    score = 50
    if vix is not None:
        score += -22 if vix >= 35 else -15 if vix >= 28 else -8 if vix >= 22 else (5 if vix < 15 else 0)
    for ticker, weight in [('SPY', 2.0), ('QQQ', 1.5), ('SMH', 1.5)]:
        if ticker in q: score += max(-8, min(8, q[ticker]['change'] * weight))
    breadth = [x['change'] for x in quotes if x['ticker'] != '^VIX']
    up = sum(x > 0 for x in breadth); down = sum(x < 0 for x in breadth)
    if breadth: score += max(-12, min(12, (up-down)/len(breadth)*18))
    avg = sum(x['sentiment'] for x in news)/len(news) if news else 50
    score = max(0, min(100, int(round(score + (avg-50)*0.12))))
    label = '极端恐慌' if score < 20 else '恐慌' if score < 38 else '谨慎' if score < 48 else '中性' if score < 62 else '乐观' if score < 80 else '过度乐观'
    # Coverage is not a probability. No calibrated model has been validated.
    evidence = 0
    if vix is not None: evidence += 25
    if len(breadth) >= 5: evidence += 25
    if q.get('QQQ') and q.get('SMH'): evidence += 25
    if news: evidence += 25
    return {'score':score if evidence else None, 'label':label if evidence else '数据不足', 'vix':vix, 'up':up, 'down':down, 'spy':q.get('SPY',{}).get('change'), 'qqq':q.get('QQQ',{}).get('change'), 'smh':q.get('SMH',{}).get('change'), 'evidence':evidence, 'note':'规则观察分数尚未验证；无数据时不生成市场结论。'}


def save_events(rows):
    with sqlite3.connect(DB) as con:
        for a in rows:
            existing=con.execute('SELECT independent_publishers FROM events WHERE link=?',(a['link'],)).fetchone()
            publishers=set(a.get('independent_publishers') or [])
            if existing:
                try:publishers.update(json.loads(existing[0] or '[]'))
                except ValueError:pass
            con.execute("INSERT INTO events(title,link,source,published,summary,impact,sentiment,label,tickers,first_seen,grade,credibility,horizon,publisher,independent_publishers) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(link) DO UPDATE SET publisher=excluded.publisher, independent_publishers=excluded.independent_publishers",
                (a['title'],a['link'],a['source'],a['published'],a['summary'],a['impact'],a['sentiment'],a['label'],','.join(a['tickers']),datetime.now().astimezone().isoformat(timespec='seconds'),a.get('grade',''),a.get('credibility',''),a.get('horizon',''),a.get('publisher',''),json.dumps(sorted(publishers),ensure_ascii=False)))


def save_snapshot(quotes, health, estimates=(), histories=(), comparisons=()):
    with sqlite3.connect(DB) as con:
        for row in quotes:
            previous=con.execute('SELECT payload FROM quote_cache WHERE ticker=?',(row['ticker'],)).fetchone()
            if previous:
                old=json.loads(previous[0])
                old_day=data_service._quote_date(old.get('asof'))
                new_day=data_service._quote_date(row.get('asof'))
                if old_day and new_day and old_day>new_day:continue
                # A temporary extended-session outage must not roll the screen
                # backwards from a known later trade to the same day's close.
                if old_day==new_day and old.get('session')=='post' and row.get('session') not in ('post',) and row.get('market_status')!='Open':
                    row={**row,**old}
                else:row={**old,**row}
            con.execute('INSERT OR REPLACE INTO quote_cache VALUES (?,?,?)',
                        (row['ticker'], json.dumps(row, ensure_ascii=False), row['fetched_at']))
        for row in health:
            con.execute('INSERT OR REPLACE INTO source_health VALUES (?,?,?)',
                        (row['source'], json.dumps(row, ensure_ascii=False), row.get('checked_at','')))
        quote_map={row['ticker']:row for row in quotes}
        for row in estimates:
            con.execute('INSERT OR REPLACE INTO estimate_cache VALUES (?,?,?)',
                        (row['ticker'],json.dumps(row,ensure_ascii=False),row['fetched_at']))
            q=quote_map.get(row['ticker'])
            if q and row['eps']>0 and row.get('basis')=='ntm_4q':
                con.execute('INSERT OR REPLACE INTO ntm_valuation_history VALUES (?,?,?,?,?,?)',
                            (row['ticker'],datetime.now(timezone.utc).date().isoformat(),
                             q['price'],row['eps'],q['price']/row['eps'],row['period']))
        for row in histories:
            previous=con.execute('SELECT payload FROM history_cache WHERE ticker=?',(row['ticker'],)).fetchone()
            if previous:
                old=json.loads(previous[0])
                bars={b['date']:b for b in old.get('bars',[])}
                bars.update({b['date']:b for b in row.get('bars',[])})
                row={**row,'bars':sorted(bars.values(),key=lambda b:b['date'])}
            con.execute('INSERT OR REPLACE INTO history_cache VALUES (?,?,?)',
                        (row['ticker'],json.dumps(row,ensure_ascii=False),row['fetched_at']))
        for row in comparisons:
            con.execute('INSERT OR REPLACE INTO comparison_cache VALUES (?,?,?)',
                        (row['ticker'],json.dumps(row,ensure_ascii=False),row['fetched_at']))


def load_snapshot(watchlist):
    with sqlite3.connect(DB) as con:
        events = con.execute('SELECT title,link,source,published,summary,impact,sentiment,label,tickers,first_seen,grade,credibility,horizon,publisher,independent_publishers FROM events ORDER BY published DESC, id DESC LIMIT 400').fetchall()
        quote_rows = con.execute('SELECT payload FROM quote_cache').fetchall()
        health_rows = con.execute('SELECT payload FROM source_health').fetchall()
    news = [dict(zip(('title','link','source','published','summary','impact','sentiment','label','tickers','first_seen','grade','credibility','horizon','publisher','independent_publishers'), row)) for row in events]
    for row in news:
        row['tickers'] = [x for x in row['tickers'].split(',') if x]
        row['published'] = data_service.parse_date(row['published'])
        try:row['independent_publishers']=json.loads(row['independent_publishers'] or '[]')
        except ValueError:row['independent_publishers']=[]
    quotes = [json.loads(row[0]) for row in quote_rows if row[0]]
    order = {ticker: i for i, ticker in enumerate(watchlist)}
    quotes = sorted((q for q in quotes if q['ticker'] in order), key=lambda q:order[q['ticker']])
    return news, quotes, [json.loads(row[0]) for row in health_rows if row[0]]


def load_estimates(watchlist):
    with sqlite3.connect(DB) as con:
        rows=con.execute('SELECT payload FROM estimate_cache').fetchall()
    order={ticker:i for i,ticker in enumerate(watchlist)}
    return sorted((item for row in rows if (item:=json.loads(row[0])).get('basis')=='ntm_4q' and item['ticker'] in order),
                  key=lambda row:order[row['ticker']])


def load_histories(watchlist):
    with sqlite3.connect(DB) as con:
        rows=con.execute('SELECT payload FROM history_cache').fetchall()
    order={ticker:i for i,ticker in enumerate(watchlist)}
    return sorted((item for row in rows if (item:=json.loads(row[0]))['ticker'] in order),
                  key=lambda row:order[row['ticker']])


def load_comparisons(watchlist):
    with sqlite3.connect(DB) as con:
        rows=con.execute('SELECT payload FROM comparison_cache').fetchall()
    order={ticker:i for i,ticker in enumerate(watchlist)}
    return sorted((item for row in rows if (item:=json.loads(row[0]))['ticker'] in order),
                  key=lambda row:order[row['ticker']])


def load_neutral_multiples():
    with sqlite3.connect(DB) as con:
        return {row[0]:row[1] for row in con.execute('SELECT ticker,pe FROM neutral_multiples')}


def load_management_guidance():
    with sqlite3.connect(DB) as con:
        return {row[0]:{'ticker':row[0],'eps':row[1],'period':row[2],
                        'source_url':row[3],'updated_at':row[4],'eps_basis':row[5]}
                for row in con.execute('SELECT ticker,eps,period,source_url,updated_at,eps_basis FROM management_guidance')}


def save_event_analysis(link,analysis):
    with sqlite3.connect(DB) as con:
        con.execute('INSERT OR REPLACE INTO event_analysis VALUES (?,?,?)',
                    (link,json.dumps(analysis,ensure_ascii=False),datetime.now(timezone.utc).isoformat(timespec='seconds')))


def load_event_analysis(links=()):
    with sqlite3.connect(DB) as con:
        if links:
            return {link:json.loads(payload) for link,payload in con.execute(
                'SELECT link,payload FROM event_analysis WHERE link IN ('+','.join('?' for _ in links)+')',tuple(links))}
        return {link:json.loads(payload) for link,payload in con.execute('SELECT link,payload FROM event_analysis')}


def save_market_extra(name,payload):
    with sqlite3.connect(DB) as con:
        con.execute('INSERT OR REPLACE INTO market_extras VALUES (?,?,?)',
                    (name,json.dumps(payload,ensure_ascii=False),datetime.now(timezone.utc).isoformat(timespec='seconds')))


def load_market_extra(name):
    with sqlite3.connect(DB) as con:
        row=con.execute('SELECT payload FROM market_extras WHERE name=?',(name,)).fetchone()
    return json.loads(row[0]) if row else None


def save_research_observations(model,risks,quotes,intraday=None):
    if not model or not model.get('available'):return
    import hashlib
    now=datetime.now(timezone.utc);hour=now.replace(minute=0,second=0,microsecond=0).isoformat()
    events=risks.get('events',[])
    minute_key=[(t,[(k,v.get('asof'),v.get('divergence'),v.get('top_divergence')) for k,v in a.get('frames',{}).items()]) for t,a in (intraday or {}).items()]
    identity=json.dumps(([(e['url'],e['stage'],e['direction'],e['verified']) for e in events],minute_key),sort_keys=True)
    event_key=hashlib.sha256((model['date']+identity).encode()).hexdigest()[:24]
    with sqlite3.connect(DB) as con:
        for ticker,target in model.get('targets',{}).items():
            quote=quotes.get(ticker) or {}
            payload={'model_version':model.get('model_version'),'market_day':model['date'],
                'up5_pct':target['up5_pct'],'up3_pct':target['up3_pct'],'setup':target['setup'],
                'risk':risks.get(ticker),'sources':[e['url'] for e in events],
                'quote_price':quote.get('price'),'quote_day':quote.get('asof'),'quote_session':quote.get('session'),
                'intraday':(intraday or {}).get(ticker),
                'endpoint':'历史概率以完整日线收盘为起点；未来新闻模型须按当时可执行时段重新匹配标签'}
            con.execute('INSERT OR IGNORE INTO research_observations VALUES (?,?,?,?,?)',
                        (now.isoformat(),hour,ticker,event_key,json.dumps(payload,ensure_ascii=False)))


def save_management_guidance(ticker,eps,source_url,eps_basis='unspecified'):
    ticker=ticker.strip().upper()
    if not re.fullmatch(r'[A-Z][A-Z0-9.^-]{0,12}',ticker):raise ValueError('证券代码无效')
    if eps<=0 or eps>10000:raise ValueError('未来12个月每股盈利指引必须为正数')
    if not source_url.startswith(('https://','http://')):raise ValueError('请提供管理层原始公告链接')
    if eps_basis not in ('reported','adjusted','unspecified'):raise ValueError('盈利口径无效')
    with sqlite3.connect(DB) as con:
        con.execute('INSERT OR REPLACE INTO management_guidance (ticker,eps,period,source_url,updated_at,eps_basis) VALUES (?,?,?,?,?,?)',
                    (ticker,eps,'未来12个月',source_url,datetime.now(timezone.utc).isoformat(timespec='seconds'),eps_basis))


def save_neutral_multiple(ticker,pe):
    ticker=ticker.strip().upper()
    if not re.fullmatch(r'[A-Z][A-Z0-9.^-]{0,12}',ticker) or not 0<pe<=500:
        raise ValueError('中性 PE 须大于 0 且不超过 500')
    with sqlite3.connect(DB) as con:
        con.execute('INSERT OR REPLACE INTO neutral_multiples VALUES (?,?,?)',
                    (ticker,pe,datetime.now(timezone.utc).isoformat(timespec='seconds')))


def valuation_ranges():
    with sqlite3.connect(DB) as con:
        return {row[0]: {'min':row[1],'max':row[2],'observations':row[3],
                         'first':row[4],'last':row[5]}
                for row in con.execute('SELECT ticker,MIN(pe),MAX(pe),COUNT(*),MIN(observed_date),MAX(observed_date) FROM ntm_valuation_history GROUP BY ticker')}


def one_year_ntm_average():
    cutoff=(datetime.now(timezone.utc)-timedelta(days=365)).date().isoformat()
    with sqlite3.connect(DB) as con:
        rows=con.execute('SELECT ticker,AVG(pe),COUNT(*),MIN(observed_date),MAX(observed_date) FROM ntm_valuation_history WHERE observed_date>=? GROUP BY ticker',(cutoff,)).fetchall()
    result={}
    for ticker,average,count,first,last in rows:
        span=(datetime.fromisoformat(last)-datetime.fromisoformat(first)).days
        result[ticker]={'average':round(average,2) if count>=120 and span>=270 else None,
                        'samples':count,'span_days':span,'first':first,'last':last}
    return result


def load_positions():
    with sqlite3.connect(DB) as con:
        return [{'ticker':row[0], 'quantity':row[1], 'cost':row[2], 'updated_at':row[3]}
                for row in con.execute('SELECT ticker,quantity,cost,updated_at FROM positions ORDER BY ticker')]


def load_holding_flags():
    with sqlite3.connect(DB) as con:
        return {row[0] for row in con.execute('SELECT ticker FROM holding_flags')}


def set_holding_flag(ticker,held):
    ticker=ticker.strip().upper()
    if not re.fullmatch(r'[A-Z][A-Z0-9.^-]{0,12}',ticker):
        raise ValueError('证券代码无效')
    with sqlite3.connect(DB) as con:
        if held:
            con.execute('INSERT OR REPLACE INTO holding_flags VALUES (?,?)',
                        (ticker,datetime.now(timezone.utc).isoformat(timespec='seconds')))
        else:
            con.execute('DELETE FROM holding_flags WHERE ticker=?',(ticker,))


def save_position(ticker, quantity, cost):
    ticker=ticker.strip().upper()
    if not re.fullmatch(r'[A-Z][A-Z0-9.^-]{0,12}',ticker) or quantity<=0 or cost<0:
        raise ValueError('请输入有效代码、正数持仓数量和非负成本')
    with sqlite3.connect(DB) as con:
        con.execute('INSERT OR REPLACE INTO positions VALUES (?,?,?,?)',
                    (ticker,quantity,cost,datetime.now(timezone.utc).isoformat(timespec='seconds')))
        con.execute('INSERT OR REPLACE INTO holding_flags VALUES (?,?)',
                    (ticker,datetime.now(timezone.utc).isoformat(timespec='seconds')))


def delete_position(ticker):
    with sqlite3.connect(DB) as con:
        con.execute('DELETE FROM positions WHERE ticker=?',(ticker,))


def load_settings():
    defaults = {'watchlist':list(DEFAULT_WATCHLIST), 'refresh_seconds': 300, 'openai_base_url':'http://localhost:11434/v1', 'openai_model':'qwen3:4b', 'openai_api_key':'', 'http_proxy':'', 'https_proxy':'', 'auto_local_proxy':True}
    if CONFIG.exists():
        try:
            loaded={**defaults, **json.loads(CONFIG.read_text(encoding='utf-8'))}
            migrated=securities.migrate_settings(loaded)
            if migrated!=loaded:save_settings(migrated)
            return migrated
        except Exception:
            pass
    return securities.migrate_settings(defaults)


def save_settings(cfg):
    # Atomic replacement preserves the previous list if a write is interrupted.
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=CONFIG.parent,
                                         prefix='.settings-',suffix='.tmp',delete=False) as output:
            temporary=Path(output.name)
            json.dump(cfg,output,ensure_ascii=False,indent=2)
            output.flush();os.fsync(output.fileno())
        os.replace(temporary,CONFIG)
    finally:
        if temporary and temporary.exists():temporary.unlink()


def sentiment_score(text):
    p = sum(1 for w in POS if term_present(text,w))
    n = sum(1 for w in NEG if term_present(text,w))
    score = 50 + max(-40, min(40, (p-n)*12))
    return int(score), '偏正面' if score >= 60 else ('偏负面' if score <= 40 else '中性')


def impact_level(text):
    if any(term_present(text,w) for w in HIGH): return '高'
    if any(term_present(text,w) for w in MED): return '中'
    return '低'


def term_present(text,term):
    if all(ord(char)<128 for char in term):
        pattern=r'(?<![a-z0-9])'+re.escape(term).replace(r'\ ',r'\s+')+r'(?![a-z0-9])'
        return re.search(pattern,text,re.IGNORECASE) is not None
    return term in text


def extract_tickers(text, watchlist):
    return data_service.ticker_matches(text, watchlist)


def fetch_news(watchlist, config):
    rows, health = data_service.fetch_news(watchlist, FEEDS, config, sentiment_score, impact_level)
    save_events(rows)
    return rows, health


def fetch_quotes(watchlist, config):
    return data_service.fetch_quotes(watchlist, config)


def ai_analyze(article, cfg):
    key = cfg.get('openai_api_key','').strip()
    base = cfg.get('openai_base_url','http://localhost:11434/v1').rstrip('/')
    is_local = ('localhost' in base or '127.0.0.1' in base)
    if not key and not is_local: return None
    model = cfg.get('openai_model','gpt-4.1-mini')
    prompt = ('你是审慎的美股事件分析员。仅根据给定新闻标题和摘要分析，不得编造事实。'
      '输出中文，包含：事件事实（区分已证实/待核实）、事件重要性1-10、基本面影响(-10到+10)、短期股价冲击(-10到+10)、可信度1-10、影响周期、关联公司、市场可能已定价程度、需要核验的原始证据。'
      '若信息不足，明确写信息不足。不要给确定性买卖指令。\n新闻：'+article['title']+'\n摘要：'+article['summary']+'\n来源：'+article['source']+'\n链接：'+article['link'])
    try:
        headers={'Content-Type':'application/json'}
        if key: headers['Authorization']='Bearer '+key
        r=requests.post(base+'/chat/completions',headers=headers,json={'model':model,'messages':[{'role':'user','content':prompt}],'temperature':0.2,'stream':False},timeout=180)
        r.raise_for_status()
        return r.json()['choices'][0]['message']['content']
    except Exception as e: return 'AI 分析调用失败：'+str(e)

class App:
    def __init__(self, root):
        init_db(); self.root=root; self.root.title('AI Market Intelligence 0.2.0 · 个人金融情报终端'); self.root.geometry('1380x860'); self.root.minsize(1100,700)
        self.cfg=load_settings(); self.news,self.quotes,self.health=load_snapshot(self.cfg['watchlist']); self.estimates=load_estimates(self.cfg['watchlist']); self.histories=load_histories(self.cfg['watchlist']); self.neutral_multiples=load_neutral_multiples(); self.positions=load_positions(); self.q=queue.Queue(); self.running=False
        self.regime=market_regime(self.quotes,self.news)
        # VPN/代理常见于桌面环境，显式传递给 RSS、行情和 AI 请求。
        for name in ('http_proxy', 'https_proxy'):
            value = self.cfg.get(name, '').strip()
            if value: os.environ[name.upper()] = value
        self.root.configure(bg='#08111f')
        self.style=ttk.Style(); self.style.theme_use('clam')
        self.style.configure('.', background='#08111f', foreground='#d8e7f5', fieldbackground='#0e1c2d', font=('Microsoft YaHei UI',9))
        self.style.configure('TFrame', background='#08111f')
        self.style.configure('TLabel', background='#08111f', foreground='#d8e7f5')
        self.style.configure('TLabelframe', background='#0b1728', foreground='#70e1d1', bordercolor='#1a3b55')
        self.style.configure('TLabelframe.Label', background='#0b1728', foreground='#70e1d1', font=('Microsoft YaHei UI',9,'bold'))
        self.style.configure('TNotebook', background='#08111f', borderwidth=0)
        self.style.configure('TNotebook.Tab', background='#0d1b2c', foreground='#8fa9be', padding=(18,9), font=('Microsoft YaHei UI',9,'bold'))
        self.style.map('TNotebook.Tab', background=[('selected','#12334a')], foreground=[('selected','#70e1d1')])
        self.style.configure('TButton', background='#12334a', foreground='#d8e7f5', bordercolor='#245a70', padding=(12,6))
        self.style.map('TButton', background=[('active','#1a5264')])
        self.style.configure('Treeview', rowheight=30, background='#0c1929', fieldbackground='#0c1929', foreground='#d8e7f5', bordercolor='#17344b', font=('Microsoft YaHei UI',9))
        self.style.configure('Treeview.Heading', background='#10263a', foreground='#70e1d1', font=('Microsoft YaHei UI',9,'bold'))
        self.style.map('Treeview', background=[('selected','#15556a')], foreground=[('selected','#ffffff')])
        self.build_ui(); self.render(); self.show_health(); self.status.config(text='本地缓存 · 正在同步' if self.news or self.quotes else '正在连接数据源')
        self.refresh_async(); self.root.after(250,self.poll_queue); self.root.after(5000,self.auto_refresh)

    def build_ui(self):
        top=ttk.Frame(self.root,padding=12); top.pack(fill='x')
        ttk.Label(top,text='AI MARKET INTELLIGENCE',font=('Segoe UI',20,'bold'),foreground='#70e1d1').pack(side='left')
        ttk.Label(top,text='GLOBAL EVENT RADAR  /  PORTFOLIO SIGNALS',font=('Segoe UI',9),foreground='#7e9bb2').pack(side='left',padx=18)
        self.status=ttk.Label(top,text='正在初始化…'); self.status.pack(side='right')
        self.tabs=ttk.Notebook(self.root); self.tabs.pack(fill='both',expand=True,padx=10,pady=(0,10))
        self.overview=ttk.Frame(self.tabs,padding=10); self.events=ttk.Frame(self.tabs,padding=10); self.watch=ttk.Frame(self.tabs,padding=10); self.settings=ttk.Frame(self.tabs,padding=10); self.history=ttk.Frame(self.tabs,padding=10)
        self.tabs.add(self.overview,text='市场总览'); self.tabs.add(self.events,text='全球事件雷达'); self.tabs.add(self.watch,text='持仓与观察列表'); self.tabs.add(self.history,text='历史事件库'); self.tabs.add(self.settings,text='设置 / AI 接口')
        self.build_overview(); self.build_events(); self.build_watch(); self.build_history(); self.build_settings()

    def build_overview(self):
        cards=ttk.Frame(self.overview); cards.pack(fill='x',pady=5)
        self.card_vars=[]
        for title in ['新闻情绪均值','高影响事件','观察列表上涨比例','VIX 最新值']:
            f=ttk.LabelFrame(cards,text=title,padding=12); f.pack(side='left',fill='x',expand=True,padx=5)
            v=tk.StringVar(value='--'); ttk.Label(f,textvariable=v,font=('Segoe UI',18,'bold')).pack(); self.card_vars.append(v)
        ttk.Label(self.overview,text='市场快照（延迟数据；具体行情权限取决于数据供应商）',font=('Microsoft YaHei UI',10,'bold')).pack(anchor='w',pady=(15,5))
        self.quote_tree=ttk.Treeview(self.overview,columns=('ticker','price','change'),show='headings',height=9)
        for c,t,w in [('ticker','代码',120),('price','最新可获取价格',180),('change','日涨跌幅',160)]: self.quote_tree.heading(c,text=t); self.quote_tree.column(c,width=w,anchor='center')
        self.quote_tree.pack(fill='x')
        self.regime_var=tk.StringVar(value='市场状态：等待数据')
        ttk.Label(self.overview,textvariable=self.regime_var,font=('Microsoft YaHei UI',12,'bold')).pack(anchor='w',pady=8)
        self.signal_var=tk.StringVar(value='交易辅助结论：等待数据')
        ttk.Label(self.overview,textvariable=self.signal_var,wraplength=1120,font=('Microsoft YaHei UI',10,'bold')).pack(anchor='w',pady=(0,6))
        ttk.Label(self.overview,text='解读原则：新闻情绪不是市场情绪的全部。系统会将新闻、价格、波动率和市场广度分开呈现；缺失数据不会伪造。',wraplength=1100).pack(anchor='w',pady=15)

    def build_events(self):
        bar=ttk.Frame(self.events); bar.pack(fill='x',pady=(0,8))
        ttk.Button(bar,text='立即刷新',command=self.refresh_async).pack(side='left')
        ttk.Button(bar,text='打开原文',command=self.open_selected).pack(side='left',padx=5)
        filters=ttk.Frame(self.events); filters.pack(fill='x',pady=(0,8))
        self.search_var=tk.StringVar(); self.level_var=tk.StringVar(value='全部等级'); self.direction_var=tk.StringVar(value='全部方向')
        ttk.Entry(filters,textvariable=self.search_var).pack(side='left',fill='x',expand=True)
        ttk.Combobox(filters,textvariable=self.level_var,values=['全部等级','S1','S2','S3','S4'],state='readonly',width=10).pack(side='left',padx=8)
        ttk.Combobox(filters,textvariable=self.direction_var,values=['全部方向','偏正面','中性','偏负面'],state='readonly',width=10).pack(side='left')
        for variable in (self.search_var,self.level_var,self.direction_var): variable.trace_add('write',lambda *_:self.render_events())
        self.news_tree=ttk.Treeview(self.events,columns=('grade','sent','tickers','trust','published','title'),show='headings')
        for c,t,w in [('grade','等级',60),('sent','方向 / 初筛',100),('tickers','关联标的',115),('trust','来源核验',145),('published','发布 UTC',145),('title','新闻标题',600)]: self.news_tree.heading(c,text=t); self.news_tree.column(c,width=w,anchor='w')
        self.news_tree.pack(fill='both',expand=True); self.news_tree.bind('<Double-1>',self.open_analysis)
        self.detail=tk.Text(self.events,height=7,wrap='word',font=('Microsoft YaHei UI',9)); self.detail.pack(fill='x',pady=8); self.news_tree.bind('<<TreeviewSelect>>',self.show_detail)

    def build_watch(self):
        ttk.Label(self.watch,text='当前观察列表',font=('Microsoft YaHei UI',12,'bold')).pack(anchor='w')
        self.watch_text=tk.StringVar(value=', '.join(self.cfg['watchlist']))
        ttk.Entry(self.watch,textvariable=self.watch_text).pack(fill='x',pady=8)
        ttk.Label(self.watch,text='建议使用美股代码；指数可使用 ^VIX。默认已加入 ORCL、MRVL、MU、LITE、INTC、SMH、NVDA、MSFT、AVGO、QQQ、SPY、VIX。',wraplength=1000).pack(anchor='w')
        ttk.Button(self.watch,text='保存观察列表并刷新',command=self.save_watchlist).pack(anchor='w',pady=12)

    def build_history(self):
        bar=ttk.Frame(self.history); bar.pack(fill='x')
        ttk.Button(bar,text='刷新历史记录',command=self.render_history).pack(side='left')
        ttk.Button(bar,text='打开选中原文',command=self.open_history).pack(side='left',padx=8)
        self.hist_tree=ttk.Treeview(self.history,columns=('seen','impact','sent','source','title'),show='headings')
        for c,t,w in [('seen','首次收录',165),('impact','影响',75),('sent','情绪',85),('source','来源',190),('title','标题',750)]:
            self.hist_tree.heading(c,text=t); self.hist_tree.column(c,width=w,anchor='w')
        self.hist_tree.pack(fill='both',expand=True,pady=8); self.render_history()

    def render_history(self):
        for item in self.hist_tree.get_children(): self.hist_tree.delete(item)
        with sqlite3.connect(DB) as con:
            self.history_rows=con.execute('SELECT first_seen,impact,sentiment,source,title,link FROM events ORDER BY id DESC LIMIT 1000').fetchall()
        for i,row in enumerate(self.history_rows): self.hist_tree.insert('', 'end', iid=str(i), values=(row[0],row[1],row[2],row[3],row[4]))

    def open_history(self):
        sel=self.hist_tree.selection()
        if sel:
            try: webbrowser.open(self.history_rows[int(sel[0])][5])
            except Exception: pass

    def build_settings(self):
        ttk.Label(self.settings,text='本地 AI 深度分析（免费优先）',font=('Microsoft YaHei UI',12,'bold')).pack(anchor='w',pady=(0,8))
        ttk.Label(self.settings,text='推荐安装 Ollama 并在本机下载 qwen3:4b。默认地址 http://localhost:11434/v1；本地模型不需要 API Key，也不产生按量 API 费用。也可改填其他 OpenAI 兼容服务。').pack(anchor='w',pady=5)
        self.base_var=tk.StringVar(value=self.cfg.get('openai_base_url','http://localhost:11434/v1')); self.model_var=tk.StringVar(value=self.cfg.get('openai_model','qwen3:4b')); self.key_var=tk.StringVar(value=self.cfg.get('openai_api_key',''))
        for label,var,show in [('API Base URL',self.base_var,None),('模型名称',self.model_var,None),('API Key（本机保存）',self.key_var,'*')]:
            ttk.Label(self.settings,text=label).pack(anchor='w',pady=(8,2)); ttk.Entry(self.settings,textvariable=var,show=show or '').pack(fill='x')
        self.http_proxy_var=tk.StringVar(value=self.cfg.get('http_proxy','')); self.https_proxy_var=tk.StringVar(value=self.cfg.get('https_proxy',''))
        for label,var in [('HTTP 代理（可选，如 http://127.0.0.1:7890）',self.http_proxy_var),('HTTPS 代理（可选）',self.https_proxy_var)]:
            ttk.Label(self.settings,text=label).pack(anchor='w',pady=(8,2)); ttk.Entry(self.settings,textvariable=var).pack(fill='x')
        self.auto_proxy_var=tk.BooleanVar(value=self.cfg.get('auto_local_proxy',True))
        ttk.Checkbutton(self.settings,text='自动探测肥猫云本地端口 127.0.0.1:7890（用于 Google News）',variable=self.auto_proxy_var).pack(anchor='w',pady=8)
        ttk.Button(self.settings,text='保存接口设置',command=self.save_settings).pack(anchor='w',pady=12)
        ttk.Label(self.settings,text=f'设置文件保存在：{CONFIG}\n本地 Ollama 无需 API Key；若使用云端接口，Key 仅保存在本机配置文件，请勿分享。').pack(anchor='w',pady=8)
        ttk.Label(self.settings,text='数据源连接状态',font=('Microsoft YaHei UI',11,'bold')).pack(anchor='w',pady=(15,4))
        self.health_tree=ttk.Treeview(self.settings,columns=('source','state','count','checked'),show='headings',height=8)
        for key,label,width in [('source','来源 / 标的',220),('state','状态',220),('count','条数',70),('checked','最近检查 UTC',180)]:
            self.health_tree.heading(key,text=label); self.health_tree.column(key,width=width,anchor='w')
        self.health_tree.pack(fill='both',expand=True)

    def show_health(self):
        if not hasattr(self,'health_tree'): return
        for item in self.health_tree.get_children(): self.health_tree.delete(item)
        for row in self.health:
            state='正常' if row['status']=='ok' else row.get('reason',row['status'])
            self.health_tree.insert('','end',values=(row['source'],state,row.get('count','—'),row.get('checked_at','')[:19]))

    def save_settings(self):
        self.cfg['openai_base_url']=self.base_var.get().strip(); self.cfg['openai_model']=self.model_var.get().strip(); self.cfg['openai_api_key']=self.key_var.get().strip(); self.cfg['http_proxy']=self.http_proxy_var.get().strip(); self.cfg['https_proxy']=self.https_proxy_var.get().strip(); self.cfg['auto_local_proxy']=self.auto_proxy_var.get(); save_settings(self.cfg)
        for name in ('http_proxy','https_proxy'):
            value=self.cfg.get(name,'').strip()
            if value: os.environ[name.upper()]=value
        messagebox.showinfo('已保存','AI 接口和 VPN/代理设置已保存到本机。')

    def save_watchlist(self):
        items=[]
        for x in self.watch_text.get().replace(';',',').split(','):
            x=x.strip().upper()
            if x and x not in items: items.append(x)
        if not items: messagebox.showwarning('提示','观察列表不能为空。'); return
        self.cfg['watchlist']=items; save_settings(self.cfg); self.refresh_async()

    def refresh_async(self):
        if self.running: return
        self.running=True; self.status.config(text='正在抓取新闻与行情…')
        def work():
            try:
                with ThreadPoolExecutor(max_workers=4) as pool:
                    nf=pool.submit(fetch_news,self.cfg['watchlist'],self.cfg)
                    qf=pool.submit(fetch_quotes,self.cfg['watchlist'],self.cfg)
                    ef=pool.submit(data_service.fetch_estimates,self.cfg['watchlist'],self.cfg)
                    hf=pool.submit(data_service.fetch_histories,self.cfg['watchlist'],self.cfg)
                    n,news_health=nf.result(); q,quote_health=qf.result()
                    estimates,estimate_health=ef.result()
                    histories,history_health=hf.result()
                health=news_health+quote_health+estimate_health+history_health
                save_snapshot(q,health,estimates,histories)
                self.q.put(('data',n,q,health,estimates,histories,None))
            except Exception as e:
                logging.exception('Refresh failed')
                self.q.put(('data',[],[],[],[],[],str(e)))
        threading.Thread(target=work,daemon=True).start()

    def poll_queue(self):
        try:
            item=self.q.get_nowait()
            if item[0]=='data':
                _,n,q,health,estimates,histories,err=item
                if n: self.news=n
                if q:
                    merged={row['ticker']:row for row in self.quotes}
                    merged.update({row['ticker']:row for row in q})
                    order={ticker:i for i,ticker in enumerate(self.cfg['watchlist'])}
                    self.quotes=sorted((row for row in merged.values() if row['ticker'] in order),key=lambda row:order[row['ticker']])
                if health: self.health=health
                if estimates: self.estimates=estimates
                if histories: self.histories=histories
                self.regime=market_regime(self.quotes,self.news); self.running=False; self.render(); self.show_health()
                ok=sum(h['status']=='ok' for h in health)
                self.status.config(text=('同步失败 · 显示缓存' if err else f'同步完成 {ok}/{len(health)} 来源 · '+datetime.now().strftime('%H:%M:%S')))
            elif item[0]=='analysis':
                self.detail.delete('1.0','end'); self.detail.insert('end',item[1]); self.status.config(text='AI 分析完成')
        except queue.Empty: pass
        self.root.after(1000,self.poll_queue)

    def auto_refresh(self):
        if not self.running: self.refresh_async()
        self.root.after(max(60,int(self.cfg.get('refresh_seconds',300)))*1000,self.auto_refresh)

    def render(self):
        self.render_events()
        for item in self.quote_tree.get_children(): self.quote_tree.delete(item)
        for q in self.quotes: self.quote_tree.insert('', 'end', values=(q['ticker'],f"{q['price']:.2f}",f"{q['change']:+.2f}%"))
        avg=round(sum(a['sentiment'] for a in self.news)/len(self.news)) if self.news else None
        high=sum(1 for a in self.news if a['impact']=='高')
        up=sum(1 for q in self.quotes if q['change']>0); ratio=f'{up}/{len(self.quotes)}' if self.quotes else '--'
        vix=next((q['price'] for q in self.quotes if q['ticker']=='^VIX'),None)
        self.card_vars[0].set(f'{avg}/100' if avg is not None else '—'); self.card_vars[1].set(str(high) if self.news else '—'); self.card_vars[2].set(ratio); self.card_vars[3].set(f'{vix:.1f}' if vix else '--')
        r=getattr(self,'regime',{})
        self.regime_var.set('综合市场状态：'+r.get('label','数据不足')+'  |  观察分数：'+str(r.get('score','--'))+'/100  |  上涨 '+str(r.get('up',0))+' / 下跌 '+str(r.get('down',0))+'\n'+r.get('note',''))
        if r:
            self.signal_var.set('交易研究：尚未完成历史校准，不输出买卖概率。')

    def render_events(self):
        if not hasattr(self,'news_tree'): return
        for item in self.news_tree.get_children(): self.news_tree.delete(item)
        query=self.search_var.get().strip().casefold()
        level=self.level_var.get(); direction=self.direction_var.get()
        for i,a in enumerate(self.news):
            grade=a.get('grade') or data_service.event_profile(a['source'],a['title'],a['impact'])[0]
            if level!='全部等级' and grade!=level: continue
            if direction!='全部方向' and a['label']!=direction: continue
            if query and query not in (a['title']+' '+a['source']+' '+' '.join(a['tickers'])).casefold(): continue
            trust=a.get('credibility') or data_service.event_profile(a['source'],a['title'],a['impact'])[1]
            self.news_tree.insert('', 'end', iid=str(i), values=(grade,a['label'],', '.join(a['tickers']) or '—',trust,a['published'][:16],a['title']))

    def open_selected(self):
        a=self.selected_article()
        if a: webbrowser.open(a['link'])

    def selected_article(self):
        sel=self.news_tree.selection()
        if not sel: return None
        try: return self.news[int(sel[0])]
        except Exception: return None

    def show_detail(self,event=None):
        a=self.selected_article()
        if not a: return
        grade,trust,horizon=data_service.event_profile(a['source'],a['title'],a['impact'])
        self.detail.delete('1.0','end'); self.detail.insert('end',f"{a['title']}\n\n来源：{a['source']}\n发布时间：{a['published'] or '来源未提供'}\n事件等级：{a.get('grade') or grade} · 标题规则初筛\n方向：{a['label']} · 可信度：{a.get('credibility') or trust}\n影响周期：{a.get('horizon') or horizon}\n关联标的：{', '.join(a['tickers']) or '待识别'}\n\n{a['summary']}\n\n原文：{a['link']}\n\n事实核验状态：聚合来源请点击原文，确认公告或原始报道。")

    def open_analysis(self,event=None):
        a=self.selected_article()
        if not a: return
        self.status.config(text='AI 正在分析…')
        def work():
            result=ai_analyze(a,self.cfg)
            if result is None: result='尚未配置 AI API Key。请到“设置 / AI 接口”配置兼容 OpenAI 的接口后重试。\n\n初筛信息：影响级别 '+a['impact']+'；标题情绪 '+a['label']+'。这只是规则筛查，不是投资结论。'
            self.q.put(('analysis',result))
        threading.Thread(target=work,daemon=True).start()

if __name__=='__main__':
    import tkinter as tk
    from tkinter import ttk, messagebox
    from terminal_ui import upgrade
    upgrade(App)
    root=tk.Tk()
    if ICON.exists(): root.iconbitmap(str(ICON))
    def report_callback_error(exc, value, tb):
        logging.error('UI callback failed', exc_info=(exc,value,tb))
        messagebox.showerror('操作失败','操作未完成。请查看本地 application.log 获取详情。')
    root.report_callback_exception=report_callback_error
    app=App(root); root.mainloop()
