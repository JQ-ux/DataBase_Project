import os
import django
import random
from datetime import timedelta
from decimal import Decimal
from django.utils import timezone

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'capstone.settings')
django.setup()

from stock.models import Simulation, Simulation_NAV_History, Company, Simulation_Holding, Simulation_Transaction, DailyPrice, User

def simulate_monthly_data():
    target_sim = Simulation.objects.first()
    if not target_sim:
        print("Error: No simulation found.")
        return

    print(f"Executing FORCED rational trade simulation for: {target_sim.name}")

    # 清空旧数据
    Simulation_NAV_History.objects.filter(sim=target_sim).delete()
    Simulation_Transaction.objects.filter(sim=target_sim).delete()
    Simulation_Holding.objects.filter(sim=target_sim).delete()

    user = target_sim.user
    user.account_balance = Decimal('100000.00')
    user.save()
    
    running_cash = user.account_balance
    companies = list(Company.objects.all())
    
    if not companies:
        print("Error: No companies found in database. Please seed your Company table first.")
        return

    current_date = timezone.now().date()
    
    for i in range(30, -1, -1):
        record_date = current_date - timedelta(days=i)
        
        # 每天固定进行两次尝试
        for _ in range(2):
            target_stock = random.choice(companies)
            # 这里的价格需要有波动才有意义，如果没有 DailyPrice，就用 current_price 并加点随机干扰
            base_price = target_stock.current_price if target_stock.current_price else Decimal('150.00')
            # 模拟每日价格微调，让 NAV 动起来
            price = (base_price * Decimal(random.uniform(0.95, 1.05))).quantize(Decimal('0.01'))
            
            holding, _ = Simulation_Holding.objects.get_or_create(
                sim=target_sim, symbol=target_stock,
                defaults={'quantity': 0, 'avg_cost': Decimal('0.00')}
            )

            # 逻辑：只要有钱就买，只要有货就卖
            if running_cash > 10000: 
                trade_type = 'BUY'
                quantity = random.randint(10, 50)
                total_amount = (quantity * price).quantize(Decimal('0.01'))
                
                if running_cash >= total_amount:
                    total_cost = (holding.quantity * holding.avg_cost) + total_amount
                    holding.quantity += quantity
                    holding.avg_cost = (total_cost / holding.quantity).quantize(Decimal('0.01'))
                    running_cash -= total_amount
                    holding.save()
                else: trade_type = None
            elif holding.quantity > 0:
                trade_type = 'SELL'
                quantity = holding.quantity // 2 + 1
                total_amount = (quantity * price).quantize(Decimal('0.01'))
                running_cash += total_amount
                holding.quantity -= quantity
                holding.save()
            else:
                trade_type = None

            if trade_type:
                Simulation_Transaction.objects.create(
                    sim=target_sim, symbol=target_stock,
                    trade_date=record_date, type=trade_type,
                    quantity=quantity, price=price, total_amount=total_amount
                )

        # 计算当日净值：现金 + 持仓市值
        current_holdings = Simulation_Holding.objects.filter(sim=target_sim, quantity__gt=0)
        # 关键：这里计算市值时也加入随机波动，模拟市场变化
        market_value = sum(h.quantity * (h.symbol.current_price * Decimal(random.uniform(0.98, 1.02))) for h in current_holdings)
        market_value = Decimal(market_value).quantize(Decimal('0.01'))
        daily_nav = running_cash + market_value

        Simulation_NAV_History.objects.create(
            sim=target_sim, record_date=record_date,
            nav=daily_nav, cash=running_cash, market_value=market_value
        )
        print(f"Day {record_date}: Cash={running_cash:.2f}, MktVal={market_value:.2f}, NAV={daily_nav:.2f}")

    user.account_balance = running_cash
    user.save()
    target_sim.current_nav = daily_nav
    target_sim.save()
    print("\nSuccess! Now you should see fluctuating NAV values.")

if __name__ == "__main__":
    simulate_monthly_data()