"""Published V7 service rates, derived from the same immutable billing snapshot."""
from decimal import Decimal


def public_rates():
    from service.usage_pricing import snapshot
    from service.usage_currency import cached_gbp_rate
    from service.usage_wallet import markup_percent, UsagePaused
    try:
        prices=snapshot()
        fx=cached_gbp_rate()
        if not fx or fx.get('stale'):
            raise ValueError('rate_unavailable')
        factor=Decimal(str(fx['rate']))*(1+markup_percent()/100)
        if not factor.is_finite() or factor<=0:
            raise ValueError('rate_unavailable')
        def money(amount):
            return str(amount.quantize(Decimal('0.000001')))
        models=[{'model':model,'input':money(Decimal(rates[0])*factor/1000),
            'cached':money(Decimal(rates[1])*factor/1000),'output':money(Decimal(rates[2])*factor/1000),
            'cache_write':money(Decimal(prices.cache_writes.get(model,rates[0]))*factor/1000),
            'long_context':model in prices.long_context_models} for model,rates in sorted(prices.rates.items())]
        audio=[{'model':model,'per_minute':money(Decimal(rate)*60*factor/10**9)} for model,rate in sorted(prices.audio_duration.items())]
        return {'available':True,'currency':'GBP','unit':'per million tokens','rate_date':fx['date'],'models':models,'audio':audio}
    except (ValueError,UsagePaused,KeyError):
        return {'available':False,'currency':'GBP','models':[],'audio':[]}
