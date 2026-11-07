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
  $('#refreshButton').disabled = !!state.busy;
  $('#translationStatus').textContent = state.translation_pending ? ` · ${state.translation_pending} 条待翻译` : '';
  $('#searchFeedback').textContent = state.search_status || '';
  $('#globalSearch').disabled=!!state.search_busy;
}
function renderPulse() {
  const model = state.market.model;
  const assessment = state.market.assessment || {};
  if (!model?.available) {
    $('#pulseHeadline').textContent = assessment.headline || '市场状态等待历史数据';
    $('#pulseDate').textContent = model?.reason || '正在获取历史行情';
    $('#pulseGrid').innerHTML = [metric('CNN 恐慌贪婪','—','官方数据待获取'),
      metric('标普500 20日广度','—','成分行情待获取'),metric('承接力度','—','量价数据不足'),
      metric('未来5日方向','—','相似样本不足'),metric('短期底部','—','相似样本不足')].join('');
    $('#pulseFoot').textContent = assessment.decision || '历史模型尚未具备足够共同交易日。';
    return;
  }
  $('#pulseHeadline').textContent = assessment.headline || `市场情绪：${model.regime}`;
  $('#pulseDate').textContent = `行情 ${model.date} · VIX ${model.vix_date}`;
  const cnn=assessment.cnn;
  const breadth=assessment.breadth;
  const upMeta=assessment.validated ? `95%区间 ${model.up5_interval.join('–')}%` : `${model.samples}组历史发生率 ${number(model.up5_pct,1)}% · 未过回测`;
  const bottomMeta=model.bottom10_pct == null ? '当前位置不属于20日低位' : assessment.validated ? `95%区间 ${model.bottom10_interval.join('–')}%` : `${model.samples}组历史发生率 ${number(model.bottom10_pct,1)}% · 未过回测`;
  $('#pulseGrid').innerHTML = [
    metric('CNN 恐慌贪婪',cnn ? number(cnn.score,1) : '—',cnn ? `CNN · ${cnn.asof.slice(0,10)}` : '官方数据不可用'),
    metric('标普500 20日广度',breadth ? `${breadth.above_20d}/${breadth.valid}` : '—',breadth ? `${number(breadth.ratio_pct,1)}% 站上均线 · ${breadth.fetched_at.slice(0,10)}` : '成分行情不足'),
    metric('承接力度',model.absorption,`QQQ 量比 ${number(model.volume_ratio)} 倍`),
    metric('未来5日上涨参考',assessment.validated ? `${number(model.up5_pct,1)}%` : '未校准',upMeta),
    metric('短期底部形成',model.bottom10_pct == null ? '非低位' : assessment.validated ? `${number(model.bottom10_pct,1)}%` : '未校准',bottomMeta)
  ].join('');
  const validation = model.validation_count
    ? `按时间回测 ${model.validation_count} 次 · 误差 ${number(model.brier,3)}，基线 ${number(model.baseline_brier,3)} · ${model.validated_better_than_baseline ? '优于基线' : '尚未优于基线'}`
    : '时间顺序回测样本不足';
  $('#pulseFoot').textContent = `${assessment.decision || ''} 证据：${(assessment.evidence || []).join(' · ')}。${assessment.risk || ''} 相似阶段 ${model.samples} 组，覆盖 ${model.history_days} 个共同交易日；${validation}。`;
  $('#pulseFoot').classList.toggle('weak-validation',!model.validated_better_than_baseline);
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
  const market = state.market;
  const qqq = market.qqq;
  const vix = market.vix;
  $('#marketMetrics').innerHTML = [
    metric('市场风险观察', market.label || '数据不足', '规则观察，尚未回测'),
    metric('波动率指数 VIX', vix ? number(vix.price) : '—', vix ? `数据日 ${vix.asof}` : '来源不可用'),
    metric('观察池涨 / 跌', `${market.up}/${market.down}`, '当前观察列表'),
    metric('QQQ 近 5 日', qqq ? signed(qqq.return5) : '—', qqq ? `截至 ${qqq.date}` : '历史行情不足', tone(qqq?.return5))
  ].join('');
  const flow = [market.qqq, market.smh, market.spy].map((item, index) => ({ticker: ['QQQ','SMH','SPY'][index], metric:item}));
  $('#flowSignals').innerHTML = flow.map(({ticker, metric}) => `<div class="flow-item"><strong>${ticker}</strong><div><div class="flow-text">${escapeHtml(metric ? state.actions.find((action) => action.ticker === ticker)?.flow : '历史行情不足')}</div><div class="flow-date">${escapeHtml(metric?.date || '')}</div></div><span class="flow-ratio">${metric ? `${number(metric.volume_ratio)} 倍` : '—'}</span></div>`).join('');
  $('#trendTable tbody').innerHTML = state.actions.filter((item) => item.metric).map((item) => `<tr><td>${escapeHtml(item.ticker)}</td><td>${escapeHtml(item.metric.trend)}</td>
    <td class="${tone(item.metric.return5)}">${signed(item.metric.return5)}</td><td>${number(item.metric.ma5)}</td><td>${number(item.metric.ma20)}</td>
    <td>${number(item.metric.volume_ratio)} 倍</td><td>${escapeHtml(item.metric.date)}</td></tr>`).join('') || '<tr><td colspan="7" class="muted">连续行情尚未取得</td></tr>';
  renderChart(market.series || {});
}
function renderChart(series) {
  const canvas = $('#trendChart');
  if (!window.Chart) { canvas.outerHTML = '<div class="empty-list">趋势图暂不可用</div>'; return; }
  const order = ['QQQ','SMH','SPY'];
  const colors = {'QQQ':'#087e78','SMH':'#2c63a9','SPY':'#ad7028'};
  const longest = order.map((ticker) => series[ticker] || []).sort((a,b) => b.length - a.length)[0] || [];
  const labels = longest.map((item) => item.date.slice(5));
  const datasets = order.filter((ticker) => (series[ticker] || []).length).map((ticker) => {
    const values = new Map(series[ticker].map((item) => [item.date.slice(5), item.close]));
    const first = series[ticker][0].close;
    return {label:ticker,data:labels.map((label) => values.has(label) ? values.get(label) / first * 100 : null),borderColor:colors[ticker],
      borderWidth:2,pointRadius:0,spanGaps:true,tension:.18};
  });
  if (chart) chart.destroy();
  chart = new Chart(canvas, {type:'line',data:{labels,datasets},options:{responsive:true,maintainAspectRatio:false,animation:false,
    interaction:{mode:'index',intersect:false},plugins:{legend:{display:false},tooltip:{callbacks:{label:(context) => `${context.dataset.label} ${number(context.parsed.y)}（起点=100）`}}},
    scales:{x:{grid:{display:false},ticks:{maxTicksLimit:6,color:'#8495a2',font:{size:10}}},y:{grid:{color:'#e7edf0'},ticks:{color:'#8495a2',font:{size:10}}}}}});
}

function renderDecisions() {
  const known = state.actions.filter((item) => item.metric).length;
  $('#decisionStatus').textContent = `可评估 ${known}/${state.actions.length} 个标的。动作是条件式研究参考，历史胜率尚未校准。`;
  $('#decisionGrid').innerHTML = state.actions.map((item) => `<button type="button" class="decision-card ${selectedAction === item.ticker ? 'selected' : ''}" data-action="${escapeHtml(item.ticker)}">
    <span class="decision-card-top"><strong>${escapeHtml(item.ticker)} ${item.held ? '<em class="held-tag">已持有</em>' : ''}</strong><small>${escapeHtml(item.metric?.date || '行情待获取')}</small></span>
    <span class="action-label ${item.advice.action.includes('风险') || item.advice.action.includes('暂缓') ? 'risk' : ''}">${escapeHtml(item.advice.action)}</span>
    <span class="decision-prices">${item.advice.in_watch_zone ? '已进入关注区' : '关注区'} ${item.advice.watch_zone ? `$${number(item.advice.watch_zone[0])}–${number(item.advice.watch_zone[1])}` : '待计算'} · 确认价 ${item.advice.buy_trigger ? `$${number(item.advice.buy_trigger)}` : '—'}</span>
    <span class="basis">${escapeHtml(item.advice.basis)}</span></button>`).join('');
  if (selectedAction == null && state.actions.length) selectedAction = state.actions[0].ticker;
  renderDecisionDetail();
}
function renderDecisionDetail() {
  const item = state.actions.find((action) => action.ticker === selectedAction);
  $('#decisionGrid').querySelectorAll('.decision-card').forEach((card) => card.classList.toggle('selected', card.dataset.action === selectedAction));
  if (!item) { $('#decisionDetail').innerHTML = '<div class="empty-detail">选择一个标的查看确认条件与失效条件</div>'; return; }
  const advice = item.advice;
  $('#decisionDetail').innerHTML = `<h3>${escapeHtml(item.ticker)} · ${escapeHtml(advice.action)} ${item.held ? '<em class="held-tag">已持有</em>' : ''}</h3>
    <div class="decision-price-row"><div><span>关注价格区间</span><strong>${advice.watch_zone ? `$${number(advice.watch_zone[0])}–$${number(advice.watch_zone[1])}` : '待计算'}</strong></div>
    <div><span>买入确认价</span><strong>${advice.buy_trigger ? `$${number(advice.buy_trigger)}` : '—'} ${advice.trigger_confirmed ? '· 已触发' : '· 待确认'}</strong></div>
    <div><span>风险失效价</span><strong>${advice.risk_price ? `$${number(advice.risk_price)}` : '—'}</strong></div></div>
    <div class="decision-detail-grid"><div><span>估值参考</span><p>${escapeHtml(advice.valuation)}</p></div>
    <div><span>确认条件</span><p>${escapeHtml(advice.confirm)}</p></div>
    <div><span>失效与风险</span><p>${escapeHtml(advice.invalidate)}</p></div></div>`;
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
    <td>${item.price == null ? '无报价' : '$' + number(item.price)}<small class="price-label">${escapeHtml(item.price_label)}</small></td><td class="${tone(item.change)}">${signed(item.change)}</td>
    <td class="${tone(item.metric?.return5)}">${signed(item.metric?.return5)}</td><td>${escapeHtml(item.metric?.trend || '数据不足')}</td>
    <td>${item.metric ? number(item.metric.volume_ratio) + ' 倍' : '—'}</td>
    <td class="muted">暂无稳定免费口径</td><td class="muted">${escapeHtml(item.asof || '来源不可用')}</td></tr>`).join('') || '<tr><td colspan="8" class="muted">观察列表中暂无宽基或行业基金</td></tr>';
  $('#watchTable tbody').innerHTML = stocks.map((item) => `<tr data-watch="${escapeHtml(item.ticker)}" class="${selectedWatch === item.ticker ? 'selected' : ''}">
    <td title="${escapeHtml(item.name)}">${escapeHtml(item.ticker)} ${item.is_held ? '<em class="held-tag">已持有</em>' : ''} <span class="muted">${escapeHtml(item.name)}</span></td>
    <td title="${escapeHtml(item.price_label)} · ${escapeHtml(item.quote_source)}">${item.price == null ? '无报价' : '$' + number(item.price)}<small class="price-label">${escapeHtml(item.price_label)}</small></td><td class="${tone(item.change)}">${signed(item.change)}</td>
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
  const basis = isFund ? '基金前瞻市盈率：当前免费来源没有稳定且可复核的口径。价格、趋势和量比可在上方查看。' :
    item.eps_ntm == null ? '未来四季一致预期不足，暂不计算未来12月市盈率。' : `未来四季每股盈利合计 ${number(item.eps_ntm)} · ${item.eps_period} · ${item.eps_source} · 抓取 ${item.eps_asof}`;
  const analyst = item.analyst_target == null ? '分析师一年目标价：暂无' : `分析师一年目标价 $${number(item.analyst_target)} · ${item.target_source} · 抓取 ${item.target_asof}`;
  const average = item.one_year_pe_average == null ? `一年平均前瞻市盈率：历史快照积累中（${item.one_year_pe_samples} 个日快照）` : `一年平均前瞻市盈率：${number(item.one_year_pe_average,1)} 倍 · 本机逐日历史`;
  const comparison = item.comparison_price == null ? '交叉核对：TradingView 暂无数据' : `TradingView 当前报价 $${number(item.comparison_price)}${item.price_gap_pct == null ? '' : ` · 与纳斯达克价差 ${number(item.price_gap_pct,2)}%`}${item.comparison_next_fy_eps == null ? '' : ` · 下一财年每股盈利预测 ${number(item.comparison_next_fy_eps)}`} · 抓取 ${item.comparison_fetched_at}${item.quote_conflict ? ' · 来源差异过大，暂停动作' : ''}`;
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
function render() {setStatus();renderPulse();renderEvents();renderMarket();renderDecisions();renderPortfolio();renderSettings();icons();}

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
