"""Sector rotation from Chaikin money flow and relative returns; no fabricated dollar flows."""
from datetime import date

SECTORS = {'XLK':'科技','SMH':'半导体','XLV':'医药健康','XLP':'必需消费','XLU':'公用事业',
           'XLY':'可选消费','XLF':'金融','XLE':'能源','XLI':'工业','XLC':'通信服务',
           'XLRE':'房地产','XLB':'原材料','TLT':'长期美债','GLD':'黄金'}
DEFENSIVE = {'XLV','XLP','XLU','TLT','GLD'}


def rotation(histories, horizon=5, today=None):
    histories = {h['ticker']:h['bars'] for h in histories}
    spy = histories.get('SPY') or []
    if len(spy) <= horizon: return {'available':False,'reason':'标普及板块历史不足'}
    day = spy[-1]['date']; today = today or date.today()
    benchmark = (spy[-1]['close']/spy[-horizon-1]['close']-1)*100
    rows = []
    for ticker, name in SECTORS.items():
        bars = [b for b in histories.get(ticker,[]) if b['date']<=day]
        if len(bars)<=max(horizon,20) or bars[-1]['date']!=day: continue
        window = bars[-horizon:]; volume = sum(b['volume'] for b in window)
        if not volume: continue
        cmf = sum(((2*b['close']-b['high']-b['low'])/(b['high']-b['low'])
                  if b['high']>b['low'] else 0)*b['volume'] for b in window)/volume
        ret = (bars[-1]['close']/bars[-horizon-1]['close']-1)*100
        avg = sum(b['volume'] for b in bars[-horizon-20:-horizon])/20
        rows.append(dict(ticker=ticker,name=name,pressure=round(cmf*100,1),
                         return_pct=round(ret,2),relative_pct=round(ret-benchmark,2),
                         volume_ratio=round(volume/horizon/avg,2) if avg else None,
                         defensive=ticker in DEFENSIVE))
    rows.sort(key=lambda r:r['pressure'],reverse=True)
    defensive = [r for r in rows if r['defensive'] and r['relative_pct']>0 and r['pressure']>0]
    leaders = [r['name'] for r in rows if r['pressure']>10 and r['relative_pct']>0][:3]
    laggards = [r['name'] for r in reversed(rows) if r['pressure']< -10 and r['relative_pct']<0][:3]
    smh = next((r for r in rows if r['ticker']=='SMH'),None)
    headline = ('防御资产相对走强，风险偏好偏谨慎' if len(defensive)>=3 else
                '板块分化，关注价格与承接是否同步' if leaders and laggards else '资金偏好尚未形成一致方向')
    evidence = []
    if leaders: evidence.append('承接与相对强弱同时改善：'+'、'.join(leaders))
    if laggards: evidence.append('卖压与相对弱势同时出现：'+'、'.join(laggards))
    if smh: evidence.append(f"半导体区间涨跌 {smh['return_pct']:+.2f}%，相对标普 {smh['relative_pct']:+.2f} 个百分点，承接得分 {smh['pressure']:+.1f}")
    if len(defensive)>=3: action='优先检查科技与半导体集中风险；等待相对跌幅收敛及承接得分转正，再评估加仓。'
    elif smh and smh['pressure']>10 and smh['relative_pct']>0: action='半导体出现相对修复，可结合个股关注区间评估分批参与；单日转强仍需后续确认。'
    else: action='优先跟踪相对大盘走强且承接为正的板块；价格走强但承接为负时，谨慎追涨。'
    return dict(available=len(rows)>=6,date=day,horizon=horizon,rows=rows,headline=headline,
                evidence=evidence,action=action,stale=(today-date.fromisoformat(day)).days>5,
                definition='承接得分=区间内每日成交量×收盘位置系数之和/总成交量×100；正值表示成交更集中在日内价格上半区。并非真实资金净流入或机构交易身份。')
