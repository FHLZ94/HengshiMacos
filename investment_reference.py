"""One-year valuation scenarios and matured historical monthly-entry outcomes."""
from math import log, sqrt
from statistics import mean, pstdev, median


def annual_reference(history, price, watch_zone, fair_price, analyst_target=None):
    result={'available':False,'valuation_range':None,'scenario_basis':'中性估值'}
    target=fair_price or analyst_target
    if not fair_price and analyst_target:result['scenario_basis']='分析师目标价'
    if target and watch_zone and min(watch_zone)>0:
        result['valuation_range']=[round((target/watch_zone[1]-1)*100,1),
                                   round((target/watch_zone[0]-1)*100,1)]
    bars=(history or {}).get('bars') or []
    if len(bars)<1260:
        result['reason']='一年历史回报至少需要5年日线；估值空间是情景，不是盈利概率'
        return result
    def feature(i):
        closes=[b['close'] for b in bars[i-125:i+1]]
        rets=[log(b/a) for a,b in zip(closes[:-1],closes[1:])]
        return [log(closes[-1]/max(closes)),log(closes[-1]/closes[-64]),pstdev(rets[-63:])]
    latest=feature(len(bars)-1);candidates=[]
    # Monthly entries overlap: report effective yearly blocks explicitly and
    # never pretend these observations or simulation paths are independent.
    for i in range(125,len(bars)-252,21):
        f=feature(i)
        distance=sum(((a-b)/scale)**2 for a,b,scale in zip(f,latest,(.15,.25,.015)))
        candidates.append((distance,i,(bars[i+252]['close']/bars[i]['close']-1)*100))
    chosen=sorted(candidates)[:min(60,len(candidates))]
    if len(chosen)<36:return {**result,'reason':'已到期一年历史样本不足36个月度起点'}
    values=sorted(r[2] for r in chosen);indices=sorted(r[1] for r in chosen)
    # A conservative count of fully non-overlapping one-year holding periods.
    selected=[]
    for i in indices:
        if not selected or i-selected[-1]>=252:selected.append(i)
    result.update(available=True,historical_positive_pct=round(sum(v>0 for v in values)/len(values)*100,1),
                  median_return=round(median(values),1),return_range=[round(values[int(.1*(len(values)-1))],1),round(values[int(.9*(len(values)-1))],1)],
                  samples=len(values),independent_periods=len(selected),
                  first_date=bars[indices[0]]['date'],last_matured_entry=bars[indices[-1]]['date'],
                  horizon=252,calibrated=False,
                  definition='在本标的历史中按回撤、63日动量和波动率选取相似的月度买入起点，持有252个交易日，不含费用和分红。起点之间存在重叠，只作历史回报参考；未转成可校准的一年盈利概率。')
    return result
