"""One canonical twelve-month reference per security; used by every view."""
from datetime import datetime,timezone,timedelta
from math import isfinite
from statistics import median


def number(value):
    return float(value) if isinstance(value,(int,float)) and isfinite(value) else None


def fresh(value,hours=72,now=None):
    now=now or datetime.now(timezone.utc)
    try:
        then=datetime.fromisoformat(value)
        return then.tzinfo is not None and timedelta(0)<=now-then<=timedelta(hours=hours)
    except (TypeError,ValueError):return False


def current_pe(quote,comparison,now):
    quote=quote or {};comparison=comparison or {};price=number(quote.get('price'))
    eps=number(quote.get('reported_ttm_eps'))
    if eps is not None:
        if eps<=0:return None,'亏损，不适用','CNBC 会计口径滚动盈利'
        if price and price>0:return round(price/eps,2),'有效','最近报价 ÷ 会计口径历史12个月EPS'
    pe=number(quote.get('reported_trailing_pe'))
    if pe is not None and pe<=0:return None,'亏损，不适用','会计口径历史盈利非正'
    if pe and fresh(quote.get('fetched_at'),hours=24*14,now=now):
        close=number(quote.get('regular_close')) or price
        return round(pe*price/close,2) if price and close else pe,'有效','CNBC 当前滚动PE'
    pe=number(comparison.get('trailing_pe'))
    if pe and pe>0 and fresh(comparison.get('fetched_at'),hours=24*14,now=now):
        base=number(comparison.get('price'))
        return round(pe*price/base,2) if price and base else pe,'有效','TradingView 当前滚动PE'
    return None,'待有效数据','当前滚动PE来源暂缺'


def analyst_reference(quote,comparison,now):
    for source in (comparison or {},quote or {}):
        rows=source.get('target_quotes') or [];latest={}
        for row in rows:
            value=number(row.get('price'));firm=str(row.get('firm') or '').strip()
            if value and value>0 and firm and fresh(row.get('published'),24*180,now):
                if firm not in latest or row['published']>latest[firm]['published']:latest[firm]=row
        if len(latest)>=3:
            return round(median(r['price'] for r in latest.values()),2),{'method':'analyst_median',
                'label':'分析师目标价中位数','source':source.get('target_source') or source.get('source',''),
                'source_url':source.get('target_url'),'fetched_at':source.get('fetched_at'),
                'count':len(latest),'quotes':list(latest.values())}
        value=number(source.get('target_median'))
        if value and value>0 and fresh(source.get('fetched_at'),24*14,now):
            return round(value,2),{'method':'analyst_median','label':'分析师目标价中位数',
                'source':source.get('target_source') or 'TradingView 分析师综合预测',
                'source_url':source.get('target_url'),'fetched_at':source.get('fetched_at'),
                'count':source.get('target_count'),'quotes':[]}
    return None,{'method':'unavailable','label':'等待分析师中位数','source':'','quotes':[]}


def calculate(quote,consensus=None,comparison=None,neutral_pe=None,management=None,historical_pe=None,now=None):
    now=now or datetime.now(timezone.utc);quote=quote or {};price=number(quote.get('price'))
    pe,status,pe_source=current_pe(quote,comparison,now)
    target,reference=analyst_reference(quote,comparison,now)
    history=historical_pe if isinstance(historical_pe,dict) else {}
    guidance=management or {};eps=number(guidance.get('eps'));history_median=number(history.get('median'))
    valid_guidance=(eps and eps>0 and guidance.get('period')=='未来12个月' and guidance.get('source_url')
                    and fresh(guidance.get('updated_at'),24*180,now))
    matching=(guidance.get('eps_basis') in ('reported','adjusted') and guidance.get('eps_basis')==history.get('basis'))
    valid_history=(history_median and history_median>0 and history.get('samples',0)>=12
                   and history.get('years',0)>=3 and fresh(history.get('fetched_at'),24*30,now))
    reason=''
    if valid_guidance and valid_history and matching:
        target=round(eps*history_median,2)
        reference={'method':'management_history_median','label':'管理层指引 × 历史PE中位数',
            'source':history.get('source'),'source_url':history.get('source_url'),
            'guidance_url':guidance['source_url'],'fetched_at':history.get('fetched_at'),
            'history_samples':history['samples'],'history_years':history['years'],'quotes':[]}
    elif valid_guidance:
        reason='管理层指引与可用历史PE缺少一致口径，采用分析师中位数' if not matching else '历史PE样本不足，采用分析师中位数'
    else:reason='缺少明确覆盖未来12个月的管理层EPS指引，采用分析师中位数'
    if target is None:reason+='；中位数尚未取得，保留空缺'
    upside=round((target/price-1)*100,1) if target and price and price>0 else None
    return {'current_pe':pe,'pe_status':status,'current_pe_source':pe_source,
            'reference_price':target,'fair_price':target,'upside_pct':upside,'reference':reference,
            'reference_method':reference['method'],'reference_label':reference['label'],'reason':reason,
            'pe_used':round(history_median,2) if reference['method']=='management_history_median' else None,
            'pe_basis':reference['label'],'eps_used':eps if reference['method']=='management_history_median' else None,
            'management_eps':eps if valid_guidance else None,'management_source':guidance.get('source_url') if valid_guidance else None,
            'historical_median':history_median,'historical_pe':history,
            'method':reference['label'],'asof':now.isoformat(timespec='seconds')}
