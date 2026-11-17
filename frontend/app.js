const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (character) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character]));
const number = (value, digits = 2) => value == null ? '—' : Number(value).toLocaleString('zh-CN', {minimumFractionDigits: digits, maximumFractionDigits: digits});
const signed = (value) => value == null ? '—' : `${value > 0 ? '+' : ''}${number(value)}%`;
const tone = (value) => value == null ? '' : value > 0 ? 'positive' : value < 0 ? 'negative' : '';
const gradeTone = (grade) => grade === 'S1' || grade === 'S2' ? 'high' : grade === 'S3' ? 'medium' : 'low';
let state = null;
let lastRevision = -1;
let selectedEvent = null;
let selectedAction = null;
let selectedWatch = null;
const aiResults = new Map();
const eventContexts = new Map();
const eventContextsLoading = new Set();
const eventTranslations = new Map();
const eventTranslationsLoading = new Set();
const eventIntelligence = new Map();
const eventIntelligenceLoading = new Set();
const eventIntelligenceFailed = new Set();
let visibleEvents = 12;
let focusEventId = null;
let chart = null;
let rotationPeriod = 5;
let toastTimer = null;
let marketSlots = ['QQQ','SPY','SMH','ORCL'];
const marketRsi = new Map();
const marketRsiLoading = new Set();

function icons() { if (window.lucide?.createIcons) window.lucide.createIcons(); }
function toast(message) {
  const element = $('#toast');
  element.textContent = message;
  element.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => element.classList.remove('show'), 3200);
}
function metric(label, value, meta = '', cls = '') {
  return `<div class="metric"><span class="label">${escapeHtml(label)}</span><span class="value ${cls}">${escapeHtml(value)}</span><span class="meta">${escapeHtml(meta)}</span></div>`;
}
function setStatus() {
  const status = $('#sourceStatus');
  status.innerHTML = `<span class="status-dot"></span>${escapeHtml(state.status)}`;
  status.classList.toggle('busy', !!state.busy);
  $('#syncTime').textContent = state.last_sync ? `最近同步 ${state.last_sync}` : '';
  $('#refreshButton').disabled = false;
  $('#refreshButton').classList.toggle('syncing',!!state.busy);
  $('#translationStatus').textContent = state.translation_pending ? ` · ${state.translation_pending} 条待翻译` : '';
  $('#searchFeedback').textContent = state.search_status || '';
  $('#globalSearch').disabled=!!state.search_busy;
}
function pairMetric(label,rows,meta='',extra=''){
  return `<div class="metric pair-metric ${extra}"><span class="label">${escapeHtml(label)}</span><div class="pair-values">${rows.map(row=>`<div><b>${escapeHtml(row.code)}</b><strong>${escapeHtml(row.value)}</strong>${row.note?`<small>${escapeHtml(row.note)}</small>`:''}</div>`).join('')}</div><span class="meta">${escapeHtml(meta)}</span></div>`;
}
function marketValuation(ticker) {
  const stock=state.watch.find(item=>item.ticker===ticker);
  if (stock && !stock.is_fund) {
    return {pe:stock?.current_pe, percentile:null, label:stock?.upside_pct==null?'参考空间待数据':`12个月参考空间 ${signed(stock.upside_pct)}`, source:stock?.valuation?.reference_label || ''};
  }
  const fund=state.watch.find(item=>item.is_fund && item.ticker===ticker) ||
    state.watch.find(item=>item.is_fund && item.fund_valuation?.proxy_ticker===ticker) ||
    (ticker==='QQQ' ? state.watch.find(item=>item.ticker==='QQQM') : null);
  const valuation=fund?.fund_valuation;
  const tenYear=Number(valuation?.years)>=9.5 && Number(valuation?.samples)>=100;
  return {pe:valuation?.pe, percentile:tenYear?valuation.percentile:null,
    label:tenYear?`近10年 ${valuation.samples} 个月样本${fund?.ticker!==ticker?' · QQQ指数代理':''}`:
      (valuation?.history_status || '十年PE序列不足'), source:valuation?.source || ''};
}
function marketTime(value) {
  if (!value) return '时间未知';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return `${new Intl.DateTimeFormat('zh-CN',{timeZone:'America/New_York',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(date)} 美东`;
}
function marketSignalCard(ticker, model, minute, risk, environment, slotIndex) {
  const target=model.targets[ticker], setup=target.setup, intraday=minute[ticker];
  const action=environment[ticker]?.reason || '等待完整数据';
  const liveQuote=state.market.live_quotes?.[ticker] || {};
  const livePosition=state.market.live_positions?.[ticker];
  const hasFreshLivePosition=livePosition?.available && !livePosition.quote_stale;
  const positionPct=hasFreshLivePosition ? livePosition.percentile : setup?.lower_tail_pct;
  const lower=positionPct==null ? '—' : number(positionPct,1)+'%';
  const lowerPosition=positionPct==null ? 50 : Math.max(0,Math.min(100,Number(positionPct)));
  const frames=intraday?.frames || {};
  const rsi=value=>frames[String(value)]?.available ? number(frames[String(value)].rsi1,2) : '—';
  const signalLabel=intraday?.stale?'分钟行情滞后':intraday?.available ? intraday.rsi_signal || '分钟结构待确认' : '分钟RSI待更新';
  const signalTone=!intraday?.stale && signalLabel.includes('超卖')?'oversold':
    !intraday?.stale && signalLabel.includes('超买')?'overbought':'';
  const minuteTime=intraday?.latest_asof ? marketTime(intraday.latest_asof) : '等待完整分钟线';
  const minuteSession=frames['5']?.session || frames['15']?.session || '';
  const freshness=intraday?.stale?'分钟线滞后':intraday?.outside_regular_session?'上个交易时段'+(minuteSession?` · ${minuteSession}`:''):
    state.market.intraday_busy?'分钟线更新中':state.market.intraday_status || '分钟线';
  const valuation=marketValuation(ticker);
  const ten=target.bottom10 || {};
  const skillLabel=!ten.weights_active?'10日采用历史基准':ten.skill>0?
    `10日样本外 Brier 改善 ${number(ten.skill*100,1)}%`:'10日混合模型未优于基准';
  const sessionName={pre:'盘前',regular:'常规',post:'盘后'}[liveQuote.session] || '';
  const dayMove=liveQuote.change==null?'':`日涨跌 ${signed(liveQuote.change)}`;
  const sessionMove=liveQuote.session_change_pct==null?'':`${sessionName || '时段'} ${signed(liveQuote.session_change_pct)}`;
  const priceContext=[dayMove,sessionMove].filter(Boolean).join(' · ');
  return `<article class="market-signal ${risk[ticker]?.critical_negative?'risk':''}">
    <div class="signal-top"><div><span class="signal-ticker">${ticker}</span><span class="signal-name">${{QQQ:'纳斯达克100',SMH:'半导体',SPY:'标普500',ORCL:'甲骨文'}[ticker]}</span></div><div class="signal-meta"><span class="signal-status ${signalTone}">短线 · ${escapeHtml(signalLabel)}</span><span class="signal-date">历史日线 ${escapeHtml(model.date)}</span></div></div>
    <div class="market-card-tools"><button type="button" class="market-replace" data-replace-market-slot="${slotIndex}" title="更换研判标的" aria-label="更换 ${ticker}"><i data-lucide="pencil"></i></button><button type="button" class="market-remove" data-remove-market-slot="${slotIndex}" title="从市场研判移除" aria-label="从市场研判移除 ${ticker}"><i data-lucide="x"></i></button></div>
    <div class="signal-live-quote"><span>${escapeHtml(sessionName || '最新价格')}</span><strong>${liveQuote.price==null?'—':'$'+number(liveQuote.price)}</strong><small>${liveQuote.stale?'报价时间待核 · ':''}${escapeHtml(liveQuote.label || '报价待同步')}${priceContext?' · '+escapeHtml(priceContext):''} · ${escapeHtml(liveQuote.asof || '时间未知')}</small></div>
    <div class="signal-valuation"><div><span>估值判断</span><strong>${valuation.pe!=null?number(valuation.pe,1)+'倍 PE':'PE待数据'}</strong></div><div><span>${ticker==='ORCL'?'统一参考价空间':'十年PE分位'}</span><strong>${ticker==='ORCL'?escapeHtml(valuation.label):valuation.percentile!=null?number(valuation.percentile,1)+'/100':'—'}</strong></div><small>${escapeHtml(ticker==='ORCL'?valuation.source:valuation.label)}</small></div>
    ${ticker==='QQQ'?'<div class="signal-earnings"><span>未来12个月加权盈利增速</span><strong>待计算</strong><small>成分权重与同口径预测覆盖不足</small></div>':'<div class="signal-earnings signal-earnings-placeholder" aria-hidden="true"></div>'}
    <div class="signal-context signal-rsi-context"><span>RSI1 · 5/15分重点</span><span>5分 <b>${rsi(5)}</b></span><span>15分 <b>${rsi(15)}</b></span><span>30分 <b>${rsi(30)}</b></span></div>
    <div class="signal-context"><span>${hasFreshLivePosition?'最新价历史分位':'最近日线历史分位'}</span><span title="当前价相对20日均线偏离，经同期波动率标准化后在已完成日线历史中的分位；不是估值PE分位。">历史下侧 <b>${lower}</b></span><span>${hasFreshLivePosition?'有效样本':'日线RSI14'} <b>${hasFreshLivePosition?number(livePosition.samples,0):number(setup?.rsi14,1)}</b></span></div>
    <div class="signal-position"><span class="signal-position-track" style="--position:${lowerPosition}%"><i></i></span><span>历史低位</span><span>常态</span><span>历史高位</span></div>
    <div class="signal-prob"><div><span title="以已完成常规交易日收盘为预测起点，按历史未来5个交易日收盘涨跌统计；不是当前盘中入场胜率。">未来 5 日上涨（日线参考）</span><strong>${number(target.up5_pct,1)}%</strong></div><div><span title="以最近已完成常规交易日为起点；未来10个交易日最低价不低于当日最低价，且第10日收盘高于当日收盘">10 日低点守稳</span><strong>${number(target.bottom10_pct,1)}%</strong></div></div>
    <div class="signal-progress" style="--signal-width:${Math.max(0,Math.min(100,Number(target.up5_pct)||0))}%"><span></span></div>
    <div class="signal-action"><i data-lucide="scan-eye"></i><span>${escapeHtml(action)}</span></div>
    <div class="signal-foot"><span>${escapeHtml(freshness)} · ${escapeHtml(minuteTime)}</span><span>${escapeHtml(skillLabel)}</span></div>
    ${risk[ticker]?.critical_negative?'<div class="signal-critical">重大事件风险，核对敞口</div>':''}
  </article>`;
}
function marketActionCard(ticker, slotIndex, asof) {
  const item=state.actions.find(action=>action.ticker===ticker);
  const watched=state.watch.find(watch=>watch.ticker===ticker);
  const metric=item?.metric || watched?.metric || {};
  const valuation=marketValuation(ticker);
  const cached=marketRsi.get(`${ticker}|${asof}`);
  const rsi=cached?.result?.ok ? number(cached.result.rsi14,1) : '—';
  const status=metric.trend || '趋势待数据';
  const action=item?.advice?.action || '交易条件待同步';
  const zone=item?.advice?.watch_zone;
  return `<article class="market-signal market-custom">
    <div class="signal-top"><div><span class="signal-ticker">${escapeHtml(ticker)}</span><span class="signal-name">${escapeHtml(item?.name || watched?.name || '同步中')}</span></div><div class="signal-meta"><span class="signal-status">短线 · ${escapeHtml(status)}</span><span class="signal-date">日线 ${escapeHtml(metric.date || asof || '待同步')}</span></div></div>
    <div class="market-card-tools"><button type="button" class="market-replace" data-replace-market-slot="${slotIndex}" title="更换研判标的" aria-label="更换 ${escapeHtml(ticker)}"><i data-lucide="pencil"></i></button><button type="button" class="market-remove" data-remove-market-slot="${slotIndex}" title="从市场研判移除" aria-label="从市场研判移除 ${escapeHtml(ticker)}"><i data-lucide="x"></i></button></div>
    <div class="signal-valuation"><div><span>当前估值</span><strong>${valuation.pe!=null?number(valuation.pe,1)+'倍 PE':'PE待数据'}</strong></div><div><span>${item?.is_fund?'十年PE分位':'12个月参考空间'}</span><strong>${item?.is_fund?(valuation.percentile!=null?number(valuation.percentile,1)+'/100':'—'):signed(item?.upside_pct ?? watched?.upside_pct)}</strong></div><small>${escapeHtml(valuation.label)}</small></div>
    <div class="signal-earnings signal-earnings-placeholder" aria-hidden="true"></div>
    <div class="signal-context"><span>短线指标</span><span>RSI14 <b>${rsi}</b></span><span>近5日 <b class="${tone(metric.return5)}">${signed(metric.return5)}</b></span></div>
    <div class="custom-quote"><span>最近报价</span><strong>${item?.current_price==null?'—':'$'+number(item.current_price)}</strong><span>${escapeHtml(item?.price_label || '行情待同步')}</span></div>
    <div class="custom-conditions"><span>关注区 ${zone?'$'+number(zone[0])+'–'+number(zone[1]):'待计算'}</span><span>失效 ${item?.advice?.risk_price?'$'+number(item.advice.risk_price):'待计算'}</span></div>
    <div class="signal-action"><i data-lucide="scan-eye"></i><span>${escapeHtml(action)}</span></div>
    <div class="signal-foot"><span>${cached?.result?.ok?'RSI日线 '+escapeHtml(cached.result.asof):'RSI历史数据待同步'}</span><span>无专属10日概率模型</span></div>
  </article>`;
}
function renderPulse(){
  const model=state.market.model,risks=state.market.event_risk || {},environment=state.market.environment || {};
  if(!model?.available || !model.targets){
    $('#pulseHeadline').textContent='正在计算短线交易环境';$('#pulseDate').textContent=model?.reason || '优先读取本地历史';
    $('#marketDecisionStrip').innerHTML='<span>等待完整交易日数据</span>';
    $('#pulseGrid').innerHTML=marketSlots.map((ticker,index)=>marketActionCard(ticker,index,state.market?.model?.date || '')).join('') || '<div class="empty-list">点击“添加跟踪”设置研判标的</div>';
    $('#pulseFoot').textContent='';$('#modelMethod').textContent='等待有效历史数据';return;
  }
  const codes=['QQQ','SPY','SMH','ORCL'],assessment=state.market.assessment || {},cnn=assessment.cnn;
  const activeCore=marketSlots.filter(t=>model.targets[t]);
  const worst=activeCore.some(t=>risks[t]?.critical_negative),minute=state.market.intraday || {};
  const labels=activeCore.map(t=>environment[t]?.label || '');
  const hot=labels.some(label=>/超买|高位|追价|滞涨/.test(label));
  const cold=labels.some(label=>/超卖|历史极低|历史偏低/.test(label));
  const stale=activeCore.some(t=>minute[t]?.stale || state.market.live_positions?.[t]?.quote_stale);
  $('#pulseHeadline').textContent=worst?'重大事件风险上升，优先核对敞口':stale?'盘中报价或分钟线滞后，短线动作待更新':hot && cold?'跟踪标的短线位置分化':hot?'最新价处偏热区间，核对追价风险':cold?'最新价与短线 RSI 显示偏冷，结合承接评估分批条件':marketSlots.some(t=>!model.targets[t])?'自选标的估值与短线信号':assessment.headline || '短线情绪与交易环境';
  $('#pulseDate').textContent=`日线模型截至 ${model.date} · 盘中报价与 RSI 按各标的来源时间更新`;
  const actionable=marketSlots.filter(t=>/分批候选|小额关注/.test(environment[t]?.label || ''));
  $('#marketDecisionStrip').innerHTML=`<div><span class="brief-kicker">今日研究状态</span><strong>${worst?'先核对重大风险':stale?'等待报价与分钟线同步':actionable.length?'有 '+actionable.length+' 个标的满足分批观察条件':'观察优先，等待确认'}</strong></div><div class="brief-items"><span><i data-lucide="crosshair"></i>${actionable.length} 个满足分批条件</span><span><i data-lucide="shield-alert"></i>${worst?'存在重大事件否决':'事件风险逐条核验'}</span><span><i data-lucide="database"></i>日线 ${escapeHtml(model.date)}</span></div>`;
  $('#pulseGrid').innerHTML=marketSlots.map((ticker,index)=>model.targets[ticker]
    ? marketSignalCard(ticker,model,minute,risks,environment,index)
    : marketActionCard(ticker,index,model.date)).join('') || '<div class="empty-list">点击“添加跟踪”设置研判标的</div>';
  $('#pulseFoot').textContent='';
  const report=(ticker,name,item)=>`<div class="model-report"><strong>${ticker} · ${name}</strong><p>${escapeHtml(item.method)} · 不重叠基准样本 ${item.training_samples} 组 · 按时间检验 ${item.validation_count} 次 · 概率误差 ${number(item.brier,4)} / 基线 ${number(item.baseline_brier,4)}（越小越好）</p><p>${escapeHtml(item.interval_scope)}：${item.interval?.join('–') || '样本不足'}%（历史发生率95%区间，不是未来真实概率保证）。</p></div>`;
  $('#modelMethod').innerHTML=codes.map(t=>report(t,'未来3日上涨',model.targets[t].up3)+report(t,'未来5日上涨',model.targets[t].up5)+report(t,'10日低点守稳',model.targets[t].bottom10)+`<details class="coefficient-report"><summary>${t} 五日模型的指标与权重</summary><p>${model.targets[t].up5.weights_active?'当前输出采用65%校准模型与35%历史基准。':'候选模型暂未提供稳定额外优势，当前输出采用100%历史基准；下列候选系数暂不用于最终概率。'}</p><table><thead><tr><th>指标</th><th>标准化系数</th><th>绝对系数占比</th></tr></thead><tbody>${model.targets[t].up5.feature_weights.map(w=>`<tr><td>${escapeHtml(w.name)}</td><td>${number(w.coefficient,4)}</td><td>${number(w.share_pct,1)}%</td></tr>`).join('')}</tbody></table><p>系数由过去训练数据拟合；占比帮助理解模型，不是因果权重，也不是概率增加的百分点。</p></details>`).join('')+`<p>${escapeHtml(model.up5_definition)}。${escapeHtml(model.bottom10_definition)}。</p><p>历史 ${model.history_start}—${model.date}，${model.history_days} 个共同交易日。${escapeHtml(model.limitations)}</p><p>${escapeHtml(risks.definition || '')}。${escapeHtml(risks.news_model_status || '')}。公开言论、议员提案与已生效政策分别处理。</p>`;
  $('#modelMethod').innerHTML+=`<details class="coefficient-report"><summary>查看RSI1 5 / 15 / 30分钟依据与权重</summary><p>短线 RSI 压力分按 5分钟40%、15分钟40%、30分钟20%加权；双周期超买/超卖分达到0.8才算短线共振。当前分数用于信号分级，不是收益概率；历史分位单独作为价格位置条件。</p><table><thead><tr><th>标的/周期</th><th>权重</th><th>RSI1</th><th>状态</th><th>交易时段/截至（美东）</th></tr></thead><tbody>${codes.flatMap(t=>['5','15','30'].map(k=>{const f=minute[t]?.frames?.[k];if(!f?.available)return `<tr><td>${t} ${k}分</td><td>${k==='30'?'20%':'40%'}</td><td colspan="3">等待分钟行情</td></tr>`;return `<tr><td>${t} ${k}分${k==='15'?'（重点）':''}</td><td>${k==='30'?'20%':'40%'}</td><td>${number(f.rsi1,2)}</td><td>${escapeHtml(f.rsi1<=30?'超卖':f.rsi1>=70?'超买':'常态')}</td><td>${escapeHtml(f.session || '—')} · ${new Date(f.asof).toLocaleString('zh-CN',{timeZone:'America/New_York',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false})}</td></tr>`;})).join('')}</tbody></table></details>`;

}

function renderEvents() {
  const cutoff = Date.now() - 72 * 3600 * 1000;
  const recent = state.news.filter((item) => {
    const timestamp = Date.parse(item.published_raw);
    return Number.isFinite(timestamp) && timestamp >= cutoff && timestamp <= Date.now();
  });
  const high = recent.filter((item) => item.grade === 'S1' || item.grade === 'S2');
  const held = new Set(state.watch.filter((item) => item.is_held).map((item) => item.ticker));
  const followed = new Set(state.actions.map((item) => item.ticker));
  const rank = {'S1':4,'S2':3,'S3':2,'S4':1};
  const focusPool = recent.filter(item =>
    item.analysis && (item.tickers.some(ticker => followed.has(ticker)) ||
      item.topics.some(topic => /半导体|算力|云|AI|光通信|存储/.test(topic))));
  const stance=state.market.event_risk?.stance || {};
  $('#eventStanceDashboard').hidden=!Object.values(stance).some(item=>item?.event_count>0 && Math.abs(item?.net_score)>0);
  const stanceCard=(name,icon)=>{const item=stance[name];if(!item)return `<div class="stance-card"><span class="stance-title">${icon} ${escapeHtml(name)}</span><strong>等待相关情报</strong><small>最近24小时暂无足够的产业链事件</small></div>`;const tone=item.net_score>15?'positive':item.net_score<-15?'negative':'neutral';const top=item.top_event;return `<div class="stance-card ${tone}"><span class="stance-title">${icon} ${escapeHtml(name)}</span><strong>${escapeHtml(item.label)}</strong><span class="stance-score">影响分 ${item.net_score>0?'+':''}${number(item.net_score,1)} / 100</span><small>${item.event_count} 条相关事件 · ${item.verified_count} 条有核验证据${top?` · 最高影响：${escapeHtml(top.stage)}`:''}</small></div>`;};
  $('#eventStanceDashboard').innerHTML=`<div class="stance-heading"><strong>过去24小时产业链信息影响</strong><span>官方公告 · 独立报道 · 产业传导 · 时效</span></div><div class="stance-grid">${stanceCard('半导体产业链','◈')}${stanceCard('大科技与AI','◌')}</div><p class="stance-method">信息影响分用于事件排序，不代表收益概率；结论结合来源等级、正文证据和市场反应。</p>`;
  const lead = [...focusPool].sort((a,b) =>
    (Number(b.tickers.some(ticker => held.has(ticker))) - Number(a.tickers.some(ticker => held.has(ticker)))) ||
    ((b.analysis?.score ?? rank[b.grade]*12)-(a.analysis?.score ?? rank[a.grade]*12)) ||
    (Date.parse(b.published_raw) - Date.parse(a.published_raw)))[0];
  focusEventId = lead?.id ?? null;
  const leadGrade=lead?.analysis?.grade || lead?.grade;
  const leadDirection=lead?.analysis?.direction || lead?.direction;
  $('#leadEvent').innerHTML = lead ? `<span class="focus-kicker"><span class="focus-caption">重点事件</span><span class="tag ${gradeTone(leadGrade)}">${escapeHtml(leadGrade)}</span>
    <span class="direction ${leadDirection === '偏正面' ? 'positive' : leadDirection === '偏负面' ? 'negative' : 'neutral'}">${escapeHtml(leadDirection)}</span>
    <span>来源 RSS 发布：${escapeHtml(lead.published_full)}（北京时）</span><span>${escapeHtml(lead.tickers.join(' / ') || '宏观')}</span></span>
    <strong>${escapeHtml(lead.title)}</strong><span class="focus-source">${escapeHtml(lead.publisher || lead.source)} · ${escapeHtml(lead.analysis?.conclusion || '正文核验中')}</span>` :
    '<span class="focus-empty">最近 72 小时暂无已初核的自选或科技产业链事件；可在下方检索全部资讯。</span>';
  const query = $('#eventSearch').value.trim().toLowerCase();
  const queryTerms = query.split(/\s+/).filter(Boolean);
  const grade = $('#gradeFilter').value;
  const direction = $('#directionFilter').value;
  const topic = $('#topicFilter').value;
  const dateRange = $('#dateFilter').value;
  const holdings = held;
  const filtered = state.news.filter((item) => {
    const timestamp = Date.parse(item.published_raw);
    const withinDate = dateRange === 'all' ||
      (Number.isFinite(timestamp) && timestamp <= Date.now() && timestamp >= Date.now() - (dateRange === '7d' ? 7 * 24 : 72) * 3600 * 1000);
    const haystack = `${item.title} ${item.raw_title} ${item.tickers.join(' ')} ${item.topics.join(' ')} ${item.source}`.toLowerCase();
    const matchesText = !query || queryTerms.every((term) => haystack.includes(term)) ||
      (item.live_match && state.search_query?.toLowerCase() === query);
    return withinDate && (grade === 'all' || (grade === 'material' ? (query || rank[item.analysis?.grade || item.grade]>=2) : grade === (item.analysis?.grade || item.grade))) &&
      (direction === 'all' || direction === (item.analysis?.direction || item.direction)) &&
      (topic === 'all' || (topic === 'holdings' ? item.tickers.some((ticker) => holdings.has(ticker)) : item.topics.includes(topic))) &&
      matchesText;
  });
  const holder = $('#eventList');
  holder.innerHTML = filtered.slice(0, visibleEvents).map((item) => {const effectiveGrade=item.analysis?.grade || item.grade; const effectiveDirection=item.analysis?.direction || item.direction; return `<button type="button" class="event-row ${item.id === selectedEvent ? 'selected' : ''}" data-event="${item.id}" role="listitem">
    <span class="event-row-meta"><span class="time" title="来源 RSS 发布时间，北京时间">${escapeHtml(item.published)}</span><span class="tag ${gradeTone(effectiveGrade)}">${escapeHtml(effectiveGrade)}</span>
    <span class="direction ${effectiveDirection === '偏正面' ? 'positive' : effectiveDirection === '偏负面' ? 'negative' : 'neutral'}">${escapeHtml(effectiveDirection)}</span>
    <span class="company">${escapeHtml(item.tickers.join(' / ') || '宏观')}</span></span>
    <span class="title">${escapeHtml(item.title)}</span><span class="event-row-source">${escapeHtml(item.analysis?.conclusion || `${item.publisher || item.source} · ${item.horizon}`)}${item.translated ? '' : ' · 译文生成中'}</span></button>`;}).join('') || '<div class="empty-list">当前筛选条件下没有事件</div>';
  $('#showMoreEvents').hidden = filtered.length <= visibleEvents;
  if (selectedEvent == null && filtered.length) selectedEvent = filtered[0].id;
  if (!filtered.some((item) => item.id === selectedEvent)) selectedEvent = filtered[0]?.id ?? null;
  renderEventDetail();
}
function renderEventDetail() {
  const item = state.news.find((news) => news.id === selectedEvent);
  $('#eventList').querySelectorAll('.event-row').forEach((row) => row.classList.toggle('selected', Number(row.dataset.event) === selectedEvent));
  if (!item) { $('#eventDetail').innerHTML = '<div class="empty-detail">选择一条事件查看依据与原始来源</div>'; return; }
  const translated=eventTranslations.get(item.url);
  const intelligence=eventIntelligence.get(item.url) || item.analysis;
  const facts=intelligence?.facts || {};
  const factRows=[['股数',facts.share_count],['持股比例',facts.ownership_pct],['机构组合占比',facts.portfolio_weight_pct],['买入价格',facts.purchase_price]].filter(([,value])=>value);
  const reaction=intelligence?.market_reaction;
  const reactionRows=reaction?.rows || [];
  const factors=intelligence?.factors || {};
  $('#eventDetail').innerHTML = `<div class="detail-kicker">${escapeHtml(intelligence?.grade || item.grade)} · ${escapeHtml(intelligence?.direction || item.direction)} · 来源 RSS 发布 ${escapeHtml(item.published_full)}（北京时间）</div>
    <h3>${escapeHtml(translated?.title || item.title)}</h3><p>${escapeHtml(translated?.summary || item.summary)}</p>
    ${!item.summary_translated && !translated ? '<div class="translation-status">正在翻译这条事件的摘要…</div>' : ''}
    <div class="intelligence-block"><span class="intelligence-label">情报结论</span><p>${escapeHtml(intelligence?.conclusion || '正在核验原文与市场反应；目前仅有标题和摘要初筛。')}</p></div>
    ${intelligence ? `<div class="intelligence-facts"><span>事件重要性 ${intelligence.score}/100 · ${escapeHtml(intelligence.confidence)} · ${escapeHtml(intelligence.event_type)}</span>
    ${factRows.map(([label,value])=>`<b>${escapeHtml(label)} ${escapeHtml(value)}</b>`).join('')}</div>
    ${intelligence.evidence?.length ? `<div class="intelligence-evidence"><strong>依据片段</strong>${(intelligence.evidence_zh || intelligence.evidence).map(text=>`<p>${escapeHtml(text)}</p>`).join('')}</div>` : ''}
    <div class="intelligence-reaction"><strong>行情核对</strong><p>${escapeHtml(reaction?.status || '正在对齐事件发布时间和交易日。')}
    ${reactionRows.map(row=>`${escapeHtml(row.ticker)} ${escapeHtml(row.date)} ${signed(row.change_pct)}${row.excess_pct == null ? '' : `，相对 ${escapeHtml(row.benchmark)} ${signed(row.excess_pct)}`}`).join('；')}</p></div>
    <details class="factor-details"><summary>查看分析权重和限制</summary><div>${Object.entries(factors).map(([label,value])=>`<span>${escapeHtml(label)} ${value}/${intelligence.max_factors?.[label] ?? 0}</span>`).join('')}</div><p>${escapeHtml(intelligence.body_error || '正文可访问')}。重要性分数用于事件排序，不代表收益概率；行情同现不证明因果。</p></details>` : `<p class="translation-status">正文分析未完成</p>`}
    <div class="detail-meta"><div>关联标的<strong>${escapeHtml(item.tickers.join(' / ') || '宏观')}</strong></div><div>影响周期<strong>${escapeHtml(item.horizon)}</strong></div>
    <div>来源等级<strong>${escapeHtml(item.source_tier || '待评估')}</strong></div>
    <div>发布媒体 / 聚合来源<strong>${escapeHtml(item.publisher ? `${item.publisher} · ${item.source}` : item.source)}</strong></div><div>核验状态<strong>${escapeHtml(item.credibility)}</strong></div>
    <div>独立发布媒体<strong>${item.independent_publishers?.length || 0} 家${item.independent_publishers?.length ? ` · ${escapeHtml(item.independent_publishers.join('、'))}` : ''}</strong></div>
    <div>行业关联<strong>${escapeHtml(item.topics.join('、') || '未分类')}</strong></div></div>
    <div class="detail-actions"><button type="button" class="detail-link" data-open-url="${item.id}"><i data-lucide="external-link"></i> 查看原始来源</button>
    <button type="button" class="detail-link" data-ai-event="${item.id}"><i data-lucide="sparkles"></i> 本地深度分析</button></div>
    <div class="event-market" id="eventMarket">${eventContexts.has(item.url) ? renderEventContext(eventContexts.get(item.url)) : item.tickers.length ? '正在读取关联公司的最近行情…' : ''}</div>
    ${aiResults.has(item.url) ? `<div class="ai-analysis">${escapeHtml(aiResults.get(item.url))}</div>` : ''}`;
  icons();
  if (!intelligence && !eventIntelligenceLoading.has(item.url) && !eventIntelligenceFailed.has(item.url)) loadIntelligence(item.url);
  if ((!item.summary_translated || !item.translated) && !eventTranslations.has(item.url) && !eventTranslationsLoading.has(item.url)) loadEventTranslation(item.url);
  if (item.tickers.length && !eventContexts.has(item.url) && !eventContextsLoading.has(item.url)) loadEventContext(item.url);
}
async function loadIntelligence(url) {
  eventIntelligenceLoading.add(url);
  const result=await call('get_event_intelligence',url);
  eventIntelligenceLoading.delete(url);
  if (result?.ok) eventIntelligence.set(url,result.analysis);
  else eventIntelligenceFailed.add(url);
  if (state.news.find((item)=>item.id === selectedEvent)?.url === url) renderEventDetail();
}
async function loadEventTranslation(url) {
  eventTranslationsLoading.add(url);
  const result=await call('translate_event',url);
  eventTranslationsLoading.delete(url);
  eventTranslations.set(url,result?.ok ? result : {ok:false});
  if (state.news.find((item) => item.id === selectedEvent)?.url === url) renderEventDetail();
}
function renderEventContext(context) {
  if (!context?.ok || !context.rows?.length) return '';
  return context.rows.map((row) => `<div class="event-market-row"><div><strong>${escapeHtml(row.name)} ${escapeHtml(row.ticker)}</strong><span>${escapeHtml(row.quote_day || '报价日期缺失')}</span></div>
    <div>${row.price == null ? '无报价' : `$${number(row.price)} · ${signed(row.change)}`}</div>
    <div>${row.current_pe == null ? escapeHtml(row.pe_status || '当前PE待数据') : `当前PE ${number(row.current_pe,1)} 倍`}</div>
    <div>${row.target == null ? '统一参考价待数据' : `未来12个月合理价值 $${number(row.target)} · ${signed(row.upside_pct)}`}</div>
    <small>${escapeHtml(row.price_confirmation)}</small></div>`).join('');
}
async function loadEventContext(url) {
  const referenceKey=state.reference_key;
  eventContextsLoading.add(url);
  const result=await call('event_market_context',url);
  eventContextsLoading.delete(url);
  const selected=state.news.find((item) => item.id === selectedEvent);
  if(referenceKey!==state.reference_key){if(selected?.url===url)renderEventDetail();return;}
  eventContexts.set(url,result);
  if (selected?.url === url) renderEventDetail();
}

function renderMarket() {
  const rotation=state.market.rotation?.[String(rotationPeriod)];
  document.querySelectorAll('#rotationPeriod button').forEach(button=>button.classList.toggle('active',Number(button.dataset.period)===rotationPeriod));
  if (!rotation?.available) {
    $('#rotationDate').textContent='等待板块行情';
    $('#rotationInsight').innerHTML='<div class="empty-detail">取得板块日线后，将计算防御、成长与半导体的资金偏好。</div>';
    return;
  }
  $('#rotationDate').textContent=`${rotationPeriod===5 ? '近5' : '近20'}个交易日 · 截至 ${rotation.date}${rotation.stale ? ' · 历史缓存' : ''}`;
  const other=state.market.rotation?.[String(rotationPeriod===5?20:5)];
  $('#rotationInsight').innerHTML=`<div class="insight-kicker"><i data-lucide="scan-line"></i> 轮动洞察 · ${rotationPeriod}个交易日</div><h3>${escapeHtml(rotation.headline)}</h3><ul>${rotation.evidence.map(line=>`<li>${escapeHtml(line)}</li>`).join('')}</ul>${other?.available?`<div class="rotation-compare"><span>另一时间窗口</span><strong>${rotationPeriod===5?'近20日':'近5日'} · ${escapeHtml(other.headline)}</strong></div>`:''}<div class="rotation-action"><strong>交易观察</strong><p>${escapeHtml(rotation.action)}</p></div><p class="method-note">这是量价资金偏好代理，不是真实净流入。得分与相对强弱同时改善才视为较强证据。</p>`;
  if (!window.Chart)return;
  if (chart)chart.destroy();
  const rows=rotation.rows;
  chart=new Chart($('#rotationChart'),{type:'bar',data:{labels:rows.map(r=>r.name),datasets:[{label:'承接 / 卖压得分',data:rows.map(r=>r.pressure),backgroundColor:rows.map(r=>r.pressure>=0?'#18a890':'#df737d'),borderRadius:4,maxBarThickness:27}]},options:{responsive:true,maintainAspectRatio:false,animation:false,indexAxis:'y',plugins:{legend:{display:false},tooltip:{callbacks:{afterLabel:ctx=>{const r=rows[ctx.dataIndex];return [`区间涨跌 ${signed(r.return_pct)}`,`相对标普 ${r.relative_pct>0?'+':''}${number(r.relative_pct)} 个百分点`,`平均成交量 / 前20日 ${number(r.volume_ratio)} 倍`];}}}},scales:{x:{min:-100,max:100,grid:{color:'#e8eef1'},ticks:{color:'#788b99'},title:{display:true,text:'卖压 ← 量价资金偏好代理 → 承接',color:'#788b99'}},y:{grid:{display:false},ticks:{color:'#38576a',font:{size:12}}}}}});
}

function annualCaption(item){
  if(item.is_fund){const fv=item.fund_valuation;return `当前PE ${fv?.pe ? number(fv.pe,1)+'倍' : '待数据'} · 历史估值分位 ${fv?.percentile!=null ? number(fv.percentile,1)+' / 100' : (fv?.history_status || '待历史数据')}`;}
  const annual=item.annual;return annual?.reference_price ? `未来12个月合理价值：$${number(annual.reference_price)} · ${signed(annual.upside_pct)}` : '未来12个月合理价值待有效数据';
}
function renderPriceMap(item) {
  const zone=item.advice?.watch_zone;
  const risk=Number(item.advice?.risk_price), current=Number(item.current_price);
  if (!Array.isArray(zone) || zone.length!==2 || !Number.isFinite(risk) || risk<=0 || !Number.isFinite(current) || current<=0) return '';
  const low=Number(zone[0]),high=Number(zone[1]);
  if (!Number.isFinite(low) || !Number.isFinite(high) || low<=0 || high<low) return '';
  const values=[risk,low,high,current],span=Math.max(...values)-Math.min(...values);
  const padding=Math.max(span*.18,current*.015),min=Math.min(...values)-padding,max=Math.max(...values)+padding;
  const point=value=>Math.max(0,Math.min(100,(value-min)/(max-min)*100));
  const zoneLeft=point(low),zoneWidth=Math.max(1,point(high)-zoneLeft);
  return `<div class="price-map"><div class="price-map-heading"><strong>短线价格位置</strong><span>关注区与失效价来自原版条件规则</span></div>
    <div class="price-map-track"><span class="price-map-zone" style="left:${zoneLeft}%;width:${zoneWidth}%"></span><span class="price-map-risk" style="left:${point(risk)}%"></span><span class="price-map-current" style="left:${point(current)}%"></span></div>
    <div class="price-map-key"><span><i class="key-risk"></i>失效 $${number(risk)}</span><span><i class="key-zone"></i>关注 $${number(low)}–${number(high)}</span><span><i class="key-current"></i>现价 $${number(current)}</span></div></div>`;
}
function renderDecisions() {
  const known=state.actions.filter(item=>item.metric).length;
  $('#decisionStatus').textContent=`${known} 个标的可评估 · 先看动作与失效，再核对估值；进入关注区不代表确认买入。`;
  $('#decisionGrid').innerHTML=state.actions.map(item=>`<article class="decision-card ${selectedAction===item.ticker?'selected':''}">
    <button type="button" class="decision-select" data-action="${escapeHtml(item.ticker)}" aria-label="查看${escapeHtml(item.ticker)}交易参考">
      <span class="decision-card-top"><span class="decision-identity"><strong>${escapeHtml(item.ticker)}</strong><span class="decision-security-name">${escapeHtml(item.name || '')}</span></span>${item.held?'<em class="held-tag">持有标记</em>':''}</span>
      <span class="decision-card-metrics"><span><small>最近报价</small><strong>${item.current_price==null?'—':'$'+number(item.current_price)}</strong></span><span><small>${item.is_fund?'历史估值分位':'12个月参考空间'}</small><strong class="${tone(item.upside_pct)}">${item.is_fund?(item.fund_valuation?.percentile!=null?number(item.fund_valuation.percentile,1)+'/100':'—'):signed(item.upside_pct)}</strong></span></span>
      <span class="action-label ${item.advice.action.includes('风险')?'risk':''}">${escapeHtml(item.advice.action)}</span>
      <span class="decision-prices">${item.advice.in_watch_zone?'已进入关注区':'关注区间'} ${item.advice.watch_zone ? '$'+number(item.advice.watch_zone[0])+'–'+number(item.advice.watch_zone[1]) : '正在获取日线并计算'}</span>
      <span class="decision-risk-price">失效价 <strong>${item.advice.risk_price?'$'+number(item.advice.risk_price):'待计算'}</strong></span>
      <span class="decision-quote-time">${escapeHtml(item.price_label)} · ${escapeHtml(item.quote_asof || '等待行情')}${item.sync_status==='正在更新'?' · 数据更新中':''}</span>
    </button><button type="button" class="tracking-remove" data-remove-tracking="${escapeHtml(item.ticker)}" title="移出跟踪，保留实际持仓" aria-label="移出跟踪${escapeHtml(item.ticker)}"><i data-lucide="x"></i></button></article>`).join('') || '<div class="empty-list">尚未设置跟踪标的，点击右上角「添加标的」开始。</div>';
  if (!state.actions.some(item=>item.ticker===selectedAction))selectedAction=state.actions[0]?.ticker || null;
  renderDecisionDetail();
}
function renderDecisionDetail() {
  const item=state.actions.find(action=>action.ticker===selectedAction);
  $('#decisionGrid').querySelectorAll('.decision-card').forEach(card=>card.classList.toggle('selected',card.querySelector('[data-action]')?.dataset.action===selectedAction));
  if (!item){$('#decisionDetail').innerHTML='<div class="empty-detail">选择标的查看依据</div>';return;}
  const a=item.advice,annual=item.annual;
  const v=item.valuation || {},ref=v.reference || {};
  $('#decisionDetail').innerHTML=`<h3>${escapeHtml(item.ticker)} <span class="decision-current">${item.current_price==null?'—':'$'+number(item.current_price)}</span> · ${escapeHtml(a.action)}</h3>
    <p class="decision-quote-time">${escapeHtml(item.price_label)} · ${escapeHtml(item.quote_asof)}${item.regular_close?' · 最近收盘 $'+number(item.regular_close):''}</p>
    <div class="decision-price-row"><div><span>短线关注区间</span><strong>${a.watch_zone?'$'+number(a.watch_zone[0])+'–$'+number(a.watch_zone[1]):'待计算'}</strong></div><div><span>${item.is_fund?'当前PE / 历史估值分位':'未来12个月合理价值 / 空间'}</span><strong>${item.is_fund ? (item.fund_valuation?.pe ? number(item.fund_valuation.pe,1)+'倍' : 'PE待数据')+' / '+(item.fund_valuation?.percentile!=null ? number(item.fund_valuation.percentile,1)+' / 100' : (item.fund_valuation?.history_status || '历史待数据')) : item.reference_price?'$'+number(item.reference_price)+' / '+signed(item.upside_pct):'待有效数据'}</strong></div><div><span>风险失效价</span><strong>${a.risk_price?'$'+number(a.risk_price):'—'}</strong></div></div>
    ${renderPriceMap(item)}
    <div class="decision-detail-grid"><div><span>参考价依据</span><p>${item.is_fund ? escapeHtml(item.fund_valuation ? item.fund_valuation.basis+' · '+item.fund_valuation.source+' · '+item.fund_valuation.asof : '正在获取基金组合PE及同口径历史；历史不足不生成分位') : escapeHtml(v.reference_label || '')+'。'+escapeHtml(v.reason || '')}</p></div><div><span>短线确认条件</span><p>${escapeHtml(a.confirm)}</p></div><div><span>失效与风险</span><p>${escapeHtml(a.invalidate)}</p></div></div><p class="method-note">${item.is_fund?'基金按当前PE与历史估值分位评估相对贵贱；分位越低，历史相对估值越低。':'参考空间＝未来12个月合理价值÷当前价－1，与下方估值表一致。'}关注区间属于短线价格条件。</p>`;

}

function renderPortfolio() {
  const priced = state.portfolio.filter((item) => item.value != null);
  const value = priced.reduce((sum, item) => sum + item.value, 0);
  const profit = priced.reduce((sum, item) => sum + item.profit, 0);
  $('#portfolioSummary').innerHTML = `<div class="portfolio-stat"><label>跟踪标的</label><strong>${state.actions.length}</strong></div>
    <div class="portfolio-stat"><label>已录入数量与成本</label><strong>${state.portfolio.length}</strong></div>
    <div class="portfolio-stat"><label>可计价市值</label><strong>$${number(value)}</strong></div>
    <div class="portfolio-stat"><label>未实现盈亏</label><strong class="${tone(profit)}">${profit > 0 ? '+' : ''}$${number(profit)}</strong></div>`;
  const funds=state.watch.filter(item=>item.is_fund && !item.ticker.startsWith('^'));
  const stocks=state.watch.filter(item=>!item.is_fund)
    .sort((a,b) => (b.upside_pct ?? -Infinity)-(a.upside_pct ?? -Infinity));
  $('#fundTable tbody').innerHTML = funds.map((item) => `<tr data-watch="${escapeHtml(item.ticker)}" class="${selectedWatch === item.ticker ? 'selected' : ''}">
    <td>${escapeHtml(item.ticker)} ${item.is_held ? '<em class="held-tag">已持有</em>' : ''} <span class="muted">${escapeHtml(item.name)}</span></td>
    <td>${item.price == null ? '无报价' : '$' + number(item.price)}<small class="price-label">${escapeHtml(item.price_label)}${item.session_change_pct!=null?' · '+signed(item.session_change_pct):''}</small></td><td class="${tone(item.change)}">${signed(item.change)}</td>
    <td class="${tone(item.metric?.return5)}">${signed(item.metric?.return5)}</td><td>${escapeHtml(item.metric?.trend || '数据不足')}</td>
    <td title="${escapeHtml(item.fund_valuation?.basis)} · ${escapeHtml(item.fund_valuation?.source)}">${item.fund_valuation?.pe ? number(item.fund_valuation.pe,2)+' 倍' : '待取得估值'}<small class="price-label">${escapeHtml(item.fund_valuation?.proxy_ticker ? 'QQQ 指数代理' : item.fund_valuation?.asof || '')}</small></td>
    <td>${item.fund_valuation?.percentile!=null ? number(item.fund_valuation.percentile,1)+' / 100<small class="price-label">近'+number(item.fund_valuation.years,0)+'年 · '+item.fund_valuation.samples+'个月度样本</small>' : '<span class="muted">历史PE不足</span>'}</td><td class="muted">${escapeHtml(item.asof || '来源不可用')}</td></tr>`).join('') || '<tr><td colspan="8" class="muted">观察列表中暂无宽基或行业基金</td></tr>';
  $('#watchTable tbody').innerHTML=stocks.map(item=>`<tr data-watch="${escapeHtml(item.ticker)}" class="${selectedWatch===item.ticker?'selected':''}"><td title="${escapeHtml(item.name)}">${escapeHtml(item.ticker)} ${item.is_held?'<em class="held-tag">已持有</em>':''}<span class="muted"> ${escapeHtml(item.name)}</span></td><td>$${number(item.price)}<small class="price-label">${escapeHtml(item.price_label)}</small></td><td class="${tone(item.change)}">${signed(item.change)}</td><td title="${escapeHtml(item.valuation.current_pe_source)}">${item.current_pe==null?escapeHtml(item.pe_status):number(item.current_pe,1)+' 倍'}</td><td>${item.fair_price?'$'+number(item.fair_price):'待有效数据'}</td><td class="${tone(item.upside_pct)}">${signed(item.upside_pct)}</td><td class="reference-method">${escapeHtml(item.valuation.reference_label)}</td><td>${escapeHtml(item.asof)}</td></tr>`).join('') || '<tr><td colspan="8">暂无个股跟踪</td></tr>';
  $('#positionTable tbody').innerHTML = state.portfolio.map((item) => `<tr><td>${escapeHtml(item.ticker)}</td><td>${number(item.quantity,0)}</td><td>$${number(item.cost,3)}</td>
    <td>${item.price == null ? '无报价' : '$' + number(item.price)}</td><td>${item.value == null ? '—' : '$' + number(item.value)}</td>
    <td class="${tone(item.profit)}">${item.profit == null ? '—' : `${item.profit > 0 ? '+' : ''}$${number(item.profit)}`}</td>
    <td><button class="small-command" data-delete="${escapeHtml(item.ticker)}">删除</button></td></tr>`).join('') || '<tr><td colspan="7" class="muted">尚未录入实际持仓</td></tr>';
  if (selectedWatch == null && state.watch.length) selectedWatch = stocks[0]?.ticker || state.watch[0].ticker;
  renderValuationDetail();
}
function renderValuationDetail() {
  const item = state.watch.find((row) => row.ticker === selectedWatch);
  $('#watchTable tbody').querySelectorAll('tr').forEach((row) => row.classList.toggle('selected', row.dataset.watch === selectedWatch));
  $('#fundTable tbody').querySelectorAll('tr').forEach((row) => row.classList.toggle('selected', row.dataset.watch === selectedWatch));
  if (!item) { $('#valuationDetail').innerHTML = '<div class="empty-detail">选择标的查看估值依据</div>'; return; }
  const news = state.news.filter((article) => article.tickers.includes(item.ticker)).slice(0,2);
  const isFund=!!item.is_fund,v=item.valuation || {},ref=v.reference || {},fv=item.fund_valuation;
  const fundCopy=fv?`当前PE ${number(fv.pe,2)} 倍 · ${fv.basis} · ${fv.source} · ${fv.asof}。${fv.percentile!=null?'近'+number(fv.years,0)+'年估值分位 '+number(fv.percentile,1)+'%。':(fv.history_status || '历史序列暂缺。')}`:'尚未取得可复核的基金PE';
  const valueCopy=item.fair_price?`未来12个月合理价值 $${number(item.fair_price)}，相对当前价 ${signed(item.upside_pct)}。${v.reference_method==='management_history_median' ? '管理层未来12个月EPS '+number(v.eps_used)+' × 历史PE中位数 '+number(v.pe_used,2)+' 倍。' : '采用来源发布的分析师目标价中位数。'}`:'未来12个月合理价值暂缺。';
  $('#valuationDetail').innerHTML=`<div class="valuation-layout"><div class="valuation-copy"><strong>${escapeHtml(item.ticker)} · ${escapeHtml(item.name)}</strong><div>${escapeHtml(isFund?fundCopy:valueCopy)}</div>${!isFund?`<div>${escapeHtml(v.reason || '')}</div><div>价格依据：${escapeHtml(ref.source || v.reference_label)}${ref.fetched_at?' · 获取 '+new Date(ref.fetched_at).toLocaleString('zh-CN',{hour12:false}):''}</div>${ref.source_url?`<button type="button" class="small-command" data-open-management="${escapeHtml(ref.source_url)}">核对参考价来源</button>`:''}${ref.guidance_url?`<button type="button" class="small-command" data-open-management="${escapeHtml(ref.guidance_url)}">核对管理层指引</button>`:''}<p class="method-note">当前PE采用历史12个月会计盈利；亏损时不生成正PE。参考价在交易卡片、估值表与事件详情共用，不混用旧版情景价与平均目标价。</p>`:''}${news.length?`<div>${escapeHtml(news.map(n=>n.title).join('；'))}</div>`:''}</div><div class="valuation-controls"><button type="button" class="quiet-button" id="toggleHolding">${item.is_held?'取消持有标记':'标记为已持有'}</button>${!isFund?'<button type="button" class="quiet-button" id="addGuidance">管理层指引</button>':''}</div></div>`;
  icons();
}

function renderSettings() {
  const proxy = $('#proxyInput');
  if (document.activeElement !== proxy) proxy.value = state.settings.https_proxy || '';
  $('#autoProxy').checked = !!state.settings.auto_local_proxy;
  if(document.activeElement!==$('#publicPostInput'))$('#publicPostInput').value=(state.settings.public_post_urls || []).join('\n');
  if (document.activeElement !== $('#modelInput')) $('#modelInput').value=state.settings.openai_model || '';
}
function syncActiveTab(){
  const anchor=document.querySelector('.topbar').getBoundingClientRect().bottom+120;
  let current='marketPulse';
  document.querySelectorAll('main > section').forEach(section=>{if(section.getBoundingClientRect().top<=anchor)current=section.id;});
  document.querySelectorAll('.section-nav a').forEach(link=>link.classList.toggle('active',link.getAttribute('href')==='#'+current));
}
function render() {setStatus();renderPulse();renderEvents();renderMarket();renderDecisions();renderPortfolio();renderSettings();icons();syncActiveTab();}

async function call(method,...args) {
  try { return await window.pywebview.api[method](...args); }
  catch (error) {toast('操作失败，请检查连接与本地日志');return {ok:false};}
}
async function loadMarketSlots() {
  const result=await call('get_market_slots');
  if (result?.ok && Array.isArray(result.slots)) marketSlots=result.slots;
}
async function saveMarketSlots(slots) {
  const result=await call('save_market_slots',slots);
  if (!result?.ok) {toast(result?.message || '研判位保存失败');return false;}
  marketSlots=result.slots;
  renderPulse();icons();
  void refreshMarketRsi();
  return true;
}
async function refreshMarketRsi() {
  const asof=state?.market?.model?.date;
  if (!asof) return;
  for (const ticker of marketSlots) {
    if (state.market.model?.targets?.[ticker]) continue;
    const key=`${ticker}|${asof}`, cached=marketRsi.get(key);
    if (marketRsiLoading.has(key) || (cached && (cached.result?.ok || Date.now()-cached.checkedAt<45000))) continue;
    marketRsiLoading.add(key);
    const result=await call('get_market_rsi',ticker,asof);
    marketRsiLoading.delete(key);
    marketRsi.set(key,{result,checkedAt:Date.now()});
    if (marketSlots.includes(ticker)) {renderPulse();icons();}
  }
}
function openMarketSlotDialog(index) {
  const select=$('#marketSlotIndex');
  select.innerHTML=marketSlots.map((ticker,slot)=>`<option value="${slot}">第 ${slot+1} 位 · ${escapeHtml(ticker)}</option>`).join('')+
    (marketSlots.length<4?`<option value="new">新增第 ${marketSlots.length+1} 位</option>`:'');
  select.value=index==null?(marketSlots.length<4?'new':String(marketSlots.length-1)):String(index);
  $('#marketSlotTicker').value=index==null?'':marketSlots[index];
  $('#marketTickerSuggestions').innerHTML=(state?.actions || []).map(item=>`<option value="${escapeHtml(item.ticker)}">${escapeHtml(item.name || '')}</option>`).join('');
  $('#marketSlotFeedback').textContent='';
  $('#marketSlotDialog').showModal();
  $('#marketSlotTicker').focus();
}
async function removeTracked(button) {
  button.disabled=true;
  const result=await call('remove_tracking',button.dataset.removeTracking);
  toast(result?.message || '已处理');
  await poll();
  button.disabled=false;
}
async function poll() {
  if (!window.pywebview?.api) return;
  try {
    const next = await window.pywebview.api.get_state();
    if(next.revision!==lastRevision){if(state?.reference_key!==next.reference_key)eventContexts.clear();state=next;lastRevision=next.revision;render();}
    void refreshMarketRsi();
  } catch (error) {toast('本地数据服务暂不可用');}
}
function bind() {
  $('#addMarketTracking').addEventListener('click',()=>openMarketSlotDialog());
  $('#marketSlotForm').addEventListener('submit',async event=>{
    event.preventDefault();
    const ticker=$('#marketSlotTicker').value.trim().toUpperCase();
    const index=$('#marketSlotIndex').value;
    const feedback=$('#marketSlotFeedback');
    if (!/^[A-Z0-9.^-]{1,15}$/.test(ticker)) {feedback.textContent='请输入有效的证券代码';return;}
    if (marketSlots.includes(ticker) && marketSlots.indexOf(ticker)!==Number(index)) {feedback.textContent='该标的已在市场研判中';return;}
    const button=$('#saveMarketSlot');button.disabled=true;
    try {
      if (!state.market.model?.targets?.[ticker] && !state.actions.some(item=>item.ticker===ticker)) {
        feedback.textContent='正在识别并同步标的';
        const added=await call('add_tracking',ticker);
        if (!added?.ok) {feedback.textContent=added?.message || '标的同步失败';return;}
        await poll();
      }
      const next=[...marketSlots];
      if (index==='new') next.push(ticker); else next[Number(index)]=ticker;
      if (await saveMarketSlots(next)) {$('#marketSlotDialog').close();toast(`${ticker} 已加入市场研判`);}
    } finally {button.disabled=false;}
  });
  $('#pulseGrid').addEventListener('click',async event=>{
    const replace=event.target.closest('[data-replace-market-slot]');if(replace){openMarketSlotDialog(Number(replace.dataset.replaceMarketSlot));return;}
    const remove=event.target.closest('[data-remove-market-slot]');
    if(remove){const index=Number(remove.dataset.removeMarketSlot);await saveMarketSlots(marketSlots.filter((_,slot)=>slot!==index));return;}
    const button=event.target.closest('[data-risk-url]');if(button){const article=state.news.find(n=>n.url===button.dataset.riskUrl);if(article){selectedEvent=article.id;renderEventDetail();$('#eventDetail').scrollIntoView({block:'center',behavior:'smooth'});}}
  });
  $('#savePublicPosts').addEventListener('click',async()=>{const r=await call('save_public_posts',$('#publicPostInput').value);toast(r.message);await poll();});
  $('#rotationPeriod').addEventListener('click',event=>{const button=event.target.closest('[data-period]');if(button){rotationPeriod=Number(button.dataset.period);renderMarket();icons();}});
  document.querySelectorAll('.section-nav a').forEach(link=>link.addEventListener('click',()=>{document.querySelectorAll('.section-nav a').forEach(a=>a.classList.remove('active'));link.classList.add('active');}));
  let tabScrollScheduled=false;
  window.addEventListener('scroll',()=>{
    if(tabScrollScheduled)return;
    tabScrollScheduled=true;
    requestAnimationFrame(()=>{syncActiveTab();tabScrollScheduled=false;});
  },{passive:true});
  $('#refreshButton').addEventListener('click', async () => { const result = await call('refresh');if (result?.message) toast(result.message);await poll(); });
  for (const selector of ['#eventSearch','#dateFilter','#topicFilter','#gradeFilter','#directionFilter']) $(selector).addEventListener(selector === '#eventSearch' ? 'input' : 'change', () => {visibleEvents=12;renderEvents();});
  $('#leadEvent').addEventListener('click', () => {if (focusEventId != null) {selectedEvent=focusEventId;renderEventDetail();$('#eventDetail').scrollIntoView({behavior:'smooth',block:'center'});}});
  $('#globalSearch').addEventListener('click', async () => {const result=await call('search_global_news',$('#eventSearch').value);toast(result?.message || '检索未完成');await poll();});
  $('#eventSearch').addEventListener('keydown',(event) => {if (event.key==='Enter') {event.preventDefault();$('#globalSearch').click();}});
  $('#showMoreEvents').addEventListener('click', () => {visibleEvents += 8;renderEvents();icons();});
  $('#eventList').addEventListener('click', (event) => {const row=event.target.closest('[data-event]');if (row) {selectedEvent=Number(row.dataset.event);renderEventDetail();}});
  $('#eventDetail').addEventListener('click', async (event) => {const button=event.target.closest('[data-open-url]');if (button) {const article=state.news.find((item) => item.id === Number(button.dataset.openUrl));if (article) await call('open_url',article.url);}});
  $('#eventDetail').addEventListener('click', async (event) => {
    const button=event.target.closest('[data-ai-event]');
    if (!button) return;
    button.disabled=true;button.textContent='正在分析…';
    const id=Number(button.dataset.aiEvent);
    const article=state.news.find((item) => item.id === id);
    const result=await call('analyze_event',article?.url);
    if (result?.ok && article) {aiResults.set(article.url,result.analysis);renderEventDetail();}
    else {toast(result?.message || '本地分析未完成');renderEventDetail();}
  });
  $('#decisionGrid').addEventListener('click',async event=>{
    const remove=event.target.closest('[data-remove-tracking]');
    if(remove){await removeTracked(remove);return;}
    const card=event.target.closest('[data-action]');if(card){selectedAction=card.dataset.action;renderDecisionDetail();}
  });
  $('#addTracking').addEventListener('click',()=>{$('#trackingForm').reset();$('#trackingFeedback').textContent='';$('#trackingDialog').showModal();$('#trackingTicker').focus();});
  $('#trackingForm').addEventListener('submit',async event=>{
    event.preventDefault();const button=$('#saveTracking');button.disabled=true;button.textContent='正在识别标的…';$('#trackingFeedback').textContent='正在核对证券代码及交易市场';
    try{const result=await call('add_tracking',$('#trackingTicker').value);if(result.ok){$('#trackingDialog').close();toast(result.message);await poll();}else{$('#trackingFeedback').textContent=result.message || '暂时无法添加，请重试';}}
    finally{button.disabled=false;button.textContent='添加并同步';}
  });
  $('#watchTable').addEventListener('click', (event) => {const row=event.target.closest('[data-watch]');if (row) {selectedWatch=row.dataset.watch;renderValuationDetail();}});
  $('#fundTable').addEventListener('click', (event) => {const row=event.target.closest('[data-watch]');if (row) {selectedWatch=row.dataset.watch;renderValuationDetail();}});
  $('#valuationDetail').addEventListener('submit', async (event) => {if (event.target.id !== 'neutralForm') return;event.preventDefault();const result=await call('save_neutral_pe',selectedWatch,$('#neutralPe').value);toast(result.message || '已处理');await poll();});
  $('#valuationDetail').addEventListener('click', async (event) => {if (event.target.id !== 'toggleHolding') return;const item=state.watch.find((row) => row.ticker === selectedWatch);if (!item) return;const result=await call('set_holding_status',selectedWatch,!item.is_held);toast(result.message || '已处理');await poll();});
  $('#valuationDetail').addEventListener('click', (event) => {if (!event.target.closest('#addGuidance')) return;$('#guidanceTicker').value=selectedWatch;$('#guidanceForm').reset();$('#guidanceTicker').value=selectedWatch;$('#guidanceDialog').showModal();});
  $('#valuationDetail').addEventListener('click', async (event) => {const button=event.target.closest('[data-open-management]');if(button)await call('open_url',button.dataset.openManagement);});
  $('#guidanceForm').addEventListener('submit', async (event) => {event.preventDefault();const result=await call('save_guidance',$('#guidanceTicker').value,$('#guidanceEps').value,$('#guidanceUrl').value,$('#guidanceBasis').value);toast(result.message || '已处理');if(result.ok)$('#guidanceDialog').close();await poll();});
  $('#editWatchlist').addEventListener('click', () => {$('#watchInput').value=state.settings.watchlist.join(', ');$('#watchDialog').showModal();});
  $('#addPosition').addEventListener('click', () => {$('#positionForm').reset();$('#positionDialog').showModal();});
  document.querySelectorAll('[data-close]').forEach((button) => button.addEventListener('click', () => $('#'+button.dataset.close).close()));
  $('#watchForm').addEventListener('submit', async (event) => {event.preventDefault();const result=await call('save_watchlist',$('#watchInput').value);toast(result.message || '已处理');if (result.ok)$('#watchDialog').close();await poll();});
  $('#positionForm').addEventListener('submit', async (event) => {event.preventDefault();const result=await call('save_position',$('#positionTicker').value,$('#positionQuantity').value,$('#positionCost').value);toast(result.message || '已处理');if (result.ok)$('#positionDialog').close();await poll();});
  $('#positionTable').addEventListener('click', async (event) => {const button=event.target.closest('[data-delete]');if (button && confirm(`删除 ${button.dataset.delete} 的本地持仓记录？`)) {const result=await call('delete_position',button.dataset.delete);toast(result.message || '已处理');await poll();}});
  $('#saveNetwork').addEventListener('click', async () => {const result=await call('save_network',$('#proxyInput').value,$('#autoProxy').checked);toast(result.message || '已处理');await poll();});
  $('#saveModel').addEventListener('click', async () => {const result=await call('set_local_model',$('#modelInput').value);toast(result.message || '已处理');await poll();});
  $('#settingsButton').addEventListener('click',() => $('#settingsDialog').showModal());
}
let booted=false;
async function boot() {
  if (booted || !window.pywebview?.api) return;
  booted=true;
  window.scrollTo({top:0,left:0,behavior:'instant'});
  bind();icons();await loadMarketSlots();await poll();setInterval(poll,2200);
}
document.addEventListener('pywebviewready',boot);
if (window.pywebview?.api) boot();
const bridgeReadyTimer = setInterval(() => {
  if (booted) clearInterval(bridgeReadyTimer);
  else if (window.pywebview?.api) boot();
}, 250);
