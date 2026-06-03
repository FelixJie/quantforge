import sys
sys.path.insert(0, 'src')
from quantforge.api.routes.research import _eastmoney_reports

print("="*50)
print("测试获取更多研报")
print("="*50)

codes = ['300024', '300008', '002008']

total_reports = 0
for code in codes:
    print(f"\n正在获取 {code} 的研报...")
    reports = _eastmoney_reports(code, max_pages=10, page_size=100)
    print(f"✅ {code} 获得 {len(reports)} 条研报")
    
    if reports:
        print(f"   前3条:")
        for i, r in enumerate(reports[:3]):
            print(f"   {i+1}. {r.get('title')[:50]}... ({r.get('orgSName')})")
    
    total_reports += len(reports)

print(f"\n" + "="*50)
print(f"总计获取: {total_reports} 条研报")
print("="*50)
