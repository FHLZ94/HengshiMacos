"""Completed MACD structures: 30-minute core with 15/60-minute checks."""
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone,timedelta
from math import isfinite
from statistics import mean
from zoneinfo import ZoneInfo
import requests
import data_service

NY=ZoneInfo('America/New_York')


def parse_chart(payload,ticker,now=None,interval=15):
    now=now or datetime.now(timezone.utc)
    result=(payload.get('chart') or {}).get('result') or []
    if not result:raise ValueError('分钟行情未提供')
    series=result[0]
    if series.get('meta',{}).get('symbol','').upper()!=ticker:raise ValueError('分钟行情标的身份不匹配')
    quotes=((series.get('indicators') or {}).get('quote') or [{}])[0];bars=[]
    for i,stamp in enumerate(series.get('timestamp') or []):
        start=datetime.fromtimestamp(stamp,timezone.utc);local=start.astimezone(NY)
        minute=local.hour*60+local.minute
        if local.weekday()>4 or not 570<=minute<960 or start+timedelta(minutes=interval)>now:continue
        try:
            values={k:float(quotes[k][i]) for k in ('open','high','low','close','volume')}
            if not all(isfinite(v) for v in values.values()) or values['close']<=0 or values['volume']<0:continue
            if not values['low']<=values['close']<=values['high']:continue
            bars.append({'time':int(stamp),'end':int(stamp)+interval*60,**values})
        except (KeyError,IndexError,TypeError,ValueError):continue
    bars=list({b['time']:b for b in bars}.values());bars.sort(key=lambda b:b['time'])
    if len(bars)<80:raise ValueError(f'完整{interval}分钟样本不足80根')
    return {'ticker':ticker,'interval':interval,'bars':bars,'source':'Yahoo Finance 公开分钟行情',
            'fetched_at':now.isoformat(timespec='seconds')}


def resample(bars,minutes):
    if minutes in (5,15):return [dict(b,end=b['time']+minutes*60,session_tail=False) for b in bars]
    buckets={}
    for b in bars:
        local=datetime.fromtimestamp(b['time'],timezone.utc).astimezone(NY)
        offset=local.hour*60+local.minute-570;slot=offset//minutes
        buckets.setdefault((local.date(),slot),[]).append(b)
    result=[]
    for (day,slot),group in sorted(buckets.items()):
        width=min(minutes,390-slot*minutes);expected=width//15
        group.sort(key=lambda b:b['time'])
        if len(group)!=expected or any(b['time']-a['time']!=900 for a,b in zip(group,group[1:])):continue
        result.append({'time':group[0]['time'],'end':group[-1]['time']+900,'open':group[0]['open'],
            'high':max(b['high'] for b in group),'low':min(b['low'] for b in group),
            'close':group[-1]['close'],'volume':sum(b['volume'] for b in group),'session_tail':width<minutes})
    return result


def ema(values,period):
    result=[None]*len(values)
    if len(values)<period:return result
    value=mean(values[:period]);result[period-1]=value;alpha=2/(period+1)
    for i in range(period,len(values)):value=alpha*values[i]+(1-alpha)*value;result[i]=value
    return result


def indicators(bars):
    close=[b['close'] for b in bars];rsi=[None]*len(close)
    changes=[b-a for a,b in zip(close,close[1:])]
    if len(changes)>=14:
        up=mean(max(x,0) for x in changes[:14]);down=mean(max(-x,0) for x in changes[:14])
        for i in range(14,len(close)):
            if i>14:up=(up*13+max(changes[i-1],0))/14;down=(down*13+max(-changes[i-1],0))/14
            rsi[i]=100-100/(1+up/down) if down>0 else 100 if up>0 else 50
    fast=ema(close,12);slow=ema(close,26)
    dif=[a-b if a is not None and b is not None else None for a,b in zip(fast,slow)]
    signal=ema(dif[25:],9);hist=[None]*25+[v-s if s is not None else None for v,s in zip(dif[25:],signal)]
    return rsi,dif,hist


def frame(bars,minutes):
    if len(bars)<60:return {'available':False,'minutes':minutes,'reason':'已完成样本不足60根'}
    rsi,dif,hist=indicators(bars);last=len(bars)-1
    pivots=[i for i in range(max(35,last-100),last-1)
            if bars[i]['low']<min(b['low'] for b in bars[i-2:i])
            and bars[i]['low']<=min(b['low'] for b in bars[i+1:i+3])]
    confirmed=None
    def compare(a,b):
        if not 5<=b-a<=50 or bars[b]['low']>=bars[a]['low']*.999:return None
        rsi_div=rsi[a] is not None and rsi[b] is not None and rsi[a]<=40 and rsi[b]<=50 and rsi[b]>=rsi[a]+3
        threshold=max(abs(dif[a] or 0)*.1, bars[b]['close']*.0001)
        macd_div=dif[a] is not None and dif[b] is not None and dif[a]<0 and dif[b]<0 and dif[b]>=dif[a]+threshold
        if not macd_div:return None
        return {'first_time':bars[a]['time'],'second_time':bars[b]['time'],'first_low':round(bars[a]['low'],4),
                'second_low':round(bars[b]['low'],4),'rsi_first':round(rsi[a],1),'rsi_second':round(rsi[b],1),
                'macd_first':round(dif[a],4),'macd_second':round(dif[b],4),'rsi_divergence':bool(rsi_div),
                'macd_divergence':bool(macd_div),'bars_after':last-b}
    for b in reversed(pivots):
        if last-b>8:break
        for a in reversed([p for p in pivots if p<b]):
            matched=compare(a,b)
            if matched and min(row['low'] for row in bars[b+1:])>=bars[b]['low']*.999:confirmed=matched;break
        if confirmed:break
    highs=[i for i in range(max(35,last-100),last-1)
           if bars[i]['high']>max(v['high'] for v in bars[i-2:i])
           and bars[i]['high']>=max(v['high'] for v in bars[i+1:i+3])]
    def compare_top(a,b):
        if not 5<=b-a<=50 or bars[b]['high']<=bars[a]['high']*1.001:return None
        rsi_div=rsi[a]>=60 and rsi[b]>=50 and rsi[b]<=rsi[a]-3
        threshold=max(abs(dif[a] or 0)*.1,bars[b]['close']*.0001)
        macd_div=dif[a] is not None and dif[b] is not None and dif[a]>0 and dif[b]>0 and dif[b]<=dif[a]-threshold
        if not macd_div:return None
        return {'first_time':bars[a]['time'],'second_time':bars[b]['time'],'first_high':round(bars[a]['high'],4),
            'second_high':round(bars[b]['high'],4),'rsi_first':round(rsi[a],1),'rsi_second':round(rsi[b],1),
            'macd_first':round(dif[a],4),'macd_second':round(dif[b],4),'rsi_divergence':bool(rsi_div),
            'macd_divergence':bool(macd_div),'bars_after':last-b}
    confirmed_top=None;candidate_top=None
    for b in reversed(highs):
        if last-b>8:break
        for a in reversed([p for p in highs if p<b]):
            confirmed_top=compare_top(a,b)
            if confirmed_top and max(row['high'] for row in bars[b+1:])<=bars[b]['high']*1.001:break
            confirmed_top=None
        if confirmed_top:break
    if not confirmed_top:
        for b in (last,last-1):
            if bars[b]['high']<max(v['high'] for v in bars[max(0,b-2):b+1]):continue
            for a in reversed(highs):
                candidate_top=compare_top(a,b)
                if candidate_top:break
            if candidate_top:break
    candidate=None
    if not confirmed:
        for b in (last,last-1):
            if bars[b]['low']>min(v['low'] for v in bars[max(0,b-2):b+1]):continue
            for a in reversed(pivots):
                matched=compare(a,b)
                if matched:candidate=matched;break
            if candidate:break
    current=bars[-1];slot=datetime.fromtimestamp(current['time'],timezone.utc).astimezone(NY).strftime('%H:%M')
    matched=[b['volume'] for b in bars[:-1] if datetime.fromtimestamp(b['time'],timezone.utc).astimezone(NY).strftime('%H:%M')==slot][-20:]
    ratio=current['volume']/mean(matched) if len(matched)>=5 and mean(matched)>0 else None
    recent=bars[-3:];volume=sum(b['volume'] for b in recent)
    pressure=sum(((2*b['close']-b['high']-b['low'])/(b['high']-b['low']) if b['high']>b['low'] else 0)*b['volume'] for b in recent)/volume if volume else 0
    rising=current['close']>bars[-4]['close'];position=(current['close']-current['low'])/max(current['high']-current['low'],.0001)
    ranges=[max(bars[i]['high']-bars[i]['low'],abs(bars[i]['high']-bars[i-1]['close']),abs(bars[i]['low']-bars[i-1]['close'])) for i in range(len(bars)-14,len(bars))]
    atr=mean(ranges);move=abs(current['close']-bars[-4]['close'])
    near_high=current['close']>=max(b['high'] for b in bars[-20:])-atr
    high_stall=bool(near_high and rsi[-1]>=55 and move<=.35*atr and ((ratio is not None and ratio>=1.2) or pressure<=-.25))
    absorption='放量承接' if rising and pressure>0 and position>=.65 and ratio and ratio>=1.2 else '初步承接' if rising and pressure>0 and position>=.6 else '放量卖压' if not rising and pressure<0 and ratio and ratio>=1.2 else '承接偏弱'
    return {'available':True,'minutes':minutes,'bars':len(bars),'asof':datetime.fromtimestamp(current['end'],timezone.utc).isoformat(),
            'rsi14':round(rsi[-1],1),'oversold':rsi[-1]<=30,'divergence':'形态确认' if confirmed else '候选背离' if candidate else '未见当前背离',
            'confirmed':bool(confirmed),'candidate':bool(candidate),'evidence':confirmed or candidate,
            'top_divergence':'形态确认' if confirmed_top else '候选背离' if candidate_top else '未见当前背离',
            'top_confirmed':bool(confirmed_top),'top_candidate':bool(candidate_top),'top_evidence':confirmed_top or candidate_top,
            'overbought':rsi[-1]>=70,
            'same_slot_volume_ratio':round(ratio,2) if ratio is not None else None,'volume_baselines':len(matched),
            'pressure_score':round(pressure*100,1),'absorption':absorption,'session_tail':current.get('session_tail',False),
            'macd_dif':round(dif[-1],5),'macd_histogram':round(hist[-1],5),'histogram_improving':hist[-1]>hist[-2],
            'high_stall':high_stall,'recent_progress_atr':round(move/atr,2) if atr else None}


def analyze(history):
    frames={str(m):frame(resample(history.get('bars',[]),m),m) for m in (15,30,60)}
    if history.get('bars5'):
        frames['5']=frame(resample(history['bars5'],5),5)
    valid=[v for v in frames.values() if v['available']]
    focus=frames['15']
    score_frames={k:frames[k] for k in ('5','15','30') if frames.get(k,{}).get('available')}
    confirmed=[v['minutes'] for v in score_frames.values() if v['confirmed']]
    resonance='三周期底结构共振' if len(confirmed)==3 else '/'.join(str(v) for v in confirmed)+'分底背离' if confirmed else '候选底结构，等待确认' if any(v['candidate'] for v in valid) else '尚未确认底背离'
    top_confirmed=[v['minutes'] for v in score_frames.values() if v['top_confirmed']]
    top_resonance='三周期顶结构共振' if len(top_confirmed)==3 else '/'.join(str(v) for v in top_confirmed)+'分顶背离' if top_confirmed else '候选顶结构，等待确认' if any(v['top_candidate'] for v in valid) else '尚未确认顶背离'
    shorter=[frames[k] for k in ('5','15') if frames.get(k,{}).get('available')]
    absorption='多周期放量承接' if len(shorter)==2 and all(v['absorption']=='放量承接' for v in shorter) else '卖压仍在' if focus.get('absorption')=='放量卖压' else '初步承接' if focus.get('absorption') in ('放量承接','初步承接') else '承接偏弱'
    weights={'5':.40,'15':.40,'30':.20}
    bottom_score=sum(weights[k]*(100 if v.get('confirmed') else 40 if v.get('candidate') else 0) for k,v in score_frames.items())
    top_score=sum(weights[k]*(100 if v.get('top_confirmed') else 40 if v.get('top_candidate') else 0) for k,v in score_frames.items())
    rsi5=frames.get('5',{}).get('rsi14');rsi15=frames.get('15',{}).get('rsi14');rsi30=frames.get('30',{}).get('rsi14')
    rsi_signal=('短线超卖，等待承接' if rsi5 is not None and rsi15 is not None and rsi5<=30 and rsi15<=30 else
                '短线超买，谨慎追价' if rsi5 is not None and rsi15 is not None and rsi5>=70 and rsi15>=70 else
                '5分超卖，15分确认中' if rsi5 is not None and rsi5<=30 else
                '15分超卖，等待5分同步' if rsi15 is not None and rsi15<=30 else
                '5分超买，15分确认中' if rsi5 is not None and rsi5>=70 else
                '15分超买，谨慎追价' if rsi15 is not None and rsi15>=70 else 'RSI处于常态区间')
    primary='5/15分底背离确认' if 5 in confirmed and 15 in confirmed else '15分底背离确认' if 15 in confirmed else '5分底背离确认' if 5 in confirmed else '15分顶背离确认' if 15 in top_confirmed else '5/15分候选结构' if 5 in [v['minutes'] for v in score_frames.values() if v.get('candidate')] and 15 in [v['minutes'] for v in score_frames.values() if v.get('candidate')] else '5/15分暂无背离'
    formation=confirmation_reference(resample(history.get('bars',[]),30),focus)
    return {'available':focus.get('available',False),'ticker':history['ticker'],'frames':frames,'resonance':resonance,'absorption':absorption,
            'primary':primary,'primary_minutes':15,'weights':weights,'rsi_signal':rsi_signal,
            'rsi_5':rsi5,'rsi_15':rsi15,'rsi_30':rsi30,
            'bottom_score':round(bottom_score),'top_score':round(top_score),'formation':formation,
            'confirmed_frames':confirmed,'source':history.get('source'),'fetched_at':history.get('fetched_at'),
            'top_confirmed_frames':top_confirmed,'top_resonance':top_resonance,
            'high_stall_frames':[v['minutes'] for v in valid if v.get('high_stall')],
            'limits':'左右各2根K线确认价格低点；候选不计作确认。5/15分钟主导短线，30分钟辅助确认；多周期使用同一成交数据，不能相乘为底部概率。'}


def confirmation_reference(bars,current):
    """Past candidate pivots must be recognised before their right-hand bars exist.

    Formation refers to a 30-minute MACD shape confirming within four bars;
    it does not mean a profitable trade or the probability of a market bottom.
    """
    from market_model import _wilson
    result={'available':False,'probability_pct':None,'samples':0,'validation_count':0,
            'definition':'30分钟MACD候选在随后4根完整K线内完成左右低点确认；不代表收益或市场底部概率',
            'reason':'尚未出现30分钟候选形态'}
    if current.get('confirmed') or current.get('top_confirmed'):
        return {**result,'reason':'30分钟形态已经确认，不再估计其形成概率','status':'confirmed'}
    direction='bottom' if current.get('candidate') else 'top' if current.get('top_candidate') else None
    if not direction:return result
    result['direction']=direction
    outcomes=[];last_anchor=-10
    # Precompute RSI/DIF once. Prefix-dependent indicators never use later bars.
    _,dif,_=indicators(bars)
    for i in range(60,len(bars)-4):
        if i-last_anchor<4:continue
        price_key='low' if direction=='bottom' else 'high'
        extreme=min if direction=='bottom' else max
        point=bars[i][price_key]
        if point!=extreme(v[price_key] for v in bars[i-2:i+1]):continue
        if direction=='bottom':
            prior=[j for j in range(max(35,i-50),i-4)
                   if bars[j]['low']<min(v['low'] for v in bars[j-2:j])
                   and bars[j]['low']<=min(v['low'] for v in bars[j+1:j+3])]
        else:
            prior=[j for j in range(max(35,i-50),i-4)
                   if bars[j]['high']>max(v['high'] for v in bars[j-2:j])
                   and bars[j]['high']>=max(v['high'] for v in bars[j+1:j+3])]

        candidate=False
        for a in reversed(prior):
            threshold=max(abs(dif[a] or 0)*.1,bars[i]['close']*.0001)
            if direction=='bottom':
                candidate=(point<bars[a]['low']*.999 and dif[a] is not None and dif[i] is not None
                           and dif[a]<0 and dif[i]<0 and dif[i]>=dif[a]+threshold)
            else:
                candidate=(point>bars[a]['high']*1.001 and dif[a] is not None and dif[i] is not None
                           and dif[a]>0 and dif[i]>0 and dif[i]<=dif[a]-threshold)
            if candidate:break
        if not candidate:continue
        last_anchor=i
        # The candidate low/high itself must hold over the next two right bars.
        right=extreme(v[price_key] for v in bars[i+1:i+3])
        outcome=int(right>=point if direction=='bottom' else right<=point)
        outcomes.append(outcome)
    n=len(outcomes);result['samples']=n
    if n<60:
        return {**result,'reason':f'已到期不重叠候选仅{n}组，至少60组后才估计形成概率；继续积累分钟历史'}
    split=max(30,n//2);checks=[]
    for i in range(split,n):
        rate=(sum(outcomes[:i])+1)/(i+2)
        checks.append((rate,outcomes[i]))
    if len(checks)<30:return {**result,'reason':'按时间验证不足30次，暂不发布形成概率'}
    p=(sum(outcomes)+1)/(n+2)
    error=mean((pred-actual)**2 for pred,actual in checks)
    return {**result,'available':True,'probability_pct':round(p*100,1),'validation_count':len(checks),
            'brier':round(error,4),'interval':_wilson(sum(outcomes),n),'method':'候选形态历史基准',
            'reason':'以过去已到期的候选计算平滑频率，按时间验证；尚非多因子校准模型'}


def fetch(config):
    def one(ticker):
        for host in ('query1.finance.yahoo.com','query2.finance.yahoo.com'):
            try:
                r=data_service.http_get(f'https://{host}/v8/finance/chart/{ticker}',params={'range':'60d','interval':'15m','includePrePost':'false'},headers=data_service.HEADERS,proxies=data_service.configured_proxy(config,for_google=True),timeout=(4,9))
                r.raise_for_status()
                base=parse_chart(r.json(),ticker,interval=15)
                r5=data_service.http_get(f'https://{host}/v8/finance/chart/{ticker}',params={'range':'10d','interval':'5m','includePrePost':'false'},headers=data_service.HEADERS,proxies=data_service.configured_proxy(config,for_google=True),timeout=(4,9))
                r5.raise_for_status();base['bars5']=parse_chart(r5.json(),ticker,interval=5)['bars']
                return ticker,base
            except (requests.RequestException,ValueError,TypeError,KeyError):continue
        return ticker,None
    result={}
    with ThreadPoolExecutor(max_workers=2) as pool:
        for future in as_completed([pool.submit(one,t) for t in ('QQQ','SMH')]):
            ticker,row=future.result()
            if row:result[ticker]=row
    return result,{'source':'分钟线与背离结构','status':'ok' if result else 'error','count':len(result)}
