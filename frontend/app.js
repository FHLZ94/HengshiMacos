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
function renderPulse() {
  const model = state.market.model;
  if (!model?.available) {
    $('#pulseHeadline').textContent = '正在准备市场研判';
    $('#pulseDate').textContent = model?.reason || '正在读取本地历史并计算';
    $('#pulseGrid').innerHTML = metric('概率参考','计算中','优先使用本机已有行情');
    $('#pulseFoot').textContent = '首次使用需要取得有效历史行情，之后可离线计算。';
    $('#modelMethod').textContent = model?.reason || '等待历史数据';
    return;
  }
  const assessment=state.market.assessment || {};
  const cnn=assessment.cnn,breadth=assessment.breadth;
  const up=model.up5 || {},bottom=model.bottom10 || {};
  const computed=model.computed_at ? new Date(model.computed_at).toLocaleTimeString('zh-CN',{hour12:false}) : '';
  $('#pulseHeadline').textContent = assessment.headline || `市场情绪：${model.regime}`;
  $('#pulseDate').textContent = `日线截至 ${model.date} · ${state.market.model_busy ? '正在重算' : `计算 ${computed}`}`;
  $('#pulseGrid').innerHTML = [
    metric('CNN 恐慌贪婪',cnn ? number(cnn.score,1) : '—',cnn ? `CNN · ${cnn.asof.slice(0,10)}` : '等待可用来源'),
    metric('标普500 20日广度',breadth ? `${number(breadth.ratio_pct,1)}%` : '—',breadth ? `${breadth.above_20d}/${breadth.valid} 站上均线` : '成分行情不足'),
    metric('承接力度',model.absorption,`量价综合观察 · ${model.date}`),
    metric('未来5日上涨参考',`${number(model.up5_pct,1)}%`,`QQQ · ${up.method || '历史估计'}`),
    metric('短期低点守稳参考',`${number(model.bottom10_pct,1)}%`,`未来10日 · ${bottom.method || '历史估计'}`)
  ].join('');
  $('#pulseFoot').textContent = `${assessment.decision || ''}。${assessment.risk || ''}。`;
  $('#pulseFoot').classList.remove('weak-validation');
  const report=(name,item,definition) => `<div class="model-report"><strong>${escapeHtml(name)}</strong><p>${escapeHtml(definition)}</p><p>${escapeHtml(item.method || '')} · 不重叠训练样本 ${item.training_samples || 0} 组 · 时间顺序检验 ${item.validation_count || 0} 次 · Brier误差 ${number(item.brier,4)} / 历史基线 ${number(item.baseline_brier,4)}（越小越好）</p><p>${escapeHtml(item.interval_scope || '历史发生率区间')}：${item.interval ? item.interval.join('–')+'%（95%）' : '样本不足'}；该区间不等于今天真实概率的保证。</p></div>`;
  $('#modelMethod').innerHTML = report('五日上涨',up,model.up5_definition)+report('十日低点守稳',bottom,model.bottom10_definition)+`<p>历史范围 ${escapeHtml(model.history_start)} — ${escapeHtml(model.date)}，${model.history_days} 个共同交易日。输入：${escapeHtml((model.feature_names || []).join('、'))}。使用过去训练、未来验证；未优于历史基线时收缩到基线，不人为提高概率。</p><p>${escapeHtml(model.limitations)}</p>`;
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
    <div>${row.ntm_pe == null ? '前瞻市盈率暂无' : `未来12月市盈率 ${number(row.ntm_pe,1)} 倍`}</div>
    <div>${row.target == null ? '一年目标价暂无' : `一年目标价 $${number(row.target)}`}</div>
    <small>${escapeHtml(row.price_confirmation)}</small></div>`).join('');
}
async function loadEventContext(url) {
  eventContextsLoading.add(url);
  const result=await call('event_market_context',url);
  eventContextsLoading.delete(url);
  eventContexts.set(url,result);
  const selected=state.news.find((item) => item.id === selectedEvent);
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

function annualCaption(annual) {
  if (annual?.valuation_range) return `一年${annual.scenario_basis || "估值"}空间 ${signed(annual.valuation_range[0])}～${signed(annual.valuation_range[1])}`;
  if (annual?.available) return `同类历史一年中位回报 ${signed(annual.median_return)}`;
  return '一年参考待补充';
}
function renderDecisions() {
  const known=state.actions.filter(item=>item.metric).length;
  $('#decisionStatus').textContent=`${known}个标的可评估 · 名称后为最近报价；关注区间为条件式买入研究区域，一年空间按区间买入价计算。`;
  $('#decisionGrid').innerHTML=state.actions.map(item=>`<button type="button" class="decision-card ${selectedAction===item.ticker?'selected':''}" data-action="${escapeHtml(item.ticker)}">
    <span class="decision-card-top"><strong>${escapeHtml(item.ticker)} <span class="decision-current">${item.current_price==null?'—':'$'+number(item.current_price)}</span></strong>${item.held?'<em class="held-tag">已持有</em>':''}</span>
    <span class="decision-quote-time">${escapeHtml(item.price_label)} · ${escapeHtml(item.quote_asof || '等待行情')}</span>
    <span class="action-label ${item.advice.action.includes('风险')?'risk':''}">${escapeHtml(item.advice.action)}</span>
    <span class="decision-prices">${item.advice.in_watch_zone?'已进入关注区':'关注区间'} ${item.advice.watch_zone ? '$'+number(item.advice.watch_zone[0])+'–'+number(item.advice.watch_zone[1]) : '待计算'}</span>
    <span class="annual-caption">${escapeHtml(annualCaption(item.annual))}</span>
    <span class="basis">${escapeHtml(item.advice.basis)}</span></button>`).join('');
  if (selectedAction==null && state.actions.length)selectedAction=state.actions[0].ticker;
  renderDecisionDetail();
}
function renderDecisionDetail() {
  const item=state.actions.find(action=>action.ticker===selectedAction);
  $('#decisionGrid').querySelectorAll('.decision-card').forEach(card=>card.classList.toggle('selected',card.dataset.action===selectedAction));
  if (!item){$('#decisionDetail').innerHTML='<div class="empty-detail">选择标的查看依据</div>';return;}
  const a=item.advice,annual=item.annual;
  const history=annual?.available ? `<p>相似月度起点的一年正收益占比 ${number(annual.historical_positive_pct,1)}%，中位回报 ${signed(annual.median_return)}，历史10%–90%分布 ${signed(annual.return_range[0])}～${signed(annual.return_range[1])}。${annual.samples}个月度起点，仅${annual.independent_periods}个不重叠年度区间，不能作为已校准的一年盈利概率。</p><p>${escapeHtml(annual.definition)}</p>` : `<p>${escapeHtml(annual?.reason || '历史不足')}</p>`;
  $('#decisionDetail').innerHTML=`<h3>${escapeHtml(item.ticker)} <span class="decision-current">${item.current_price==null?'—':'$'+number(item.current_price)}</span> · ${escapeHtml(a.action)}</h3>
    <p class="decision-quote-time">${escapeHtml(item.price_label)} · ${escapeHtml(item.quote_asof)}${item.regular_close ? ' · 最近收盘 $'+number(item.regular_close):''}${item.session_change_pct!=null ? ' · 较收盘 '+signed(item.session_change_pct):''}</p>
    <div class="decision-price-row"><div><span>关注价格区间</span><strong>${a.watch_zone?'$'+number(a.watch_zone[0])+'–$'+number(a.watch_zone[1]):'待计算'}</strong></div><div><span>一年${escapeHtml(annual?.scenario_basis || "估值")}情景空间</span><strong>${annual?.valuation_range ? signed(annual.valuation_range[0])+'～'+signed(annual.valuation_range[1]):'估值数据不足'}</strong></div><div><span>风险失效价</span><strong>${a.risk_price?'$'+number(a.risk_price):'—'}</strong></div></div>
    <div class="decision-detail-grid"><div><span>估值与盈利预期</span><p>${escapeHtml(a.valuation)}</p></div><div><span>触发条件（不是当前报价）</span><p>${escapeHtml(a.confirm)}</p></div><div><span>失效与风险</span><p>${escapeHtml(a.invalidate)}</p></div></div><details class="model-method"><summary>一年回报的历史证据与口径</summary><div>${history}<p>估值空间假设未来盈利兑现及估值倍数不变，未计费用、分红和买入区间能否到达；管理层指引影响估值情景，不直接换算胜率。</p></div></details>`;
}

function renderPortfolio() {
  const priced = state.portfolio.filter((item) => item.value != null);
  const value = priced.reduce((sum, item) => sum + item.value, 0);
  const profit = priced.reduce((sum, item) => sum + item.profit, 0);
  $('#portfolioSummary').innerHTML = `<div class="portfolio-stat"><label>观察标的</label><strong>${state.watch.length}</strong></div>
    <div class="portfolio-stat"><label>已录入持仓</label><strong>${state.portfolio.length}</strong></div>
    <div class="portfolio-stat"><label>可计价市值</label><strong>$${number(value)}</strong></div>
    <div class="portfolio-stat"><label>未实现盈亏</label><strong class="${tone(profit)}">${profit > 0 ? '+' : ''}$${number(profit)}</strong></div>`;
  const funds=state.watch.filter((item) => ['QQQ','SPY','QQQM','SMH'].includes(item.ticker));
  const stocks=state.watch.filter((item) => !['QQQ','SPY','QQQM','SMH','^VIX'].includes(item.ticker))
    .sort((a,b) => (b.upside_pct ?? -Infinity)-(a.upside_pct ?? -Infinity));
  $('#fundTable tbody').innerHTML = funds.map((item) => `<tr data-watch="${escapeHtml(item.ticker)}" class="${selectedWatch === item.ticker ? 'selected' : ''}">
    <td>${escapeHtml(item.ticker)} ${item.is_held ? '<em class="held-tag">已持有</em>' : ''} <span class="muted">${escapeHtml(item.name)}</span></td>
    <td>${item.price == null ? '无报价' : '$' + number(item.price)}<small class="price-label">${escapeHtml(item.price_label)}${item.session_change_pct!=null?' · '+signed(item.session_change_pct):''}</small></td><td class="${tone(item.change)}">${signed(item.change)}</td>
    <td class="${tone(item.metric?.return5)}">${signed(item.metric?.return5)}</td><td>${escapeHtml(item.metric?.trend || '数据不足')}</td>
    <td title="${escapeHtml(item.fund_valuation?.basis)} · ${escapeHtml(item.fund_valuation?.source)}">${item.fund_valuation?.pe ? number(item.fund_valuation.pe,2)+' 倍' : '待取得估值'}<small class="price-label">${escapeHtml(item.fund_valuation?.proxy_ticker ? 'QQQ 指数代理' : item.fund_valuation?.asof || '')}</small></td>
    <td>${item.fund_valuation?.percentile!=null ? number(item.fund_valuation.percentile,1)+'%<small class="price-label">近'+number(item.fund_valuation.years,0)+'年 · '+item.fund_valuation.samples+'个月度样本</small>' : '<span class="muted">历史PE不足</span>'}</td><td class="muted">${escapeHtml(item.asof || '来源不可用')}</td></tr>`).join('') || '<tr><td colspan="8" class="muted">观察列表中暂无宽基或行业基金</td></tr>';
  $('#watchTable tbody').innerHTML = stocks.map((item) => `<tr data-watch="${escapeHtml(item.ticker)}" class="${selectedWatch === item.ticker ? 'selected' : ''}">
    <td title="${escapeHtml(item.name)}">${escapeHtml(item.ticker)} ${item.is_held ? '<em class="held-tag">已持有</em>' : ''} <span class="muted">${escapeHtml(item.name)}</span></td>
    <td title="${escapeHtml(item.price_label)} · ${escapeHtml(item.quote_source)}">${item.price == null ? '无报价' : '$' + number(item.price)}<small class="price-label">${escapeHtml(item.price_label)}${item.session_change_pct!=null?' · '+signed(item.session_change_pct):''}</small></td><td class="${tone(item.change)}">${signed(item.change)}</td>
    <td>${number(item.valuation?.eps_used)}</td><td title="${escapeHtml(item.neutral_source)}">${item.neutral_pe == null ? '—' : number(item.neutral_pe,1) + ' 倍'}</td>
    <td>${item.fair_price == null ? '—' : '$' + number(item.fair_price)}</td>
    <td class="${tone(item.upside_pct)}">${signed(item.upside_pct)}</td>
    <td>${item.analyst_target == null ? '—' : '$' + number(item.analyst_target)}</td>
    <td class="muted" title="${escapeHtml(item.price_label)} · ${escapeHtml(item.quote_source)}">${escapeHtml(item.asof || '来源不可用')}</td></tr>`).join('') || '<tr><td colspan="9" class="muted">观察列表中暂无个股</td></tr>';
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
  const isFund=['QQQ','SPY','QQQM','SMH'].includes(item.ticker);
  const fv=item.fund_valuation;
  const basis = isFund ? (fv ? `当前PE ${number(fv.pe,2)} 倍 · ${fv.basis} · ${fv.source} · 估值日期 ${fv.asof}。历史分位 ${number(fv.percentile,1)}%，在 ${fv.start} 至 ${fv.end} 的 ${fv.samples} 个月度PE样本中比较；分位越高，历史相对估值越贵。该口径不能和其他来源的前瞻PE直接混用。` : '尚未取得可复核的基金PE历史，取得后显示估值分位。') :
    item.eps_ntm == null ? '未来四季一致预期不足，暂不计算未来12月市盈率。' : `未来四季每股盈利合计 ${number(item.eps_ntm)} · ${item.eps_period} · ${item.eps_source} · 抓取 ${item.eps_asof}`;
  const analyst = item.analyst_target == null ? '分析师一年目标价：暂无' : `分析师一年目标价 $${number(item.analyst_target)} · ${item.target_source} · 抓取 ${item.target_asof}`;
  const average = item.one_year_pe_average == null ? `一年平均前瞻市盈率：历史快照积累中（${item.one_year_pe_samples} 个日快照）` : `一年平均前瞻市盈率：${number(item.one_year_pe_average,1)} 倍 · 本机逐日历史`;
  const comparison = item.comparison_price == null ? '交叉核对：TradingView 暂无数据' : `TradingView 当前报价 $${number(item.comparison_price)}${item.price_gap_pct == null ? '' : ` · 与常规交易时段价差 ${number(item.price_gap_pct,2)}%`}${item.comparison_next_fy_eps == null ? '' : ` · 下一财年每股盈利预测 ${number(item.comparison_next_fy_eps)}`} · 抓取 ${item.comparison_fetched_at}${item.quote_conflict ? ' · 来源差异过大，暂停动作' : ''}`;
  const valuation=item.valuation || {};
  const fair=item.fair_price == null ? '当前缺少可核对的盈利或市盈率，暂不能计算情景价。' :
    `${number(valuation.eps_used)} × ${number(valuation.pe_used,1)} 倍 = $${number(item.fair_price)}，相对最近报价 ${signed(item.upside_pct)}。盈利口径：${valuation.earnings_basis}；倍数口径：${valuation.pe_basis}。`;
  const guidance = valuation.management_source ? `<div>管理层指引来源：<button type="button" class="small-command" data-open-management="${escapeHtml(valuation.management_source)}">查看公司公告</button></div>` : '';
  $('#valuationDetail').innerHTML = `<div class="valuation-layout"><div class="valuation-copy"><strong>${escapeHtml(item.ticker)} · ${escapeHtml(item.name)}</strong>
    <div>${escapeHtml(basis)}</div>${isFund ? '' : `<div class="valuation-result">${escapeHtml(fair)}</div>${guidance}<div>${escapeHtml(average)}</div><div>${escapeHtml(analyst)}</div>`}
    <div>${escapeHtml(comparison)}</div>${news.length ? `<div>${escapeHtml(news.map((article) => article.title).join('；'))}</div>` : ''}</div>
    <div class="valuation-controls"><button type="button" class="quiet-button" id="toggleHolding">${item.is_held ? '取消持有标记' : '标记为已持有'}</button>
    ${isFund ? '' : `<button type="button" class="quiet-button" id="addGuidance"><i data-lucide="file-chart-column-increasing"></i> 管理层指引</button><form class="neutral-form" id="neutralForm"><label for="neutralPe">估值倍数</label><input id="neutralPe" type="number" min="0.1" max="500" step="0.1" value="${item.neutral_pe ?? ''}" placeholder="倍数" required><button type="submit" class="quiet-button">保存倍数</button></form>`}</div></div>`;
  icons();
}

function renderSettings() {
  const proxy = $('#proxyInput');
  if (document.activeElement !== proxy) proxy.value = state.settings.https_proxy || '';
  $('#autoProxy').checked = !!state.settings.auto_local_proxy;
  if (document.activeElement !== $('#modelInput')) $('#modelInput').value=state.settings.openai_model || '';
}
function syncActiveTab(){
  const anchor=document.querySelector('.topbar').getBoundingClientRect().bottom+32;
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
    if (next.revision !== lastRevision) {state = next;lastRevision = next.revision;render();}
  } catch (error) {toast('本地数据服务暂不可用');}
}
function bind() {
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
  $('#decisionGrid').addEventListener('click', (event) => {const card=event.target.closest('[data-action]');if (card) {selectedAction=card.dataset.action;renderDecisionDetail();}});
  $('#watchTable').addEventListener('click', (event) => {const row=event.target.closest('[data-watch]');if (row) {selectedWatch=row.dataset.watch;renderValuationDetail();}});
  $('#fundTable').addEventListener('click', (event) => {const row=event.target.closest('[data-watch]');if (row) {selectedWatch=row.dataset.watch;renderValuationDetail();}});
  $('#valuationDetail').addEventListener('submit', async (event) => {if (event.target.id !== 'neutralForm') return;event.preventDefault();const result=await call('save_neutral_pe',selectedWatch,$('#neutralPe').value);toast(result.message || '已处理');await poll();});
  $('#valuationDetail').addEventListener('click', async (event) => {if (event.target.id !== 'toggleHolding') return;const item=state.watch.find((row) => row.ticker === selectedWatch);if (!item) return;const result=await call('set_holding_status',selectedWatch,!item.is_held);toast(result.message || '已处理');await poll();});
  $('#valuationDetail').addEventListener('click', (event) => {if (!event.target.closest('#addGuidance')) return;$('#guidanceTicker').value=selectedWatch;$('#guidanceForm').reset();$('#guidanceTicker').value=selectedWatch;$('#guidanceDialog').showModal();});
  $('#valuationDetail').addEventListener('click', async (event) => {const button=event.target.closest('[data-open-management]');if(button)await call('open_url',button.dataset.openManagement);});
  $('#guidanceForm').addEventListener('submit', async (event) => {event.preventDefault();const result=await call('save_guidance',$('#guidanceTicker').value,$('#guidanceEps').value,$('#guidanceUrl').value);toast(result.message || '已处理');if(result.ok)$('#guidanceDialog').close();await poll();});
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
