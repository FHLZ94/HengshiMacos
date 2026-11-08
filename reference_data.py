"""Historical reported-earnings PE observations, never current-EPS backfills."""
from datetime import datetime,timezone,timedelta
from statistics import median
import json,re
import requests
from data_service import http_get,HEADERS,configured_proxy
from valuation import fresh

SLUGS={'ORCL':'oracle','MRVL':'marvell-technology-group','MU':'micron-technology',
       'LITE':'lumentum','INTC':'intel','AVGO':'broadcom','GOOG':'alphabet-google','SKHY':'sk-hynix'}


def parse_history(text,ticker,url,now=None):
    now=now or datetime.now(timezone.utc)
    title=re.search(r'<title>(.*?)</title>',text,re.S|re.I)
    identities=(ticker,'000660.KS') if ticker=='SKHY' else (ticker,)
    if not title or not any('('+t+')' in title.group(1) for t in identities):raise ValueError('历史估值证券身份不匹配')
    match=re.search(r'\bdata\s*=\s*(\[\s*\{.*?\}\s*\])\s*;',text,re.S)
    if not match:raise ValueError('历史PE数据缺失')
    raw=json.loads(match.group(1));cutoff=now-timedelta(days=365.25*5);quarters={}
    for item in raw:
        try:
            day=datetime.fromtimestamp(float(item['d']),timezone.utc);value=float(item['v'])
            if not cutoff<=day<=now or not 0<value<1000:continue
            key=(day.year,(day.month-1)//3)
            if key not in quarters or day>quarters[key][0]:quarters[key]=(day,value)
        except (ValueError,KeyError,TypeError):continue
    values=sorted(quarters.values())
    if len(values)<12 or (values[-1][0]-values[0][0]).days<365*3:raise ValueError('有效历史不足三年及12个季度')
    return {'ticker':ticker,'median':round(median(v for _,v in values),4),'basis':'reported',
            'samples':len(values),'years':round((values[-1][0]-values[0][0]).days/365.25,1),
            'start':values[0][0].date().isoformat(),'asof':values[-1][0].date().isoformat(),
            'fetched_at':now.isoformat(timespec='seconds'),'source':'CompaniesMarketCap 历史滚动PE',
            'source_url':url,'definition':'近五年正盈利季度的历史滚动PE中位数；同季度保留最后观测，亏损及不适用PE不纳入'}


def fetch_histories(tickers,config):
    from concurrent.futures import ThreadPoolExecutor,as_completed
    def one(ticker):
        cached=(config.get('_pe_cached') or {}).get(ticker)
        if cached and fresh(cached.get('fetched_at'),24):return ticker,cached,None
        url='https://companiesmarketcap.com/'+SLUGS[ticker]+'/pe-ratio/'
        try:
            r=http_get(url,headers=HEADERS,proxies=configured_proxy(config,for_google=True),timeout=(4,9));r.raise_for_status()
            return ticker,parse_history(r.text,ticker,url),None
        except (requests.RequestException,ValueError,TypeError) as e:return ticker,None,type(e).__name__
    result={};health=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures=[pool.submit(one,t) for t in dict.fromkeys(tickers) if t in SLUGS]
        for future in as_completed(futures):
            t,row,error=future.result()
            if row:result[t]=row
            health.append({'source':'历史估值 '+t,'status':'ok' if row else 'error','reason':error})
    return result,health
