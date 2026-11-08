"""Combine independent market observations without turning uncalibrated analogs into forecasts."""
from datetime import datetime, timedelta, timezone


CNN_RATINGS={'extreme fear':'极度恐慌','fear':'恐慌','neutral':'中性',
             'greed':'贪婪','extreme greed':'极度贪婪'}


def _fresh(item,max_days=4,now=None):
    if not item:return False
    now=now or datetime.now(timezone.utc)
    try:
        age=now-datetime.fromisoformat(item['asof'] if 'asof' in item else item['fetched_at'])
        return timedelta(0)<=age<=timedelta(days=max_days)
    except (KeyError,ValueError,TypeError):
        return False


def compose(model,cnn,breadth,now=None):
    now=now or datetime.now(timezone.utc)
    cnn=cnn if _fresh(cnn,4,now) else None
    breadth=breadth if _fresh(breadth,1,now) else None
    model=model or {'available':False}
    if not model.get('available'):
        return {'headline':'市场数据不足，暂停短期判断','decision':'等待连续行情与波动数据',
                'evidence':[],'risk':'历史模型无法运行','validated':False}
    evidence=[]
    if cnn:evidence.append(f"CNN 恐慌贪婪 {cnn['score']:.1f}（{CNN_RATINGS.get(cnn['rating'].lower(),cnn['rating'])}）")
    evidence.append(f"VIX {model['vix']:.2f}")
    if breadth:evidence.append(f"标普500 20日参与 {breadth['above_20d']}/{breadth['valid']}（{breadth['ratio_pct']:.1f}%）")
    evidence.append(f"QQQ 近5日 {model['qqq_return5']:+.2f}%")
    if 'smh_return5' in model:
        evidence.append(f"SMH 近5日 {model['smh_return5']:+.2f}%")
    evidence.append(f"量比 {model['volume_ratio']:.2f}")
    panic=(cnn and cnn['score']<30) or model['vix']>=28
    weak_breadth=breadth and breadth['ratio_pct']<35
    broad_healthy=breadth and breadth['ratio_pct']>=55
    weak_absorption='偏弱' in model.get('absorption','') or '未见' in model.get('absorption','')
    sector_divergence=(model.get('smh_return5') is not None and
                       model['smh_return5']-model['qqq_return5']<=-4)
    if panic and broad_healthy and sector_divergence:
        headline='情绪极度恐慌，但标普广度仍过半；半导体承压更集中'
        decision=('优先核对半导体订单与资本开支事实，并观察 SMH 相对 QQQ 的跌幅是否收敛；'
                  '在量价承接确认前，不把恐慌数值直接当成见底信号')
    elif panic and weak_breadth and weak_absorption:
        headline='恐慌定价加深，广度偏弱，承接尚未确认'
        decision='重点关注低位修复；等待成交量和广度同时改善后再评估加仓'
    elif panic and not weak_absorption:
        headline='恐慌区出现承接迹象，等待后续交易日确认'
        decision='核验关键事件与价格是否持续修复；避免单日反弹直接视作底部'
    elif model['regime_score']>=70:
        headline='短期风险偏好偏热，追价需核对估值与成交量'
        decision='优先检查组合集中度与高估值标的的失效条件'
    else:
        headline=f"市场处于{model['regime']}区间，趋势需要进一步确认"
        decision='结合持仓估值和新事件，逐项核对关注区、确认价与风险价'
    validated=bool(model.get('validated_better_than_baseline') and model.get('samples',0)>=40
                   and model.get('validation_count',0)>=40)
    if model.get('model_version'):
        validated=model.get('up5',{}).get('method')=='校准多因子'
        risk=('当前五日参考采用历史基准收缩，多因子暂未提供稳定的额外预测能力'
              if not validated else '五日参考使用多因子校准；历史表现不能保证未来，需结合触发与失效条件')
    else:
        risk=('历史相似模型未优于滚动基线，不能把发生率当成可用预测概率'
              if not validated else '历史模型通过当前基线检验，但市场结构可能变化')
    return {'headline':headline,'decision':decision,'evidence':evidence,
            'risk':risk,'validated':validated,'cnn':cnn,'breadth':breadth}
