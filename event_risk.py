"""Live event risk and conditional short-term actions. Scores are not probabilities."""
from datetime import datetime,timezone,timedelta
from urllib.parse import urlsplit
import re

POLICY=re.compile(r'moratorium|export control|export ban|executive order|sanction|tariff|(?:halt|pause|stop|ban).{0,45}(?:\bAI\b|artificial intelligence|data.cent)|(?:\bAI\b|artificial intelligence|data.cent).{0,45}(?:moratorium|halt|pause|ban)|人工智能.{0,12}(?:暂停|停止)|暂停.{0,12}(?:人工智能|数据中心)|禁令|出口管制',re.I)
SEMIS=re.compile(r'semiconductor|\bchip\b|nvidia|broadcom|marvell|micron|hynix|半导体|芯片|英伟达|海力士|美光',re.I)
AI=re.compile(r'artificial intelligence|\bAI\b|data.cent(?:er|re)|cloud compute|人工智能|数据中心|算力',re.I)
NEG=re.compile(r'\b(?:ban|halt|pause|stop|cut|cuts|cancel|restrict|moratorium|sanction|selloff|warning)\b|下调|停止|暂停|禁令|限制|取消|制裁',re.I)
POS=re.compile(r'\b(?:raises?|raised).{0,25}(?:guidance|forecast|outlook)|\b(?:approval|approved|lift|lifts|resume|resumes|reopen|beats)\b|上调.{0,8}(?:指引|预期)|恢复|获批|解除',re.I)
DISPUTE=re.compile(r'denies|denied|not confirmed|unconfirmed|rumou?r|rejects.{0,40}(?:ban|halt|pause)|\b(?:no|not)\b.{0,35}\b(?:ban|halt|pause|moratorium)\b|反对.{0,15}(?:禁令|暂停)|否认|未经证实',re.I)


def _stamp(value):
    try:
        d=datetime.fromisoformat(value)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (ValueError,TypeError):return None


def classify(text,official=False):
    if re.search(r'signed into law|takes effect|effective immediately|正式生效|签署成法|立即生效',text,re.I):return '正式生效',95
    if re.search(r'executive order|presidential proclamation|行政命令|总统令',text,re.I):return '行政措施',90
    if re.search(r'(?:senate|house|congress).{0,35}(?:passes|passed|approves)|参议院.{0,15}通过|国会.{0,15}通过',text,re.I):return '议案通过，待核对生效',78
    if re.search(r'proposes|proposal|introduces.{0,25}bill|calls for|urges|提议|提案|呼吁',text,re.I):return '提议或呼吁',55
    return ('公开表态',40) if POLICY.search(text) else ('业绩与需求',65) if re.search(r'guidance|earnings|capex|指引|资本开支|业绩',text,re.I) else ('市场言论',25)


def assess_events(news,analyses=None,now=None):
    now=now or datetime.now(timezone.utc);analyses=analyses or {};events=[];seen=set();latest=None
    for article in news:
        stamp=_stamp(article.get('published'))
        if not stamp or stamp>now:continue
        age=(now-stamp).total_seconds()/3600
        if age>120:continue
        analysis=analyses.get(article.get('link'),{}) or {}
        text=' '.join([article.get('title',''),article.get('summary',''),*analysis.get('evidence',[])])
        # Passive holdings filings do not describe current buying demand.
        if re.search(r'institutional investor|shares purchased|acquired.{0,30}shares|机构.{0,10}增持',text,re.I) and not (POLICY.search(text) or re.search(r'guidance|指引',text,re.I)):continue
        if not (POLICY.search(text) or AI.search(text) or SEMIS.search(text) or re.search(r'Fed|inflation|CPI|war|金融危机|利率|通胀',text,re.I)):continue
        if latest is None or stamp>latest:latest=stamp
        key=re.sub(r'\s+-\s+[^-]{2,65}$','',article.get('title','')).casefold()
        if key in seen:continue
        seen.add(key)
        host=(urlsplit(analysis.get('resolved_url') or article.get('link','')).hostname or '').lower()
        corporate=any(host==d or host.endswith('.'+d) for d in ('nvidia.com','amd.com','micron.com','broadcom.com','oracle.com','marvell.com','intel.com','lumentum.com','skhynix.com'))
        official=host.endswith('.gov') or host in ('federalreserve.gov','sec.gov') or corporate
        social=host in ('x.com','twitter.com','www.x.com','www.twitter.com') or article.get('source')=='X 公开帖子'
        stage,material=classify(text,official)
        # The user's book is sensitive to policy and supply-chain shocks. Macro /
        # geopolitical transmission gets more weight only when the article also
        # names a credible policy or technology channel.
        category_weight=1.0
        if POLICY.search(text) and (AI.search(text) or SEMIS.search(text)):
            category_weight=1.25
        elif SEMIS.search(text) or re.search(r'advanced packaging|hbm|memory|封装|存储',text,re.I):
            category_weight=1.15
        elif re.search(r'guidance|earnings|capex|指引|财报|资本开支',text,re.I):
            category_weight=1.0
        elif stage in ('公开表态','提议或呼吁'):
            category_weight=.6
        material=round(material*category_weight,1)
        publisher=(article.get('publisher') or article.get('source') or '').lower()
        trust=1 if official else .9 if any(p in publisher for p in ('reuters','路透','bloomberg','彭博','cnbc','new york times','纽约时报')) else .55 if social else .7
        independent=len(set(article.get('independent_publishers') or []))
        evidence=1 if analysis.get('full_text') and (official or independent>=2) else .8 if analysis.get('full_text') else .75 if official else .65 if independent>=2 else .4
        disputed=bool(DISPUTE.search(text[:2200]) or '争议' in analysis.get('direction',''))
        direction=0 if disputed else -1 if NEG.search(text) else 1 if POS.search(text) else 0
        if re.search(r'lifts?.{0,25}(?:ban|restriction)|解除.{0,15}(?:禁令|限制)',text,re.I):direction=1
        decay=2**(-age/(48 if POLICY.search(text) else 24))
        scopes={'QQQ':1.,'SMH':1.} if POLICY.search(text) or AI.search(text) else {'QQQ':.65,'SMH':1.} if SEMIS.search(text) else {'QQQ':1.,'SMH':.7}
        scores={t:round(material*trust*evidence*relevance*decay,1) for t,relevance in scopes.items()}
        if stage in ('公开表态','提议或呼吁'):scores={t:min(v,45) for t,v in scores.items()}
        if social:scores={t:min(v,30) for t,v in scores.items()}
        if disputed:scores={t:min(v,20) for t,v in scores.items()}
        events.append({'title':article.get('title'),'url':article.get('link'),'published':stamp.isoformat(),
             'stage':stage,'direction':direction,'scores':scores,'verified':bool(evidence>=.75 and not disputed and not social),
             'evidence_label':'有可核对的原始证据' if evidence>=.75 and not disputed else '待进一步核验',
             'factors':{'materiality':material,'category_weight':category_weight,'source_reliability':trust,'evidence':evidence,'recency':round(decay,3)},
             'social':social})
    events.sort(key=lambda e:max(e['scores'].values()),reverse=True)
    result={'events':events[:8],'latest_published':latest.isoformat() if latest else None,
            'coverage_fresh':bool(latest and now-latest<=timedelta(hours=48)),
            'definition':'事件影响分＝事件强度×来源可靠性×证据充分度×指数相关度×时效衰减；属于风险排序，不是涨跌概率，也不直接加减概率百分点',
            'news_probability_adjustment':None,'news_model_status':'尚无足够的历史时点新闻样本，事件仅调整风险评级和动作条件'}
    recent=[event for event in events if (now-_stamp(event['published'])).total_seconds()<=24*3600]
    for name,keys in (('半导体产业链',('SMH',)),('大科技与AI',('QQQ',))):
        scoped=[e for e in recent if any(e['scores'].get(k,0)>=8 for k in keys)]
        signed=sum(e['direction']*max(e['scores'].get(k,0) for k in keys) for e in scoped)
        gross=sum(max(e['scores'].get(k,0) for k in keys) for e in scoped)
        normalized=(signed/gross*100) if gross else 0
        if normalized>=45:label='明显偏正面'
        elif normalized>=15:label='偏正面'
        elif normalized<=-45:label='极度负面'
        elif normalized<=-15:label='偏负面'
        else:label='中性整理'
        stance={'label':label,'net_score':round(normalized,1),
            'event_count':len(scoped),'gross_score':round(gross,1),
            'verified_count':sum(bool(e['verified']) for e in scoped),
            'top_event':max(scoped,key=lambda e:max(e['scores'].get(k,0) for k in keys),default=None),
            'window_hours':24,'definition':'最近24小时相关情报按事件强度、来源、证据、行业相关度与时效衰减聚合；是信息情绪档位，不是指数涨跌概率'}
        result.setdefault('stance',{})[name]=stance
        result[name]=stance
    for ticker in ('QQQ','SMH'):
        relevant=[e for e in events if e['scores'][ticker]>=8]
        negatives=[e for e in relevant if e['direction']<0]
        positives=[e for e in relevant if e['direction']>0]
        critical=next((e for e in negatives if e['verified'] and e['scores'][ticker]>=55),None)
        top=negatives[0] if negatives else relevant[0] if relevant else None
        result[ticker]={'risk_score':top['scores'][ticker] if top else 0,'critical_negative':bool(critical),
             'level':'重大负面冲击' if critical else '有待核验的风险线索' if negatives else '有正面线索' if positives else '未见高等级事件冲击',
             'top_event':top,'positive_score':positives[0]['scores'][ticker] if positives else 0}
    return result


def trading_environment(model,event_risk,metrics=None,intraday=None):
    metrics=metrics or {};result={}
    for ticker,data in (model or {}).get('targets',{}).items():
        setup=data['setup'];risk=event_risk[ticker];metric=metrics.get(ticker) or {}
        minute=(intraday or {}).get(ticker) or {}
        stage=market_stage(setup,minute)
        live=metric.get('live_price') or metric.get('price')
        invalid=(metric.get('support20',0)-.75*metric.get('atr14',0)) if metric.get('support20') else None
        if live and invalid and live<invalid:
            label='跌破风险线，先控敞口';reason=f'最近报价已跌破 {invalid:.2f} 的波动调整风险位，等待支撑重建'
        elif risk['critical_negative']:
            label='先控制事件风险';reason='高影响负面事件有原始证据，超卖不足以抵消政策或盈利风险'
        elif setup.get('overbought') and minute.get('available') and minute.get('frames',{}).get('30',{}).get('top_confirmed'):
            label='高位背离，复核敞口';reason='历史高位叠加分钟级顶结构，先核对失效位与止盈条件'
        elif stage=='高位滞涨':
            label='高位滞涨，放缓追价';reason='高位价格推进不足，且出现放量或卖压分歧，等待方向重新确认'
        elif setup.get('overbought'):
            label='偏热拥挤，避免追价';reason=f"历史上侧 {setup.get('upper_tail_pct',0):.1f}%，属于价量过热代理；不等于真实持仓拥挤，也不自动代表即将下跌"
        elif setup['oversold'] and minute.get('available') and minute.get('frames',{}).get('30',{}).get('confirmed') and minute.get('absorption')=='多周期放量承接' and data['up3_pct']>=50 and risk['risk_score']<30:
            label='结构修复，分批候选';reason='分钟级底结构与放量承接联动，先小额观察，后续仍须守住风险位'
        elif setup['oversold'] and setup['recovery_confirmed'] and data['up3_pct']>=50 and not risk['risk_score']>=30:
            label='小额分批候选';reason='进入历史低位区，且收盘位置与成交量出现修复；仍须守住失效价'
        elif setup['oversold'] and data['up3_pct']<50:
            label='超卖但反弹参考偏弱';reason='三日上涨参考低于50%，价格低位尚未转成反弹优势，等待新确认'
        elif setup['oversold'] and minute.get('available') and minute.get('frames',{}).get('30',{}).get('confirmed'):
            label='底结构修复，量能待确认';reason=minute['resonance']+'；当前'+minute['absorption']+'，先观察短周期能否放量守住低点'
        elif setup['oversold']:
            label='超卖观察，等待承接';reason=f"历史下侧 {setup['lower_tail_pct']:.1f}%，但持续承接尚未确认；避免一次性接满"
        elif setup['lower_tail_pct']>90:
            label='不宜追价';reason='价格处于历史偏高区间，等待回撤或盈利预期进一步兑现'
        else:
            label='按条件跟踪';reason='尚未同时满足低位与承接条件，结合关注区和失效价评估'
        if not event_risk['coverage_fresh']:
            reason+='；情报缓存较旧，先同步新事件'
        result[ticker]={'label':label,'reason':reason,'horizon':'下一交易时段至未来1—3个交易日',
            'stage':stage,
            'up3_pct':data['up3_pct'],'oversold':setup['oversold'],'history_tail_pct':setup['lower_tail_pct'],
            'source_date':data['date'],'risk_score':risk['risk_score']}
    return result


def market_stage(setup,minute=None):
    minute=minute or {}
    if setup.get('overbought') and minute.get('available') and minute.get('frames',{}).get('30',{}).get('top_confirmed'):return '顶部背离风险'
    if setup.get('lower_tail_pct',50)>=85 and minute.get('available') and minute.get('high_stall_frames'):return '高位滞涨'
    if setup.get('extreme_overbought'):return '极端过热'
    if setup.get('overbought'):return '明显过热'
    if setup.get('oversold') and minute.get('available') and minute.get('frames',{}).get('30',{}).get('confirmed'):
        return '放量承接增强' if minute.get('absorption')=='多周期放量承接' else '底结构修复'
    if setup.get('extreme_oversold'):return '极端超卖'
    if setup.get('oversold'):return '明显超卖'
    if setup.get('lower_tail_pct',50)>=85:return '偏热上行'
    if setup.get('lower_tail_pct',50)<=15:return '偏冷观察'
    if setup.get('return5',0)>0 and setup.get('rsi14',50)>=55:return '趋势偏强'
    return '中性整理'
