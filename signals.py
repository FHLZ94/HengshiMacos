"""Evidence-first short-horizon scenarios from daily price and volume history."""
from datetime import date, datetime, timezone


def analyze_history(history):
    bars=history.get('bars') or []
    if len(bars)<21:
        return None
    if any(not all(key in row for key in ('date','close','high','low','volume')) for row in bars):
        return None
    closes=[float(row['close']) for row in bars]
    volumes=[int(row['volume']) for row in bars]
    if min(closes[-21:])<=0 or sum(volumes[-21:-1])<=0:
        return None
    last, previous=bars[-1],bars[-2]
    ma5=sum(closes[-5:])/5
    ma20=sum(closes[-20:])/20
    return5=(closes[-1]/closes[-6]-1)*100
    day_change=(closes[-1]/closes[-2]-1)*100
    volume_ratio=volumes[-1]/(sum(volumes[-21:-1])/20)
    previous_ratio=volumes[-2]/(sum(volumes[-22:-2])/20) if len(bars)>=22 and sum(volumes[-22:-2])>0 else None
    true_ranges=[max(float(bars[i]['high'])-float(bars[i]['low']),
                     abs(float(bars[i]['high'])-closes[i-1]),abs(float(bars[i]['low'])-closes[i-1]))
                 for i in range(max(1,len(bars)-14),len(bars))]
    close_position=(float(last['close'])-float(last['low']))/(float(last['high'])-float(last['low'])) if float(last['high'])>float(last['low']) else None
    trend=('上行' if closes[-1]>ma5>ma20 and return5>0 else
           '下行' if closes[-1]<ma5<ma20 and return5<0 else '震荡')
    return {'ticker':history['ticker'],'date':last['date'],'price':closes[-1],'close_price':closes[-1],
            'atr14':round(sum(true_ranges)/len(true_ranges),4),
            'ma5':round(ma5,2),'ma20':round(ma20,2),'return5':round(return5,2),
            'support20':round(min(float(row['low']) for row in bars[-20:]),2),
            'resistance20':round(max(float(row['high']) for row in bars[-20:]),2),
            'day_change':round(day_change,2),'volume_ratio':round(volume_ratio,2),
            'previous_volume_ratio':round(previous_ratio,2) if previous_ratio is not None else None,
            'previous_change':round((closes[-2]/closes[-3]-1)*100,2),
            'volume_vs_previous':round(volumes[-1]/volumes[-2],2) if volumes[-2]>0 else None,
            'close_position':round(close_position,2) if close_position is not None else None,
            'trend':trend,'bars':len(bars)}


def flow_proxy(metric):
    if not metric:
        return '量价数据不足'
    if metric['previous_change']<=-2 and (metric['previous_volume_ratio'] or 0)>=1.4 and metric['day_change']>0.5:
        if (metric['volume_vs_previous'] or 0)>=1 and (metric['close_position'] or 0)>=0.7:
            return '杀跌后放量修复；买盘代理增强，仍需后续确认'
        return '杀跌后反弹量能不足；尚不能确认持续买盘'
    if metric['day_change']<0 and metric['volume_ratio']>=1.5:
        return '放量下跌；卖压代理增强'
    if metric['day_change']>0 and metric['volume_ratio']>=1.5:
        return '放量上涨；买盘代理增强'
    return '量价未出现显著异常'


def scenario(metric, held=False, negative_event=False, fair_price=None, analyst_target=None, data_conflict=False):
    if not metric:
        return {'action':'等待数据','horizon':'1-5个交易日','basis':'历史行情不足',
                'confirm':'取得至少21个有效交易日数据','invalidate':'—',
                'watch_zone':None,'buy_trigger':None,'risk_price':None,'valuation':'估值待核验'}
    price=metric['price']
    support=metric['support20']
    zone_low=round(support*1.005,2)
    zone_high=round(support*1.08,2)
    trigger=round(max(metric['ma5'],support*1.025),2)
    risk=round(support*.975,2)
    atr=metric.get('atr14')
    if atr and atr>0:
        zone_low=round(support+.1*atr,2)
        zone_high=round(support+atr,2)
        trigger=round(max(metric['ma5'],support+.5*atr),2)
        risk=round(max(.01,support-.75*atr),2)
    fair_gap=(fair_price/price-1)*100 if fair_price and price>0 else None
    target_gap=(analyst_target/price-1)*100 if analyst_target and price>0 else None
    cheap=fair_gap is not None and fair_gap>=15
    target_discount=target_gap is not None and target_gap>=25
    near_support=price<=zone_high
    reversal=(metric['day_change']>0 and metric['close_position'] is not None
              and metric['close_position']>=.65 and metric['volume_ratio']>=1.1)
    if price<risk:
        action='支撑失效，复核风险' if held else '等待支撑重建'
        basis=f'最近报价已低于风险失效价 {risk:.2f}，原关注区间需要重新评估'
    elif cheap and near_support and reversal:
        action='分批买入候选' if not held else '分批加仓候选'
        basis=f'至中性估值参考空间 {fair_gap:.0f}%，接近20日低位且出现量价修复'
    elif (cheap or target_discount) and near_support and reversal:
        action='分批买入候选' if not held else '分批加仓候选'
        reason=f'至中性估值参考空间 {fair_gap:.0f}%' if cheap else f'至分析师一年目标价空间 {target_gap:.0f}%'
        basis=f'{reason}，进入低位区并出现收盘修复；须等待确认价'
    elif (cheap or target_discount) and near_support:
        action='重点关注'
        reason=f'至中性估值参考空间 {fair_gap:.0f}%' if cheap else f'至分析师一年目标价空间 {target_gap:.0f}%'
        basis=f'{reason}，价格进入20日低位区，等待承接确认'
    elif metric['trend']=='上行' and metric['volume_ratio']>=1.2 and (fair_gap is None or fair_gap>=-5):
        action='回撤买入候选' if not held else '持有，回撤加仓候选'
        basis=f'5日/20日趋势上行，量比 {metric["volume_ratio"]:.2f}；回撤到关注区再评估'
    elif negative_event and metric['trend']=='下行':
        action='风险复核' if held else '重点观察支撑'
        basis='近期高等级负面事件叠加20日趋势下行'
    elif near_support:
        action='重点关注'
        basis=f'距离20日低点较近；量比 {metric["volume_ratio"]:.2f}，等待收盘确认'
    else:
        action='持有观察' if held else '关注回撤价位'
        basis=f'当前价 {price:.2f}，距离20日低位区较远；短期趋势{metric["trend"]}'
    valuation=(f'中性估值合理价 {fair_price:.2f}，相对当前价 {fair_gap:+.0f}%'
               if fair_gap is not None else '中性估值尚未设定')
    if target_gap is not None:
        valuation+=f'；分析师一年目标价 {analyst_target:.2f}，相对当前价 {target_gap:+.0f}%'
    if negative_event:
        basis+='；近期有高等级负面事件待核验'
    if data_conflict:
        action='报价冲突，复核来源'
        basis='两个公开行情来源相差超过 2.5%，交易价位暂不作为动作依据'
    return {'action':action,'horizon':'1-5个交易日','basis':basis,
            'confirm':f'收盘站上 {trigger:.2f} 且量比达到 1.2；若在区间内修复，可考虑分批',
            'invalidate':f'跌破 {risk:.2f}（20日低点下方约0.75倍日均真实波幅）或盈利预期显著下修' if atr else f'跌破 {risk:.2f}（20日低点下方约2.5%）或盈利预期显著下修',
            'watch_zone':[zone_low,zone_high],'buy_trigger':trigger,
            'risk_price':risk,'valuation':valuation,
            'in_watch_zone':zone_low<=price<=zone_high,
            'trigger_confirmed':metric.get('close_price',price)>=trigger and metric['volume_ratio']>=1.2,
            'valuation_gap_pct':round(fair_gap,1) if fair_gap is not None else None,
            'target_gap_pct':round(target_gap,1) if target_gap is not None else None}
