from django.shortcuts import render, HttpResponseRedirect
from django.urls import reverse
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q, F, Sum
from django.utils import timezone

import json
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from .models import *

# ==========================================
# GLOBAL SETTINGS & PRECISION CONSTANTS
# ==========================================
SEARCH_LIMIT = 20
INITIAL_BALANCE = Decimal('100000.00')
PRECISION_4 = Decimal('0.0001')
PRECISION_2 = Decimal('0.01')
COMMISSION_RATE = Decimal('0.0003') # 0.03% Transaction Fee

def quantize_4(value):
    return Decimal(value).quantize(PRECISION_4, rounding=ROUND_HALF_UP)

# ==========================================
# 1. ROBUST MARKET DATA ENGINE
# ==========================================

def get_market_price(symbol_obj, target_date):
    """
    Finds the most recent closing price on or before target_date.
    Handles weekends, holidays, and market suspensions.
    """
    try:
        price_record = DailyPrice.objects.filter(
            symbol=symbol_obj,
            trade_date__lte=target_date
        ).latest('trade_date')
        return price_record
    except DailyPrice.DoesNotExist:
        return None

def calculate_nav_optimized(sim, target_date):
    """
    Core NAV Engine:
    NAV = User Cash (account_balance) + Sum(Holding_Quantity * Market_Price)
    This ensures that NAV reflects the absolute liquidation value at target_date.
    """
    # 1. Start with the actual cash in the user's account
    current_cash = sim.user.account_balance 
    
    # 2. Identify all active holdings (where quantity > 0)
    holdings = Simulation_Holding.objects.filter(sim=sim).exclude(quantity=0)
    total_market_value = Decimal('0.00')
    
    if holdings.exists():
        for hold in holdings:
            # Get price from history or fallback to the real-time price
            price_rec = get_market_price(hold.symbol, target_date)
            exec_price = price_rec.close_price if price_rec else hold.symbol.current_price
            
            # Use quantize_4 to maintain consistency with precision settings
            total_market_value += quantize_4(hold.quantity * exec_price)
            
    # Returns (Total NAV, Total Market Value)
    return current_cash + total_market_value, total_market_value

# ==========================================
# 2. AUTHENTICATION & IDENTITY (ER: Stock_User)
# ==========================================

def register_view(request):
    if request.method == "POST":
        d = request.POST
        if d['password'] != d['confirmation']:
            return render(request, "stock/register.html", {"message": "Passwords mismatch."})
        
        try:
            with transaction.atomic():
                # 1. Create the User
                user = User.objects.create_user(d['username'], d['email'], d['password'])
                user.first_name = d.get('firstname', '')
                user.last_name = d.get('lastname', '')
                user.gender = d.get('gender', 'Other')
                user.account_balance = INITIAL_BALANCE
                user.save()
                
                # 2. Create the Simulation and assign it to 'new_sim'
                new_sim = Simulation.objects.create(
                    user=user,
                    name=f"Standard Alpha Strategy - {user.username}",
                    start_date=timezone.now().date(),
                    initial_cash=INITIAL_BALANCE,
                    current_nav=INITIAL_BALANCE
                )

                # 3. Create the initial NAV history entry (The starting point of the chart)
                Simulation_NAV_History.objects.create(
                    sim=new_sim,
                    record_date=new_sim.start_date,
                    nav=INITIAL_BALANCE,
                    cash=INITIAL_BALANCE,
                    market_value=Decimal('0.00')
                )

            login(request, user)
            return HttpResponseRedirect(reverse("index"))
        except Exception as e:
            return render(request, "stock/register.html", {"message": str(e)})
    return render(request, "stock/register.html")

def login_view(request):
    if request.method == "POST":
        u, p = request.POST.get("username"), request.POST.get("password")
        user = authenticate(request, username=u, password=p)
        if user:
            login(request, user)
            return HttpResponseRedirect(reverse("index"))
        return render(request, "stock/login.html", {"message": "Access Denied."})
    return render(request, "stock/login.html")

@login_required
def logout_view(request):
    logout(request)
    return HttpResponseRedirect(reverse("login"))

# ==========================================
# 3. MARKET EXPLORER (ER: Company, Financials)
# ==========================================

@login_required
def index(request):
    """
    Dashboard view showing user's simulations, market context, and performance metrics.
    Includes NAV history for visualization and pre-calculated portfolio stats.
    """
    # 1. Fetch all simulations for the current user
    user_sims = Simulation.objects.filter(user=request.user).order_by('-created_at')
    
    # 2. Automatically create a default simulation if none exists
    if not user_sims.exists():
        new_sim = Simulation.objects.create(
            user=request.user,
            name=f"Standard Alpha Strategy - {request.user.username}",
            start_date=timezone.now().date(),
            initial_cash=INITIAL_BALANCE,
            current_nav=INITIAL_BALANCE
        )
        # Create the initial anchor point for the NAV line chart
        Simulation_NAV_History.objects.create(
            sim=new_sim, 
            record_date=new_sim.start_date,
            nav=INITIAL_BALANCE, 
            cash=INITIAL_BALANCE, 
            market_value=Decimal('0.00')
        )
        user_sims = Simulation.objects.filter(user=request.user).order_by('-created_at')

    # Identify the primary active simulation
    active_sim = user_sims.first() 
    
    # 3. Fetch NAV history data for the performance chart
    nav_history_qs = Simulation_NAV_History.objects.filter(sim=active_sim).order_by('record_date')
    
    # Prepare data for Chart.js
    chart_labels = [record.record_date.strftime("%m-%d") for record in nav_history_qs]
    chart_data = [float(record.nav) for record in nav_history_qs]

    # 4. Fetch additional dashboard components with database-level calculation
    # Using annotate to avoid 'multiply' filter errors in template
    user_holdings = Simulation_Holding.objects.filter(
        sim=active_sim
    ).exclude(quantity=0).select_related('symbol').annotate(
        market_value=F('quantity') * F('symbol__current_price')
    )

    recent_actions = Simulation_Transaction.objects.filter(sim=active_sim).order_by('-created_at')[:5]
    top_movers = Company.objects.all().order_by('-market_cap')[:SEARCH_LIMIT]
    
    # 5. Calculate real-time profit metrics
    total_profit = active_sim.current_nav - active_sim.initial_cash
    profit_rate = (total_profit / active_sim.initial_cash * 100) if active_sim.initial_cash else 0
    
    return render(request, "stock/index.html", {
        "simulations": user_sims,
        "companies": top_movers,
        "holdings": user_holdings,
        "transactions": recent_actions,
        "sim": active_sim,
        "total_profit": total_profit,
        "profit_rate": round(profit_rate, 2),
        "chart_labels_json": json.dumps(chart_labels),
        "chart_data_json": json.dumps(chart_data),
    })

def api_search(request):
    """Fast search API with query limit for UI responsiveness."""
    term = request.GET.get('q', '').strip().upper()
    if len(term) < 1: return JsonResponse([], safe=False)
    
    matches = Company.objects.filter(
        Q(symbol__icontains=term) | Q(full_name__icontains=term)
    )[:SEARCH_LIMIT]
    
    results = [{
        "symbol": m.symbol, 
        "name": m.full_name, 
        "price": str(m.current_price),
        "pe": str(m.trailing_pe)
    } for m in matches]
    return JsonResponse(results, safe=False)



# ==========================================

# 4. TRADING CORE (ER: Transactions, Holdings)

# ==========================================
@csrf_exempt
@login_required
def process_transaction(request):
    """
    High-integrity transaction handler.
    Ensures synchronization between User balance and Simulation cash.
    """
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    try:
        # 1. Parse payload
        if request.content_type == 'application/json':
            payload = json.loads(request.body)
            date_str = payload.get('date')
        else:
            payload = request.POST
            date_str = None

        sim_id = payload.get('sim_id')
        if not sim_id:
            active_sim = Simulation.objects.filter(user=request.user).order_by('-created_at').first()
            if not active_sim:
                return JsonResponse({"success": False, "error": "No active simulation found."})
            sim_id = active_sim.id
        symbol = payload.get('symbol')
        qty = int(payload.get('quantity', 0))
        side = payload.get('type', payload.get('side', '')).upper()
        date_obj = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else timezone.now().date()

        if side not in ['BUY', 'SELL'] or qty <= 0:
            return JsonResponse({"success": False, "error": "Invalid trade parameters."})

        with transaction.atomic():
            # 1. Lock both Simulation AND User records to prevent any data overwrite
            sim = Simulation.objects.select_for_update().get(id=sim_id, user=request.user)
            # Fetch the user instance again with a lock to ensure we are modifying the latest DB state
            user = User.objects.select_for_update().get(id=request.user.id)
            
            company = Company.objects.get(symbol=symbol)

            if sim.current_nav is None:
                sim.current_nav = sim.initial_cash

            price_rec = get_market_price(company, date_obj)
            exec_price = price_rec.close_price if price_rec else company.current_price
            
            subtotal = exec_price * qty
            fee = quantize_4(subtotal * COMMISSION_RATE)
            total_cost = (subtotal + fee) if side == 'BUY' else (subtotal - fee)

            if side == "BUY":
                if user.account_balance < total_cost:
                    return JsonResponse({"success": False, "error": "Insufficient funds."})
                
                # Update local values
                user.account_balance -= total_cost
                sim.current_nav -= total_cost
                
                holding, created = Simulation_Holding.objects.get_or_create(
                    sim=sim, symbol=company,
                    defaults={'quantity': 0, 'avg_cost': Decimal('0.00')}
                )
                new_total_qty = holding.quantity + qty
                holding.avg_cost = quantize_4(((holding.quantity * holding.avg_cost) + subtotal) / new_total_qty)
                holding.quantity = new_total_qty
                holding.save()

            elif side == "SELL":
                holding = Simulation_Holding.objects.filter(sim=sim, symbol=company).first()

                if not holding:
                    return JsonResponse({"success": False, "error": "No holdings."})
                if holding.quantity < qty:
                    return JsonResponse({"success": False, "error": "Not enough shares."})

                user.account_balance += total_cost
                sim.current_nav += total_cost
                holding.quantity -= qty
                if holding.quantity == 0:
                    holding.delete()
                else:
                    holding.save()

            # 2. SAVE ORDER: Save user first, then link it back to sim, then save sim
            user.save()
            
            print(f"DEBUG SQL: User ID {user.id} balance saved as {user.account_balance}")
            
            # Check if this object is actually updated in memory
            check_user = User.objects.get(id=user.id)
            print(f"DEBUG DB: Re-fetched User {check_user.username} balance is {check_user.account_balance}")
            sim.user = user # Explicitly re-link to avoid simulation overwriting user with old state
            sim.save()

            

            # 7. Create transaction log
            Simulation_Transaction.objects.create(
                sim=sim, symbol=company, daily_price=price_rec,
                trade_date=date_obj, type=side, quantity=qty,
                price=exec_price, total_amount=total_cost
            )

            # ==========================================
            # FINAL FIX STEP 8: Atomic Daily Snapshot
            # ==========================================
            total_nav, market_val = calculate_nav_optimized(sim, date_obj)

         
            Simulation_NAV_History.objects.filter(
                sim=sim, 
                record_date=date_obj
            ).delete()

      
            Simulation_NAV_History.objects.create(
                sim=sim,
                record_date=date_obj,
                nav=total_nav,
                cash=user.account_balance,
                market_value=market_val
            )


            sim.current_nav = total_nav
            sim.save()
            # 9. Return Response
            if request.content_type == 'application/json':
                return JsonResponse({
                    "success": True, 
                    "new_cash": str(sim.current_nav),
                    "total_user_balance": str(user.account_balance)
                })
            else:
                # Use symbol to stay on the same company detail page
                return HttpResponseRedirect(reverse("stock_detail", args=[symbol]))

    except Exception as e:
        # Print to console for debugging
        print(f"CRITICAL ERROR in process_transaction: {str(e)}")
        import traceback
        traceback.print_exc()
        
        return JsonResponse({
            "success": False, 
            "error": str(e),
            "detail": "Check server console for traceback"
        }, status=500)

# ==========================================
# 5. ANALYSIS & REPORTING
# ==========================================

@login_required
def company_financials(request, symbol):
    """Deep fundamental data extraction for analysis."""
    company = Company.objects.get(symbol=symbol)
    # Using ER Financials fields
    fin_list = Financials.objects.filter(symbol=company).order_by('-report_date')
    
    reports = []
    for f in fin_list:
        # Calculate Margin on-the-fly (Industrial standard: avoid storing derived fields)
        net_margin = (f.net_income / f.total_revenue * 100) if f.total_revenue else 0
        reports.append({
            "date": f.report_date,
            "revenue": f.total_revenue,
            "income": f.net_income,
            "margin": round(net_margin, 2),
            "eps": f.basic_eps
        })

    return render(request, "stock/financials.html", {
        "stock": company,
        "reports": reports
    })

@login_required
def simulation_performance(request, sim_id):
    """Generates a performance report for a specific simulation."""
    sim = Simulation.objects.get(id=sim_id, user=request.user)
    current_date = timezone.now().date()
    
    # Get current state
    total_nav, mkt_val = calculate_nav_optimized(sim, current_date)
    holdings = Simulation_Holding.objects.filter(sim=sim).annotate(
        current_market_value=F('quantity') * F('symbol__current_price')
    )
    
    # Performance Metric
    profit_loss = total_nav - sim.initial_cash
    roi = (profit_loss / sim.initial_cash * 100)
    
    history = Simulation_NAV_History.objects.filter(sim=sim).order_by('record_date')
    
    return render(request, "stock/report.html", {
        "sim": sim,
        "holdings": holdings,
        "nav_history": history,
        "stats": {
            "roi": round(roi, 2),
            "total_nav": total_nav,
            "cash": sim.current_nav
        }
    })

@login_required
def stock_detail(request, symbol):
    """
    Stock Detail View: Displays financial reports, historical price trends, 
    and the user's current holdings for a specific company.
    """
    from django.shortcuts import get_object_or_404
    
    # 1. Fetch company basic info (Returns 404 if symbol not found)
    company = get_object_or_404(Company, symbol=symbol)
    
    # 2. Fetch all financial reports for this company, ordered by date descending
    financial_reports = Financials.objects.filter(symbol=company).order_by('-report_date')
    
    # 3. Fetch price history (latest 30 trading days)
    price_history = DailyPrice.objects.filter(symbol=company).order_by('-trade_date')[:30]
    
    # 4. Get the active simulation account for the current user
    active_sim = Simulation.objects.filter(user=request.user).order_by('-created_at').first()
    
    # 5. Check if the user currently holds this stock in the active simulation
    user_holding = None
    if active_sim:
        user_holding = Simulation_Holding.objects.filter(sim=active_sim, symbol=company).first()
    
    return render(request, "stock/detail.html", {
        "company": company,
        "financials": financial_reports,
        "history": price_history,
        "holding": user_holding,
        "sim": active_sim
    })

@login_required
def stock_history_full(request, symbol):
    """
    Dedicated view for historical price data.
    Provides a deep dive into price movements beyond the summary.
    """
    from django.shortcuts import get_object_or_404
    # 1. Fetch company or 404
    company = get_object_or_404(Company, symbol=symbol)
    
    # 2. Fetch extended price history (e.g., last 100 entries)
    # You can adjust the slicing [:100] based on how much data you want to show
    price_history = DailyPrice.objects.filter(symbol=company).order_by('-trade_date')[:100]
    
    # 3. Get simulation context for the sidebar navigation
    active_sim = Simulation.objects.filter(user=request.user).order_by('-created_at').first()

    return render(request, "stock/history_page.html", {
        "company": company,
        "history": price_history,
        "sim": active_sim
    })

@login_required
def portfolio_view(request):
    """
    Enhanced portfolio view that pre-calculates performance metrics
    to avoid complex logic in Django templates.
    """
    active_sim = Simulation.objects.filter(user=request.user).order_by('-created_at').first()
    
    # Initialize default stats for context
    stats = {
        "profit_amount": Decimal('0.00'),
        "profit_rate": Decimal('0.00'),
    }
    user_holdings = []

    if active_sim:
        # 1. Use annotate to calculate market value (qty * price) for each holding in the database
        user_holdings = Simulation_Holding.objects.filter(
            sim=active_sim
        ).exclude(quantity=0).annotate(
            market_value=F('quantity') * F('symbol__current_price')
        )

        # 2. Calculate aggregate performance metrics
        # Profit Amount = Current NAV - Initial Cash
        stats["profit_amount"] = active_sim.current_nav - active_sim.initial_cash
        
        # Profit Rate = (Profit / Initial Cash) * 100
        if active_sim.initial_cash > 0:
            stats["profit_rate"] = (stats["profit_amount"] / active_sim.initial_cash) * 100

    return render(request, "stock/portfolio.html", {
        "holdings": user_holdings,
        "sim": active_sim,
        "stats": stats  # Pre-calculated results passed to template
    })

@login_required
def transactions_view(request):
    """
    View to display the full transaction history for the active simulation.
    Uses select_related to optimize database performance for joined tables.
    """
    active_sim = Simulation.objects.filter(user=request.user).order_by('-created_at').first()
    recent_actions = []
    
    if active_sim:
        # We use select_related('symbol') to pre-fetch company names 
        # and avoid the N+1 query problem in the template.
        recent_actions = Simulation_Transaction.objects.filter(
            sim=active_sim
        ).select_related('symbol').order_by('-trade_date', '-created_at')
    
    return render(request, "stock/transactions.html", {
        "transactions": recent_actions,
        "sim": active_sim
    })