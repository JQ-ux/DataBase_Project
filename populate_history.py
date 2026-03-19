import os
import django
import random
from decimal import Decimal
from datetime import timedelta, date

# 1. Django 环境初始化
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'capstone.settings')
django.setup()

from django.db import transaction
from stock.models import (
    User, Company, Simulation, Simulation_Holding, 
    Simulation_Transaction, Simulation_NAV_History, 
    TradeOrder, DailyPrice, GlobalSimulationState
)

try:
    from stock.views import internal_matching_engine, calculate_nav_optimized
except ImportError:
    print("错误：无法从 stock.views 导入核心函数。")
    exit()

def run_engine_simulation():
    # 获取测试用户
    try:
        sim_a = Simulation.objects.get(user__username='jinqi')
        sim_b = Simulation.objects.get(user__username='Jinqi')
    except Exception:
        print("错误：请确保用户 jinqi 和 Jinqi 及其 Simulation 已创建。")
        return

    # --- 1. 数据彻底重置 ---
    start_test_date = date(2026, 3, 2)
    end_date = date(2026, 3, 12)
    
    print(f"⏳ 正在初始化测试环境 (2026-03-02)...")
    
    with transaction.atomic():
        for s in [sim_a, sim_b]:
            Simulation_NAV_History.objects.filter(sim=s).delete()
            Simulation_Transaction.objects.filter(sim=s).delete()
            TradeOrder.objects.filter(sim=s).delete()
            Simulation_Holding.objects.filter(sim=s).delete()
            s.available_cash = Decimal('100000.0000') # 初始资金 10万
            s.save()

    company_pool = list(Company.objects.all()[:15]) # 增加股票池范围
    current_day = start_test_date

    while current_day <= end_date:
        if current_day.weekday() >= 5: 
            current_day += timedelta(days=1)
            continue
        
        print(f"📅 正在处理日期: {current_day}")

        # 更新全局日期
        gs, _ = GlobalSimulationState.objects.get_or_create(id=1)
        gs.current_global_date = current_day
        gs.save()

        # --- A. 智能下单逻辑 ---
        # 每天每个账户尝试下 8-12 个单
        for active_sim in [sim_a, sim_b]:
            num_orders = random.randint(8, 12)
            
            # 动态调整买卖倾向：回测前期多买入，后期有货了再随机卖出
            day_index = (current_day - start_test_date).days
            if day_index < 3:
                sides_weights = ['BUY'] * 80 + ['SELL'] * 20  # 前三天 80% 概率买入
            else:
                sides_weights = ['BUY'] * 40 + ['SELL'] * 60  # 之后 60% 概率卖出

            for _ in range(num_orders):
                target_stock = random.choice(company_pool)
                price_rec = DailyPrice.objects.filter(symbol=target_stock, trade_date=current_day).first()
                if not price_rec: continue
                
                side = random.choice(sides_weights)
                # 随机价格（基于当日波动）
                price = Decimal(random.uniform(float(price_rec.low_price), float(price_rec.high_price))).quantize(Decimal('0.0001'))
                qty = random.randint(1, 10) * 10 # 10-100股
                
                total_cost = (price * qty * Decimal('1.0003')).quantize(Decimal('0.0001'))

                with transaction.atomic():
                    # 重新锁定账户，防止并发计算
                    s_lock = Simulation.objects.select_for_update().get(id=active_sim.id)
                    can_place = False
                    avg_cost_val = Decimal('0.0000')

                    if side == 'BUY':
                        if s_lock.available_cash >= total_cost:
                            s_lock.available_cash -= total_cost
                            s_lock.save()
                            can_place = True
                    else:
                        # 卖出：必须真的有货
                        h = Simulation_Holding.objects.filter(sim=s_lock, symbol=target_stock).select_for_update().first()
                        if h and h.quantity >= qty:
                            avg_cost_val = h.avg_cost # 获取买入成本，用于计算盈亏
                            h.quantity -= qty
                            if h.quantity == 0: h.delete()
                            else: h.save()
                            can_place = True
                    
                    if can_place:
                        TradeOrder.objects.create(
                            user=s_lock.user, sim=s_lock, symbol=target_stock,
                            side=side, price=price, quantity=qty,
                            status='PENDING', order_date=current_day,
                            avg_cost_snapshot=avg_cost_val # 关键：存储成本快照
                        )

        # --- B. 运行撮合引擎 ---
        # 这一步会根据 TradeOrder 生成 Simulation_Transaction
        matches = internal_matching_engine(current_day)
        print(f"   🤖 撮合完成: {matches} 笔交易")

        # --- C. 每日净值结算 ---
        for s in [sim_a, sim_b]:
            nav, mkt_val = calculate_nav_optimized(s, current_day)
            Simulation_NAV_History.objects.update_or_create(
                sim=s, record_date=current_day,
                defaults={'nav': nav, 'cash': s.available_cash, 'market_value': mkt_val}
            )

        current_day += timedelta(days=1)

    print(f"\n✨ 回测数据填充完成。请查看前端『操作日志』，现在应该有实现盈亏了。")

if __name__ == "__main__":
    run_engine_simulation()