import os
import django
import random
from datetime import timedelta
from decimal import Decimal
from django.utils import timezone

# 1. Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'capstone.settings')
django.setup()

from stock.models import Simulation, Simulation_NAV_History, Company, Simulation_Holding

def simulate_monthly_data():
    """
    Simulates 30 days of portfolio history for the primary active simulation.
    """
    # 2. Get the target simulation (using your default naming convention)
    # Adjust the filter if you want to target a specific user
    target_sim = Simulation.objects.first()
    
    if not target_sim:
        print("Error: No simulation found. Please log in to the web app first to create one.")
        return

    print(f"Starting simulation for: {target_sim.name}")

    # 3. Clean up existing history to prevent duplicates
    Simulation_NAV_History.objects.filter(sim=target_sim).delete()

    current_date = timezone.now().date()
    start_balance = Decimal('100000.00')
    running_cash = start_balance * Decimal('0.4')  # Assume 40% cash
    running_market_value = start_balance * Decimal('0.6')  # Assume 60% invested
    
    # 4. Loop through the last 30 days
    for i in range(30, -1, -1):
        record_date = current_date - timedelta(days=i)
        
        # Simulate slight market fluctuations (-2% to +2.5% daily)
        fluctuation = Decimal(random.uniform(0.98, 1.025))
        running_market_value = (running_market_value * fluctuation).quantize(Decimal('0.01'))
        
        # Calculate daily NAV
        daily_nav = running_cash + running_market_value
        
        # Create history record
        Simulation_NAV_History.objects.create(
            sim=target_sim,
            record_date=record_date,
            nav=daily_nav,
            cash=running_cash,
            market_value=running_market_value
        )
        print(f"Generated data for {record_date}: NAV = ¥{daily_nav}")

    # 5. Update the main simulation object to match the last day
    target_sim.current_nav = daily_nav
    target_sim.save()
    
    print("\nSimulation complete! Refresh your dashboard to see the 30-day trend.")

if __name__ == "__main__":
    simulate_monthly_data()