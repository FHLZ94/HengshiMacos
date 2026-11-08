"""Free official/public intelligence and optional original X post imports."""
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
from urllib.parse import quote,urlsplit
import re
from lxml import html
import data_service

QUICK_FEEDS=[
 ('白宫·总统行动','https://www.whitehouse.gov/presidential-actions/feed/'),
 ('国会·政策与AI监管','https://news.google.com/rss/search?q='+quote('(Congress OR Senate OR White House) (AI OR semiconductor OR data center) (moratorium OR halt OR export controls OR bill) when:3d')+'&hl=en-US&gl=US&ceid=US:en'),
 ('公开言论·半导体投资','https://news.google.com/rss/search?q='+quote('(Nvidia OR Broadcom OR Micron OR Hynix OR semiconductor) (CEO OR analyst OR "on X") (guidance OR capex OR demand) when:3d')+'&hl=en-US&gl=US&ceid=US:en'),
 ('公开言论·白宫与参议员','https://news.google.com/rss/search?q='+quote('(Bernie Sanders OR Elizabeth Warren OR Mark Warner OR Ted Cruz OR White House) (AI OR chips OR data center) when:3d')+'&hl=en-US&gl=US&ceid=US:en')]
POST_RE=re.compile(r'^https://(?:www\.)?(?:x|twitter)\.com/(?:[A-Za-z0-9_]{1,15}|i/web)/status/(\d{10,25})(?:[?/#].*)?$')


def validate_posts(raw):
    urls=list(dict.fromkeys(str(raw).split()))
    if len(urls)>20:raise ValueError('最多可补充20条公开帖子链接')
    if any(not POST_RE.fullmatch(u) for u in urls):raise ValueError('请填写完整的 X 公开帖子链接，例如 https://x.com/账号/status/编号')
    return urls


def public_post(url,config,sentiment_fn,impact_fn):
    match=POST_RE.fullmatch(url)
    if not match:raise ValueError('公开帖子链接无效')
    identity=match.group(1)
    response=data_service.http_get('https://publish.twitter.com/oembed',params={'url':url,'omit_script':'true'},
        headers=data_service.HEADERS,proxies=data_service.configured_proxy(config,for_google=True),timeout=(4,9))
    response.raise_for_status();payload=response.json()
    if '/status/'+identity not in payload.get('url',''):raise ValueError('返回帖子身份不匹配')
    root=html.fromstring(payload.get('html') or '<div/>')
    body=' '.join(' '.join(node.text_content().split()) for node in root.xpath('//p'))
    if not body:raise ValueError('公开帖子正文不可读')
    stamp=datetime.fromtimestamp(((int(identity)>>22)+1288834974657)/1000,timezone.utc)
    if stamp>datetime.now(timezone.utc):raise ValueError('帖子发布时间异常')
    title=(payload.get('author_name') or '公开账号')+'：'+body[:180]
    score,label=sentiment_fn(body);impact=impact_fn(body)
    return {'title':title,'summary':body[:3000],'link':payload['url'],'source':'X 公开帖子',
        'publisher':payload.get('author_name',''),'published':stamp.isoformat(timespec='seconds'),
        'tickers':data_service.ticker_matches(body,config.get('watchlist',[]),config),
        'impact':impact,'sentiment':score,'label':label,'grade':'S3','credibility':'公开言论，需交叉核验',
        'horizon':'1—3个交易日','independent_publishers':[]}


def fetch_public(config,sentiment_fn,impact_fn,on_rows=None):
    coverage=list(dict.fromkeys(config.get('watchlist',[])+list(data_service.INTELLIGENCE_TICKERS)))
    rows=[];health=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs=[pool.submit(data_service._feed,name,url,config,sentiment_fn,impact_fn,coverage) for name,url in QUICK_FEEDS]
        for future in as_completed(jobs):
            try:
                items,state=future.result();rows.extend(items);health.append(state)
                if items and on_rows:on_rows(items)
            except Exception:continue
        for url in config.get('public_post_urls',[]):
            try:
                item=public_post(url,config,sentiment_fn,impact_fn);rows.append(item)
                if on_rows:on_rows([item])
            except Exception:continue
    return rows,health
