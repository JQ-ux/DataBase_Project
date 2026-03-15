import os
import csv
import django
import sys
from decimal import Decimal

# ==========================================
# 1. 环境初始化 (针对 capstone 项目)
# ==========================================
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

# 核心修正：你的配置文件夹叫 capstone
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'capstone.settings') 

try:
    django.setup()
except Exception as e:
    print(f"Django 初始化失败: {e}")
    sys.exit(1)

# 导入模型
from stock.models import Company, Financials, DailyPrice

# ==========================================
# 2. 配置 CSV 文件路径
# ==========================================
BASE_DIR = r"C:\Users\24300\Desktop\Stock\Data"
COMPANIES_CSV = os.path.join(BASE_DIR, "companies.csv")
FINANCIALS_CSV = os.path.join(BASE_DIR, "financials.csv")
PRICES_CSV = os.path.join(BASE_DIR, "daily_prices.csv")

def import_companies():
    print("正在导入公司档案...")
    if not os.path.exists(COMPANIES_CSV):
        print(f"错误：找不到文件 {COMPANIES_CSV}")
        return
        
    with open(COMPANIES_CSV, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        count = 0
        for row in reader:
            Company.objects.update_or_create(
                symbol=row['symbol'],
                defaults={
                    'full_name': row['full_name'],
                    'market_cap': Decimal(row['market_cap']) if row.get('market_cap') else None,
                    'trailing_pe': Decimal(row['trailing_pe']) if row.get('trailing_pe') else None,
                    'price_sales': Decimal(row['price_sales']) if row.get('price_sales') else None,
                    'current_price': Decimal(row['current_price']) if row.get('current_price') else None,
                }
            )
            count += 1
    print(f"成功导入/更新 {count} 家公司。")

def import_financials():
    print("正在导入财务报表...")
    if not os.path.exists(FINANCIALS_CSV):
        return
    with open(FINANCIALS_CSV, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                comp = Company.objects.get(symbol=row['symbol'])
                Financials.objects.get_or_create(
                    symbol=comp,
                    report_date=row['report_date'],
                    defaults={
                        'total_revenue': int(float(row['total_revenue'])) if row.get('total_revenue') else 0,
                        'gross_profit': int(float(row['gross_profit'])) if row.get('gross_profit') else 0,
                        'operating_income': int(float(row['operating_income'])) if row.get('operating_income') else 0,
                        'net_income': int(float(row['net_income'])) if row.get('net_income') else 0,
                        'basic_eps': Decimal(row['basic_eps']) if row.get('basic_eps') else 0,
                    }
                )
            except Company.DoesNotExist:
                continue

def import_daily_prices():
    print("正在导入每日股价（批量写入中...）")
    if not os.path.exists(PRICES_CSV):
        return
    with open(PRICES_CSV, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        prices_to_create = []
        count = 0
        for row in reader:
            try:
                comp = Company.objects.get(symbol=row['symbol'])
                prices_to_create.append(DailyPrice(
                    symbol=comp,
                    trade_date=row['trade_date'],
                    open_price=Decimal(row['open_price']),
                    high_price=Decimal(row['high_price']),
                    low_price=Decimal(row['low_price']),
                    close_price=Decimal(row['close_price']),
                    volume=int(float(row['volume'])) if row.get('volume') else 0
                ))
                if len(prices_to_create) >= 1000:
                    DailyPrice.objects.bulk_create(prices_to_create)
                    count += len(prices_to_create)
                    prices_to_create = []
                    print(f"已写入 {count} 条...")
            except Company.DoesNotExist:
                continue
        if prices_to_create:
            DailyPrice.objects.bulk_create(prices_to_create)
            count += len(prices_to_create)
    print(f"全部完成！共 {count} 条股价记录。")

if __name__ == "__main__":
    import_companies()
    import_financials()
    import_daily_prices()