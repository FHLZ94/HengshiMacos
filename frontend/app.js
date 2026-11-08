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
function renderPulse(){
  const model=state.market.model,risks=state.market.event_risk || {},environment=state.market.environment || {};
  if(!model?.available || !model.targets){
    $('#pulseHeadline').textContent='正在计算短线交易环境';$('#pulseDate').textContent=model?.reason || '优先读取本地历史';
    $('#pulseGrid').innerHTML=metric('QQQ / SMH','计算中','分别训练、校准与检验');$('#pulseFoot').textContent='正在计算概率、超卖位置与事件风险。';$('#modelMethod').textContent='等待有效历史数据';return;
  }
  const codes=['QQQ','SMH'],assessment=state.market.assessment || {},cnn=assessment.cnn;
  const worst=codes.some(t=>risks[t]?.critical_negative),minute=state.market.intraday || {};
  const hot=codes.some(t=>model.targets[t].setup.overbought),cold=codes.some(t=>model.targets[t].setup.oversold);
  $('#pulseHeadline').textContent=worst?'重大事件风险上升，优先核对敞口':hot && cold?'科技与半导体位置分化，分别核对过热与超卖':hot?'部分指数高位偏热，核对拥挤与追价风险':codes.every(t=>model.targets[t].setup.oversold)?'科技与半导体进入明显超卖区，承接决定能否出手':assessment.headline || '短线情绪与交易环境';
  $('#pulseDate').textContent=`日线截至 ${model.date} · ${state.market.model_busy?'正在重算':'计算 '+new Date(model.computed_at).toLocaleTimeString('zh-CN',{hour12:false})}`;
  const stageCard=pairMetric('市场阶段',codes.map(t=>({code:t,value:environment[t]?.stage || model.targets[t].setup.label})),'','stage-pulse');
  $('#pulseGrid').innerHTML=[
    pairMetric('未来1~3日波段研判',codes.map(t=>({code:t,value:environment[t]?.label || '等待条件'})),'','action-pulse'),
    pairMetric('未来5日上涨概率',codes.map(t=>({code:t,value:number(model.targets[t].up5_pct,1)+'%'})),'','probability-pulse'),
    pairMetric('10日低点企稳概率',codes.map(t=>({code:t,value:number(model.targets[t].bottom10_pct,1)+'%'})),'','probability-pulse'),
    pairMetric('超买超卖与历史位置',codes.map(t=>{const p=model.targets[t].setup;return {code:t,value:p.label,note:`${p.overbought || p.lower_tail_pct>=85?'上':'下'}侧 ${number(p.overbought || p.lower_tail_pct>=85?p.upper_tail_pct:p.lower_tail_pct,1)}% · RSI ${number(p.rsi14,1)}`};}),'','position-pulse'),
    stageCard,
    pairMetric('情绪与承接',codes.map(t=>{const m=minute[t];if(!m?.available)return {code:t,value:'等待RSI数据'};return {code:t,value:m.rsi_signal || 'RSI常态区间',note:`RSI 5/15/30：${number(m.rsi_5,1)} / ${number(m.rsi_15,1)} / ${number(m.rsi_30,1)}`};}),'','absorption-pulse')
  ].join('');
  $('#pulseFoot').textContent=codes.map(t=>`${t}：${environment[t]?.reason || ''}`).join('。')+'。新闻改变风险评级与动作条件；未通过历史检验的消息分数不直接加减概率。';
  const report=(ticker,name,item)=>`<div class="model-report"><strong>${ticker} · ${name}</strong><p>${escapeHtml(item.method)} · 不重叠基准样本 ${item.training_samples} 组 · 按时间检验 ${item.validation_count} 次 · 概率误差 ${number(item.brier,4)} / 基线 ${number(item.baseline_brier,4)}（越小越好）</p><p>${escapeHtml(item.interval_scope)}：${item.interval?.join('–') || '样本不足'}%（历史发生率95%区间，不是未来真实概率保证）。</p></div>`;
  $('#modelMethod').innerHTML=codes.map(t=>report(t,'未来3日上涨',model.targets[t].up3)+report(t,'未来5日上涨',model.targets[t].up5)+report(t,'10日低点守稳',model.targets[t].bottom10)+`<details class="coefficient-report"><summary>${t} 五日模型的指标与权重</summary><p>${model.targets[t].up5.weights_active?'当前输出采用65%校准模型与35%历史基准。':'候选模型暂未提供稳定额外优势，当前输出采用100%历史基准；下列候选系数暂不用于最终概率。'}</p><table><thead><tr><th>指标</th><th>标准化系数</th><th>绝对系数占比</th></tr></thead><tbody>${model.targets[t].up5.feature_weights.map(w=>`<tr><td>${escapeHtml(w.name)}</td><td>${number(w.coefficient,4)}</td><td>${number(w.share_pct,1)}%</td></tr>`).join('')}</tbody></table><p>系数由过去训练数据拟合；占比帮助理解模型，不是因果权重，也不是概率增加的百分点。</p></details>`).join('')+`<p>${escapeHtml(model.up5_definition)}。${escapeHtml(model.bottom10_definition)}。</p><p>历史 ${model.history_start}—${model.date}，${model.history_days} 个共同交易日。${escapeHtml(model.limitations)}</p><p>${escapeHtml(risks.definition || '')}。${escapeHtml(risks.news_model_status || '')}。公开言论、议员提案与已生效政策分别处理。</p>`;
  $('#modelMethod').innerHTML+=`<details class="coefficient-report"><summary>查看RSI 5 / 15 / 30分钟依据</summary><table><thead><tr><th>标的/周期</th><th>RSI14</th><th>状态</th><th>截至（美东）</th></tr></thead><tbody>${codes.flatMap(t=>['5','15','30'].map(k=>{const f=minute[t]?.frames?.[k];if(!f?.available)return `<tr><td>${t} ${k}分</td><td colspan="3">等待分钟行情</td></tr>`;return `<tr><td>${t} ${k}分${k==='15'?'（重点）':''}</td><td>${number(f.rsi14,1)}</td><td>${escapeHtml(f.rsi14<=30?'超卖':f.rsi14>=70?'超买':'常态')}</td><td>${new Date(f.asof).toLocaleString('zh-CN',{timeZone:'America/New_York',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false})}</td></tr>`;})).join('')}</tbody></table></details>`;

}

function renderEvents() {
  const cutoff = Date.now() - 72 * 3600 * 1000;
  const recent = state.news.filter((item) => {
    const timestamp = Date.parse(item.published_raw);
    return Number.isFinite(timestamp) && timestamp >= cutoff && timestamp <= Date.now();
  });
  const high = recent.filter((item) => item.grade === 'S1' || item.grade === 'S2');
  const held = new Set(state.watch.filter((item) => item.is_held).map((item) => item.ticker));
  const rank = {'S1':4,'S2':3,'S3':2,'S4':1};
  const focusPool = recent;
  const stance=state.market.event_risk?.stance || {};
  const stanceCard=(name,icon)=>{const item=stance[name];if(!item)return `<div class="stance-card"><span class="stance-title">${icon} ${escapeHtml(name)}</span><strong>等待相关情报</strong><small>最近24小时暂无足够的产业链事件</small></div>`;const tone=item.net_score>15?'positive':item.net_score<-15?'negative':'neutral';const top=item.top_event;return `<div class="stance-card ${tone}"><span class="stance-title">${icon} ${escapeHtml(name)}</span><strong>${escapeHtml(item.label)}</strong><span class="stance-score">影响分 ${item.net_score>0?'+':''}${number(item.net_score,1)} / 100</span><small>${item.event_count} 条相关事件 · ${item.verified_count} 条有核验证据${top?` · 最高影响：${escapeHtml(top.stage)}`:''}</small></div>`;};
  $('#eventStanceDashboard').innerHTML=`<div class="stance-heading"><strong>过去24小时产业链信息影响</strong><span>宏观政策/地缘传导权重1.25 · 半导体与AI产业权重1.15 · 普通公司信息1.0 · 单条公开表态0.6</span></div><div class="stance-grid">${stanceCard('半导体产业链','◈')}${stanceCard('大科技与AI','◌')}</div><p class="stance-method">影响分用于信息情绪排序：事件强度 × 来源可靠性 × 证据充分度 × 行业相关度 × 时效衰减，并按上述类别加权；不是市场涨跌概率。泛治安、恐怖主义和无产业传导的国家新闻不会进入该仪表盘。</p>`;
  const lead = [...focusPool].sort((a,b) =>
    ((b.analysis?.score ?? rank[b.grade]*12)-(a.analysis?.score ?? rank[a.grade]*12)) ||
    (Number(b.tickers.some((ticker) => held.has(ticker))) - Number(a.tickers.some((ticker) => held.has(ticker)))) ||
    (Date.parse(b.published_raw) - Date.parse(a.published_raw)))[0];
  focusEventId = lead?.id ?? null;
  const leadGrade=lead?.analysis?.grade || lead?.grade;
  const leadDirection=lead?.analysis?.direction || lead?.direction;
  $('#leadEvent').innerHTML = lead ? `<span class="focus-kicker"><span class="focus-caption">重点事件</span><span class="tag ${gradeTone(leadGrade)}">${escapeHtml(leadGrade)}</span>
    <span class="direction ${leadDirection === '偏正面' ? 'positive' : leadDirection === '偏负面' ? 'negative' : 'neutral'}">${escapeHtml(leadDirection)}</span>
    <span>来源 RSS 发布：${escapeHtml(lead.published_full)}（北京时）</span><span>${escapeHtml(lead.tickers.join(' / ') || '宏观')}</span></span>
    <strong>${escapeHtml(lead.title)}</strong><span class="focus-source">${escapeHtml(lead.publisher || lead.source)} · ${escapeHtml(lead.analysis?.conclusion || '正文核验中')}</span>` :
    '<span class="focus-empty">最近 72 小时暂无来源明确发布时间的事件</span>';
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
    return withinDate && (grade === 'all' || grade === (item.analysis?.grade || item.grade)) &&
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
  $('#rotationInsight').innerHTML=`<div class="insight-kicker"><i data-lucide="scan-line"></i> 轮动洞察</div><h3>${escapeHtml(rotation.headline)}</h3><ul>${rotation.evidence.map(line=>`<li>${escapeHtml(line)}</li>`).join('')}</ul><div class="rotation-action"><strong>交易观察</strong><p>${escapeHtml(rotation.action)}</p></div><p class="method-note">得分与相对强弱同时改善才视为较强证据。点击另一时间窗口，核对轮动是否持续。</p>`;
  if (!window.Chart)return;
  if (chart)chart.destroy();
  const rows=rotation.rows;
  chart=new Chart($('#rotationChart'),{type:'bar',data:{labels:rows.map(r=>r.name),datasets:[{label:'承接 / 卖压得分',data:rows.map(r=>r.pressure),backgroundColor:rows.map(r=>r.pressure>=0?'#18a890':'#df737d'),borderRadius:4,maxBarThickness:27}]},options:{responsive:true,maintainAspectRatio:false,animation:false,indexAxis:'y',plugins:{legend:{display:false},tooltip:{callbacks:{afterLabel:ctx=>{const r=rows[ctx.dataIndex];return [`区间涨跌 ${signed(r.return_pct)}`,`相对标普 ${r.relative_pct>0?'+':''}${number(r.relative_pct)} 个百分点`,`平均成交量 / 前20日 ${number(r.volume_ratio)} 倍`];}}}},scales:{x:{min:-100,max:100,grid:{color:'#e8eef1'},ticks:{color:'#788b99'},title:{display:true,text:'卖压 ← 量价资金偏好代理 → 承接',color:'#788b99'}},y:{grid:{display:false},ticks:{color:'#38576a',font:{size:12}}}}}});
}

function annualCaption(item){
  if(item.is_fund){const fv=item.fund_valuation;return `当前PE ${fv?.pe ? number(fv.pe,1)+'倍' : '待数据'} · 历史估值分位 ${fv?.percentile!=null ? number(fv.percentile,1)+' / 100' : (fv?.history_status || '待历史数据')}`;}
  const annual=item.annual;return annual?.reference_price ? `未来12个月合理价值：$${number(annual.reference_price)} · ${signed(annual.upside_pct)}` : '未来12个月合理价值待有效数据';
}
function renderDecisions() {
  const known=state.actions.filter(item=>item.metric).length;
  $('#decisionStatus').textContent=`${known}个标的可评估 · 个股共用未来12个月合理价值与空间；基金仅显示当前PE和历史估值分位。`;
  $('#decisionGrid').innerHTML=state.actions.map(item=>`<article class="decision-card ${selectedAction===item.ticker?'selected':''}">
    <button type="button" class="decision-select" data-action="${escapeHtml(item.ticker)}" aria-label="查看${escapeHtml(item.ticker)}交易参考">
      <span class="decision-card-top"><strong>${escapeHtml(item.ticker)} <span class="decision-current">${item.current_price==null?'—':'$'+number(item.current_price)}</span></strong>${item.held?'<em class="held-tag">已持有</em>':''}</span>
      <span class="decision-security-name">${escapeHtml(item.name || '')}</span>
      <span class="decision-quote-time">${escapeHtml(item.price_label)} · ${escapeHtml(item.quote_asof || '等待行情')}${item.sync_status==='正在更新'?' · 数据更新中':''}</span>
      <span class="action-label ${item.advice.action.includes('风险')?'risk':''}">${escapeHtml(item.advice.action)}</span>
      <span class="decision-prices">${item.advice.in_watch_zone?'已进入关注区':'关注区间'} ${item.advice.watch_zone ? '$'+number(item.advice.watch_zone[0])+'–'+number(item.advice.watch_zone[1]) : '正在获取日线并计算'}</span>
      <span class="annual-caption">${escapeHtml(annualCaption(item))}</span>
      <span class="basis">${escapeHtml(item.advice.basis)}</span>
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
    <div class="decision-detail-grid"><div><span>参考价依据</span><p>${item.is_fund ? escapeHtml(item.fund_valuation ? item.fund_valuation.basis+' · '+item.fund_valuation.source+' · '+item.fund_valuation.asof : '正在获取基金组合PE及同口径历史；历史不足不生成分位') : escapeHtml(v.reference_label || '')+'。'+escapeHtml(v.reason || '')}</p></div><div><span>短线确认条件</span><p>${escapeHtml(a.confirm)}</p></div><div><span>失效与风险</span><p>${escapeHtml(a.invalidate)}</p></div></div><p class="method-note">${item.is_fund?'基金按当前PE与历史估值分位评估相对贵贱；分位越低，历史相对估值越低。':'参考空间＝未来12个月合理价值÷当前价－1，与下方估值表一致。'}关注区间属于短线价格条件。</p>`;

}

function renderPortfolio() {
  const priced = state.portfolio.filter((item) => item.value != null);
  const value = priced.reduce((sum, item) => sum + item.value, 0);
  const profit = priced.reduce((sum, item) => sum + item.profit, 0);
  $('#portfolioSummary').innerHTML = `<div class="portfolio-stat"><label>跟踪标的</label><strong>${state.actions.length}</strong></div>
    <div class="portfolio-stat"><label>已录入持仓</label><strong>${state.portfolio.length}</strong></div>
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
async function poll() {
  if (!window.pywebview?.api) return;
  try {
    const next = await window.pywebview.api.get_state();
    if(next.revision!==lastRevision){if(state?.reference_key!==next.reference_key)eventContexts.clear();state=next;lastRevision=next.revision;render();}
  } catch (error) {toast('本地数据服务暂不可用');}
}
function bind() {
  $('#pulseGrid').addEventListener('click',event=>{const button=event.target.closest('[data-risk-url]');if(button){const article=state.news.find(n=>n.url===button.dataset.riskUrl);if(article){selectedEvent=article.id;renderEventDetail();$('#eventDetail').scrollIntoView({block:'center',behavior:'smooth'});}}});
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
    if(remove){remove.disabled=true;const result=await call('remove_tracking',remove.dataset.removeTracking);toast(result.message || '已处理');await poll();return;}
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
  bind();icons();await poll();setInterval(poll,2200);
}
document.addEventListener('pywebviewready',boot);
if (window.pywebview?.api) boot();
const bridgeReadyTimer = setInterval(() => {
  if (booted) clearInterval(bridgeReadyTimer);
  else if (window.pywebview?.api) boot();
}, 250);
