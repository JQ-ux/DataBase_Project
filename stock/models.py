from django.db import models
from django.contrib.auth.models import AbstractUser
from django.db.models import Sum, F, Q
from django.core.exceptions import ValidationError
from decimal import Decimal
from django.utils import timezone
# ==========================================
# 0. Global Constants
# ==========================================
ZERO = Decimal('0.0000')

# ==========================================
# 1. User Model
# ==========================================
class User(AbstractUser):
    gender = models.CharField(max_length=20, blank=True, null=True)
    account_balance = models.DecimalField(
        max_digits=20, 
        decimal_places=4, 
        default=Decimal('100000.0000')
    )

# ==========================================
# 2. Market Reference Data
# ==========================================
class Company(models.Model):
    symbol = models.CharField(max_length=10, primary_key=True)
    full_name = models.CharField(max_length=255)
    market_cap = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    trailing_pe = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    price_sales = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    current_price = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)

    def __str__(self):
        return self.symbol

class Financials(models.Model):
    symbol = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='financials')
    report_date = models.DateField()
    total_revenue = models.BigIntegerField(null=True, blank=True)
    gross_profit = models.BigIntegerField(null=True, blank=True)
    operating_income = models.BigIntegerField(null=True, blank=True)
    net_income = models.BigIntegerField(null=True, blank=True)
    basic_eps = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)

class DailyPrice(models.Model):
    symbol = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='daily_prices')
    financial_id = models.ForeignKey(Financials, on_delete=models.SET_NULL, null=True, blank=True)
    trade_date = models.DateField()
    open_price = models.DecimalField(max_digits=12, decimal_places=4)
    high_price = models.DecimalField(max_digits=12, decimal_places=4)
    low_price = models.DecimalField(max_digits=12, decimal_places=4)
    close_price = models.DecimalField(max_digits=12, decimal_places=4)
    volume = models.BigIntegerField()

    class Meta:
        indexes = [
            models.Index(fields=['symbol', '-trade_date']),
            models.Index(fields=['trade_date']),
        ]


class GlobalSimulationState(models.Model):
    """
    Global control table to synchronize all users to the same virtual timeline.
    """
    current_global_date = models.DateField(default=timezone.now)
    is_market_open = models.BooleanField(default=True)
    last_step_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Global Simulation State"
        verbose_name_plural = "Global Simulation State"

    def __str__(self):
        return f"Global Virtual Date: {self.current_global_date}"
    

# ==========================================
# 3. Simulation & Portfolio
# ==========================================
class Simulation(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        CLOSED = 'CLOSED', 'Closed'

    class Mode(models.TextChoices):
        LIVE = 'LIVE', 'Live Multiplayer'  # Now implies the shared exchange mode
        BACKTEST = 'BACKTEST', 'Private Backtest'

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='simulations')
    name = models.CharField(max_length=100)
    start_date = models.DateField()
    
    # This now syncs with GlobalSimulationState.current_global_date for LIVE mode
    current_virtual_date = models.DateField(default=timezone.now)

    initial_cash = models.DecimalField(max_digits=20, decimal_places=4)
    available_cash = models.DecimalField(max_digits=20, decimal_places=4, default=ZERO)
    current_nav = models.DecimalField(max_digits=20, decimal_places=4, default=ZERO)
    
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    mode = models.CharField(max_length=10, choices=Mode.choices, default=Mode.LIVE)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def market_value(self):
        """
        Calculates total market value based on historical close prices 
        relative to the current_virtual_date.
        """
        # Logic to be handled in views or specific manager to ensure historical accuracy
        return ZERO 

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(available_cash__gte=0),
                name='simulation_cash_non_negative_v2'
            )
        ]


class TradeOrder(models.Model):
    """
    Order Book for peer-to-peer trading.
    """
    class OrderSide(models.TextChoices):
        BUY = 'BUY', 'Buy'
        SELL = 'SELL', 'Sell'

    class OrderStatus(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        PARTIAL = 'PARTIAL', 'Partially Filled'
        FILLED = 'FILLED', 'Filled'
        CANCELLED = 'CANCELLED', 'Cancelled'
        EXPIRED = 'EXPIRED', 'Expired'

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    sim = models.ForeignKey(Simulation, on_delete=models.CASCADE, related_name='orders')
    symbol = models.ForeignKey(Company, on_delete=models.CASCADE)
    
    side = models.CharField(max_length=10, choices=OrderSide.choices)
    price = models.DecimalField(max_digits=12, decimal_places=4)
    quantity = models.IntegerField()
    filled_quantity = models.IntegerField(default=0)
    
    status = models.CharField(max_length=10, choices=OrderStatus.choices, default=OrderStatus.PENDING)
    order_date = models.DateField() # The virtual date when the order was placed
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['symbol', 'status', 'side', 'price']),
        ]
# ==========================================
# 4. Trading & Auditing
# ==========================================
class Simulation_Transaction(models.Model):
    class TransType(models.TextChoices):
        BUY = 'BUY', 'Buy'
        SELL = 'SELL', 'Sell'

    sim = models.ForeignKey(Simulation, on_delete=models.CASCADE, related_name='transactions')
    symbol = models.ForeignKey(Company, on_delete=models.CASCADE)
    daily_price = models.ForeignKey(DailyPrice, on_delete=models.SET_NULL, null=True)
    trade_date = models.DateField()
    type = models.CharField(max_length=4, choices=TransType.choices)
    quantity = models.IntegerField()
    price = models.DecimalField(max_digits=12, decimal_places=4)
    total_amount = models.DecimalField(max_digits=20, decimal_places=4)
    created_at = models.DateTimeField(auto_now_add=True)
    matched_order = models.ForeignKey(TradeOrder, on_delete=models.SET_NULL, null=True, blank=True)
    opponent_order = models.ForeignKey(TradeOrder, on_delete=models.SET_NULL, null=True, related_name='counterpart_transactions')

    
class Simulation_Cash_Flow(models.Model):
    class FlowType(models.TextChoices):
        BUY = 'BUY', 'Purchase'
        SELL = 'SELL', 'Liquidation'
        FEE = 'FEE', 'Commission'
        INIT = 'INIT', 'Initial Deposit'

    sim = models.ForeignKey(Simulation, on_delete=models.CASCADE, related_name='cash_flows')
    change_type = models.CharField(max_length=10, choices=FlowType.choices)
    before_balance = models.DecimalField(max_digits=20, decimal_places=4)
    amount = models.DecimalField(max_digits=20, decimal_places=4) # Negative for Buy/Fee
    after_balance = models.DecimalField(max_digits=20, decimal_places=4)
    transaction = models.ForeignKey(Simulation_Transaction, on_delete=models.SET_NULL, null=True, blank=True)
    request_id = models.CharField(max_length=64, unique=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        if abs((self.before_balance + self.amount) - self.after_balance) > Decimal('0.0001'):
            raise ValidationError("Cash flow audit failed: balance mismatch.")

# ==========================================
# 5. Inventory & Snapshots
# ==========================================
class Simulation_Holding(models.Model):
    sim = models.ForeignKey(Simulation, on_delete=models.CASCADE, related_name='holdings')
    symbol = models.ForeignKey(Company, on_delete=models.CASCADE)
    quantity = models.IntegerField()
    avg_cost = models.DecimalField(max_digits=20, decimal_places=4)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['sim', 'symbol'], name='unique_holding_per_sim')
        ]
        indexes = [
            models.Index(fields=['sim', 'symbol']),
        ]

class Simulation_NAV_History(models.Model):
    sim = models.ForeignKey(Simulation, on_delete=models.CASCADE, related_name='nav_history')
    record_date = models.DateField()
    nav = models.DecimalField(max_digits=20, decimal_places=4)
    cash = models.DecimalField(max_digits=20, decimal_places=4)
    market_value = models.DecimalField(max_digits=20, decimal_places=4)
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self):
        
        return f"{self.sim.name} - {self.record_date}"