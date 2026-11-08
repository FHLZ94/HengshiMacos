"""Free public market sources with bounded requests and explicit source health."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from io import StringIO
from pathlib import Path
from urllib.parse import quote
import html
import re
import socket
import sys
import threading
import time

import feedparser
import requests
import securities
from math import isfinite

TIMEOUT = (4, 9)
HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; NexusResearch/0.3; personal market reader)',
           'Accept': 'application/json, application/rss+xml, application/xml, */*'}
QUOTE_HEADERS = {**HEADERS, 'Origin': 'https://www.nasdaq.com'}
CNN_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36',
    'Referer': 'https://www.cnn.com/markets/fear-and-greed',
    'Origin': 'https://www.cnn.com',
    'Accept': 'application/json, text/plain, */*',
}
SP500_LIST = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / 'assets' / 'sp500_constituents.csv'
NETWORK_LIMIT = threading.BoundedSemaphore(6)
SECTOR_TICKERS = ('XLK','SMH','XLV','XLP','XLU','XLY','XLF','XLE','XLI','XLC','XLRE','XLB','TLT','GLD')
ETF_TICKERS = securities.FUND_CODES
INTELLIGENCE_TERMS = ('semiconductor','chip','ai infrastructure','artificial intelligence','data center','datacenter',
                      'advanced packaging','chiplet','hbm','memory','optical interconnect','photonic','foundry',
                      'export control','export ban','tariff','commerce department','white house','congress','senate',
                      'federal reserve','interest rate','capex','cloud compute','supply chain','advanced packaging',
                      '半导体','芯片','人工智能','算力','数据中心','先进封装','芯粒','存储','光通信','光模块','晶圆','封装','出口管制','商务部','白宫','国会','供应链','资本开支')
IRRELEVANT_TERMS = ('terrorism','terrorist','terrorist attack','murder','crime','poland investigation','poland probe',
                     'celebrity','sports','entertainment','恐怖主义','恐袭','谋杀','犯罪','波兰调查','名人','体育','娱乐')


def http_get(*args, **kwargs):
    with NETWORK_LIMIT:
        return requests.get(*args, **kwargs)


def http_post(*args, **kwargs):
    with NETWORK_LIMIT:
        return requests.post(*args, **kwargs)
ALIASES = {
    'ORCL': ('ORACLE',), 'MRVL': ('MARVELL',), 'LITE': ('LUMENTUM',),
    'INTC': ('INTEL',), 'AVGO': ('BROADCOM',), 'QQQM': ('INVESCO NASDAQ 100 ETF',),
    'SMH': ('VANECK SEMICONDUCTOR',), 'MU': ('MICRON',),
    'NVDA': ('NVIDIA',), 'AMD': ('ADVANCED MICRO DEVICES',),
    'TSM': ('TSMC', 'TAIWAN SEMICONDUCTOR'), 'ASML': ('ASML HOLDING',),
    'AMAT': ('APPLIED MATERIALS',), 'KLAC': ('KLA CORPORATION', 'KLA CORP'),
    'LRCX': ('LAM RESEARCH',), 'ARM': ('ARM HOLDINGS',),
    'QCOM': ('QUALCOMM',), 'COHR': ('COHERENT CORP', 'COHERENT INC'),
    'ANET': ('ARISTA NETWORKS',), 'MSFT': ('MICROSOFT',),
    'AMZN': ('AMAZON',), 'GOOGL': ('ALPHABET', 'GOOGLE'), 'GOOG': ('ALPHABET','GOOGLE'),
    'SKHY': ('SK HYNIX','SKHYNIX'), 'VGT': ('VANGUARD INFORMATION TECHNOLOGY',),
}
INTELLIGENCE_TICKERS = ('NVDA', 'AMD', 'TSM', 'ASML', 'AMAT', 'KLAC', 'LRCX',
                        'ARM', 'QCOM', 'COHR', 'ANET', 'MSFT', 'AMZN', 'GOOGL')
SMH_RELATED = frozenset(('NVDA', 'AMD', 'TSM', 'ASML', 'AMAT', 'KLAC', 'LRCX',
                         'ARM', 'QCOM', 'AVGO', 'MRVL', 'MU', 'INTC','SKHY'))


def intelligence_topics(tickers, title=''):
    symbols=set(tickers)
    upper=title.upper()
    topics=[]
    if symbols & SMH_RELATED or any(term in upper for term in ('SEMICONDUCTOR','CHIPMAKER','CHIP MAKER')):
        topics.append('SMH 行业相关')
    if symbols & {'COHR','LITE','ANET'}: topics.append('光通信与网络')
    if symbols & {'MSFT','AMZN','GOOGL','GOOG','ORCL'}: topics.append('云与算力')
    if symbols & {'MU','SKHY'} or any(term in upper for term in ('SK HYNIX','SAMSUNG','HBM MEMORY')):
        topics.append('存储')
    return topics


def configured_proxy(config, for_google=False):
    explicit = (config.get('https_proxy') or config.get('http_proxy') or '').strip()
    if explicit:
        return {'http': explicit, 'https': explicit}
    if for_google and config.get('auto_local_proxy', True):
        try:
            with socket.create_connection(('127.0.0.1', 7890), timeout=0.3):
                return {'http': 'http://127.0.0.1:7890', 'https': 'http://127.0.0.1:7890'}
        except OSError:
            pass
    return None


def parse_date(value):
    if not value:
        return ''
    try:
        parsed = parsedate_to_datetime(value)
    except (ValueError, TypeError, IndexError):
        try:
            parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        except (ValueError, TypeError):
            return ''
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec='seconds')


def clean(value):
    return ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', value or '')).split())


def intelligence_relevant(title, summary, tickers=()):
    """Keep stories with a credible path to the user's AI/semiconductor book."""
    text=(title+' '+summary).casefold()
    if tickers:return True
    has_chain=any(term.casefold() in text for term in INTELLIGENCE_TERMS)
    if not has_chain:return False
    if any(term.casefold() in text for term in IRRELEVANT_TERMS):
        # Generic crime/geopolitical stories stay out unless the same text also
        # names an explicit technology, supply-chain or policy transmission.
        return any(term.casefold() in text for term in ('semiconductor','chip','ai','data center','export control','tariff','半导体','芯片','人工智能','数据中心','出口管制','供应链'))
    return True


def event_profile(source, title, impact):
    text=title.casefold()
    official=source.startswith(('Federal Reserve', 'SEC'))
    grade={'高':'S2', '中':'S3', '低':'S4'}.get(impact,'S4')
    if impact=='高' and any(term in text for term in ('war','bankruptcy','systemic','emergency','战争','破产')):
        grade='S1'
    if any(term in text for term in ('earnings','guidance','capex','财报','指引','资本开支')):
        horizon='数周至季度'
    elif any(term in text for term in ('fed','rate','cpi','policy','tariff','利率','政策')):
        horizon='数日至数月'
    else:
        horizon='待评估'
    return grade, ('官方来源' if official else '转载/聚合，待核验'), horizon


def title_key(title):
    # Google News appends the publisher name to titles across search feeds.
    base = re.sub(r'\s+-\s+[^-]{2,65}$', '', title).casefold()
    return re.sub(r'[^\w]+', ' ', base).strip()


def ticker_matches(text, watchlist, config=None):
    upper = text.upper()
    found = []
    for ticker in watchlist:
        if ticker == 'DRAM':
            continue
        aliases=list(ALIASES.get(ticker,()))
        company=(((config or {}).get('securities') or {}).get(ticker) or {}).get('name','')
        short=re.split(r'\b(?:Inc\.?|Corp\.?|Corporation|Class|Common Stock|Holdings)\b',company,flags=re.I)[0].strip()
        if len(short)>=4:aliases.append(short.upper())
        symbol_text=text if len(ticker.lstrip('^'))<=3 else upper
        if re.search(r'(?<![A-Za-z0-9])' + re.escape(ticker.lstrip('^')) + r'(?![A-Za-z0-9])', symbol_text):
            found.append(ticker)
        elif any(re.search(r'(?<![A-Z0-9])' + re.escape(alias) + r'(?![A-Z0-9])', upper)
                 for alias in aliases):
            found.append(ticker)
    return found


def _feed(source, url, config, sentiment_fn, impact_fn, watchlist):
    started = time.monotonic()
    proxy = configured_proxy(config, for_google='news.google.com' in url)
    try:
        response = http_get(url, timeout=TIMEOUT, headers=HEADERS, proxies=proxy)
        response.raise_for_status()
        parsed = feedparser.parse(response.content)
        if parsed.bozo and not parsed.entries:
            raise ValueError('RSS 解析失败')
        rows = []
        for entry in parsed.entries[:30]:
            title = clean(entry.get('title', ''))
            link = entry.get('link', '')
            if not title or not link:
                continue
            summary = clean(entry.get('summary', ''))[:500]
            body = title + ' ' + summary
            score, label = sentiment_fn(body)
            impact=impact_fn(body)
            grade,trust,horizon=event_profile(source,title,impact)
            publisher=clean((entry.get('source') or {}).get('title') or '')
            tickers=ticker_matches(body, watchlist, config)
            if not intelligence_relevant(title,summary,tickers):continue
            rows.append({'title': title, 'summary': summary, 'link': link,
                         'source': source, 'publisher': publisher,
                         'published': parse_date(entry.get('published')),
                         'impact': impact, 'grade': grade, 'credibility': trust, 'horizon': horizon,
                         'sentiment': score, 'label': label,
                         'tickers': tickers})
        return rows, {'source': source, 'status': 'ok', 'count': len(rows),
                      'latency_ms': round((time.monotonic()-started)*1000), 'checked_at': datetime.now(timezone.utc).isoformat(timespec='seconds')}
    except requests.Timeout:
        reason = '连接超时'
    except requests.HTTPError as exc:
        reason = f'HTTP {exc.response.status_code}' if exc.response is not None else 'HTTP 错误'
    except requests.RequestException as exc:
        reason = type(exc).__name__
    except Exception as exc:
        reason = type(exc).__name__
    return [], {'source': source, 'status': 'error', 'count': 0, 'reason': reason,
                'checked_at': datetime.now(timezone.utc).isoformat(timespec='seconds')}


def fetch_news(watchlist, feeds, config, sentiment_fn, impact_fn):
    sources = list(feeds)
    coverage=list(dict.fromkeys([*watchlist,*INTELLIGENCE_TICKERS]))
    for ticker in watchlist:
        if ticker.startswith('^'):
            continue
        query = quote(f'"{ticker}" stock OR {ticker} company')
        sources.append((f'Google News · {ticker}', f'https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en'))
    all_rows, health = [], []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(_feed, name, url, config, sentiment_fn, impact_fn, coverage) for name, url in sources]
        for future in as_completed(futures):
            rows, state = future.result()
            all_rows.extend(rows)
            health.append(state)
    unique = {}
    for row in all_rows:
        key = title_key(row['title']) or row['link']
        old = unique.get(key)
        publisher=row.get('publisher') or (row['source'] if not row['source'].startswith('Google News') else '')
        if old is None:
            unique[key]={**row,'independent_publishers':[publisher] if publisher else []}
            continue
        publishers=set(old.get('independent_publishers') or [])
        if publisher:publishers.add(publisher)
        if (row['published'], len(row['tickers'])) > (old['published'], len(old['tickers'])):
            unique[key]={**row,'independent_publishers':sorted(publishers)}
        else:
            old['independent_publishers']=sorted(publishers)
    rank = {'高': 3, '中': 2, '低': 1}
    rows = sorted(unique.values(), key=lambda row: (row['published'],rank[row['impact']]), reverse=True)
    return rows[:400], sorted(health, key=lambda x:x['source'])


def search_news(query, config, sentiment_fn, impact_fn, watchlist):
    query=' '.join(str(query).split())[:120]
    if len(query)<2:
        return [],{'source':'即时检索','status':'error','count':0,'reason':'至少输入两个字符'}
    url=f'https://news.google.com/rss/search?q={quote(query)}&hl=en-US&gl=US&ceid=US:en'
    coverage=list(dict.fromkeys([*watchlist,*INTELLIGENCE_TICKERS]))
    return _feed(f'即时检索 · {query}',url,config,sentiment_fn,impact_fn,coverage)


def _quote(ticker, config):
    started = time.monotonic()
    if ticker == 'DRAM':
        return None, {'source': 'DRAM', 'status': 'unresolved', 'reason': '需确认具体证券代码'}
    if ticker == '^VIX':
        try:
            response = http_get('https://fred.stlouisfed.org/graph/fredgraph.csv?id=VIXCLS',
                                    timeout=TIMEOUT, headers=HEADERS, proxies=configured_proxy(config))
            response.raise_for_status()
            values = [(item.get('observation_date') or item.get('DATE'),float(item['VIXCLS']))
                      for item in csv.DictReader(StringIO(response.text))
                      if item.get('VIXCLS') not in ('', '.')]
            if len(values)<2: raise ValueError('VIX 序列为空')
            date, price = values[-1]
            row = {'ticker':ticker,'name':'CBOE VIX (FRED)','exchange':'CBOE', 'price':price,
                   'change':(price/values[-2][1]-1)*100, 'asof':date,
                   'fetched_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),'source':'FRED'}
            return row, {'source':ticker,'status':'ok','count':1,'checked_at':row['fetched_at']}
        except (requests.RequestException,ValueError,KeyError,ZeroDivisionError) as exc:
            return None, {'source':ticker,'status':'error','reason':type(exc).__name__,
                          'checked_at':datetime.now(timezone.utc).isoformat(timespec='seconds')}
    if ticker.startswith('^'):
        return None, {'source': ticker, 'status': 'unsupported', 'reason': '不支持此指数'}
    kind = 'etf' if securities.is_fund(ticker,config) else 'stocks'
    url = f'https://api.nasdaq.com/api/quote/{quote(ticker)}/info?assetclass={kind}'
    try:
        try:
            response = http_get(url, timeout=TIMEOUT, headers=QUOTE_HEADERS,
                                    proxies=configured_proxy(config))
        except requests.Timeout:
            time.sleep(0.3)
            response = http_get(url, timeout=TIMEOUT, headers=QUOTE_HEADERS,
                                    proxies=configured_proxy(config))
        response.raise_for_status()
        data = response.json().get('data')
        if not data or not data.get('primaryData'):
            raise ValueError('代码无报价')
        primary = data['primaryData']
        price = float(re.sub(r'[^0-9.\-]', '', primary['lastSalePrice']))
        change = float(re.sub(r'[^0-9.\-]', '', primary['percentageChange']))
        row = {'ticker': ticker, 'name': data.get('companyName', ticker), 'exchange': data.get('exchange', ''),
               'price': price, 'change': change, 'asof': primary.get('lastTradeTimestamp',''),
               'fetched_at': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'source': 'Nasdaq',
               'market_status':data.get('marketStatus',''),'session':'regular','is_realtime':bool(primary.get('isRealTime')),
               'price_label':'最近成交' if primary.get('isRealTime') else '延迟最近成交'}
        try:
            summary_url=f'https://api.nasdaq.com/api/quote/{quote(ticker)}/summary?assetclass={kind}'
            summary=http_get(summary_url,timeout=TIMEOUT,headers=QUOTE_HEADERS,
                                 proxies=configured_proxy(config,for_google=True))
            summary.raise_for_status()
            values=(summary.json().get('data') or {}).get('summaryData') or {}
            target_raw=(values.get('OneYrTarget') or {}).get('value')
            if target_raw and target_raw!='N/A':
                target=float(re.sub(r'[^0-9.]','',target_raw))
                if target>0:
                    row['target_price']=target
                    row['target_source']='Nasdaq 1 Year Target'
                    row['target_fetched_at']=row['fetched_at']
            volume_raw=primary.get('volume') or ''
            average_raw=(values.get('AverageVolume') or {}).get('value') or ''
            volume=float(re.sub(r'[^0-9.]','',volume_raw)) if volume_raw else 0
            avg=float(re.sub(r'[^0-9.]','',average_raw)) if average_raw else 0
            if avg>0:
                row['volume_ratio']=round(volume/avg,2)
                row['volume']=int(volume)
                row['average_volume']=int(avg)
        except (requests.RequestException,ValueError,TypeError,AttributeError,KeyError):
            pass
        return row, {'source': ticker, 'status': 'ok', 'count': 1,
                     'latency_ms': round((time.monotonic()-started)*1000), 'checked_at': row['fetched_at']}
    except requests.Timeout:
        reason = '连接超时'
    except requests.HTTPError as exc:
        reason = f'HTTP {exc.response.status_code}' if exc.response is not None else 'HTTP 错误'
    except (ValueError, KeyError, TypeError) as exc:
        reason = str(exc)[:70]
    except requests.RequestException as exc:
        reason = type(exc).__name__
    return None, {'source': ticker, 'status': 'error', 'reason': reason,
                  'checked_at': datetime.now(timezone.utc).isoformat(timespec='seconds')}


def fetch_quotes(watchlist, config):
    rows, health = [], []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(_quote, ticker, config) for ticker in watchlist]
        for future in as_completed(futures):
            row, state = future.result()
            if row:
                rows.append(row)
            health.append(state)
    order = {ticker: i for i, ticker in enumerate(watchlist)}
    extended, extra_health = fetch_session_quotes(watchlist, config)
    base = {r['ticker']:r for r in rows}
    for item in extended:
        merged = merge_session_quote(base.get(item['ticker']), item)
        if merged: base[item['ticker']] = merged
    health.append(extra_health)
    return sorted(base.values(), key=lambda row: order[row['ticker']]), health


def _estimate(ticker, config):
    if ticker=='DRAM' or securities.is_fund(ticker,config) or ticker.startswith('^'):
        return None, {'source':'EPS '+ticker,'status':'unsupported','reason':'基金/指数或代码未确认'}
    try:
        url=f'https://api.nasdaq.com/api/analyst/{quote(ticker)}/earnings-forecast'
        response=http_get(url,timeout=(5,15),headers=QUOTE_HEADERS,proxies=configured_proxy(config))
        response.raise_for_status()
        data=response.json().get('data') or {}
        periods=(data.get('quarterlyForecast') or {}).get('rows') or []
        forecast=select_ntm_forecast(periods)
        if not forecast: raise ValueError('未来四季 EPS 预期不足')
        fetched=datetime.now(timezone.utc).isoformat(timespec='seconds')
        row={'ticker':ticker,**forecast,'fetched_at':fetched,
             'source':'Nasdaq 分析师季度一致预期','basis':'ntm_4q'}
        try:
            reported_url=f'https://api.nasdaq.com/api/company/{quote(ticker)}/earnings-surprise'
            reported=http_get(reported_url,timeout=(4,9),headers=QUOTE_HEADERS,proxies=configured_proxy(config))
            reported.raise_for_status()
            actual_rows=((reported.json().get('data') or {}).get('earningsSurpriseTable') or {}).get('rows') or []
            actual=select_reported_eps(actual_rows)
            if actual:row.update(actual,reported_source_url=reported_url)
        except (requests.RequestException,ValueError,TypeError,KeyError):pass
        return row,{'source':'EPS '+ticker,'status':'ok','count':1,'checked_at':fetched}
    except (requests.RequestException,ValueError,TypeError,KeyError) as exc:
        return None,{'source':'EPS '+ticker,'status':'error','reason':type(exc).__name__,
                     'checked_at':datetime.now(timezone.utc).isoformat(timespec='seconds')}


def fetch_estimates(watchlist, config):
    rows,health=[],[]
    symbols=[ticker for ticker in watchlist
             if ticker!='DRAM' and not securities.is_fund(ticker,config) and not ticker.startswith('^')]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures=[pool.submit(_estimate,ticker,config) for ticker in symbols]
        for future in as_completed(futures):
            row,state=future.result()
            if row: rows.append(row)
            health.append(state)
    order={ticker:i for i,ticker in enumerate(watchlist)}
    return sorted(rows,key=lambda row:order[row['ticker']]),sorted(health,key=lambda row:order[row['source'].removeprefix('EPS ')])


def select_ntm_forecast(periods, now=None):
    now=now or datetime.now(timezone.utc)
    valid=[]
    for row in periods:
        try:
            end=datetime.strptime(row['fiscalEnd'],'%b %Y').replace(tzinfo=timezone.utc)
            eps=float(row['consensusEPSForecast'])
            if end.year < now.year or (end.year==now.year and end.month<now.month):
                continue
            valid.append((end,row,eps))
        except (ValueError,KeyError,TypeError):
            continue
    valid.sort(key=lambda item:item[0])
    selected=valid[:4]
    if len(selected)!=4 or any(not isfinite(item[2]) for item in selected) or sum(item[2] for item in selected)<=0:
        return None
    months=[item[0].year*12+item[0].month for item in selected]
    if any(right-left not in (2,3,4) for left,right in zip(months,months[1:])):
        return None
    rows=[item[1] for item in selected]
    return {'period':f"{rows[0]['fiscalEnd']} - {rows[-1]['fiscalEnd']}",
            'eps':round(sum(item[2] for item in selected),4),
            'analysts':min((int(row.get('noOfEstimates') or 0) for row in rows),default=0),
            'revisions_up':sum(int(row.get('up') or 0) for row in rows),
            'revisions_down':sum(int(row.get('down') or 0) for row in rows)}


def _history(ticker, config):
    if ticker=='^VIX':
        try:
            response=http_get('https://fred.stlouisfed.org/graph/fredgraph.csv?id=VIXCLS',
                                  timeout=(5,18),headers=HEADERS,proxies=configured_proxy(config))
            response.raise_for_status()
            start=(datetime.now(timezone.utc)-timedelta(days=3700)).date().isoformat()
            bars=[{'date':item.get('observation_date') or item.get('DATE'),
                   'close':float(item['VIXCLS'])}
                  for item in csv.DictReader(StringIO(response.text))
                  if item.get('VIXCLS') not in ('','.') and (item.get('observation_date') or item.get('DATE') or '')>=start]
            if len(bars)<200:raise ValueError('VIX 历史不足')
            checked=datetime.now(timezone.utc).isoformat(timespec='seconds')
            return ({'ticker':ticker,'bars':bars,'fetched_at':checked,'source':'FRED VIX'},
                    {'source':'历史 '+ticker,'status':'ok','count':len(bars),'checked_at':checked})
        except (requests.RequestException,ValueError,KeyError) as exc:
            return None,{'source':'历史 '+ticker,'status':'error','reason':type(exc).__name__,
                         'checked_at':datetime.now(timezone.utc).isoformat(timespec='seconds')}
    if ticker=='DRAM' or ticker.startswith('^'):
        return None,{'source':'历史 '+ticker,'status':'unsupported','reason':'不支持此代码'}
    kind='etf' if securities.is_fund(ticker,config) else 'stocks'
    now=datetime.now(timezone.utc)
    long_history=ticker in ('QQQ','SPY','SMH') or (ticker not in SECTOR_TICKERS and ticker not in ('IWM','RSP'))
    start=(now-timedelta(days=3700 if long_history else 190)).date().isoformat()
    end=now.date().isoformat()
    url=f'https://api.nasdaq.com/api/quote/{quote(ticker)}/historical?assetclass={kind}&fromdate={start}&todate={end}&limit={2700 if long_history else 140}'
    try:
        response=http_get(url,headers=QUOTE_HEADERS,timeout=(5,15),
                              proxies=configured_proxy(config))
        response.raise_for_status()
        data=response.json().get('data') or {}
        raw=((data.get('tradesTable') or {}).get('rows') or [])
        bars=[]
        for item in raw:
            try:
                bars.append({'date':datetime.strptime(item['date'],'%m/%d/%Y').date().isoformat(),
                             'open':float(item['open'].replace(',','').replace('$','')),
                             'high':float(item['high'].replace(',','').replace('$','')),
                             'low':float(item['low'].replace(',','').replace('$','')),
                             'close':float(item['close'].replace(',','').replace('$','')),
                             'volume':int(item['volume'].replace(',',''))})
            except (ValueError,KeyError,TypeError,AttributeError):
                continue
        bars.sort(key=lambda item:item['date'])
        if len(bars)<21: raise ValueError('历史样本不足 21 日')
        checked=now.isoformat(timespec='seconds')
        return ({'ticker':ticker,'bars':bars,'fetched_at':checked,'source':'Nasdaq Historical'},
                {'source':'历史 '+ticker,'status':'ok','count':len(bars),'checked_at':checked})
    except (requests.RequestException,ValueError,TypeError) as exc:
        return None,{'source':'历史 '+ticker,'status':'error','reason':type(exc).__name__,
                     'checked_at':datetime.now(timezone.utc).isoformat(timespec='seconds')}


def fetch_histories(watchlist, config):
    watchlist=list(dict.fromkeys(watchlist))
    rows,health=[],[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures=[pool.submit(_history,ticker,config) for ticker in watchlist]
        for future in as_completed(futures):
            row,state=future.result()
            if row: rows.append(row)
            health.append(state)
    order={ticker:i for i,ticker in enumerate(watchlist)}
    return sorted(rows,key=lambda row:order[row['ticker']]),sorted(health,key=lambda row:order[row['source'].removeprefix('历史 ')])


def reconcile_closed_quotes(quotes, histories):
    history_map={row['ticker']:row.get('bars') or [] for row in histories}
    result=[]
    for quote_row in quotes:
        updated=dict(quote_row)
        bars=history_map.get(updated['ticker'],[])
        if updated.get('market_status')=='Closed' and updated.get('session') not in ('pre','post') and len(bars)>=2:
            try:
                quote_date=datetime.strptime(updated['asof'],'%b %d, %Y').date().isoformat()
            except (TypeError,ValueError):
                quote_date=updated.get('asof','')
            if bars[-1]['date']==quote_date and bars[-2]['close']>0:
                updated['price']=round(float(bars[-1]['close']),4)
                updated['change']=round((updated['price']/bars[-2]['close']-1)*100,4)
                updated['price_label']='最近收盘'
                updated['price_source_detail']='Nasdaq 历史日线与报价日期核对'
        result.append(updated)
    return result


TRADINGVIEW_SYMBOLS={
    'QQQ':'NASDAQ:QQQ','SPY':'AMEX:SPY','QQQM':'NASDAQ:QQQM','SMH':'NASDAQ:SMH',
    'ORCL':'NYSE:ORCL','MRVL':'NASDAQ:MRVL','MU':'NASDAQ:MU','LITE':'NASDAQ:LITE',
    'INTC':'NASDAQ:INTC','AVGO':'NASDAQ:AVGO',
    'VGT':'AMEX:VGT','GOOG':'NASDAQ:GOOG','GOOGL':'NASDAQ:GOOGL','SKHY':'NASDAQ:SKHY',
}


def fetch_comparison(watchlist,config):
    mapping={ticker:TRADINGVIEW_SYMBOLS.get(ticker) or securities.tv_symbol(ticker,config) for ticker in watchlist}
    symbols=[symbol for symbol in mapping.values() if symbol]
    if not symbols:return [],{'source':'TradingView 交叉核对','status':'unsupported','reason':'无可核对代码'}
    payload={'symbols':{'tickers':symbols},
             'columns':['name','close','earnings_per_share_forecast_next_fy','price_earnings_ttm',
                        'price_target_median','price_target_high','price_target_low']}
    try:
        response=http_post('https://scanner.tradingview.com/america/scan',json=payload,
                               headers=HEADERS,timeout=(5,15),proxies=configured_proxy(config,for_google=True))
        response.raise_for_status()
        entries=response.json().get('data') or []
        reverse={symbol:ticker for ticker,symbol in mapping.items() if symbol}
        checked=datetime.now(timezone.utc).isoformat(timespec='seconds')
        rows=[]
        for entry in entries:
            ticker=reverse.get(entry.get('s'))
            values=entry.get('d') or []
            if not ticker or len(values)<4:continue
            rows.append({'ticker':ticker,'price':values[1],
                         'next_fy_eps':values[2],'trailing_pe':values[3],
                         'target_median':finite_number(values[4]) if len(values)>4 else None,
                         'target_high':finite_number(values[5]) if len(values)>5 else None,
                         'target_low':finite_number(values[6]) if len(values)>6 else None,
                         'target_source':'TradingView 分析师目标价中位数',
                         'target_url':'https://www.tradingview.com/symbols/'+entry['s'].replace(':','-')+'/forecast/',
                         'fetched_at':checked,'source':'TradingView Scanner'})
        return rows,{'source':'TradingView 交叉核对','status':'ok','count':len(rows),'checked_at':checked}
    except (requests.RequestException,ValueError,KeyError,TypeError) as exc:
        return [],{'source':'TradingView 交叉核对','status':'error','reason':type(exc).__name__,
                   'checked_at':datetime.now(timezone.utc).isoformat(timespec='seconds')}


def fetch_cnn_fear_greed(config):
    source='CNN 恐慌贪婪指数'
    try:
        response=http_get('https://production.dataviz.cnn.io/index/fearandgreed/graphdata',
                          headers=CNN_HEADERS,proxies=configured_proxy(config,for_google=True),timeout=(5,12))
        response.raise_for_status()
        data=response.json().get('fear_and_greed') or {}
        score=float(data['score'])
        timestamp=parse_date(data.get('timestamp'))
        if not 0<=score<=100 or not timestamp:
            raise ValueError('CNN 数据缺少有效得分或时间')
        result={'score':round(score,1),'rating':data.get('rating',''),
                'asof':timestamp,'source':source,'url':'https://www.cnn.com/markets/fear-and-greed',
                'fetched_at':datetime.now(timezone.utc).isoformat(timespec='seconds')}
        return result,{'source':source,'status':'ok','count':1,'checked_at':result['fetched_at']}
    except (requests.RequestException,ValueError,TypeError,KeyError) as exc:
        return None,{'source':source,'status':'error','reason':type(exc).__name__,
                     'checked_at':datetime.now(timezone.utc).isoformat(timespec='seconds')}


def calculate_sp500_breadth(data, expected_count):
    seen={}
    for entry in data:
        values=entry.get('d') or []
        if len(values)<3 or not isinstance(values[1],(float,int)) or not isinstance(values[2],(float,int)):
            continue
        ticker=values[0]
        if isinstance(ticker,str) and ticker and values[1]>0 and values[2]>0:
            seen[ticker]=(values[1],values[2])
    valid=len(seen)
    if valid<max(350,int(expected_count*.85)):
        raise ValueError(f'标普成分覆盖不足：{valid}/{expected_count}')
    above=sum(price>average for price,average in seen.values())
    return {'above_20d':above,'valid':valid,'ratio_pct':round(above/valid*100,1),
            'expected':expected_count,'below_or_equal_20d':valid-above}


def fetch_sp500_breadth(config):
    source='标普500 20日参与度'
    try:
        with SP500_LIST.open(encoding='utf-8-sig',newline='') as stream:
            tickers=[row['Symbol'].strip().replace('.','-')
                     for row in csv.DictReader(stream) if row.get('Symbol')]
        if len(tickers)<450:
            raise ValueError('标普成分名单不足')
        candidates=[exchange+ticker for ticker in tickers for exchange in ('NYSE:','NASDAQ:')]
        response=http_post('https://scanner.tradingview.com/america/scan',
                           json={'symbols':{'tickers':candidates},'columns':['name','close','SMA20']},
                           timeout=(5,20),proxies=configured_proxy(config,for_google=True),headers=HEADERS)
        response.raise_for_status()
        result=calculate_sp500_breadth(response.json().get('data') or [],len(tickers))
        result.update({'source':source,'constituents_source':'datasets/s-and-p-500-companies',
                       'constituents_snapshot_date':'2026-11-08',
                       'fetched_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),
                       'price_source':'TradingView Scanner'})
        return result,{'source':source,'status':'ok','count':result['valid'],'checked_at':result['fetched_at']}
    except (OSError,requests.RequestException,ValueError,TypeError,KeyError) as exc:
        return None,{'source':source,'status':'error','reason':type(exc).__name__,
                     'checked_at':datetime.now(timezone.utc).isoformat(timespec='seconds')}


def _quote_date(value):
    value = value or ''
    match=re.search(r'[A-Za-z]{3}\s+\d{1,2},\s*\d{4}',value)
    if match:
        try:return datetime.strptime(match.group(),'%b %d, %Y').date()
        except ValueError:pass
    for fmt in ('%Y-%m-%d','%b %d, %Y','%m/%d/%y'):
        try:return datetime.strptime(value[:10] if fmt!='%b %d, %Y' else value,fmt).date()
        except ValueError:pass
    return None


def merge_session_quote(regular,item):
    """Compare observation dates, never retrieval times, before replacing."""
    if not regular:return item
    old_day = _quote_date(regular.get('asof')); new_day = _quote_date(item.get('asof'))
    if not new_day or (old_day and new_day<old_day):return regular
    if new_day==old_day and item.get('session')=='pre' and regular.get('market_status') in ('Open','Closed'):return regular
    if new_day==old_day and item.get('session')=='post' and regular.get('market_status')=='Open':return regular
    if new_day==old_day and item.get('session')=='regular':return regular
    return {**regular,**item}


def parse_session_quotes(entries,watchlist,checked):
    if isinstance(entries,dict):entries=[entries]
    rows=[]
    for entry in entries:
        ticker=entry.get('symbol')
        if ticker not in watchlist:continue
        try:
            regular=float(entry['last']);prior=float(entry['previous_day_closing'])
            day=_quote_date(entry.get('last_timedate','').split(' ')[0])
            if regular<=0 or not day:continue
            ext=entry.get('ExtendedMktQuote') or {}
            ext_day=_quote_date(ext.get('last_time')) or _quote_date(ext.get('last_timedate','').split(' ')[0])
            ext_type=ext.get('type');status=entry.get('curmktstatus')
            use_ext=(ext_day and ext_day>=day and ext_type in ('POST_MKT','PRE_MKT')
                     and status in ('POST_MKT','PRE_MKT','CLOSED') and float(ext.get('last') or 0)>0)
            price=float(ext['last']) if use_ext else regular
            session=('post' if ext_type=='POST_MKT' else 'pre') if use_ext else 'regular'
            label=('盘后成交' if session=='post' else '盘前成交' if session=='pre'
                   else '盘中成交' if status=='REG_MKT' else '最近收盘')
            rows.append(dict(ticker=ticker,price=price,change=round((price/prior-1)*100,4) if prior>0 else 0,
                asof=(ext_day if use_ext else day).isoformat(),fetched_at=checked,
                source='CNBC · Nasdaq 延长时段' if use_ext else 'CNBC 报价',
                session=session,price_label=label,is_realtime=False,regular_close=regular,
                regular_asof=day.isoformat(),session_change_pct=round((price/regular-1)*100,4) if use_ext else None,
                market_status='Open' if status=='REG_MKT' else 'Closed',
                timestamp_precision='date',currency=entry.get('currencyCode') or 'USD',
                name=entry.get('name') or ticker,exchange=entry.get('exchange') or '',
                asset_type='etf' if 'fund' in entry.get('subType','').lower() else 'stocks',
                reported_ttm_eps=finite_number(entry.get('eps')),
                reported_trailing_pe=finite_number(entry.get('pe')),
                provider_forward_pe=finite_number(entry.get('fpe'))))
        except (ValueError,TypeError,KeyError):continue
    return rows


def fetch_session_quotes(watchlist,config,priority=False):
    symbols=[t for t in watchlist if not t.startswith('^') and t!='DRAM']
    checked=datetime.now(timezone.utc).isoformat(timespec='seconds')
    if not symbols:return [],dict(source='盘前盘后行情',status='unsupported',checked_at=checked)
    try:
        response=(requests.get if priority else http_get)('https://quote.cnbc.com/quote-html-webservice/quote.htm',
            params={'symbols':'|'.join(symbols),'requestMethod':'itv','noform':'1','partnerId':'2',
                    'fund':'1','exthrs':'1','output':'json'},headers=HEADERS,
            proxies=configured_proxy(config),timeout=(4,9))
        response.raise_for_status()
        entries=(response.json().get('ITVQuoteResult') or {}).get('ITVQuote') or []
        rows=parse_session_quotes(entries,symbols,checked)
        if not rows:raise ValueError('无有效分时段报价')
        return rows,dict(source='盘前盘后行情',status='ok',count=len(rows),checked_at=checked)
    except (requests.RequestException,ValueError,TypeError,KeyError) as exc:
        return [],dict(source='盘前盘后行情',status='error',reason=type(exc).__name__,checked_at=checked)


def finite_number(value):
    try:
        number=float(str(value).replace(',','').replace('$',''))
        return number if isfinite(number) else None
    except (ValueError,TypeError):return None


def select_reported_eps(rows,now=None):
    """Four actually reported consecutive quarters, using the same Nasdaq vendor."""
    now=now or datetime.now(timezone.utc);valid={}
    for row in rows:
        try:
            period=datetime.strptime(row['fiscalQtrEnd'],'%b %Y')
            reported=datetime.strptime(row['dateReported'],'%m/%d/%Y').date()
            value=finite_number(row.get('eps'))
            if value is None or reported>now.date():continue
            month=period.year*12+period.month
            valid[month]=(period,reported,value)
        except (ValueError,TypeError,KeyError):continue
    selected=sorted(valid.items())[-4:]
    if len(selected)!=4 or any(b[0]-a[0]!=3 for a,b in zip(selected,selected[1:])):return None
    current=now.year*12+now.month
    if not 0<=current-selected[-1][0]<=6:return None
    return {'reported_eps_ttm':round(sum(item[1][2] for item in selected),4),
            'reported_period':selected[0][1][0].strftime('%b %Y')+' - '+selected[-1][1][0].strftime('%b %Y'),
            'reported_basis':'nasdaq_earnings_surprise',
            'reported_quarters':[{'period':item[1][0].strftime('%b %Y'),'eps':item[1][2],
                                  'reported':item[1][1].isoformat()} for item in selected]}


def resolve_security(raw,config):
    ticker=securities.normalize(raw)
    rows,_=fetch_session_quotes([ticker],config,priority=True)
    if rows:
        row=rows[0]
        if row.get('currency')!='USD':return {'ok':False,'message':'目前仅支持以美元报价的美股和ETF'}
        return {'ok':True,'ticker':ticker,'quote':row,
                'security':{'name':row['name'],'name_zh':securities.CHINESE_NAMES.get(ticker,''),
                            'exchange':row['exchange'],'asset_type':row['asset_type'],'currency':'USD'}}
    received=False
    for kind in ('stocks','etf'):
        try:
            response=requests.get(f'https://api.nasdaq.com/api/quote/{quote(ticker)}/info',
                params={'assetclass':kind},headers=QUOTE_HEADERS,timeout=(3,6),proxies=configured_proxy(config))
            response.raise_for_status();payload=response.json();received=True;data=payload.get('data') or {}
            primary=data.get('primaryData') or {};price=finite_number(primary.get('lastSalePrice'))
            if not price or price<=0 or data.get('symbol','').upper()!=ticker:continue
            asset='etf' if str(data.get('assetClass') or kind).lower()=='etf' else 'stocks'
            meta={'name':data.get('companyName') or ticker,'name_zh':securities.CHINESE_NAMES.get(ticker,''),
                  'exchange':data.get('exchange') or '', 'asset_type':asset,'currency':'USD'}
            row={'ticker':ticker,'name':meta['name'],'exchange':meta['exchange'],'price':price,
                 'change':finite_number(str(primary.get('percentageChange') or '0').replace('%','')) or 0,
                 'asof':primary.get('lastTradeTimestamp',''),'fetched_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),
                 'source':'Nasdaq','market_status':data.get('marketStatus',''),'session':'regular',
                 'price_label':'最近可得成交','asset_type':asset,'currency':'USD'}
            return {'ok':True,'ticker':ticker,'quote':row,'security':meta}
        except (requests.RequestException,ValueError,TypeError):continue
    return {'ok':False,'message':f'未找到可跟踪的美股或ETF代码 {ticker}，请核对代码' if received else '行情服务暂时无法连接，请检查网络后重试'}
