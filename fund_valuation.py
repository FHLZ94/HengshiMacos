"""Free issuer/index PE time series, always compare within one source and basis."""
from datetime import date, datetime, timezone
import re
from lxml import html
from io import BytesIO
from pypdf import PdfReader
import requests

URLS = {'QQQ':'https://worldperatio.com/index/nasdaq-100/',
        'SPY':'https://worldperatio.com/index/sp-500/'}
VGT_HISTORY_PROXY='https://worldperatio.com/sector/sp-500-information-technology'
VGT_FACTSHEET='https://fund-docs.vanguard.com/F0958.pdf'
SMH_FACTSHEET='https://www.vaneck.com/us/en/investments/semiconductor-etf-smh-fact-sheet.pdf'


def parse_vanguard_vgt(text,now=None):
    plain=' '.join(text.split())
    if not re.search(r'Vanguard Information Technology ETF\s*\|\s*VGT',plain):raise ValueError('基金身份不匹配')
    day=re.search(r'As of ([A-Za-z]+ \d{1,2}, \d{4})',plain)
    value=re.search(r'Price/earnings ratio\s+([\d.]+)x',plain,re.I)
    if not day or not value:raise ValueError('发行人PE或日期缺失')
    asof=datetime.strptime(day.group(1),'%B %d, %Y').date()
    if asof>(now or datetime.now(timezone.utc)).date():raise ValueError('发行人报告日期超前')
    return dict(ticker='VGT',pe=float(value.group(1)),asof=asof.isoformat(),source='先锋官方季度报告',
                url=VGT_FACTSHEET,basis='发行人组合市盈率（季度报告口径）',history=[],percentile=None,
                years=0,samples=0,fetched_at=datetime.now(timezone.utc).isoformat(timespec='seconds'))


def parse_vaneck_smh(text,now=None):
    plain=' '.join(text.split());now=now or datetime.now(timezone.utc)
    if 'VanEck Semiconductor ETF' not in plain or not re.search(r'\bSMH\b',plain):raise ValueError('基金身份不匹配')
    day=re.search(r'As of ([A-Za-z]+ \d{1,2}, \d{4})',plain)
    value=re.search(r'Price/Earnings Ratio\*?\s+([\d.]+)',plain,re.I)
    if not day or not value:raise ValueError('发行人PE或日期缺失')
    asof=datetime.strptime(day.group(1),'%B %d, %Y').date()
    if asof>now.date():raise ValueError('发行人日期超前')
    return dict(ticker='SMH',pe=float(value.group(1)),asof=asof.isoformat(),source='VanEck 官方月度报告',
                url=SMH_FACTSHEET,basis='发行人组合市盈率（报告口径）',history=[],percentile=None,
                years=0,samples=0,fetched_at=now.isoformat(timespec='seconds'))


def percentile(snapshot,years=10):
    end=date.fromisoformat(snapshot['asof']);current=snapshot['pe']
    samples={}
    for row in snapshot['history']:
        day=date.fromisoformat(row['date'])
        if 0<row['pe'] and day<=end and (end-day).days<=years*365.25:
            samples[(day.year,day.month)]=row
    rows=sorted(samples.values(),key=lambda r:r['date'])
    if len(rows)<30:return dict(percentile=None,years=0,samples=len(rows))
    span=(end-date.fromisoformat(rows[0]['date'])).days/365.25
    if span<2.5:return dict(percentile=None,years=round(span,1),samples=len(rows))
    values=[r['pe'] for r in rows]
    rank=(sum(v<current for v in values)+.5*sum(v==current for v in values))/len(values)*100
    return dict(percentile=round(rank,1),years=min(years,round(span,1)),samples=len(values),
                start=rows[0]['date'],end=snapshot['asof'])


def parse_world_pe(text,ticker,url):
    root=html.fromstring(text);plain=' '.join(root.text_content().split())
    current=re.search(r'estimated Price-to-Earnings \(P/E\) Ratio for .+? is ([\d.]+), calculated on (\d{1,2} [A-Za-z]+ \d{4})',plain)
    series=re.search(r'detailPE_data\s*=\s*\[(.*?)\];',text,re.S)
    if not current or not series:raise ValueError('PE字段缺失')
    history=[]
    for yy,mm,dd,pe in re.findall(r'\[Date.UTC\((\d{4}),\s*(\d+),\s*(\d+)\),\s*([\d.]+)\]',series.group(1)):
        value=float(pe)
        if value>0:history.append(dict(date=date(int(yy),int(mm)+1,int(dd)).isoformat(),pe=value))
    asof=datetime.strptime(current.group(2),'%d %B %Y').date().isoformat()
    if len(history)<30:raise ValueError('PE历史不足')
    # The provider estimates ETF PE. Do not mix with another provider's index
    # reported-earnings PE or claim this is forward 12-month PE.
    result=dict(ticker=ticker,pe=float(current.group(1)),asof=asof,history=history,
                source='World PE Ratio',url=url,basis='ETF 组合市盈率估计（来源口径）',
                fetched_at=datetime.now(timezone.utc).isoformat(timespec='seconds'))
    result.update(percentile(result));return result


def fetch_fund_valuations(config):
    from concurrent.futures import ThreadPoolExecutor,as_completed
    from data_service import http_get,HEADERS,configured_proxy
    def one(ticker,url):
        try:
            r=http_get(url,headers=HEADERS,timeout=(5,15),proxies=configured_proxy(config))
            r.raise_for_status()
            if ticker in ('VGT','SMH'):
                if len(r.content)>5_000_000:raise ValueError('发行人报告大小异常')
                reader=PdfReader(BytesIO(r.content))
                report='\n'.join(page.extract_text() or '' for page in reader.pages[:3])
                row=parse_vanguard_vgt(report) if ticker=='VGT' else parse_vaneck_smh(report)
                if ticker=='SMH':
                    row['history_status']='发行人未公开历史PE序列；仅显示官方当前PE'
                if ticker=='VGT':
                    proxy=http_get(VGT_HISTORY_PROXY,headers=HEADERS,timeout=(5,15),proxies=configured_proxy(config))
                    proxy.raise_for_status();history_row=parse_world_pe(proxy.text,'VGT',VGT_HISTORY_PROXY)
                    row['history']=history_row['history'];row.update(percentile(row));row['history_status']='VGT历史分位采用标普500信息技术行业PE代理；当前PE仍来自先锋官方报告';row['history_proxy']=True
            else:row=parse_world_pe(r.text,ticker,url)
            return ticker,row,None
        except (requests.RequestException,ValueError,TypeError,KeyError) as first:
            try:
                r=http_get(url,headers=HEADERS,timeout=(8,25),proxies=configured_proxy(config,for_google=True))
                r.raise_for_status()
                if ticker=='SMH':
                    reader=PdfReader(BytesIO(r.content));row=parse_vaneck_smh('\n'.join(page.extract_text() or '' for page in reader.pages[:3]));row['history_status']='发行人未公开历史PE序列；仅显示官方当前PE'
                elif ticker=='VGT':
                    reader=PdfReader(BytesIO(r.content));row=parse_vanguard_vgt('\n'.join(page.extract_text() or '' for page in reader.pages[:3]))
                    proxy=http_get(VGT_HISTORY_PROXY,headers=HEADERS,timeout=(8,25),proxies=configured_proxy(config,for_google=True));proxy.raise_for_status();history_row=parse_world_pe(proxy.text,'VGT',VGT_HISTORY_PROXY);row['history']=history_row['history'];row.update(percentile(row));row['history_status']='VGT历史分位采用标普500信息技术行业PE代理；当前PE仍来自先锋官方报告';row['history_proxy']=True
                else:row=parse_world_pe(r.text,ticker,url)
                return ticker,row,None
            except Exception:return ticker,None,type(first).__name__
    rows={};health=[]
    with ThreadPoolExecutor(max_workers=3) as pool:
        sources=dict(URLS)
        if 'VGT' in config.get('watchlist',[]):sources['VGT']=VGT_FACTSHEET
        if 'SMH' in config.get('watchlist',[]):sources['SMH']=SMH_FACTSHEET
        fs=[pool.submit(one,t,u) for t,u in sources.items()]
        for f in as_completed(fs):
            t,row,error=f.result()
            if row:rows[t]=row
            health.append(dict(source='基金估值 '+t,status='ok' if row else 'error',reason=error))
    if 'QQQ' in rows:
        rows['QQQM']={**rows['QQQ'],'ticker':'QQQM','proxy_ticker':'QQQ',
                       'basis':'同一纳斯达克100指数，采用QQQ估值代理'}
    return rows,health
