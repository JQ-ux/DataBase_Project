from django.contrib import admin

# Register your models here.
from django.contrib import admin
from .models import (
    User, Company, Financials, DailyPrice, 
    Simulation, Simulation_Transaction, 
    Simulation_NAV_History, Simulation_Holding
)

@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ('symbol', 'full_name', 'current_price', 'market_cap')
    search_fields = ('symbol', 'full_name')

@admin.register(DailyPrice)
class DailyPriceAdmin(admin.ModelAdmin):
    list_display = ('symbol', 'trade_date', 'close_price', 'volume')
    list_filter = ('symbol', 'trade_date')
    
    search_fields = ('symbol__symbol',)

admin.site.register(User)
admin.site.register(Financials)
admin.site.register(Simulation)
admin.site.register(Simulation_Transaction)
admin.site.register(Simulation_NAV_History)
admin.site.register(Simulation_Holding)