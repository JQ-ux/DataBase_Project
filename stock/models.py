from django.db import models
from django.contrib.auth.models import AbstractUser

# ==========================================
# 4. 用户基础表 (继承 AbstractUser 以适配 Django Auth)
# ==========================================
class User(AbstractUser):
    # 对应 ER 图中的 Stock_User 字段
    gender = models.CharField(max_length=20, blank=True, null=True)
    account_balance = models.DecimalField(max_digits=20, decimal_places=2, default=100000.00)

# ==========================================
# 1. 公司基础档案
# ==========================================
class Company(models.Model):
    symbol = models.CharField(max_length=10, primary_key=True)
    full_name = models.CharField(max_length=255)
    market_cap = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    trailing_pe = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    price_sales = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    current_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    def __str__(self):
        return self.symbol

# ==========================================
# 2. 财务报表
# ==========================================
class Financials(models.Model):
    symbol = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='financials')
    report_date = models.DateField()
    total_revenue = models.BigIntegerField(null=True, blank=True)
    gross_profit = models.BigIntegerField(null=True, blank=True)
    operating_income = models.BigIntegerField(null=True, blank=True)
    net_income = models.BigIntegerField(null=True, blank=True)
    basic_eps = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)

# ==========================================
# 3. 每日股价流水表
# ==========================================
class DailyPrice(models.Model):
    symbol = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='daily_prices')
    # 对应 ER 图的 financial_id
    financial_id = models.ForeignKey(Financials, on_delete=models.SET_NULL, null=True, blank=True)
    trade_date = models.DateField()
    open_price = models.DecimalField(max_digits=12, decimal_places=4)
    high_price = models.DecimalField(max_digits=12, decimal_places=4)
    low_price = models.DecimalField(max_digits=12, decimal_places=4)
    close_price = models.DecimalField(max_digits=12, decimal_places=4)
    volume = models.BigIntegerField()

# ==========================================
# 5. 模拟组合表
# ==========================================
class Simulation(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='simulations')
    name = models.CharField(max_length=100)
    start_date = models.DateField()
    initial_cash = models.DecimalField(max_digits=20, decimal_places=2)
    current_nav = models.DecimalField(max_digits=20, decimal_places=2, default=0.00)
    created_at = models.DateTimeField(auto_now_add=True)

# ==========================================
# 6. 模拟交易记录表
# ==========================================
class Simulation_Transaction(models.Model):
    sim = models.ForeignKey(Simulation, on_delete=models.CASCADE, related_name='transactions')
    symbol = models.ForeignKey(Company, on_delete=models.CASCADE)
    # 对应 ER 图中的 daily_price_id
    daily_price = models.ForeignKey(DailyPrice, on_delete=models.SET_NULL, null=True)
    trade_date = models.DateField()
    type = models.CharField(max_length=4) # Buy / Sell
    quantity = models.IntegerField()
    price = models.DecimalField(max_digits=12, decimal_places=4)
    total_amount = models.DecimalField(max_digits=20, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

# ==========================================
# 7. 模拟每日净值快照表
# ==========================================
class Simulation_NAV_History(models.Model):
    sim = models.ForeignKey(Simulation, on_delete=models.CASCADE, related_name='nav_history')
    record_date = models.DateField()
    nav = models.DecimalField(max_digits=20, decimal_places=2)
    cash = models.DecimalField(max_digits=20, decimal_places=2)
    market_value = models.DecimalField(max_digits=20, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

# ==========================================
# 8. 模拟实时持仓表
# ==========================================
class Simulation_Holding(models.Model):
    sim = models.ForeignKey(Simulation, on_delete=models.CASCADE, related_name='holdings')
    symbol = models.ForeignKey(Company, on_delete=models.CASCADE)
    quantity = models.IntegerField()
    avg_cost = models.DecimalField(max_digits=12, decimal_places=4)
    updated_at = models.DateTimeField(auto_now=True)