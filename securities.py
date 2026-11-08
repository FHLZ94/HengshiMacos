"""Security identity and tracking defaults; benchmark inputs stay independent."""
import re

DEFAULT_TRACKING = ['VGT','SPY','QQQM','SMH','ORCL','MRVL','MU','LITE','INTC','AVGO','GOOG','SKHY','^VIX']
MODEL_INPUTS = ('QQQ','SPY','SMH','^VIX')
FUND_CODES = frozenset(('VGT','QQQ','QQQM','SPY','SMH','IWM','RSP','XLK','XLV','XLP','XLU',
                       'XLY','XLF','XLE','XLI','XLC','XLRE','XLB','TLT','GLD'))
CHINESE_NAMES = {'VGT':'先锋信息技术ETF','GOOGL':'谷歌A类股','GOOG':'谷歌C类股','SKHY':'SK海力士',
                 'AAPL':'苹果','TSLA':'特斯拉','META':'元宇宙平台','MSFT':'微软','NVDA':'英伟达',
                 'AMZN':'亚马逊','AMD':'超威半导体','TSM':'台积电','ASML':'阿斯麦',
                 'CRM':'赛富时','ADBE':'奥多比','NFLX':'奈飞','PLTR':'帕兰提尔','ARM':'安谋',
                 'COHR':'相干公司','ANET':'阿里斯塔网络','COST':'开市客','JPM':'摩根大通',
                 'BAC':'美国银行','WMT':'沃尔玛','LLY':'礼来','UNH':'联合健康','TQQQ':'三倍纳指ETF',
                 'SOXX':'半导体精选ETF','VOO':'先锋标普500ETF','VTI':'先锋全美股票ETF','SCHD':'嘉信美国红利ETF'}


def normalize(value):
    if not isinstance(value,str):raise ValueError('请输入证券代码')
    ticker=value.strip().upper()
    if not re.fullmatch(r'[A-Z][A-Z0-9.-]{0,14}',ticker):raise ValueError('请输入有效的美股或ETF代码，例如 NVDA、VGT、SKHY')
    return 'MU' if ticker=='DRAM' else ticker


def is_fund(ticker,config=None):
    return ticker in FUND_CODES or ((config or {}).get('securities',{}).get(ticker) or {}).get('asset_type')=='etf'


def migrate_settings(config):
    result=dict(config);current=list(dict.fromkeys('MU' if t=='DRAM' else t for t in config.get('watchlist',DEFAULT_TRACKING)))
    if not result.get('tracking_editor_v1'):
        current=['VGT' if t=='QQQ' else t for t in current]
        for ticker in ('GOOG','SKHY'):
            if ticker not in current:current.insert(current.index('^VIX') if '^VIX' in current else len(current),ticker)
        result['tracking_editor_v1']=True
    result['watchlist']=list(dict.fromkeys(current))
    result['securities']=dict(config.get('securities') or {})
    return result


def tv_symbol(ticker,config=None):
    meta=((config or {}).get('securities') or {}).get(ticker) or {}
    exchange=(meta.get('exchange') or '').upper()
    if exchange.startswith('NASDAQ'):return 'NASDAQ:'+ticker
    if exchange in ('NYSE','NYSE-GS'):return 'NYSE:'+ticker
    if exchange in ('NYSE ARCA','NYSEARCA','PSE','AMEX','NYSE AMERICAN'):return 'AMEX:'+ticker
    return None
