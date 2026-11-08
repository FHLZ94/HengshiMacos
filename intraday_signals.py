"""Completed 15/30/60 minute structure, Wilder RSI and confirmed swing divergence."""
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone,timedelta
from math import isfinite
from statistics import mean
from zoneinfo import ZoneInfo
import requests
import data_service

NY=ZoneInfo('America/New_York')


def parse_chart(payload,ticker,now=None):
    now=now or datetime.now(timezone.utc)
    result=(payload.get('chart') or {}).get('result') or []
    if not result:raise ValueError('分钟行情未提供')
    series=result[0]
    if series.get('meta',{}).get('symbol','').upper()!=ticker:raise ValueError('分钟行情标的身份不匹配')
    quotes=((series.get('indicators') or {}).get('quote') or [{}])[0];bars=[]
    for i,stamp in enumerate(series.get('timestamp') or []):
        start=datetime.fromtimestamp(stamp,timezone.utc);local=start.astimezone(NY)
        minute=local.hour*60+local.minute
        if local.weekday()>4 or not 570<=minute<960 or start+timedelta(minutes=15)>now:continue
        try:
            values={k:float(quotes[k][i]) for k in ('open','high','low','close','volume')}
            if not all(isfinite(v) for v in values.values()) or values['close']<=0 or values['volume']<0:continue
            if not values['low']<=values['close']<=values['high']:continue
            bars.append({'time':int(stamp),'end':int(stamp)+900,**values})
        except (KeyError,IndexError,TypeError,ValueError):continue
    bars=list({b['time']:b for b in bars}.values());bars.sort(key=lambda b:b['time'])
    if len(bars)<80:raise ValueError('完整15分钟样本不足80根')
    return {'ticker':ticker,'bars':bars,'source':'Yahoo Finance 公开分钟行情',
            'fetched_at':now.isoformat(timespec='seconds')}


def resample(bars,minutes):
    if minutes==15:return [dict(b,end=b['time']+900,session_tail=False) for b in bars]
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
        if not (rsi_div or macd_div):return None
        return {'first_time':bars[a]['time'],'second_time':bars[b]['time'],'first_low':round(bars[a]['low'],4),
                'second_low':round(bars[b]['low'],4),'rsi_first':round(rsi[a],1),'rsi_second':round(rsi[b],1),
                'macd_first':round(dif[a],4),'macd_second':round(dif[b],4),'rsi_divergence':bool(rsi_div),
                'macd_divergence':bool(macd_div),'bars_after':last-b}
    for b in reversed(pivots):
        if last-b>8:break
        for a in reversed([p for p in pivots if p<b]):
            matched=compare(a,b)
            if matched:confirmed=matched;break
        if confirmed:break
    highs=[i for i in range(max(35,last-100),last-1)
           if bars[i]['high']>max(v['high'] for v in bars[i-2:i])
           and bars[i]['high']>=max(v['high'] for v in bars[i+1:i+3])]
    def compare_top(a,b):
        if not 5<=b-a<=50 or bars[b]['high']<=bars[a]['high']*1.001:return None
        rsi_div=rsi[a]>=60 and rsi[b]>=50 and rsi[b]<=rsi[a]-3
        threshold=max(abs(dif[a] or 0)*.1,bars[b]['close']*.0001)
        macd_div=dif[a] is not None and dif[b] is not None and dif[a]>0 and dif[b]>0 and dif[b]<=dif[a]-threshold
        if not (rsi_div or macd_div):return None
        return {'first_time':bars[a]['time'],'second_time':bars[b]['time'],'first_high':round(bars[a]['high'],4),
            'second_high':round(bars[b]['high'],4),'rsi_first':round(rsi[a],1),'rsi_second':round(rsi[b],1),
            'macd_first':round(dif[a],4),'macd_second':round(dif[b],4),'rsi_divergence':bool(rsi_div),
            'macd_divergence':bool(macd_div),'bars_after':last-b}
    confirmed_top=None;candidate_top=None
    for b in reversed(highs):
        if last-b>8:break
        for a in reversed([p for p in highs if p<b]):
            confirmed_top=compare_top(a,b)
            if confirmed_top:break
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
            'high_stall':high_stall,'recent_progress_atr':round(move/atr,2) if atr else None}


def analyze(history):
    frames={str(m):frame(resample(history.get('bars',[]),m),m) for m in (15,30,60)}
    valid=[v for v in frames.values() if v['available']]
    confirmed=[v['minutes'] for v in valid if v['confirmed']]
    resonance='三周期底结构共振' if len(confirmed)==3 else '/'.join(str(v) for v in confirmed)+'分底背离' if confirmed else '候选底结构，等待确认' if any(v['candidate'] for v in valid) else '尚未确认底背离'
    top_confirmed=[v['minutes'] for v in valid if v['top_confirmed']]
    top_resonance='三周期顶结构共振' if len(top_confirmed)==3 else '/'.join(str(v) for v in top_confirmed)+'分顶背离' if top_confirmed else '候选顶结构，等待确认' if any(v['top_candidate'] for v in valid) else '尚未确认顶背离'
    shorter=[frames[k] for k in ('15','30') if frames[k]['available']]
    absorption='多周期放量承接' if len(shorter)==2 and all(v['absorption']=='放量承接' for v in shorter) else '初步承接' if any(v['absorption'] in ('放量承接','初步承接') for v in shorter) else '卖压仍在' if any(v['absorption']=='放量卖压' for v in shorter) else '承接偏弱'
    return {'available':bool(valid),'ticker':history['ticker'],'frames':frames,'resonance':resonance,'absorption':absorption,
            'confirmed_frames':confirmed,'source':history.get('source'),'fetched_at':history.get('fetched_at'),
            'top_confirmed_frames':top_confirmed,'top_resonance':top_resonance,
            'high_stall_frames':[v['minutes'] for v in valid if v.get('high_stall')],
            'limits':'左右各2根K线确认价格低点；候选不计作确认。多周期使用同一成交数据，不能相乘为底部概率。'}


def fetch(config):
    def one(ticker):
        for host in ('query1.finance.yahoo.com','query2.finance.yahoo.com'):
            try:
                r=data_service.http_get(f'https://{host}/v8/finance/chart/{ticker}',params={'range':'1mo','interval':'15m','includePrePost':'false'},headers=data_service.HEADERS,proxies=data_service.configured_proxy(config,for_google=True),timeout=(4,9))
                r.raise_for_status();return ticker,parse_chart(r.json(),ticker)
            except (requests.RequestException,ValueError,TypeError,KeyError):continue
        return ticker,None
    result={}
    with ThreadPoolExecutor(max_workers=2) as pool:
        for future in as_completed([pool.submit(one,t) for t in ('QQQ','SMH')]):
            ticker,row=future.result()
            if row:result[ticker]=row
    return result,{'source':'分钟线与背离结构','status':'ok' if result else 'error','count':len(result)}
