"""Free issuer/index PE time series, always compare within one source and basis."""
from datetime import date, datetime, timezone
import re
from lxml import html
import requests

URLS = {'QQQ':'https://worldperatio.com/index/nasdaq-100/',
        'SPY':'https://worldperatio.com/index/sp-500/'}


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
            r=http_get(url,headers=HEADERS,timeout=(4,10),proxies=configured_proxy(config))
            r.raise_for_status();return ticker,parse_world_pe(r.text,ticker,url),None
        except (requests.RequestException,ValueError,TypeError) as e:return ticker,None,type(e).__name__
    rows={};health=[]
    with ThreadPoolExecutor(max_workers=3) as pool:
        fs=[pool.submit(one,t,u) for t,u in URLS.items()]
        for f in as_completed(fs):
            t,row,error=f.result()
            if row:rows[t]=row
            health.append(dict(source='基金估值 '+t,status='ok' if row else 'error',reason=error))
    if 'QQQ' in rows:
        rows['QQQM']={**rows['QQQ'],'ticker':'QQQM','proxy_ticker':'QQQ',
                       'basis':'同一纳斯达克100指数，采用QQQ估值代理'}
    return rows,health
