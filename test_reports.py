import sys
sys.path.insert(0, 'src')
from quantforge.api.routes.research import _eastmoney_reports
print('正在获取 300024 (机器人) 的研报...')
reports = _eastmoney_reports('300024', max_pages=1)
print(f'共获取到 {len(reports)} 条研报')
if reports:
    print('前3条研报:')
    for i, r in enumerate(reports[:3]):
        print(f'{i+1}. {r.get("title")} ({r.get("orgSName")})')
        print(f'   infoCode: {r.get("infoCode")}')
