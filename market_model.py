"""Historical analog probabilities, defined outcomes and chronological validation."""
from datetime import date
from math import sqrt

PARTICIPATION_ETFS=('QQQ','SPY','SMH','IWM','RSP','XLF','XLE','XLI','XLY')


def _pct(current, previous):
    return (current / previous - 1) * 100 if previous else 0.0


def _prepare(histories):
    mapping={row['ticker']:{bar['date']:bar for bar in row['bars']} for row in histories}
    if not all(ticker in mapping for ticker in ('QQQ','SPY','SMH','^VIX')):
        return []
    common=sorted(set(mapping['QQQ']) & set(mapping['SPY']) & set(mapping['SMH']))
    vix_dates=sorted(mapping['^VIX'])
    rows=[];vix_index=0
    for day in common:
        while vix_index+1<len(vix_dates) and vix_dates[vix_index+1]<=day:
            vix_index+=1
        vix_day=vix_dates[vix_index] if vix_dates and vix_dates[vix_index]<=day else None
        if not vix_day or (date.fromisoformat(day)-date.fromisoformat(vix_day)).days>4:
            continue
        rows.append({'date':day,'qqq':mapping['QQQ'][day],
                     'spy':mapping['SPY'][day],'smh':mapping['SMH'][day],
                     'vix':mapping['^VIX'][vix_day]['close'],'vix_date':vix_day})
    return rows


def _features(rows,index):
    if index<21:return None
    current=rows[index]
    qqq=current['qqq']
    recent=[row['qqq']['close'] for row in rows[index-19:index+1]]
    previous_volumes=[row['qqq']['volume'] for row in rows[index-20:index]]
    mean_volume=sum(previous_volumes)/20
    if not mean_volume or min(recent)<=0:return None
    return {'return5':_pct(qqq['close'],rows[index-5]['qqq']['close']),
            'ma20_gap':_pct(qqq['close'],sum(recent)/20),
            'drawdown20':_pct(qqq['close'],max(recent)),
            'volume_ratio':qqq['volume']/mean_volume,
            'spy5':_pct(current['spy']['close'],rows[index-5]['spy']['close']),
            'smh5':_pct(current['smh']['close'],rows[index-5]['smh']['close']),
            'vix':float(current['vix'])}


def _distance(left,right):
    scales={'return5':5,'ma20_gap':5,'drawdown20':6,'volume_ratio':0.7,
            'spy5':4,'smh5':7,'vix':12}
    return sum(((left[key]-right[key])/scale)**2 for key,scale in scales.items())


def _neighbors(rows,features,prior_index,count=45):
    candidates=[]
    for index in range(21,prior_index-10):
        other=_features(rows,index)
        if other:candidates.append((_distance(features,other),index))
    selected=[]
    for distance,index in sorted(candidates):
        if all(abs(index-prior)>=10 for _,prior in selected):
            selected.append((distance,index))
            if len(selected)>=count:break
    return selected


def _outcomes(rows,index):
    today=rows[index]['qqq']
    future=rows[index+1:index+11]
    if len(future)!=10:return None
    up5=future[4]['qqq']['close']>today['close']
    stable10=min(row['qqq']['low'] for row in future)>=today['low'] and future[-1]['qqq']['close']>today['close']
    return up5,stable10


def _wilson(success,total):
    if not total:return None
    z=1.96
    p=success/total
    denominator=1+z*z/total
    middle=(p+z*z/(2*total))/denominator
    spread=z*sqrt((p*(1-p)+z*z/(4*total))/total)/denominator
    return [round(max(0,middle-spread)*100,1),round(min(1,middle+spread)*100,1)]


def _regime(features):
    score=50
    score+=max(-18,min(18,features['return5']*2.1))
    score+=max(-12,min(12,features['ma20_gap']*1.6))
    score+=max(-12,min(8,(18-features['vix'])*0.8))
    score+=max(-8,min(8,(features['smh5']-features['spy5'])*0.8))
    score=max(0,min(100,round(score)))
    label=('极度悲观' if score<20 else '悲观' if score<35 else '偏谨慎' if score<46
           else '中性' if score<56 else '偏乐观' if score<69 else '乐观' if score<83 else '过热')
    return score,label


def analyze_market(histories):
    rows=_prepare(histories)
    if len(rows)<300:return {'available':False,'reason':'QQQ、SPY、SMH 与 VIX 的共同历史不足 300 日'}
    latest=len(rows)-1
    features=_features(rows,latest)
    if features is None:return {'available':False,'reason':'最近交易日历史数据不足'}
    near_low=features['drawdown20']<=-4
    neighbors=_neighbors(rows,features,latest)
    if len(neighbors)<30:return {'available':False,'reason':'独立相似样本少于 30 组'}
    outcomes=[_outcomes(rows,index) for _,index in neighbors]
    up_count=sum(item[0] for item in outcomes)
    bottom_count=sum(item[1] for item in outcomes)
    score,label=_regime(features)
    # Each validation date uses only observations that ended before that date.
    checks=[]
    for index in range(max(300,latest-260),latest-10,5):
        past=_neighbors(rows,_features(rows,index),index,count=35)
        if len(past)<25:continue
        predicted=sum(_outcomes(rows,prior)[0] for _,prior in past)/len(past)
        actual=_outcomes(rows,index)[0]
        known=[_outcomes(rows,prior)[0] for prior in range(21,index-10)]
        baseline_rate=sum(known)/len(known)
        checks.append((predicted,actual,baseline_rate))
    brier=sum((p-int(actual))**2 for p,actual,_ in checks)/len(checks) if checks else None
    baseline=sum((base-int(actual))**2 for _,actual,base in checks)/len(checks) if checks else None
    day=rows[-1]['date']
    qqq=rows[-1]['qqq']
    previous=rows[-2]['qqq']
    absorption=('放量承接增强' if previous['close']<rows[-3]['qqq']['close'] and qqq['close']>previous['close']
                and features['volume_ratio']>=1.2 and qqq['close']>=qqq['low']+(qqq['high']-qqq['low'])*0.7
                else '反弹量能偏弱' if previous['close']<rows[-3]['qqq']['close'] and qqq['close']>previous['close']
                else '未见明确承接信号')
    participation=0
    participation_total=0
    for ticker in PARTICIPATION_ETFS:
        history=next((item for item in histories if item['ticker']==ticker),None)
        if not history:continue
        usable=[bar for bar in history['bars'] if bar['date']<=day]
        if len(usable)<20 or usable[-1]['date']!=day:continue
        average=sum(bar['close'] for bar in usable[-20:])/20
        participation+=usable[-1]['close']>average
        participation_total+=1
    return {'available':True,'date':day,'vix_date':rows[-1]['vix_date'],
            'regime':label,'regime_score':score,
            'participation':participation,'participation_total':participation_total,
            'participation_scope':'、'.join(ticker for ticker in PARTICIPATION_ETFS
                                           if any(item['ticker']==ticker for item in histories)),
            'absorption':absorption,'qqq_return5':round(features['return5'],2),
            'smh_return5':round(features['smh5'],2),
            'volume_ratio':round(features['volume_ratio'],2),'vix':round(features['vix'],2),
            'near_20day_low':near_low,'up5_pct':round(up_count/len(neighbors)*100,1),
            'up5_interval':_wilson(up_count,len(neighbors)),
            'bottom10_pct':round(bottom_count/len(neighbors)*100,1) if near_low else None,
            'bottom10_interval':_wilson(bottom_count,len(neighbors)) if near_low else None,
            'samples':len(neighbors),'history_days':len(rows),
            'validation_count':len(checks),'brier':round(brier,3) if brier is not None else None,
            'baseline_brier':round(baseline,3) if baseline is not None else None,
            'validated_better_than_baseline':brier is not None and baseline is not None and brier<baseline}
