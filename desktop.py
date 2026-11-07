"""WebView desktop shell backed by local data and research services."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import copy
import logging
import os
import re
import sys
import threading
import time
import webbrowser

import requests

import data_service
import main
import market_model
import market_view
import valuation
import event_intelligence
from signals import analyze_history, flow_proxy, scenario
from translation_service import TranslationStore

APP_NAME = '衡势'
ASSETS = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / 'frontend'
LOCAL_TZ = timezone(timedelta(hours=8))
MARKET_SAMPLE=('IWM','RSP','XLF','XLE','XLI','XLY')


def local_time(value):
    if not value: return '时间未提供'
    try:return datetime.fromisoformat(value).astimezone(LOCAL_TZ).strftime('%m-%d %H:%M')
    except (ValueError,TypeError):return str(value)[:16]


def full_local_time(value):
    if not value:return '时间未提供'
    try:return datetime.fromisoformat(value).astimezone(LOCAL_TZ).strftime('%Y-%m-%d %H:%M')
    except (ValueError,TypeError):return str(value)[:19]


def trade_date(value):
    try:return datetime.strptime(value,'%b %d, %Y').strftime('%Y-%m-%d')
    except (ValueError,TypeError):return value or ''


MONTHS={'Jan':1,'Feb':2,'Mar':3,'Apr':4,'May':5,'Jun':6,'Jul':7,'Aug':8,
        'Sep':9,'Oct':10,'Nov':11,'Dec':12}


def chinese_period(value):
    def convert(match):
        return f'{match.group(2)}年{MONTHS[match.group(1)]}月'
    return re.sub(r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) (\d{4})\b',convert,value or '')


def source_name(value):
    names={'Federal Reserve · Press Releases':'美国联邦储备委员会',
           'SEC · Press Releases':'美国证券交易委员会',
           'Yahoo Finance · Markets':'雅虎财经',
           'Google News · World Markets':'全球市场聚合',
           'Google News · AI Infrastructure':'人工智能与算力聚合',
           'Google News · Geopolitics':'全球政策聚合',
           'Google News · Semiconductor Leaders':'半导体龙头新闻聚合',
           'Google News · AI Compute Leaders':'人工智能算力新闻聚合',
           'Google News · Optical Interconnect':'光通信新闻聚合',
           'Google News · Memory Leaders':'全球存储新闻聚合',
           'New York Times · Business':'纽约时报商业版',
           'Bloomberg · Markets':'彭博市场',
           'Seeking Alpha · Market Currents':'Seeking Alpha 市场快讯',
           'Investing · Markets':'Investing 市场资讯',
           'Google News · CNBC Tech':'CNBC 科技新闻聚合',
           'Google News · Reuters Markets':'路透市场新闻聚合',
           'Nasdaq':'纳斯达克','FRED':'圣路易斯联储'}
    if value in names:return names[value]
    if value.startswith('Google News · '):return '公司新闻聚合 · '+value.split(' · ',1)[1]
    if value.startswith('即时检索 · '):return '即时检索 · '+value.split(' · ',1)[1]
    if value.startswith('EPS '):return '盈利预测 · '+value[4:]
    if value.startswith('历史 '):return '历史行情 · '+value[3:]
    return value


COMPANY_NAMES={'QQQ':'纳斯达克100指数基金','SPY':'标普500指数基金',
               'QQQM':'纳斯达克100低费率基金','SMH':'半导体指数基金',
               'ORCL':'甲骨文','MRVL':'迈威尔科技','MU':'美光科技',
               'LITE':'卢门特姆','INTC':'英特尔','AVGO':'博通','^VIX':'波动率指数',
               'NVDA':'英伟达','AMD':'超威半导体','TSM':'台积电','ASML':'阿斯麦',
               'AMAT':'应用材料','KLAC':'科磊','LRCX':'泛林集团','ARM':'安谋',
               'QCOM':'高通','COHR':'相干公司','ANET':'阿里斯塔网络',
               'MSFT':'微软','AMZN':'亚马逊','GOOGL':'谷歌母公司'}


def health_reason(value):
    names={'ReadTimeout':'读取超时','ConnectTimeout':'连接超时','ConnectionError':'连接中断',
           'HTTP 403':'来源拒绝访问','HTTP 429':'请求过频','JSONDecodeError':'返回数据无效',
           '需确认具体证券代码':'代码待确认','未来四季 EPS 预期不足':'未来四季预期不足',
           'unsupported':'暂不支持','error':'连接异常','unresolved':'代码待确认'}
    return names.get(value,value or '')


def recent_negative(news,ticker):
    now=datetime.now(timezone.utc)
    for article in news:
        if ticker not in article['tickers'] or article['label']!='偏负面':continue
        grade=article.get('grade') or data_service.event_profile(article['source'],article['title'],article['impact'])[0]
        if grade not in ('S1','S2'):continue
        try:
            age=now-datetime.fromisoformat(article['published'])
            if timedelta(0)<=age<=timedelta(days=3):return True
        except (ValueError,TypeError):pass
    return False


def current_price_gap(quote,comparison):
    if not quote or not comparison:return None
    try:
        gap_seconds=abs((datetime.fromisoformat(quote['fetched_at'])-
                         datetime.fromisoformat(comparison['fetched_at'])).total_seconds())
        if gap_seconds>86400:return None
        if not isinstance(comparison.get('price'),(int,float)) or quote['price']<=0:return None
        return (comparison['price']/quote['price']-1)*100
    except (ValueError,TypeError,KeyError,ZeroDivisionError):
        return None


def merge_news(existing,incoming,limit=400):
    combined={data_service.title_key(row['title']) or row['link']:row for row in existing}
    for row in incoming:
        key=data_service.title_key(row['title']) or row['link']
        old=combined.get(key)
        if old:
            publishers=set(old.get('independent_publishers') or [])
            publishers.update(row.get('independent_publishers') or [])
            row['independent_publishers']=sorted(publishers)
        combined[key]=row
    return sorted(combined.values(),key=lambda row:row.get('published',''),reverse=True)[:limit]


class DesktopAPI:
    def __init__(self):
        main.init_db()
        self.lock=threading.RLock()
        self.settings=main.load_settings()
        self.translation=TranslationStore(main.APP_DIR/'translations.sqlite3')
        self.news,self.quotes,self.health=main.load_snapshot(self.settings['watchlist'])
        self.estimates=main.load_estimates(self.settings['watchlist'])
        self.histories=main.load_histories(self.settings['watchlist']+list(MARKET_SAMPLE))
        self.positions=main.load_positions()
        self.holding_flags=main.load_holding_flags()
        self.neutral=main.load_neutral_multiples()
        self.management=main.load_management_guidance()
        self.comparisons=main.load_comparisons(self.settings['watchlist'])
        self.fear_greed=main.load_market_extra('cnn_fear_greed')
        self.sp500_breadth=main.load_market_extra('sp500_breadth')
        self._model_key=None
        self._model_result=None
        self.busy=False
        self.search_busy=False
        self.search_status=''
        self.search_result_count=0
        self.search_query=''
        self.last_search_urls=set()
        self.event_context_cache={}
        self.event_analysis=main.load_event_analysis()
        self.analyzing_events=set()
        self.translating=False
        self.status='本地历史已加载，正在连接来源' if self.news or self.quotes else '正在首次获取公开数据'
        self.last_sync=''
        self.revision=1
        if self.news:self._start_translation()
        self.refresh()
        threading.Thread(target=self._scheduler,daemon=True).start()

    def _scheduler(self):
        while True:
            with self.lock:
                seconds=max(120,int(self.settings.get('refresh_seconds',300)))
            time.sleep(seconds)
            self.refresh()

    def refresh(self):
        with self.lock:
            if self.busy:return {'ok':True,'message':'同步正在进行'}
            self.busy=True;self.status='正在同步新闻、行情与预期';self.revision+=1
            config=copy.deepcopy(self.settings)
        threading.Thread(target=self._refresh_worker,args=(config,),daemon=True).start()
        return {'ok':True,'message':'已开始同步'}

    def _refresh_worker(self,config):
        try:
            with ThreadPoolExecutor(max_workers=7) as pool:
                nf=pool.submit(main.fetch_news,config['watchlist'],config)
                qf=pool.submit(main.fetch_quotes,config['watchlist'],config)
                ef=pool.submit(data_service.fetch_estimates,config['watchlist'],config)
                hf=pool.submit(data_service.fetch_histories,config['watchlist']+list(MARKET_SAMPLE),config)
                cf=pool.submit(data_service.fetch_comparison,config['watchlist'],config)
                with self.lock:
                    cached_cnn=self.fear_greed
                    cached_breadth=self.sp500_breadth
                def should_fetch(item,seconds):
                    try:return (datetime.now(timezone.utc)-datetime.fromisoformat(item['fetched_at'])).total_seconds()>seconds
                    except (KeyError,TypeError,ValueError):return True
                cnn_future=pool.submit(data_service.fetch_cnn_fear_greed,config) if should_fetch(cached_cnn,1200) else None
                breadth_future=pool.submit(data_service.fetch_sp500_breadth,config) if should_fetch(cached_breadth,1800) else None
                news,nh=nf.result();quotes,qh=qf.result();estimates,eh=ef.result();histories,hh=hf.result()
                comparisons,ch=cf.result()
                cnn,cnn_health=cnn_future.result() if cnn_future else (cached_cnn,None)
                breadth,breadth_health=breadth_future.result() if breadth_future else (cached_breadth,None)
            quotes=data_service.reconcile_closed_quotes(quotes,histories)
            health=nh+qh+eh+hh+[ch]+[row for row in (cnn_health,breadth_health) if row]
            main.save_snapshot(quotes,health,estimates,histories,comparisons)
            if cnn:main.save_market_extra('cnn_fear_greed',cnn)
            if breadth:main.save_market_extra('sp500_breadth',breadth)
            with self.lock:
                if news:self.news=merge_news(self.news,news)
                self.quotes=main.load_snapshot(self.settings['watchlist'])[1]
                if health:self.health=health
                if estimates:self.estimates=main.load_estimates(self.settings['watchlist'])
                if histories:self.histories=main.load_histories(self.settings['watchlist']+list(MARKET_SAMPLE))
                if comparisons:self.comparisons=main.load_comparisons(self.settings['watchlist'])
                if cnn:self.fear_greed=cnn
                if breadth:self.sp500_breadth=breadth
                ok=sum(item['status']=='ok' for item in health)
                self.status=f'已同步 {ok}/{len(health)} 个来源'
                self.last_sync=datetime.now(LOCAL_TZ).strftime('%m-%d %H:%M')
                self.busy=False;self.revision+=1
            if news:self._start_translation()
            if news:self._start_priority_analysis()
        except Exception:
            logging.exception('Desktop refresh failed')
            with self.lock:
                self.status='同步失败，正在显示本地历史';self.busy=False;self.revision+=1

    def _start_translation(self):
        with self.lock:
            if self.translating:return
            self.translating=True
            prioritized=sorted(self.news,key=lambda article:article.get('published',''),reverse=True)
            texts=[article['title'] for article in prioritized if article['title']]
            config=copy.deepcopy(self.settings)
        last_report=[0.0]
        def progress(done,total):
            now=time.monotonic()
            if done<total and now-last_report[0]<2:
                return
            last_report[0]=now
            with self.lock:
                self.status=f'中文整理中 {done}/{total}'
                self.revision+=1
        def work():
            try:self.translation.translate_missing(texts,config,progress)
            except Exception:logging.exception('Translation failed')
            finally:
                with self.lock:
                    self.translating=False
                    self.status='中文信息已更新' if self.news else self.status
                    self.revision+=1
        threading.Thread(target=work,daemon=True).start()

    def _start_priority_analysis(self):
        now=datetime.now(timezone.utc)
        with self.lock:
            held=set(self.holding_flags)
            candidates=[]
            for item in self.news:
                try:
                    age=now-datetime.fromisoformat(item['published'])
                except (TypeError,ValueError):continue
                if not timedelta(0)<=age<=timedelta(days=3):continue
                if item['link'] in self.event_analysis or item['link'] in self.analyzing_events:continue
                if item['impact']=='高' or held.intersection(item['tickers']):
                    candidates.append(item)
            candidates.sort(key=lambda item:(item['impact']=='高', bool(held.intersection(item['tickers'])),item['published']),reverse=True)
            selected=candidates[:4]
            self.analyzing_events.update(item['link'] for item in selected)
        for item in selected:
            threading.Thread(target=self._analyze_article,args=(item,),daemon=True).start()

    def _analyze_article(self,article):
        try:
            with self.lock:
                config=copy.deepcopy(self.settings)
                histories=copy.deepcopy(self.histories)
            result=event_intelligence.analyze(article,config,histories)
            main.save_event_analysis(article['link'],result)
            with self.lock:
                self.event_analysis[article['link']]=result
                self.revision+=1
            if result.get('evidence'):
                self.translation.translate_missing(result['evidence'],config)
                result['evidence_zh']=[self.translation.get(text) or text for text in result['evidence']]
                main.save_event_analysis(article['link'],result)
                with self.lock:
                    self.event_analysis[article['link']]=result
                    self.revision+=1
        except Exception:
            logging.exception('Article intelligence failed')
        finally:
            with self.lock:self.analyzing_events.discard(article['link'])

    def get_event_intelligence(self,event_url):
        with self.lock:
            article=next((item for item in self.news if item['link']==event_url),None)
            cached=self.event_analysis.get(event_url)
        if not article:return {'ok':False,'message':'事件已更新'}
        if cached:return {'ok':True,'analysis':cached}
        self._analyze_article(article)
        with self.lock:result=self.event_analysis.get(event_url)
        return {'ok':bool(result),'analysis':result,'message':'已完成原文核验' if result else '原文分析暂不可用'}

    def search_global_news(self,query):
        query=' '.join(str(query).split())[:120]
        if len(query)<2:return {'ok':False,'message':'请输入至少两个字符进行即时检索'}
        with self.lock:
            if self.search_busy:return {'ok':False,'message':'上一轮检索尚未结束'}
            self.search_busy=True
            self.search_status=f'正在检索：{query}'
            self.search_result_count=0
            self.search_query=query
            self.last_search_urls=set()
            config=copy.deepcopy(self.settings)
            self.revision+=1
        def work():
            try:
                rows,health=data_service.search_news(query,config,main.sentiment_score,main.impact_level,
                                                     config['watchlist'])
                if health['status']!='ok':
                    raise ValueError(health.get('reason','检索来源异常'))
                for row in rows:
                    row['independent_publishers']=[row['publisher']] if row.get('publisher') else []
                main.save_events(rows)
                with self.lock:
                    self.news=merge_news(self.news,rows,limit=650)
                    self.health=[item for item in self.health if not item['source'].startswith('即时检索 · ')]+[health]
                    self.search_result_count=len(rows)
                    self.last_search_urls={row['link'] for row in rows}
                    self.search_status=f'检索完成：{len(rows)} 条'
                    self.search_busy=False
                    self.revision+=1
                texts=[row['title'] for row in rows if row['title']]
                self.translation.translate_missing(texts,config)
                with self.lock:self.revision+=1
            except Exception as exc:
                logging.warning('Global news search failed: %s',type(exc).__name__)
                with self.lock:
                    self.search_status=f'检索失败：{health_reason(str(exc))}'
                    self.search_busy=False
                    self.revision+=1
        threading.Thread(target=work,daemon=True).start()
        return {'ok':True,'message':f'正在检索：{query}'}

    def get_state(self):
        with self.lock:
            news=copy.deepcopy(self.news);quotes=copy.deepcopy(self.quotes)
            histories=copy.deepcopy(self.histories);estimates=copy.deepcopy(self.estimates)
            positions=copy.deepcopy(self.positions);neutral=dict(self.neutral)
            management=copy.deepcopy(self.management)
            holding_flags=set(self.holding_flags)
            comparisons=copy.deepcopy(self.comparisons)
            cnn=copy.deepcopy(self.fear_greed)
            breadth=copy.deepcopy(self.sp500_breadth)
            health=copy.deepcopy(self.health);watchlist=list(self.settings['watchlist'])
            status=self.status;revision=self.revision;busy=self.busy;last_sync=self.last_sync
            search_busy=self.search_busy;search_status=self.search_status;search_result_count=self.search_result_count
            search_query=self.search_query;search_urls=set(self.last_search_urls)
            analyses=dict(self.event_analysis)
            proxy=self.settings.get('https_proxy','')
        translated=self.translation.get_many(text for item in news for text in (item['title'],item['summary']))
        public_news=[]
        for index,article in enumerate(sorted(news,key=lambda item:item.get('published',''),reverse=True)):
            grade=article.get('grade') or data_service.event_profile(article['source'],article['title'],article['impact'])[0]
            topics=data_service.intelligence_topics(article['tickers'],article['title'])
            if 'SMH 行业相关' in topics:
                impact_note=f"标题初筛为{article['label']}，可能影响半导体板块风险偏好；对 SMH 的实际传导需核对 ETF 成分权重与行情反应。"
            else:
                impact_note=f"标题初筛为{article['label']}；基本面影响仍需原始公告和行情确认。"
            public_news.append({'id':index,'title':translated.get(article['title'],article['title']),
                'raw_title':article['title'],
                'summary':translated.get(article['summary'],article['summary']) if article['summary'] else '来源未提供摘要',
                'summary_translated':article['summary'] in translated if article['summary'] else True,
                'source':source_name(article['source']),'publisher':article.get('publisher') or '',
                'published':local_time(article.get('published')),
                'published_full':full_local_time(article.get('published')),
                'published_raw':article.get('published',''),'grade':grade,'direction':article['label'],
                'credibility':article.get('credibility') or data_service.event_profile(article['source'],article['title'],article['impact'])[1],
                'horizon':article.get('horizon') or '待评估','tickers':article['tickers'],
                'topics':topics,'impact_note':impact_note,
                'independent_publishers':article.get('independent_publishers') or [],
                'url':article['link'],'translated':article['title'] in translated})
            public_news[-1]['analysis']=analyses.get(article['link'])
            public_news[-1]['live_match']=article['link'] in search_urls
        quote_map={q['ticker']:q for q in quotes}
        estimate_map={item['ticker']:item for item in estimates}
        history_map={item['ticker']:item for item in histories}
        comparison_map={item['ticker']:item for item in comparisons}
        one_year=main.one_year_ntm_average()
        metrics={}
        for ticker,history in history_map.items():
            if ticker.startswith('^'):
                continue
            metric=analyze_history(history)
            if metric:
                try:
                    if (date.today()-date.fromisoformat(metric['date'])).days<=5:metrics[ticker]=metric
                except ValueError:pass
        held=holding_flags|{position['ticker'] for position in positions}
        watch=[];actions=[]
        for ticker in watchlist:
            q=quote_map.get(ticker);e=estimate_map.get(ticker)
            average=one_year.get(ticker,{}).get('average')
            comparison=comparison_map.get(ticker)
            price=q['price'] if q else None
            eps=e['eps'] if e else None
            price_gap=current_price_gap(q,comparison)
            conflict=price_gap is not None and abs(price_gap)>2.5
            is_fund=ticker in ('QQQ','SPY','QQQM','SMH') or ticker.startswith('^')
            calculated=valuation.calculate(q,e,comparison,neutral.get(ticker),management.get(ticker),average)
            if is_fund: calculated=valuation.calculate(q,None,None)
            watch.append({'ticker':ticker,'name':COMPANY_NAMES.get(ticker,'自选标的'),
                'price':price,'change':q['change'] if q else None,'asof':trade_date(q.get('asof')) if q else '',
                'quote_source':source_name(q.get('source','')) if q else '来源暂不可用',
                'price_label':q.get('price_label','最近可得价格') if q else '报价缺失',
                'market_status':q.get('market_status') if q else None,
                'is_realtime':q.get('is_realtime',False) if q else False,
                'eps_ntm':eps,'eps_period':chinese_period(e.get('period','')) if e else '',
                'eps_source':'纳斯达克分析师季度一致预期' if e else '',
                'eps_asof':local_time(e.get('fetched_at')) if e else '',
                'ntm_pe':price/eps if price is not None and eps and eps>0 else None,
                'neutral_pe':calculated['pe_used'],'fair_price':calculated['fair_price'],
                'upside_pct':calculated['upside_pct'],
                'neutral_source':calculated['pe_basis'],
                'valuation':calculated,
                'one_year_pe_average':average,
                'one_year_pe_samples':one_year.get(ticker,{}).get('samples',0),
                'comparison_price':comparison.get('price') if comparison else None,
                'comparison_next_fy_eps':comparison.get('next_fy_eps') if comparison else None,
                'comparison_fetched_at':local_time(comparison.get('fetched_at')) if comparison else '',
                'price_gap_pct':round(price_gap,2) if price_gap is not None else None,
                'quote_conflict':conflict,
                'analyst_target':q.get('target_price') if q else None,
                'target_source':'纳斯达克分析师一年目标价' if q and q.get('target_price') else '',
                'target_asof':local_time(q.get('target_fetched_at')) if q and q.get('target_price') else '',
                'is_held':ticker in held,'metric':metrics.get(ticker)})
            if ticker.startswith('^'):continue
            metric=metrics.get(ticker)
            q=quote_map.get(ticker);e=estimate_map.get(ticker)
            comparison=comparison_map.get(ticker)
            gap=current_price_gap(q,comparison)
            average=one_year.get(ticker,{}).get('average')
            fair=valuation.calculate(q,e,comparison,neutral.get(ticker),management.get(ticker),average)['fair_price']
            advice=scenario(metric,ticker in held,recent_negative(news,ticker),fair,
                            q.get('target_price') if q else None,data_conflict=gap is not None and abs(gap)>2.5)
            actions.append({'ticker':ticker,'held':ticker in held,'metric':metric,
                            'flow':flow_proxy(metric),'advice':advice})
        portfolio=[]
        for position in positions:
            q=quote_map.get(position['ticker']);value=q['price']*position['quantity'] if q else None
            portfolio.append({**position,'price':q['price'] if q else None,'value':value,
                              'profit':value-position['quantity']*position['cost'] if value is not None else None})
        market=main.market_regime(quotes,news)
        model_key=tuple((row['ticker'],row.get('fetched_at')) for row in histories)
        if model_key!=self._model_key:
            try:
                self._model_result=market_model.analyze_market(histories)
            except Exception:
                logging.exception('Market model failed')
                self._model_result={'available':False,'reason':'历史行情校验失败'}
            self._model_key=model_key
        series={ticker:history_map[ticker]['bars'][-30:] for ticker in ('QQQ','SMH','SPY') if ticker in history_map}
        market_assessment=market_view.compose(self._model_result,cnn,breadth)
        return {'revision':revision,'status':status,'busy':busy,'last_sync':last_sync,
                'search_busy':search_busy,'search_status':search_status,'search_result_count':search_result_count,
                'search_query':search_query,
                'news':public_news,'watch':watch,'portfolio':portfolio,'actions':actions,
                'market':{'label':market['label'],'score':market['score'],'up':market['up'],'down':market['down'],
                          'vix':quote_map.get('^VIX'),'qqq':metrics.get('QQQ'),'smh':metrics.get('SMH'),
                          'spy':metrics.get('SPY'),'series':series,'model':self._model_result,
                          'assessment':market_assessment},
                'health':[{'source':source_name(h['source']),'status':'正常' if h['status']=='ok' else health_reason(h.get('reason') or h['status']),
                           'count':h.get('count'),'checked':local_time(h.get('checked_at'))} for h in health],
                'settings':{'watchlist':watchlist,'auto_local_proxy':self.settings.get('auto_local_proxy',True),
                            'https_proxy':proxy,'openai_model':self.settings.get('openai_model','qwen3:4b')},
                'translation_pending':sum(not item['translated'] for item in public_news)}

    def save_watchlist(self,raw):
        if isinstance(raw,str):raw=re.split(r'[,，;；\s]+',raw)
        items=[]
        for ticker in raw:
            ticker=str(ticker).strip().upper()
            if ticker and not re.fullmatch(r'[A-Z^][A-Z0-9.^-]{0,12}',ticker):
                return {'ok':False,'message':f'证券代码无效：{ticker}'}
            if ticker and ticker not in items:items.append(ticker)
        if not items:return {'ok':False,'message':'观察列表不能为空'}
        front=[item for item in ('QQQ','SPY','QQQM','SMH') if item in items]
        ordered=front+[item for item in items if item not in front]
        with self.lock:
            self.settings['watchlist']=ordered;main.save_settings(self.settings)
            self.revision+=1
        self.refresh()
        return {'ok':True,'message':'观察列表已保存'}

    def save_position(self,ticker,quantity,cost):
        try:main.save_position(ticker,float(quantity),float(cost))
        except (ValueError,TypeError) as exc:return {'ok':False,'message':str(exc)}
        with self.lock:
            self.positions=main.load_positions();self.holding_flags=main.load_holding_flags();self.revision+=1
        return {'ok':True,'message':'持仓已保存'}

    def delete_position(self,ticker):
        main.delete_position(ticker)
        with self.lock:self.positions=main.load_positions();self.revision+=1
        return {'ok':True,'message':'持仓已删除'}

    def set_holding_status(self,ticker,held):
        try:main.set_holding_flag(ticker,bool(held))
        except ValueError as exc:return {'ok':False,'message':str(exc)}
        with self.lock:self.holding_flags=main.load_holding_flags();self.revision+=1
        return {'ok':True,'message':'持有状态已更新'}

    def save_neutral_pe(self,ticker,multiple):
        try:main.save_neutral_multiple(ticker,float(multiple))
        except (ValueError,TypeError) as exc:return {'ok':False,'message':str(exc)}
        with self.lock:self.neutral=main.load_neutral_multiples();self.revision+=1
        return {'ok':True,'message':'中性估值倍数已保存'}

    def save_guidance(self,ticker,eps,source_url):
        try:main.save_management_guidance(ticker,float(eps),source_url.strip())
        except (ValueError,TypeError,AttributeError) as exc:return {'ok':False,'message':str(exc)}
        with self.lock:
            self.management=main.load_management_guidance()
            self.revision+=1
        return {'ok':True,'message':'管理层指引已保存，按70%权重参与估值'}

    def save_network(self,proxy,auto):
        if proxy and not re.fullmatch(r'https?://[^\s]+',str(proxy)):
            return {'ok':False,'message':'代理地址需以 http:// 或 https:// 开头'}
        with self.lock:
            self.settings['https_proxy']=str(proxy).strip();self.settings['http_proxy']=str(proxy).strip()
            self.settings['auto_local_proxy']=bool(auto)
            main.save_settings(self.settings);self.revision+=1
        return {'ok':True,'message':'连接设置已保存'}

    def set_local_model(self,name):
        name=str(name).strip()
        if not name or len(name)>100:return {'ok':False,'message':'模型名称无效'}
        with self.lock:
            self.settings['openai_model']=name
            main.save_settings(self.settings)
            self.revision+=1
        return {'ok':True,'message':'本地模型已保存'}

    def open_url(self,url):
        if not isinstance(url,str) or not url.startswith(('https://','http://')):
            return {'ok':False,'message':'原文链接无效'}
        webbrowser.open(url)
        return {'ok':True}

    def analyze_event(self,event_url):
        with self.lock:
            article=next((row for row in self.news if row['link']==event_url),None)
            config=copy.deepcopy(self.settings)
        if article is None:
            return {'ok':False,'message':'事件已更新，请重新选择'}
        base=config.get('openai_base_url','http://localhost:11434/v1').rstrip('/')
        if not base.startswith(('http://localhost','http://127.0.0.1')):
            return {'ok':False,'message':'本版仅支持本机 Ollama 模型分析'}
        try:
            response=requests.get(base+'/models',timeout=(2,4))
            response.raise_for_status()
        except requests.RequestException:
            return {'ok':False,'message':'本地分析模型未启动。请先运行 Ollama 并下载所选模型。'}
        result=main.ai_analyze(article,config)
        if not result:return {'ok':False,'message':'未配置可用的本地分析模型'}
        return {'ok':True,'analysis':result}

    def translate_event(self,event_url):
        with self.lock:
            article=next((row for row in self.news if row['link']==event_url),None)
            config=copy.deepcopy(self.settings)
        if not article:return {'ok':False,'message':'事件已更新'}
        title=self.translation.translate_one(article['title'],config)
        summary=self.translation.translate_one(article['summary'],config) if article['summary'] else '来源未提供摘要'
        with self.lock:self.revision+=1
        return {'ok':True,'title':title,'summary':summary,
                'translated':title!=article['title'] or summary!=article['summary']}

    def event_market_context(self,event_url):
        with self.lock:
            cached=self.event_context_cache.get(event_url)
            if cached and time.time()-cached[0]<900:
                return cached[1]
            article=next((row for row in self.news if row['link']==event_url),None)
            config=copy.deepcopy(self.settings)
            existing_quotes={row['ticker']:row for row in self.quotes}
            existing_estimates={row['ticker']:row for row in self.estimates}
        if article is None:return {'ok':False,'message':'事件已更新'}
        tickers=[ticker for ticker in article['tickers'] if not ticker.startswith('^')][:3]
        if not tickers:return {'ok':True,'rows':[]}
        missing_quotes=[ticker for ticker in tickers if ticker not in existing_quotes]
        missing_estimates=[ticker for ticker in tickers if ticker not in existing_estimates]
        with ThreadPoolExecutor(max_workers=2) as pool:
            quote_future=pool.submit(data_service.fetch_quotes,missing_quotes,config) if missing_quotes else None
            estimate_future=pool.submit(data_service.fetch_estimates,missing_estimates,config) if missing_estimates else None
            if quote_future:
                fetched,_=quote_future.result()
                existing_quotes.update({row['ticker']:row for row in fetched})
            if estimate_future:
                fetched,_=estimate_future.result()
                existing_estimates.update({row['ticker']:row for row in fetched})
        rows=[]
        for ticker in tickers:
            quote_row=existing_quotes.get(ticker)
            estimate=existing_estimates.get(ticker)
            quote_day=trade_date(quote_row.get('asof')) if quote_row else ''
            try:
                event_day=datetime.fromisoformat(article['published']).astimezone(LOCAL_TZ).date().isoformat()
            except (ValueError,TypeError):
                event_day=''
            rows.append({'ticker':ticker,'name':COMPANY_NAMES.get(ticker,ticker),
                         'price':quote_row.get('price') if quote_row else None,
                         'change':quote_row.get('change') if quote_row else None,
                         'quote_day':quote_day,
                         'eps_ntm':estimate.get('eps') if estimate else None,
                         'ntm_pe':quote_row['price']/estimate['eps'] if quote_row and estimate and estimate.get('eps',0)>0 else None,
                         'target':quote_row.get('target_price') if quote_row else None,
                         'price_confirmation':'事件后尚无可用收盘数据' if event_day and quote_day and quote_day<event_day else '日涨跌仅供参考，不能单独归因于事件'})
        result={'ok':True,'rows':rows}
        with self.lock:self.event_context_cache[event_url]=(time.time(),result)
        return result


def main_entry():
    import webview
    api=DesktopAPI()
    window=webview.create_window(APP_NAME,str(ASSETS/'index.html'),js_api=api,width=1280,height=820,
                                 min_size=(950,640),background_color='#f3f6f8')
    def diagnose():
        time.sleep(3)
        logging.info('WebView state %s',window.evaluate_js("JSON.stringify({bridge:!!window.pywebview,api:!!window.pywebview?.api,boot:typeof boot,scripts:document.scripts.length})"))
        logging.info('Frontend DOM %s',window.evaluate_js("JSON.stringify({metrics:document.getElementById('eventMetrics').innerHTML.length,status:document.getElementById('sourceStatus').textContent,toast:document.getElementById('toast').textContent})"))
        window.evaluate_js("window.__probe='pending';window.pywebview.api.get_state().then(s=>{window.__probe='news:'+s.news.length;try{state=s;render();window.__probe+=' rendered'}catch(e){window.__probe=e.stack}}).catch(e=>window.__probe='bridge:'+e);")
        time.sleep(3)
        logging.info('Frontend probe %s',window.evaluate_js('window.__probe'))
    gui='cocoa' if sys.platform=='darwin' else 'edgechromium'
    webview.start(diagnose if os.getenv('NEXUS_DEBUG') else None,gui=gui,debug=bool(os.getenv('NEXUS_DEBUG')))


if __name__=='__main__':
    main_entry()
