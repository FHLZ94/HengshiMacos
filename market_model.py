"""Daily QQQ probabilities: purged walk-forward ridge logistic and past-only calibration."""
from datetime import date, datetime, timezone
from math import sqrt
import hashlib
import json
from zoneinfo import ZoneInfo
import numpy as np

MODEL_VERSION = '3.0.0'
FEATURE_NAMES = ('5日动量','20日动量','60日动量','20日均线偏离','60日均线偏离',
                 '63日回撤','相对标普强弱','半导体相对强弱','波动率水平','波动率变化',
                 '短长波动比','量比','收盘位置','下跌放量')


def history_key(histories):
    payload = [(h['ticker'], h.get('bars', [])) for h in histories
               if h['ticker'] in ('QQQ','SPY','SMH','^VIX')]
    return hashlib.sha256(json.dumps(sorted(payload), sort_keys=True).encode()).hexdigest()


def _pct(current, previous):
    return (current / previous - 1) * 100 if previous else 0.0


def _prepare(histories):
    now = datetime.now(timezone.utc).astimezone(ZoneInfo('America/New_York'))
    cutoff = now.date().isoformat()
    closed = (now.hour,now.minute)>=(16,15)
    mapping = {r['ticker']: {b['date']: b for b in r.get('bars', [])
                            if float(b.get('close', 0)) > 0 and
                            (b['date']<cutoff or b['date']==cutoff and closed)} for r in histories}
    if not all(mapping.get(t) for t in ('QQQ','SPY','SMH','^VIX')):
        return []
    days = sorted(set(mapping['QQQ']) & set(mapping['SPY']) & set(mapping['SMH']))
    vdays = sorted(mapping['^VIX']); vi = 0; rows = []
    for day in days:
        while vi + 1 < len(vdays) and vdays[vi + 1] <= day: vi += 1
        vd = vdays[vi]
        if vd > day or (date.fromisoformat(day)-date.fromisoformat(vd)).days > 4: continue
        bars = [mapping[t][day] for t in ('QQQ','SPY','SMH')]
        if any(not all(k in b for k in ('high','low','volume')) for b in bars): continue
        rows.append(dict(date=day, qqq=bars[0], spy=bars[1], smh=bars[2],
                         vix=float(mapping['^VIX'][vd]['close']), vix_date=vd))
    return rows


def _features(rows, i, ticker="QQQ"):
    if i < 63: return None
    key=ticker.lower()
    q = np.array([r[key]['close'] for r in rows[i-63:i+1]], dtype=float)
    returns = np.diff(np.log(q)); vol = max(float(np.std(returns[-20:])), .003)
    vol60 = max(float(np.std(returns)), .003)
    b = rows[i][key]; volumes = [r[key]['volume'] for r in rows[i-20:i]]
    vr = b['volume']/max(float(np.mean(volumes)), 1)
    r5 = float(np.log(q[-1]/q[-6])); r20 = float(np.log(q[-1]/q[-21]))
    spy5 = np.log(rows[i]['spy']['close']/rows[i-5]['spy']['close'])
    smh5 = np.log(rows[i]['smh']['close']/rows[i-5]['smh']['close'])
    pos = (b['close']-b['low'])/max(b['high']-b['low'], .001)
    values = [r5/(vol*sqrt(5)), r20/(vol*sqrt(20)), np.log(q[-1]/q[0])/(vol60*sqrt(63)),
              np.log(q[-1]/np.mean(q[-20:]))/(vol*sqrt(20)),
              np.log(q[-1]/np.mean(q[-60:]))/(vol60*sqrt(60)),
              np.log(q[-1]/max(q))/(vol60*sqrt(63)),
              (r5-spy5)/(vol*sqrt(5)), (smh5-np.log(rows[i]['qqq']['close']/rows[i-5]['qqq']['close']))/(vol*sqrt(5)),
              np.log(max(rows[i]['vix'], 1)/20),
              np.log(max(rows[i]['vix'],1)/max(rows[i-5]['vix'],1)),
              vol/vol60, np.log(max(vr,.01)), pos, np.log(max(vr,.01))*min(0,returns[-1]/vol)]
    return np.clip(np.array(values, dtype=float), -8, 8)


def _outcome(rows,i,horizon,ticker='QQQ'):
    if i+horizon>=len(rows):return np.nan
    key=ticker.lower()
    if horizon in (3,5):return float(rows[i+horizon][key]['close']>rows[i][key]['close'])
    future=rows[i+1:i+horizon+1]
    return float(min(r[key]['low'] for r in future)>=rows[i][key]['low']
                 and future[-1][key]['close']>rows[i][key]['close'])


def _sigmoid(x): return 1/(1+np.exp(-np.clip(x,-30,30)))


def _fit(x, y, penalty=35):
    # Scale only on training data. Strong ridge regularisation limits false precision.
    mean = x.mean(axis=0); scale = np.maximum(x.std(axis=0), .05)
    a = np.column_stack((np.ones(len(x)), (x-mean)/scale))
    beta = np.zeros(a.shape[1]); rate = (y.sum()+1)/(len(y)+2)
    beta[0] = np.log(rate/(1-rate))
    reg = np.diag([.001]+[penalty]*(a.shape[1]-1))
    for _ in range(25):
        p = _sigmoid(a@beta); w = np.maximum(p*(1-p), 1e-5)
        step = np.linalg.solve((a.T*w)@a+reg, a.T@(p-y)+reg@beta)
        beta -= step
        if np.max(np.abs(step)) < 1e-6: break
    return mean, scale, beta


def _predict(fit, x):
    mean, scale, beta = fit
    return _sigmoid(beta[0]+((x-mean)/scale)@beta[1:])


def _wilson(success, total):
    if not total: return None
    z = 1.96; p = success/total; den = 1+z*z/total
    mid = (p+z*z/(2*total))/den
    spread = z*sqrt((p*(1-p)+z*z/(4*total))/total)/den
    return [round(100*max(0,mid-spread),1), round(100*min(1,mid+spread),1)]


def _forecast(x, y, horizon):
    n = len(x); raw = np.full(n, np.nan);last_fit=None
    # Labels ending on the decision close are knowable; overlapping future labels
    # are purged. Each historical forecast is fitted with earlier data only.
    for origin in range(504+horizon, n, 63):
        end = origin-horizon+1; start = max(0,end-1260)
        fit = _fit(x[start:end], y[start:end]);last_fit=fit
        raw[origin:origin+63] = _predict(fit, x[origin:origin+63])
    scored = []; latest = None
    anchors = sorted(set(range(504+horizon,n,horizon)) | {n-1})
    for i in anchors:
        if not np.isfinite(raw[i]): continue
        eligible = np.arange(max(0,i-1260), i-horizon+1, horizon)
        known = y[eligible]; known = known[np.isfinite(known)]
        base = float((known.sum()+1)/(len(known)+2))
        ci = np.arange(max(0,i-1008),i-horizon+1,horizon)
        ci = ci[np.isfinite(raw[ci]) & np.isfinite(y[ci])]
        calibrated = base; calibration_n = len(ci)
        if len(ci) >= 40 and min(sum(y[ci]),len(ci)-sum(y[ci])) >= 6:
            logits = np.log(np.clip(raw[ci],.01,.99)/(1-np.clip(raw[ci],.01,.99)))[:,None]
            cal = _fit(logits, y[ci], penalty=10)
            current_logit = np.array([[np.log(raw[i]/(1-raw[i]))]])
            calibrated = .65*float(_predict(cal,current_logit)[0])+.35*base
        past = [s for s in scored if s['index']+horizon <= i][-126:]
        skill = (np.mean([(s['base']-s['y'])**2 for s in past])-
                 np.mean([(s['candidate']-s['y'])**2 for s in past])) if past else 0
        use_model = len(past) >= 40 and calibration_n >= 40 and skill > .001
        probability = calibrated if use_model else base
        latest = dict(probability=probability, method='校准多因子' if use_model else '历史基准收缩',
                      training_samples=int(len(known)), calibration_samples=int(calibration_n),
                      interval=_wilson(float(known.sum()),len(known)))
        if np.isfinite(y[i]):
            scored.append(dict(index=i,p=probability,base=base,candidate=calibrated,y=float(y[i])))
    if latest is None:
        known = y[np.arange(0,max(1,n-horizon),horizon)]
        known = known[np.isfinite(known)]
        latest = dict(probability=float((known.sum()+1)/(len(known)+2)),
                      method='历史基准收缩', training_samples=int(len(known)),
                      calibration_samples=0, interval=_wilson(float(known.sum()),len(known)))
    evaluation = scored[-252:]
    brier = float(np.mean([(s['p']-s['y'])**2 for s in evaluation])) if evaluation else None
    baseline = float(np.mean([(s['base']-s['y'])**2 for s in evaluation])) if evaluation else None
    similar = [s for s in evaluation if abs(s['p']-latest['probability']) <= .10]
    if latest['method']=='校准多因子' and len(similar) >= 30:
        latest['interval'] = _wilson(sum(s['y'] for s in similar),len(similar))
        latest['interval_scope'] = '相近预测档历史发生率区间'
    else: latest['interval_scope'] = '不重叠历史样本发生率区间'
    latest.update(validation_count=len(evaluation),
                  brier=round(brier,4) if brier is not None else None,
                  baseline_brier=round(baseline,4) if baseline is not None else None,
                  skill=round(1-brier/baseline,4) if baseline else None,
                  calibration_bins=[dict(low=lo,high=lo+20,n=len(group),
                     predicted=round(float(np.mean([s['p'] for s in group]))*100,1),
                     observed=round(float(np.mean([s['y'] for s in group]))*100,1))
                    for lo in range(0,100,20)
                    if (group:=[s for s in evaluation if lo<=s['p']*100<lo+20])])
    coefficients=last_fit[2][1:] if last_fit else np.zeros(len(FEATURE_NAMES))
    total=float(np.sum(np.abs(coefficients)))
    latest['feature_weights']=[{'name':name,'coefficient':round(float(value),4),
        'share_pct':round(abs(float(value))/total*100,1) if total else 0}
        for name,value in zip(FEATURE_NAMES,coefficients)]
    latest['weights_active']=latest['method']=='校准多因子'
    latest['calibrated_model_weight']=.65 if latest['weights_active'] else 0
    latest['baseline_weight']=.35 if latest['weights_active'] else 1
    return latest


def _regime(r5, gap, vix, smh5, spy5):
    score = round(max(0,min(100,50+np.clip(r5*2.1,-18,18)+np.clip(gap*1.6,-12,12)
                    +np.clip((18-vix)*.8,-12,8)+np.clip((smh5-spy5)*.8,-8,8))))
    label = ('极度悲观' if score<20 else '悲观' if score<35 else '偏谨慎' if score<46
             else '中性' if score<56 else '偏乐观' if score<69 else '乐观' if score<83 else '过热')
    return score,label


def analyze_market(histories):
    rows = _prepare(histories)
    if len(rows) < 300: return dict(available=False,reason='QQQ、SPY、SMH 与 VIX 共同历史不足300日')
    targets={}
    for ticker in ('QQQ','SMH'):
        x=np.array([_features(rows,i,ticker) for i in range(63,len(rows))])
        predictions={}
        for horizon in (3,5,10):
            y=np.array([_outcome(rows,i,horizon,ticker) for i in range(63,len(rows))])
            predictions[horizon]=_forecast(x,y,horizon)
        setup=oversold_setup(rows,ticker,x)
        targets[ticker]={'ticker':ticker,'date':rows[-1]['date'],
            'up3':predictions[3],'up5':predictions[5],'bottom10':predictions[10],
            'up3_pct':round(predictions[3]['probability']*100,1),
            'up5_pct':round(predictions[5]['probability']*100,1),
            'bottom10_pct':round(predictions[10]['probability']*100,1),'setup':setup}
    up,bottom=targets['QQQ']['up5'],targets['QQQ']['bottom10']
    b = rows[-1]['qqq']; previous = rows[-2]['qqq']; day = rows[-1]['date']
    q20 = [r['qqq']['close'] for r in rows[-20:]]
    vr = b['volume']/max(np.mean([r['qqq']['volume'] for r in rows[-21:-1]]),1)
    r5 = _pct(b['close'],rows[-6]['qqq']['close'])
    smh5 = _pct(rows[-1]['smh']['close'],rows[-6]['smh']['close'])
    spy5 = _pct(rows[-1]['spy']['close'],rows[-6]['spy']['close'])
    score,label = _regime(r5,_pct(b['close'],np.mean(q20)),rows[-1]['vix'],smh5,spy5)
    rebound = previous['close']<rows[-3]['qqq']['close'] and b['close']>previous['close']
    absorption = ('放量承接增强' if rebound and vr>=1.2 and b['close']>=b['low']+(b['high']-b['low'])*.7
                  else '反弹量能偏弱' if rebound else '未见明确承接信号')
    return dict(available=True,model_version=MODEL_VERSION,targets=targets,date=day,vix_date=rows[-1]['vix_date'],
        computed_at=datetime.now(timezone.utc).isoformat(timespec='seconds'),
        regime=label,regime_score=score,absorption=absorption,vix=round(rows[-1]['vix'],2),
        qqq_return5=round(r5,2),smh_return5=round(smh5,2),volume_ratio=round(float(vr),2),
        near_20day_low=_pct(b['close'],max(q20))<=-4,
        up5_pct=round(up['probability']*100,1),up5_interval=up['interval'],
        bottom10_pct=round(bottom['probability']*100,1),bottom10_interval=bottom['interval'],
        up5=up,bottom10=bottom,samples=up['training_samples'],history_days=len(rows),
        history_start=rows[0]['date'],validation_count=up['validation_count'],
        brier=up['brier'],baseline_brier=up['baseline_brier'],
        validated_better_than_baseline=up['method']=='校准多因子',
        up5_definition='各标的未来第5个交易日收盘价高于其最新完整交易日收盘价；QQQ和SMH分别训练与检验',
        bottom10_definition='各标的未来10个交易日最低价不低于本日最低价，且第10日收盘高于本日收盘；这是低点守稳事件，不是长期底部保证',
        feature_names=list(FEATURE_NAMES),
        limitations='日线模型每天收盘后更新输入；盘前盘后报价单独刷新。CNN和当前成分广度用于情绪解释，未伪造其历史输入。')



def oversold_setup(rows,ticker,x):
    key=ticker.lower();bars=[r[key] for r in rows];closes=np.array([b['close'] for b in bars],dtype=float)
    changes=np.diff(closes);gains=np.maximum(changes,0);losses=np.maximum(-changes,0)
    gain=float(np.mean(gains[:14]));loss=float(np.mean(losses[:14]))
    for up,down in zip(gains[14:],losses[14:]):gain=(gain*13+up)/14;loss=(loss*13+down)/14
    rsi=100-100/(1+gain/loss) if loss>0 else 100 if gain>0 else 50
    deviations=x[:-1,3];current=float(x[-1,3])
    rank=(float(np.sum(deviations<current))+.5*float(np.sum(deviations==current)))/len(deviations)*100
    b=bars[-1];prior=bars[-2];vr=b['volume']/max(float(np.mean([r['volume'] for r in bars[-21:-1]])),1)
    position=(b['close']-b['low'])/max(b['high']-b['low'],.001)
    return {'rsi14':round(float(rsi),1),'lower_tail_pct':round(rank,1),'rank_samples':len(deviations),
            'rank_definition':'20日均线偏离经同期波动率标准化后的历史下侧分位，越小越接近历史低位',
            'extreme_oversold':bool(rank<=1 and rsi<35),'oversold':bool(rank<=5 and rsi<40),
            'label':'极端超卖' if rank<=1 and rsi<35 else '明显超卖' if rank<=5 and rsi<40 else '偏超卖' if rank<=15 else '非明显超卖',
            'volume_ratio':round(vr,2),'close_position':round(position,2),
            'recovery_confirmed':bool(b['close']>prior['close'] and position>=.65 and vr>=1.1),
            'return5':round(float(_pct(closes[-1],closes[-6])),2)}
