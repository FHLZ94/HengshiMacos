"""Evidence-based article analysis. Headlines alone never become verified facts."""
from datetime import datetime, time, timedelta, timezone
from ipaddress import ip_address
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
import re
import socket

import requests
import trafilatura
from googlenewsdecoder import gnewsdecoder

from data_service import configured_proxy, http_get

NEW_YORK = ZoneInfo('America/New_York')
MATERIAL_TERMS = {
    '合同变化': ('contract cancel', 'deal cancel', 'deal collaps', 'agreement collaps',
               'terminated agreement', 'agreement terminated', 'contract termination',
               'lease cancellation', 'order cancellation', 'cancellation report',
               'shelved expansion', 'still on track'),
    '业绩预期': ('guidance', 'earnings', 'revenue forecast', 'margin forecast', 'profit warning'),
    '政策监管': ('export controls', 'sanction', 'tariff', 'regulation', 'antitrust','moratorium','ai pause','halt ai','executive order'),
    '资本开支': ('capital expenditure', 'capex', 'data center spending', 'ai spending'),
    '股权交易': ('shares acquired', 'shares purchased', 'shares bought', 'stake increased',
               'bought shares', 'purchased shares'),
}
NEGATIONS = re.compile(r'\b(?:not|never|no)\s+(?:\w+\s+){0,3}(?:cancel(?:led|ed)?|terminat(?:e|ed)|cut)\b', re.I)
DISPUTED_CLAIM = re.compile(r'\b(?:den(?:y|ies|ied)|reject(?:s|ed)?|disput(?:e|es|ed))\b.{0,150}\b(?:cancel|collaps|terminat|scrap|shelv|fell apart|fall through|failed)|\b(?:still on track|not cancelled|not canceled|no cancellation)\b',re.I)
SHARES_RE = re.compile(r'\b(\d[\d,]*(?:\.\d+)?)\s*(million|billion|thousand|m|bn)?\s+shares\b', re.I)
PERCENT_RE = re.compile(r'\b(\d{1,2}(?:\.\d+)?)\s*%\s*(?:stake|ownership|of (?:the )?(?:company|shares|outstanding shares))', re.I)
PERCENT_RE_ALT = re.compile(r'\b(?:stake|ownership|holding|interest)\s+(?:of|to|at)\s+(\d{1,2}(?:\.\d+)?)\s*%', re.I)
PORTFOLIO_RE = re.compile(r'\b(\d{1,2}(?:\.\d+)?)\s*%\s+of\s+(?:its|the|their)\s+(?:investment\s+)?portfolio', re.I)
PORTFOLIO_RE_ALT = re.compile(r'\brepresenting\s+(\d{1,2}(?:\.\d+)?)\s*%\s+of\s+(?:its|the|their)\s+portfolio', re.I)
PRICE_RE = re.compile(r'\b(?:average (?:purchase|buying) price|purchase price|paid|at a price of|at an average price of)\s*(?:of\s*)?\$\s*(\d[\d,]*(?:\.\d+)?)\s*(?:per share)?', re.I)
ACTION_RE = re.compile(r'\b(bought|purchased|acquired|added|increased (?:its|their) stake)\b', re.I)
SENTENCE_RE = re.compile(r'(?<=[.!?])\s+(?=[A-Z0-9])')
OFFICIAL_HOSTS = ('sec.gov', 'federalreserve.gov', 'investor.', 'ir.')
PROTECTED_HOSTS = ('reuters.com', 'bloomberg.com', 'seekingalpha.com', 'investing.com')


def _safe_public_url(url):
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    if host in ('localhost',) or host.endswith(('.local', '.internal')):
        return False
    try:
        return ip_address(host).is_global
    except ValueError:
        return True


def resolve_article_url(url, config):
    if not _safe_public_url(url):
        return None, '原文链接无效'
    if 'news.google.com/rss/articles/' not in url:
        return url, None
    proxy = (configured_proxy(config, for_google=True) or {}).get('https')
    try:
        decoded = gnewsdecoder(url, proxy=proxy, timeout=9)
        if decoded.get('success') and _safe_public_url(decoded.get('decoded_url', '')):
            return decoded['decoded_url'], None
    except Exception:
        pass
    return None, 'Google News 原文链接暂无法解析'


def extract_article(url, config):
    if not _safe_public_url(url):
        return '', '原文链接无效'
    host = urlsplit(url).hostname.lower()
    if any(host == item or host.endswith('.' + item) for item in PROTECTED_HOSTS):
        return '', '发布方限制全文访问，使用公开摘要'
    try:
        response = http_get(url, timeout=(5, 13), headers={'User-Agent': 'Mozilla/5.0 (compatible; Hengshi/0.5)'},
                            proxies=configured_proxy(config, for_google=True), allow_redirects=True)
        response.raise_for_status()
        if not _safe_public_url(response.url):
            return '', '重定向目标无效'
        if 'html' not in response.headers.get('content-type', '').lower():
            return '', '来源不是网页正文'
        body = trafilatura.extract(response.text, include_comments=False, include_tables=True,
                                  no_fallback=False, favor_precision=True) or ''
        body = ' '.join(body.split())[:18000]
        if len(body) < 180:
            return '', '来源未提供可提取的正文'
        return body, None
    except requests.HTTPError as exc:
        return '', f'来源拒绝访问（HTTP {exc.response.status_code}）'
    except requests.RequestException:
        return '', '原文连接超时或中断'
    except Exception:
        return '', '原文结构暂无法解析'


def _sentences(text):
    return [part.strip() for part in SENTENCE_RE.split(text) if len(part.strip()) > 25]


def key_facts(text, title=''):
    # Related-story blocks later in an article can describe entirely different trades.
    lead = re.split(r'\b(?:Several other institutional investors|Other institutional investors|In related news)\b',text[:1600],maxsplit=1,flags=re.I)[0]
    candidates = [sentence for sentence in _sentences(lead) if ACTION_RE.search(sentence)]
    shares = percent = portfolio_weight = price = None
    evidence = []
    for sentence in candidates:
        share_match = SHARES_RE.search(sentence)
        percent_match = PERCENT_RE.search(sentence) or PERCENT_RE_ALT.search(sentence)
        portfolio_match = PORTFOLIO_RE.search(sentence) or PORTFOLIO_RE_ALT.search(sentence)
        price_match = PRICE_RE.search(sentence)
        if share_match or percent_match or portfolio_match or price_match:
            evidence.append(sentence[:350])
            if share_match and shares is None:
                shares = share_match.group(0)
            if percent_match and percent is None:
                percent = percent_match.group(1) + '%'
            if portfolio_match and portfolio_weight is None:
                portfolio_weight = portfolio_match.group(1) + '%'
            if price_match and price is None:
                price = '$' + price_match.group(1)
        if len(evidence) >= 3:
            break
    if portfolio_weight is None and candidates:
        for sentence in _sentences(lead):
            portfolio_match = PORTFOLIO_RE.search(sentence) or PORTFOLIO_RE_ALT.search(sentence)
            if portfolio_match:
                portfolio_weight = portfolio_match.group(1) + '%'
                if sentence[:350] not in evidence:
                    evidence.append(sentence[:350])
                break
    if shares is None and candidates:
        title_shares=SHARES_RE.search(title)
        if title_shares and title_shares.group(1).replace(',','') in lead.replace(',',''):
            shares=title_shares.group(0)
    return {'share_count': shares, 'ownership_pct': percent, 'portfolio_weight_pct': portfolio_weight,
            'purchase_price': price,
            'evidence': evidence}


def classify_materiality(title, body=''):
    title_lower = title.lower()
    lead = (title + ' ' + body[:550]).lower()
    if any(term in title_lower for term in MATERIAL_TERMS['股权交易']) or re.search(r'\b(?:purchases|buys|acquires|adds)\s+[\d,.]+\s+shares\b',title_lower):
        return '股权交易'
    for event_type, terms in MATERIAL_TERMS.items():
        if any(term in title_lower for term in terms):
            return event_type
    for event_type, terms in MATERIAL_TERMS.items():
        if any(term in lead for term in terms):
            return event_type
    return '一般市场信息'


def material_evidence(text,event_type):
    terms=MATERIAL_TERMS.get(event_type,())
    sentences=_sentences(text[:4500])
    matched=[sentence[:350] for sentence in sentences if DISPUTED_CLAIM.search(sentence)]
    matched.extend(sentence[:350] for sentence in sentences
                   if any(term in sentence.lower() for term in terms) and sentence[:350] not in matched)
    return matched[:3]


def price_reaction(article, histories):
    published = article.get('published')
    try:
        local = datetime.fromisoformat(published).astimezone(NEW_YORK)
    except (TypeError, ValueError):
        return {'status': '来源未提供发布时间，无法对齐行情'}
    event_day = local.date()
    if local.time() >= time(16, 0):
        event_day += timedelta(days=1)
    mapping = {row['ticker']: row.get('bars') or [] for row in histories}
    results = []
    for ticker in article.get('tickers', [])[:3]:
        bars = mapping.get(ticker, [])
        matched = next((i for i, bar in enumerate(bars)
                        if bar['date'] >= event_day.isoformat() and i > 0), None)
        if matched is None:
            continue
        current, previous = bars[matched], bars[matched-1]
        if previous.get('close', 0) <= 0:
            continue
        change = (current['close'] / previous['close'] - 1) * 100
        benchmark = 'SMH' if ticker in ('NVDA', 'AMD', 'TSM', 'ASML', 'AMAT', 'KLAC', 'LRCX',
                                      'ARM', 'QCOM', 'AVGO', 'MRVL', 'MU', 'INTC') else 'QQQ'
        base_bars = mapping.get(benchmark, [])
        base_idx = next((i for i, bar in enumerate(base_bars) if bar['date'] == current['date'] and i > 0), None)
        base_change = ((base_bars[base_idx]['close'] / base_bars[base_idx-1]['close'] - 1) * 100
                       if base_idx is not None and base_bars[base_idx-1].get('close', 0) > 0 else None)
        results.append({'ticker': ticker, 'date': current['date'], 'change_pct': round(change, 2),
                        'benchmark': benchmark if base_change is not None else None,
                        'excess_pct': round(change-base_change, 2) if base_change is not None else None})
    return {'status': '观察到事件后的行情变动；时间重合不证明因果' if results else '事件后尚无可用收盘数据',
            'rows': results}


def assess(article, text, resolved_url, body_error, histories):
    complete = bool(text and len(text) >= 180)
    basis = text if complete else ' '.join((article.get('title') or '', article.get('summary') or ''))
    facts = key_facts(basis,article.get('title') or '')
    event_type = classify_materiality(article.get('title') or '',basis)
    source = (article.get('publisher') or article.get('source') or '').lower()
    official = any(host in (resolved_url or '').lower() for host in OFFICIAL_HOSTS)
    source_score = 20 if official else 15 if any(name in source for name in ('reuters', 'bloomberg', 'cnbc', 'new york times')) else 10 if source else 5
    material_score = {'合同变化': 30, '业绩预期': 27, '政策监管': 30,
                      '资本开支': 20, '股权交易': 12}.get(event_type, 6)
    specifics = sum(value is not None for value in (facts['share_count'], facts['ownership_pct'],
                                                   facts['portfolio_weight_pct'], facts['purchase_price']))
    specificity_score = min(20, specifics*5 + (6 if complete else 0))
    publishers = len(set(article.get('independent_publishers') or []))
    corroboration_score = 10 if publishers >= 3 else 5 if publishers >= 2 else 0
    reaction = price_reaction(article, histories)
    market_score = 0
    if reaction.get('rows'):
        biggest = max((abs(row['excess_pct']) for row in reaction['rows'] if row['excess_pct'] is not None), default=0)
        market_score = min(15, round(biggest*3))
    score = min(100, source_score + material_score + specificity_score + corroboration_score + market_score)
    grade = 'S1' if score >= 85 else 'S2' if score >= 65 else 'S3' if score >= 40 else 'S4'
    confidence = ('较高' if complete and (official or publishers >= 2) else
                  '中等' if complete or official else '低，需核验原文')
    direction = article.get('label') or '中性'
    dispute=event_type=='合同变化' and bool(DISPUTED_CLAIM.search(basis[:2200]) or NEGATIONS.search(basis[:2200]))
    if dispute:
        direction = '事实争议，待核验'
    elif not complete and direction != '中性':
        direction = '标题方向待核验'
    evidence = (facts['evidence'] if event_type=='股权交易' else material_evidence(basis,event_type)) or [sentence[:350] for sentence in _sentences(basis)[:2]]
    if not evidence and article.get('title'):
        evidence = [article['title'][:350]]
    factual = '已提取原文正文' if complete else '仅有标题或 RSS 摘要'
    if event_type == '股权交易':
        known = []
        if facts['share_count']: known.append(f"股数 {facts['share_count']}")
        if facts['ownership_pct']: known.append(f"持股比例 {facts['ownership_pct']}")
        if facts['portfolio_weight_pct']: known.append(f"该机构投资组合占比 {facts['portfolio_weight_pct']}")
        if facts['purchase_price']: known.append(f"买入价格 {facts['purchase_price']}")
        conclusion = '报道涉及增持或买入股份。'
        if known: conclusion += ' 已提取：' + '，'.join(known) + '。'
    elif dispute:
        conclusion=('原文出现对合同取消或合作破裂说法的否认或修正。'
                    '不能把单一项目调整直接等同于整个合作终止；需核对双方公告、项目范围与合同金额。')
    elif event_type=='业绩预期':
        conclusion=(f'{factual}，主要涉及公司业绩或指引变化。'
                    '需区分已公布业绩、管理层新指引与分析师预测，再观察未来四季每股盈利是否调整。')
    elif event_type=='政策监管':
        conclusion=(f'{factual}，主要涉及政策或监管变化。'
                    '应核对正式文件、生效日期、受影响地区与产品范围，再评估半导体订单和供应链传导。')
    elif event_type=='资本开支':
        conclusion=(f'{factual}，主要涉及资本开支。'
                    '应区分计划、已签合同与实际交付金额，再评估算力需求及相关供应商受益程度。')
    else:
        conclusion=(f'{factual}，目前缺少足以改变盈利预期或估值的具体事实。'
                    '该事件暂列跟踪，不单独形成交易动作。')
    if reaction.get('rows'):
        first = reaction['rows'][0]
        conclusion += f" {first['ticker']} 在 {first['date']} 收盘变动 {first['change_pct']:+.2f}%"
        if first['excess_pct'] is not None:
            conclusion += f"，相对 {first['benchmark']} 超额变动 {first['excess_pct']:+.2f}%"
        conclusion += '；这只是行情同现，不代表该事件造成了变动。'
    return {'grade': grade, 'score': score, 'confidence': confidence, 'direction': direction,
            'event_type': event_type, 'full_text': complete, 'body_error': body_error,
            'resolved_url': resolved_url, 'facts': facts, 'evidence': evidence[:3],
            'market_reaction': reaction, 'conclusion': conclusion,
            'factors': {'来源': source_score, '事件规模': material_score, '具体事实': specificity_score,
                        '独立报道': corroboration_score, '价格确认': market_score},
            'max_factors': {'来源':20,'事件规模':35,'具体事实':20,'独立报道':10,'价格确认':15},
            'limits': ['重要性分数用于事件排序，不代表收益概率',
                       '时间重合的行情不能证明新闻是价格变动的原因']}


def analyze(article, config, histories):
    url, resolution_error = resolve_article_url(article.get('link',''), config)
    body, body_error = extract_article(url, config) if url else ('', resolution_error)
    return assess(article, body, url, body_error, histories)
