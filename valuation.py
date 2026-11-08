"""Traceable forward valuation scenarios for individual stocks."""
from datetime import datetime, timezone, timedelta


def fresh(value, hours=72, now=None):
    now=now or datetime.now(timezone.utc)
    try:
        then=datetime.fromisoformat(value)
        return then.tzinfo is not None and timedelta(0)<=now-then<=timedelta(hours=hours)
    except (TypeError,ValueError):
        return False


def calculate(quote, consensus, comparison, neutral_pe=None, management=None, historical_pe=None, now=None):
    now=now or datetime.now(timezone.utc)
    price=quote.get('price') if quote else None
    analyst_eps=consensus.get('eps') if consensus and consensus.get('basis')=='ntm_4q' else None
    manager_eps=(management.get('eps') if management and management.get('period')=='未来12个月'
                 and management.get('source_url') and fresh(management.get('updated_at'),hours=24*180,now=now)
                 else None)
    if analyst_eps is not None and analyst_eps<=0: analyst_eps=None
    if manager_eps is not None and manager_eps<=0: manager_eps=None
    if manager_eps and analyst_eps:
        forward_eps=.7*manager_eps+.3*analyst_eps
        earnings_basis='管理层指引 70% + 分析师未来四季预期 30%'
    elif manager_eps:
        forward_eps=manager_eps
        earnings_basis='管理层未来12个月指引'
    else:
        forward_eps=analyst_eps
        earnings_basis='分析师未来四季一致预期' if analyst_eps else '未来12个月盈利预期不足'
    pe=None;pe_basis='市盈率数据不足'
    reported_eps=(consensus.get('reported_eps_ttm') if consensus
                  and consensus.get('reported_basis')=='nasdaq_earnings_surprise'
                  and fresh(consensus.get('fetched_at'),now=now) else None)
    comparable_pe=price/reported_eps if price and reported_eps and reported_eps>0 else None
    if neutral_pe and 0<neutral_pe<=500:
        pe=float(neutral_pe);pe_basis='用户设定中性市盈率'
    elif historical_pe and 0<historical_pe<=500:
        pe=float(historical_pe);pe_basis='本机过去一年平均未来市盈率'
    elif comparable_pe and 0<comparable_pe<=500:
        pe=float(comparable_pe);pe_basis='纳斯达克同源财报四季市盈率不变（供应商EPS口径）'
    elif comparison and fresh(comparison.get('fetched_at'),now=now):
        trailing=comparison.get('trailing_pe')
        if isinstance(trailing,(int,float)) and 0<trailing<=150:
            pe=float(trailing);pe_basis='TradingView 当前滚动市盈率不变'
    if pe is None and quote and fresh(quote.get('fetched_at'),now=now):
        trailing=quote.get('reported_trailing_pe')
        if isinstance(trailing,(int,float)) and 0<trailing<=150:
            pe=float(trailing);pe_basis='CNBC 当前滚动市盈率不变'
    fair=round(forward_eps*pe,2) if forward_eps and pe else None
    upside=round((fair/price-1)*100,1) if fair is not None and price and price>0 else None
    return {'eps_used':round(forward_eps,4) if forward_eps else None,
            'earnings_basis':earnings_basis,'management_eps':manager_eps,'analyst_eps':analyst_eps,
            'management_source':management.get('source_url') if manager_eps else None,
            'pe_used':round(pe,2) if pe else None,'pe_basis':pe_basis,
            'fair_price':fair,'upside_pct':upside,
            'current_forward_pe':round(price/forward_eps,2) if price and forward_eps else None,
            'reported_eps_ttm':reported_eps,
            'reported_period':consensus.get('reported_period') if consensus else None,
            'reported_source':consensus.get('reported_source_url') if reported_eps is not None else None,
            'reported_quarters':consensus.get('reported_quarters',[]) if consensus else [],
            'accounting_ttm_eps':quote.get('reported_ttm_eps') if quote else None,
            'pe_note':'财报与预测EPS采用供应商口径，可能经过调整，与会计准则滚动PE不可直接混用' if reported_eps is not None else '',
            'method':'未来12个月每股盈利 × 市盈率不变情景',
            'asof':now.isoformat(timespec='seconds')}
