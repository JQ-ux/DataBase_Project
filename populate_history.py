import os
import django
import random
from decimal import Decimal
from datetime import timedelta, date

# 1. 环境初始化
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'capstone.settings')
django.setup()

from stock.models import (
    User, Company, Simulation, Simulation_Holding, 
    Simulation_Transaction, Simulation_NAV_History
)
from django.utils import timezone

def run_multi_user_simulation():
    # 获取两个核心账号
    try:
        user_a = User.objects.get(username='jinqi')
        user_b = User.objects.get(username='Jinqi')
    except User.DoesNotExist:
        print("❌ 错误：请确保用户名 'jinqi' 和 'Jinqi' 都已注册。")
        return

    # 获取两人的 LIVE 模式模拟器
    sim_a = Simulation.objects.filter(user=user_a, mode='LIVE').first()
    sim_b = Simulation.objects.filter(user=user_b, mode='LIVE').first()
    
    if not sim_a or not sim_b:
        print("❌ 错误：其中一个账号缺少 LIVE 模式的 Simulation 实例。")
        return

    print(f"🧹 正在重置 {user_a.username} 和 {user_b.username} 的 3 月历史数据...")
    
    # 清理指定时间段的数据，防止重复运行导致图表错乱
    for s in [sim_a, sim_b]:
        Simulation_NAV_History.objects.filter(sim=s).delete()
        Simulation_Transaction.objects.filter(sim=s).delete()
        Simulation_Holding.objects.filter(sim=s).delete()
        s.available_cash = Decimal('100000.0000')
        s.save()

    try:
        target_stock = Company.objects.get(symbol='NVDA')
    except Company.DoesNotExist:
        print("❌ 错误：数据库中找不到 NVDA。")
        return

    start_date = date(2026, 3, 2)
    end_date = date(2026, 3, 12)
    current_day = start_date

    print(f"🚀 开始全真对倒交易模拟: {start_date} -> {end_date}\n")

    while current_day <= end_date:
        # 排除周末
        if current_day.weekday() >= 5:
            print(f"📅 {current_day} [休市]")
        else:
            # 同步两人的虚拟日期
            for s in [sim_a, sim_b]:
                s.current_virtual_date = current_day
                s.save()

            # 每天进行 2-3 笔对倒
            trades_today = random.randint(2, 3)
            last_price = Decimal('180.0000') 

            for _ in range(trades_today):
                # 随机分配买卖方
                buyer_sim, seller_sim = (sim_a, sim_b) if random.random() > 0.5 else (sim_b, sim_a)
                
                # 模拟股价波动
                price = Decimal(random.uniform(180, 200)).quantize(Decimal('0.0001'))
                last_price = price
                qty = random.randint(5, 15) * 10 
                total_amount = (qty * price).quantize(Decimal('0.0001'))

                if buyer_sim.available_cash >= total_amount:
                    # --- 1. 执行买方逻辑 ---
                    buyer_sim.available_cash -= total_amount
                    buyer_sim.save()
                    
                    h_buy, _ = Simulation_Holding.objects.get_or_create(
                        sim=buyer_sim, 
                        symbol=target_stock,
                        defaults={'quantity': 0, 'avg_cost': Decimal('0.0000')}
                    )
                    
                    old_cost_total = h_buy.avg_cost * h_buy.quantity
                    h_buy.quantity += qty
                    h_buy.avg_cost = ((old_cost_total + total_amount) / h_buy.quantity).quantize(Decimal('0.0001'))
                    h_buy.save()
                    
                    # 匹配你的模型：字段是 type 和 total_amount
                    Simulation_Transaction.objects.create(
                        sim=buyer_sim, symbol=target_stock, 
                        type='BUY', # 对应 TransType.BUY
                        quantity=qty, price=price, total_amount=total_amount,
                        trade_date=current_day
                    )

                    # --- 2. 执行卖方逻辑 ---
                    seller_sim.available_cash += total_amount
                    seller_sim.save()
                    
                    h_sell, _ = Simulation_Holding.objects.get_or_create(
                        sim=seller_sim, 
                        symbol=target_stock,
                        defaults={'quantity': 0, 'avg_cost': Decimal('0.0000')}
                    )
                    h_sell.quantity -= qty # 允许负持仓作为初始测试
                    h_sell.save()
                    
                    Simulation_Transaction.objects.create(
                        sim=seller_sim, symbol=target_stock, 
                        type='SELL', # 对应 TransType.SELL
                        quantity=qty, price=price, total_amount=total_amount,
                        trade_date=current_day
                    )
                    
                    print(f"  ✅ {current_day}: {buyer_sim.user.username} 买入 {qty}股 NVDA @ {price}")

            # 每日收盘记录 NAV
            for s in [sim_a, sim_b]:
                # 根据持仓计算市值
                holding = Simulation_Holding.objects.filter(sim=s, symbol=target_stock).first()
                q = holding.quantity if holding else 0
                mkt_val = (q * last_price).quantize(Decimal('0.0001'))
                daily_nav = s.available_cash + mkt_val
                
                Simulation_NAV_History.objects.update_or_create(
                    sim=s, record_date=current_day,
                    defaults={
                        'nav': daily_nav,
                        'cash': s.available_cash,
                        'market_value': mkt_val
                    }
                )

        current_day += timedelta(days=1)

    print(f"\n✨ 模拟完成！数据已同步至 3 月 12 日。")
    print("现在去网页端查看‘交易流水’和‘资产曲线’，字段已经完全对齐了！")

if __name__ == "__main__":
    run_multi_user_simulation()