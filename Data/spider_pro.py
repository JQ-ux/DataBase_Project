import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import time

# 1. 定义 15 家目标公司
SYMBOLS = ['NVDA', 'AAPL', 'TSLA', 'GOOGL', 'AMZN', 'MSFT', 'META', 'AAL', 'INTC', 'PLTR', 'SOFI', 'AMD', 'NFLX', 'PYPL', 'BAC']

def fetch_all_data():
    company_list = []
    financials_list = []
    daily_prices_list = []
    
    # 设定日期范围：2026-02-12 到 2026-03-18
    # yfinance 抓取的是 [start, end) 左闭右开区间，所以 end 设为 03-19
    start_date = "2026-02-12"
    end_date = "2026-03-19"

    for symbol in SYMBOLS:
        print(f"--- 正在爬取 {symbol} 的全量数据 (含 Industry & Balance Sheet) ---")
        try:
            ticker = yf.Ticker(symbol)
            
            # --- 1. 对应 Company & Industry 表 ---
            info = ticker.info
            company_list.append({
                'symbol': symbol,
                'full_name': info.get('longName', 'N/A'),
                'industry': info.get('industry', 'N/A'),  # 用于关联 Industry 表
                'sector': info.get('sector', 'N/A'),      # 用于 Industry 表的描述
                'market_cap': info.get('marketCap'),
                'trailing_pe': info.get('trailingPE'),
                'price_sales': info.get('priceToSalesTrailing12Months'),
                'current_price': info.get('currentPrice')
            })

            # --- 2. 对应 Financials 表 (利润表 + 资产负债表) ---
            # 获取利润表
            income = ticker.financials.T 
            # 获取资产负债表
            balance = ticker.balance_sheet.T 

            if not income.empty:
                for date, row in income.iterrows():
                    # 尝试匹配同一日期的资产负债表数据
                    b_row = balance.loc[date] if date in balance.index else {}
                    
                    financials_list.append({
                        'symbol': symbol,
                        'report_date': date.strftime('%Y-%m-%d'),
                        'total_revenue': row.get('Total Revenue'),
                        'gross_profit': row.get('Gross Profit'),
                        'operating_income': row.get('Operating Income'),
                        'net_income': row.get('Net Income'),
                        'basic_eps': row.get('Basic EPS'),
                        # --- 新增的资产负债字段 ---
                        'total_assets': b_row.get('Total Assets'),
                        'total_liabilities': b_row.get('Total Liabilities Net Minority Interest'),
                        'current_assets': b_row.get('Current Assets'),
                        'current_liabilities': b_row.get('Current Liabilities'),
                        'inventory': b_row.get('Inventory', 0)
                    })

            # --- 3. 对应 DailyPrice 表 (历史流水) ---
            hist = ticker.history(start=start_date, end=end_date)
            for date, row in hist.iterrows():
                daily_prices_list.append({
                    'symbol': symbol,
                    'trade_date': date.strftime('%Y-%m-%d'),
                    'open_price': round(row['Open'], 4),
                    'high_price': round(row['High'], 4),
                    'low_price': round(row['Low'], 4),
                    'close_price': round(row['Close'], 4),
                    'volume': int(row['Volume'])
                })
            
            # 频率控制，避免被封
            time.sleep(1)

        except Exception as e:
            print(f"跳过 {symbol}，原因: {e}")

    # --- 导出 CSV (覆盖旧文件) ---
    pd.DataFrame(company_list).to_csv('companies.csv', index=False)
    pd.DataFrame(financials_list).to_csv('financials.csv', index=False)
    pd.DataFrame(daily_prices_list).to_csv('daily_prices.csv', index=False)
    
    print("\n数据抓取任务已完成！CSV 文件已在当前文件夹更新并覆盖。")

if __name__ == "__main__":
    fetch_all_data()