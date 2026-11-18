const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'frontend', 'app.js'), 'utf8');
const html = fs.readFileSync(path.join(__dirname, '..', 'frontend', 'index.html'), 'utf8');
assert.match(html, /重点关注标的（宽基、个股）/);
assert.match(html, /id="addTracking"/);
assert.match(html, /id="watchTable"/);
assert.doesNotMatch(html, /id="positionTable"|<h3>实际持仓<\/h3>/);
assert.match(source, /data-remove-tracking=/);
const prefix = source.slice(0, source.indexOf('function renderPulse(){'));
const context = vm.createContext({});
vm.runInContext(prefix, context);
vm.runInContext(`state = {
  watch: [
    {ticker:'QQQM',is_fund:true,fund_valuation:{pe:29.25,percentile:57.5,years:10,samples:120,proxy_ticker:'QQQ',source:'QQQ index'}},
    {ticker:'SMH',is_fund:true,fund_valuation:{pe:26.1,percentile:null,history_status:'历史PE数据不足',source:'公开基金数据'}},
    {ticker:'ORCL',current_pe:19.4,upside_pct:87.9,valuation:{reference_label:'分析师目标价中位数'}}
  ],
  actions: [
    {ticker:'QQQM',name:'纳斯达克100低费率基金',current_price:282.25,upside_pct:null,
      fund_valuation:{percentile:57.5},is_fund:true,advice:{action:'持有观察',watch_zone:[267.25,273.78],risk_price:261.07}},
    {ticker:'AMD',name:'超威半导体',current_price:211.4,price_label:'延迟行情',metric:{return5:2.1},
      advice:{action:'关注回落',watch_zone:[198,203],risk_price:190}}
  ],
  market:{live_quotes:{QQQ:{price:582.4,change:0.42,session:'post',session_change_pct:-0.31,label:'延迟盘后报价',asof:'11-17 23:12 北京时间'}},
    live_positions:{QQQ:{available:true,percentile:18.6,samples:430}},intraday_status:'分钟行情已更新',intraday_busy:false,
    intraday:{AMD:{available:true,rsi_signal:'短线超卖',frames:{
      5:{available:true,rsi1:24.3},15:{available:true,rsi1:27.72,asof:'2026-11-17T15:10:00-05:00'},
      30:{available:true,rsi1:34.1}}}}}
}`, context);

assert.equal(vm.runInContext("marketValuation('QQQ').percentile", context), 57.5);
assert.equal(vm.runInContext("marketValuation('QQQ').pe", context), 29.25);
assert.equal(vm.runInContext("marketValuation('ORCL').label", context), '12个月参考空间 +87.90%');
assert.equal(vm.runInContext("marketValuation('SMH').label", context), '');

const card = vm.runInContext(`marketSignalCard('QQQ', {
  date:'2026-11-10',targets:{QQQ:{setup:{label:'常态区间',lower_tail_pct:16.3,rsi14:40.1},
  up5_pct:57.1,bottom10_pct:21.4,up5:{brier:0.24,baseline_brier:0.25,weights_active:false}}}
}, {QQQ:{available:true,rsi_signal:'RSI常态',latest_asof:'2026-11-17T15:10:00-05:00',outside_regular_session:true,
  frames:{5:{available:true,rsi1:27.72},15:{available:true,rsi1:31.8},30:{available:true,rsi1:42.1}}}}, {},
{QQQ:{reason:'等待承接'}}, 0)`, context);
assert.match(card, /57\.5\/100/);
assert.match(card, /\$582\.40/);
assert.match(card, /class="signal-rsi-heading"><strong>RSI1<\/strong><span>5 \/ 15 分重点<\/span>/);
assert.match(card, /class="rsi-tag cold"><small>5 分钟<\/small><b>27\.72<\/b>/);
assert.match(card, /class="rsi-tag[^"]*"><small>15 分钟<\/small><b>31\.80<\/b>/);
assert.match(card, /class="rsi-tag[^"]*"><small>30 分钟<\/small><b>42\.10<\/b>/);
assert.match(card, /历史下侧 <b>18\.6%<\/b>/);
assert.match(card, /日涨跌 \+0\.42%/);
assert.match(card, /盘后 -0\.31%/);
assert.match(card, /class="signal-status ">短线 · RSI常态<\/span>/);
assert.match(card, /上个交易时段/);
assert.match(card, /11\/17 15:10 美东/);
assert.match(card, /data-remove-market-slot="0"/);
assert.doesNotMatch(card, /事件风险以原文/);

const spy = vm.runInContext(`marketSignalCard('SPY', {
  date:'2026-11-10',targets:{SPY:{setup:{label:'常态区间',lower_tail_pct:20.6,rsi14:40.1},
  up5_pct:58.9,bottom10_pct:24.4,up5:{brier:0.24,baseline_brier:0.25,weights_active:false}}}
}, {}, {}, {SPY:{reason:'等待承接'}}, 1)`, context);
assert.match(spy, /signal-earnings-placeholder/);
assert.equal((card.match(/class="signal-earnings/g) || []).length, (spy.match(/class="signal-earnings/g) || []).length);

vm.runInContext("marketRsi.set('QQQM|2026-11-10',{result:{ok:true,rsi14:38.4,asof:'2026-11-10'},checkedAt:Date.now()})", context);
const tracking = vm.runInContext("marketActionCard('QQQM', 2, '2026-11-10')", context);
assert.match(tracking, /QQQM/);
assert.match(tracking, /\$282\.25/);
assert.match(tracking, /RSI1/);
assert.match(tracking, /5 分钟<\/small><b>—<\/b>/);
assert.match(tracking, /关注区 \$267\.25–273\.78/);
assert.match(tracking, /失效 \$261\.07/);
assert.match(tracking, /概率模型未校准/);
const custom = vm.runInContext("marketActionCard('AMD', 4, '2026-11-10')", context);
assert.match(custom, /RSI1/);
assert.match(custom, /5 分钟<\/small><b>24\.30<\/b>/);
assert.match(custom, /15 分钟<\/small><b>27\.72<\/b>/);
assert.match(custom, /30 分钟<\/small><b>34\.10<\/b>/);
assert.match(custom, /短线 · 短线超卖/);
assert.match(custom, /概率模型未校准/);

console.log('Market card data mapping passed');
