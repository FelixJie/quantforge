import sys
sys.path.insert(0, 'src')
from quantforge.data.feed.mootdx_feed import _tencent_quote
print('正在获取行情...')
quotes = _tencent_quote(['300024', '300008', '002008'])
for code, q in quotes.items():
    print(f'{code} {q.get("name")} 价格:{q.get("price")} PE:{q.get("pe_ttm")}')
