"""Single-reference upside: identical price and denominator across the application."""


def annual_reference(history,price,watch_zone,fair_price,analyst_target=None):
    if not fair_price or not price or price<=0:
        return {'available':False,'reference_price':None,'upside_pct':None,'valuation_range':None,
                'reason':'统一12月参考价尚未取得','definition':'所有板块以同一参考价与同一当前价计算空间'}
    upside=round((fair_price/price-1)*100,1)
    return {'available':True,'reference_price':fair_price,'current_price':price,'upside_pct':upside,
            'valuation_range':[upside,upside],'scenario_basis':'统一参考价','calibrated':False,
            'definition':'参考空间＝统一12月参考价÷当前价－1；关注区间属于短线入场条件，不改变涨幅的比较基准'}
