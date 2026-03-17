import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta

# 1. 定义 15 家目标公司
SYMBOLS = ['NVDA', 'AAPL', 'TSLA', 'GOOGL', 'AMZN', 'MSFT', 'META', 'AAL', 'INTC', 'PLTR', 'SOFI', 'AMD', 'NFLX', 'PYPL', 'BAC']

def fetch_all_data():
    company_list = []
    financials_list = []
    daily_prices_list = []
    
    # 设定日期范围（近一个月）
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)

    for symbol in SYMBOLS:
        print(f"--- 正在爬取 {symbol} 的全量数据 ---")
        try:
            ticker = yf.Ticker(symbol)
            
            # --- 1. 对应 Company 表 ---
            info = ticker.info
            company_list.append({
                'symbol': symbol,
                'full_name': info.get('longName', 'N/A'),
                'market_cap': info.get('marketCap'),
                'trailing_pe': info.get('trailingPE'),
                'price_sales': info.get('priceToSalesTrailing12Months'),
                'current_price': info.get('currentPrice')
            })

            # --- 2. 对应 Financials 表 (财报) ---
            # 获取年度财报并提取你需要的字段
            fin = ticker.financials.T # 转置方便处理
            if not fin.empty:
                for date, row in fin.iterrows():
                    financials_list.append({
                        'symbol': symbol,
                        'report_date': date.strftime('%Y-%m-%d'),
                        'total_revenue': row.get('Total Revenue'),
                        'gross_profit': row.get('Gross Profit'),
                        'operating_income': row.get('Operating Income'),
                        'net_income': row.get('Net Income'),
                        'basic_eps': row.get('Basic EPS')
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

        except Exception as e:
            print(f"跳过 {symbol}，原因: {e}")

    # --- 导出 CSV ---
    # --- 导出 CSV (将 'Data/' 去掉，直接写文件名) ---
    pd.DataFrame(company_list).to_csv('companies.csv', index=False)
    pd.DataFrame(financials_list).to_csv('financials.csv', index=False)
    pd.DataFrame(daily_prices_list).to_csv('daily_prices.csv', index=False)
    
    print("\n数据抓取任务已完成！CSV 已保存在当前文件夹。")
if __name__ == "__main__":
    fetch_all_data()