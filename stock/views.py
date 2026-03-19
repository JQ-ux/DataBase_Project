from django.shortcuts import render, HttpResponseRedirect
from django.urls import reverse
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q, F, Sum
from django.utils import timezone
from .models import Company
import json
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from .models import *
from django.db.models import  OuterRef, Subquery, DecimalField
from django.db import transaction
# ==========================================
# GLOBAL SETTINGS & PRECISION CONSTANTS
# ==========================================
ZERO = Decimal('0.0000')
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
            trade_date__lt=target_date
        ).latest('trade_date')
        return price_record
    except DailyPrice.DoesNotExist:
        return None


def calculate_nav_optimized(sim, target_date):
    """
    Production-grade NAV calculation optimized for RDBMS.
    Formula: Available Cash + Frozen Buying Cash + Current Market Value
    
    This implementation replaces Python loops with Database Aggregations.
    """
    
    # --- 1. Subquery: Get the latest close price for each symbol before target_date ---
    # This prevents loading thousands of historical price rows into memory.
    latest_price_subquery = DailyPrice.objects.filter(
        symbol=OuterRef('symbol'),
        trade_date__lt=target_date
    ).order_by('-trade_date').values('close_price')[:1]

    # --- 2. Calculate Frozen Cash (Unfilled Buy Orders) ---
    # Summing (price * remaining_qty) directly in the database.
    # We ignore COMMISSION_RATE here for simplicity, or add it if strictly required.
    frozen_data = TradeOrder.objects.filter(
        sim=sim,
        side='BUY',
        status__in=['PENDING', 'PARTIAL']
    ).aggregate(
        total_frozen=Sum(
            F('price') * (F('quantity') - F('filled_quantity')),
            output_field=DecimalField()
        )
    )
    frozen_cash = frozen_data['total_frozen'] or Decimal('0.0000')

    # --- 3. Calculate Market Value (Existing Holdings) ---
    # Annotate each holding with the latest price from subquery, then aggregate.
    holding_data = sim.holdings.exclude(quantity=0).annotate(
        latest_price=Subquery(latest_price_subquery, output_field=DecimalField())
    ).aggregate(
        total_mkt_val=Sum(
            F('quantity') * F('latest_price'),
            output_field=DecimalField()
        )
    )
    holdings_market_value = holding_data['total_mkt_val'] or Decimal('0.0000')

    # --- 4. Calculate Market Value (Locked in Sell Orders) ---
    # Shares locked in sell orders are still assets owned by the user.
    sell_order_data = TradeOrder.objects.filter(
        sim=sim,
        side='SELL',
        status__in=['PENDING', 'PARTIAL']
    ).annotate(
        latest_price=Subquery(latest_price_subquery, output_field=DecimalField())
    ).aggregate(
        frozen_mkt_val=Sum(
            (F('quantity') - F('filled_quantity')) * F('latest_price'),
            output_field=DecimalField()
        )
    )
    frozen_shares_market_value = sell_order_data['frozen_mkt_val'] or Decimal('0.0000')

    # --- 5. Final Aggregation ---
    total_market_value = holdings_market_value + frozen_shares_market_value
    total_nav = sim.available_cash + frozen_cash + total_market_value

    # Returns exactly what the frontend needs
    return total_nav, total_market_value

# Helper to ensure 4 decimal places for financial calculations
def quantize_4(val):
    return val.quantize(Decimal('0.0001'))

# ==========================================
# 2. AUTHENTICATION & IDENTITY (ER: Stock_User)
# ==========================================

def register_view(request):
    """
    Handles user registration and initializes a default trading simulation.
    Synchronizes the new user's virtual clock with the Global Master Clock.
    """
    if request.method == "POST":
        d = request.POST
        if d['password'] != d['confirmation']:
            return render(request, "stock/register.html", {"message": "Passwords mismatch."})
        
        try:
            with transaction.atomic():
                # 1. Fetch Global Simulation State to sync the start date
                global_state = GlobalSimulationState.objects.select_for_update().first()
                if not global_state:
                    # Emergency initialization if global state is missing
                    initial_date = datetime.strptime("2026-03-02", "%Y-%m-%d").date()
                    global_state = GlobalSimulationState.objects.create(
                        current_global_date=initial_date,
                        is_market_open=True
                    )
                
                # The "Time Machine" entry point for this user
                shared_virtual_date = global_state.current_global_date

                # 2. Create the User profile
                user = User.objects.create_user(d['username'], d['email'], d['password'])
                user.first_name = d.get('firstname', '')
                user.last_name = d.get('lastname', '')
                user.gender = d.get('gender', 'Other')
                user.account_balance = INITIAL_BALANCE
                user.save()
                
                # 3. Create the Simulation instance synced to Global Clock
                new_sim = Simulation.objects.create(
                    user=user,
                    name=f"Standard Alpha Strategy - {user.username}",
                    start_date=shared_virtual_date,
                    current_virtual_date=shared_virtual_date,
                    initial_cash=INITIAL_BALANCE,
                    available_cash=INITIAL_BALANCE,
                    current_nav=INITIAL_BALANCE
                )

                # 4. Create the initial NAV history entry for the shared start date
                Simulation_NAV_History.objects.create(
                    sim=new_sim,
                    record_date=shared_virtual_date,
                    nav=INITIAL_BALANCE,
                    cash=INITIAL_BALANCE,
                    market_value=Decimal('0.00')
                )

            login(request, user)
            return HttpResponseRedirect(reverse("index"))
            
        except Exception as e:
            # It's better to log the exception here for debugging
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
    Dashboard view for the multiplayer trading simulation.
    Synchronizes all users to a shared virtual timeline via GlobalSimulationState.
    """
    # 1. Fetch or Initialize Global Simulation State (The Master Clock)
    global_state = GlobalSimulationState.objects.first()
    if not global_state:
        return HttpResponse("系统错误：请联系管理员初始化全局时钟。")
    
    virtual_today = global_state.current_global_date
    if not global_state:
        # Emergency fallback if no state exists in DB
        initial_date = datetime.strptime("2026-03-02", "%Y-%m-%d").date()
        global_state = GlobalSimulationState.objects.create(
            current_global_date=initial_date,
            is_market_open=True
        )
    
    virtual_today = global_state.current_global_date

    # 2. Fetch the primary simulation account for the current user
    user_sims = Simulation.objects.filter(user=request.user).order_by('-created_at')
    active_sim = user_sims.first()
    
    # 3. Lazy Initialization: Create a simulation if none exists
    if not active_sim:
        active_sim = Simulation.objects.create(
            user=request.user,
            name=f"Alpha Strategy - {request.user.username}",
            start_date=virtual_today,
            current_virtual_date=virtual_today, # Sync with global clock
            initial_cash=INITIAL_BALANCE,
            available_cash=INITIAL_BALANCE,
            current_nav=INITIAL_BALANCE
        )
        # Create the initial record for the performance chart
        Simulation_NAV_History.objects.create(
            sim=active_sim, 
            record_date=virtual_today,
            nav=INITIAL_BALANCE, 
            cash=INITIAL_BALANCE, 
            market_value=Decimal('0.00')
        )

    # 4. Market Explorer Logic: Fetch industries and filter companies
    all_industries = Industry.objects.all()
    selected_industry_id = request.GET.get('industry')
    query = request.GET.get('q', '').strip()

    # Start with all companies
    companies_qs = Company.objects.all()

    # Apply Industry filter if selected
    if selected_industry_id:
        companies_qs = companies_qs.filter(industry_id=selected_industry_id)

    # Apply Search query if exists
    if query:
        companies_qs = companies_qs.filter(
            Q(symbol__icontains=query) | Q(full_name__icontains=query)
        )

    # Slice to top 10 and process prices based on virtual timeline
    popular_companies = companies_qs[:10]
    processed_stocks = []
    
    for comp in popular_companies:
        price_rec = DailyPrice.objects.filter(
            symbol=comp,
            trade_date__lt=virtual_today
        ).order_by('-trade_date').first()
        
        if price_rec:
            processed_stocks.append({
                "symbol": comp.symbol,
                "name": comp.full_name,
                "price": price_rec.close_price,
            })
    # 5. Portfolio Accounting: Calculate NAV and Current Holdings
    # This now uses the global virtual_today for consistent valuation
    total_nav, total_mkt_val = calculate_nav_optimized(active_sim, virtual_today)
    
    raw_holdings = Simulation_Holding.objects.filter(sim=active_sim).exclude(quantity=0).select_related('symbol')
    processed_holdings = []
    
    for h in raw_holdings:
        price_rec = get_market_price(h.symbol, virtual_today)
        exec_price = price_rec.close_price if price_rec else h.symbol.current_price
        
        processed_holdings.append({
            "symbol": h.symbol,
            "quantity": h.quantity,
            "avg_cost": h.avg_cost,
            "current_price": exec_price,
            "market_value": quantize_4(h.quantity * exec_price),
            "calc_pnl": quantize_4((exec_price - h.avg_cost) * h.quantity)
        })

    # 6. Data Visualization: Prepare labels and datasets for Chart.js
    nav_history_qs = Simulation_NAV_History.objects.filter(sim=active_sim,record_date__gte="2026-02-12",record_date__lte=virtual_today).order_by('record_date')
    chart_labels = [record.record_date.strftime("%m-%d") for record in nav_history_qs]
    chart_data = [float(record.nav) for record in nav_history_qs]
    recent_transactions = Simulation_Transaction.objects.filter(sim=active_sim).order_by('-trade_date', '-created_at')[:5]


    # 7. Render Response with full context
    context = {
        "sim": active_sim,
        "holdings": processed_holdings,
        "popular_stocks": processed_stocks,
        "industries": all_industries,               
        "current_industry": selected_industry_id,
        "total_profit": total_nav - active_sim.initial_cash,
        "profit_rate": round(((total_nav - active_sim.initial_cash) / active_sim.initial_cash * 100), 2),
        "chart_labels_json": json.dumps(chart_labels),
        "chart_data_json": json.dumps(chart_data),
        "virtual_today": virtual_today, # Passed from global state
        "is_market_open": global_state.is_market_open,
        "recent_transactions": recent_transactions,
    }
    
    return render(request, "stock/index.html", context)


def api_search_companies(request):
    query = request.GET.get('q', '').strip()
    if len(query) < 1:
        return JsonResponse({'results': []})
    
    
    companies = Company.objects.filter(
        Q(symbol__icontains=query) | Q(full_name__icontains=query)
    )[:5]
    
    results = []
    for c in companies:
        results.append({
            'symbol': c.symbol,
            'full_name': c.full_name,
        })
    
    return JsonResponse({'results': results})

def api_search(request):
    """
    Fast search API synchronized with the GLOBAL virtual simulation date.
    Ensures all users see the same market prices regardless of their individual sim state.
    """
    term = request.GET.get('q', '').strip().upper()
    if len(term) < 1: 
        return JsonResponse([], safe=False)
    
    # 1. Get the GLOBAL simulation date (The Master Clock)
    global_state = GlobalSimulationState.objects.first()
    if global_state:
        reference_date = global_state.current_global_date
    else:
        # Fallback to a safe date if global state isn't initialized
        return JsonResponse({"error": "Global state missing"}, status=500)

    # 2. Find matching companies
    matches = Company.objects.filter(
        Q(symbol__icontains=term) | Q(full_name__icontains=term)
    )[:SEARCH_LIMIT]
    
    results = []
    for m in matches:
        # 3. Fetch historical price based on the GLOBAL reference date
        price_rec = DailyPrice.objects.filter(
            symbol=m,
            trade_date__lt=reference_date 
        ).order_by('-trade_date').first()
        
        # If no price exists for this company at this point in time, skip it
        if not price_rec:
            continue 

        results.append({
            "symbol": m.symbol, 
            "name": m.full_name, 
            "price": str(price_rec.close_price),
            "pe": str(m.trailing_pe)
        })
        
    return JsonResponse({"results": results})



# ==========================================

# 4. TRADING CORE (ER: Transactions, Holdings)

# ==========================================
@csrf_exempt
@login_required
def process_transaction(request):
    """
    Refactored Transaction Handler for Peer-to-Peer Trading.
    Directly deducts assets (freezing) and creates a PENDING TradeOrder.
    """
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    try:
        # 1. Parse payload
        if request.content_type == 'application/json':
            payload = json.loads(request.body)
        else:
            payload = request.POST

        sim_id = payload.get('sim_id')
        symbol = payload.get('symbol')
        qty = int(payload.get('quantity', 0))
        side = payload.get('type', payload.get('side', '')).upper()
        order_price = Decimal(payload.get('price', '0.0000'))
        request_id = payload.get('request_id')

        if not sim_id or side not in ['BUY', 'SELL'] or qty <= 0 or order_price <= 0:
            return JsonResponse({"success": False, "error": "Invalid parameters or price."})

        with transaction.atomic():
            # 2. Check Global Market State
            global_state = GlobalSimulationState.objects.select_for_update().first()
            if not global_state or not global_state.is_market_open:
                return JsonResponse({"success": False, "error": "Market is currently closed."})
            
            virtual_today = global_state.current_global_date

            # 3. Lock Simulation record
            sim = Simulation.objects.select_for_update().filter(
                id=sim_id, 
                user=request.user, 
                status='ACTIVE'
            ).first()

            if not sim:
                return JsonResponse({"success": False, "error": "Active simulation not found."})

            # 4. Idempotency Check
            if request_id and TradeOrder.objects.filter(id=request_id).exists():
                return JsonResponse({"success": True, "message": "Order already placed."})

            company = Company.objects.get(symbol=symbol)

            # 5. God's Price Boundary Validation (Refined for P2P Visibility)
            # Use TODAY'S real market boundaries to ensure the order is physically possible.
            today_price_rec = DailyPrice.objects.filter(
                symbol=company, 
                trade_date=virtual_today  # Use the actual simulation date
            ).first()
            
            if today_price_rec:
                # If buying, the order price must be at least the day's LOW to have any chance of filling.
                if side == "BUY" and order_price < today_price_rec.low_price:
                    return JsonResponse({
                        "success": False, 
                        "error": f"Order price {order_price} is below today's market low ({today_price_rec.low_price}). Adjust your bid."
                    })
                
                # If selling, the order price must be at most the day's HIGH to have any chance of filling.
                if side == "SELL" and order_price > today_price_rec.high_price:
                    return JsonResponse({
                        "success": False, 
                        "error": f"Order price {order_price} is above today's market high ({today_price_rec.high_price}). Adjust your ask."
                    })
            else:
                # Fallback: If no price record exists for today yet, block to prevent blind trading.
                return JsonResponse({
                    "success": False, 
                    "error": "Market data for today is not yet synchronized. Please try again later."
                })
            
            # 6. Asset Freezing (Deduction)
            subtotal = order_price * qty
            estimated_fee = quantize_4(subtotal * COMMISSION_RATE)
            avg_cost_at_order = ZERO

            if side == "BUY":
                total_required = subtotal + estimated_fee
                if sim.available_cash < total_required:
                    return JsonResponse({"success": False, "error": "Insufficient cash."})
                
                # Deduct cash immediately
                sim.available_cash -= total_required
                sim.save()

            elif side == "SELL":
                holding = Simulation_Holding.objects.filter(sim=sim, symbol=company).first()
                if not holding or holding.quantity < qty:
                    return JsonResponse({"success": False, "error": "Insufficient shares."})
                avg_cost_at_order = holding.avg_cost

                # Deduct shares immediately
                holding.quantity -= qty
                if holding.quantity == 0:
                    holding.delete()
                else:
                    holding.save()

            # 7. Create the PENDING Order
            new_order = TradeOrder.objects.create(
                user=request.user,
                sim=sim,
                symbol=company,
                side=side,
                price=order_price,
                quantity=qty,
                filled_quantity=0,
                status=TradeOrder.OrderStatus.PENDING,
                order_date=virtual_today,
                avg_cost_snapshot=avg_cost_at_order if side == "SELL" else ZERO
            )

            # 8. Log Cash Flow (For Buyer Only)
            if side == 'BUY':
                Simulation_Cash_Flow.objects.create(
                    sim=sim,
                    request_id=f"FREEZE_{new_order.id}",
                    change_type='FEE',
                    before_balance=sim.available_cash + total_required,
                    amount=-total_required,
                    after_balance=sim.available_cash
                )

            return JsonResponse({
                "success": True,
                "message": f"Order for {symbol} placed.",
                "order_id": new_order.id,
                "available_cash": str(sim.available_cash)
            })

    except Company.DoesNotExist:
        return JsonResponse({"success": False, "error": "Company not found."}, status=404)
    except Exception as e:
        print(f"Error: {str(e)}")
        return JsonResponse({"success": False, "error": "Order failed."}, status=500)


@csrf_exempt
@login_required
def cancel_order(request):
    """
    Cancels a PENDING or PARTIAL trade order and releases REMAINING frozen assets.
    """
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    try:
        payload = json.loads(request.body) if request.content_type == 'application/json' else request.POST
        order_id = payload.get('order_id')

        if not order_id:
            return JsonResponse({"success": False, "error": "Order ID is required."})

        with transaction.atomic():
            # 1. Lock the order and verify ownership. 
            # Crucial: Allow cancellation for both PENDING and PARTIAL.
            order = TradeOrder.objects.select_for_update().filter(
                id=order_id,
                user=request.user,
                status__in=[TradeOrder.OrderStatus.PENDING, TradeOrder.OrderStatus.PARTIAL]
            ).first()

            if not order:
                return JsonResponse({"success": False, "error": "Order not found or cannot be cancelled."})

            sim = order.sim
            # Calculate what is left to be returned
            remaining_qty = order.quantity - order.filled_quantity
            
            if remaining_qty <= 0:
                return JsonResponse({"success": False, "error": "Order is already fully filled."})

            # 2. Asset Release Logic (Only for the remaining portion)
            if order.side == 'BUY':
                # Refund only the part that hasn't been spent
                subtotal = order.price * remaining_qty
                estimated_fee = quantize_4(subtotal * COMMISSION_RATE)
                refund_amount = subtotal + estimated_fee
                
                sim.available_cash += refund_amount
                sim.save()

            elif order.side == 'SELL':
                # Return only the remaining shares to the Simulation_Holding
                holding, created = Simulation_Holding.objects.get_or_create(
                    sim=sim,
                    symbol=order.symbol,
                    defaults={'quantity': 0, 'avg_cost': order.price}
                )
                holding.quantity += remaining_qty
                holding.save()

            # 3. Update Order Status
            order.status = TradeOrder.OrderStatus.CANCELLED
            order.save()

            return JsonResponse({
                "success": True, 
                "message": f"Order {order_id} cancelled. {remaining_qty} shares released.",
                "available_cash": str(sim.available_cash)
            })

    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=500)


def internal_matching_engine(execution_date):
    """
    Core matching engine:
    Processes peer-to-peer matching between users within market High/Low boundaries.
    """
    # 1. Fetch all unique symbols that have pending or partially filled orders
    active_symbols = TradeOrder.objects.filter(
        status__in=[TradeOrder.OrderStatus.PENDING, TradeOrder.OrderStatus.PARTIAL]
    ).values_list('symbol', flat=True).distinct()

    match_count = 0

    for symbol_id in active_symbols:
        # 2. God's boundary check: retrieve market performance for the execution date
        price_rec = DailyPrice.objects.filter(
            symbol_id=symbol_id, 
            trade_date=execution_date
        ).first()
        
        if not price_rec:
            continue 

        # 3. Build the Order Book for this symbol (Strictly within God's boundaries)
        # Buy Side: Price Priority. Order price must be at least the market LOW to be fillable today.
        buy_orders = TradeOrder.objects.filter(
            symbol_id=symbol_id,
            side=TradeOrder.OrderSide.BUY,
            status__in=[TradeOrder.OrderStatus.PENDING, TradeOrder.OrderStatus.PARTIAL],
            price__gte=price_rec.low_price  # Must hit today's low to exist in the pool
        ).order_by('-price', 'created_at')

        # Sell Side: Price Priority. Order price must be at most the market HIGH to be fillable today.
        sell_orders = TradeOrder.objects.filter(
            symbol_id=symbol_id,
            side=TradeOrder.OrderSide.SELL,
            status__in=[TradeOrder.OrderStatus.PENDING, TradeOrder.OrderStatus.PARTIAL],
            price__lte=price_rec.high_price  # Must hit today's high to exist in the pool
        ).order_by('price', 'created_at')

        # Sell Side: Lower price first (Price Priority). Must be <= market high to be valid.
        sell_orders = TradeOrder.objects.filter(
            symbol_id=symbol_id,
            side=TradeOrder.OrderSide.SELL,
            status__in=[TradeOrder.OrderStatus.PENDING, TradeOrder.OrderStatus.PARTIAL],
            price__lte=price_rec.high_price
        ).order_by('price', 'created_at')

        # 4. Peer-to-Peer Matching Logic
        for b_order in buy_orders:
            # Refresh buyer status from DB to handle partial fills in the same loop
            b_order.refresh_from_db()
            if b_order.filled_quantity >= b_order.quantity:
                continue

            for s_order in sell_orders:
                s_order.refresh_from_db()
                if s_order.filled_quantity >= s_order.quantity:
                    continue

                # P2P Condition: Buyer's price covers Seller's ask
                if b_order.price >= s_order.price:
                    # Execution Price: Uses the price of the order that was placed first
                    exec_price = s_order.price if s_order.created_at < b_order.created_at else b_order.price
                    
                    # Match Quantity: Min of remaining amounts
                    rem_buy = b_order.quantity - b_order.filled_quantity
                    rem_sell = s_order.quantity - s_order.filled_quantity
                    match_qty = min(rem_buy, rem_sell)

                    if match_qty > 0:
                        # 5. Execute P2P Settlement
                        execute_settlement(b_order, s_order, match_qty, exec_price, execution_date, price_rec)
                        match_count += 1
                        
                        # Re-check buyer after a match
                        if b_order.filled_quantity + match_qty >= b_order.quantity:
        
                            break
        # 6. P2M (User-to-Market) Matching Logic
        # After P2P loop, any remaining quantity in valid orders is filled by the "Market"
        
        # Check remaining Buy Orders
        for b_order in buy_orders:
            b_order.refresh_from_db()
            rem_buy = b_order.quantity - b_order.filled_quantity
            if rem_buy > 0:
                # If the limit price is valid against today's range, fill with system
                # Using order.price as the execution price per your requirement
                execute_settlement(b_order, None, rem_buy, b_order.price, execution_date, price_rec)
                match_count += 1

        # Check remaining Sell Orders
        for s_order in sell_orders:
            s_order.refresh_from_db()
            rem_sell = s_order.quantity - s_order.filled_quantity
            if rem_sell > 0:
                # If the limit price is valid against today's range, fill with system
                execute_settlement(None, s_order, rem_sell, s_order.price, execution_date, price_rec)
                match_count += 1

    return match_count

def execute_settlement(b_order, s_order, qty, price, trade_date, price_rec):
    """
    Handles assets transfer. Supports both P2P (b_order & s_order) 
    and P2M (one of the orders is None).
    """
    with transaction.atomic():
        subtotal = price * qty
        
        # Using global constants and quantization
        buy_fee = quantize_4(subtotal * COMMISSION_RATE)
        sell_fee = quantize_4(subtotal * COMMISSION_RATE)

        # ==========================================
        # A & C. Buyer Side Logic (Only if b_order exists)
        # ==========================================
        if b_order:
            # A. Update Buyer's Portfolio (Simulation_Holding)
            b_holding, created = Simulation_Holding.objects.get_or_create(
                sim=b_order.sim,
                symbol=b_order.symbol,
                defaults={'quantity': 0, 'avg_cost': ZERO}
            )
            total_cost = (b_holding.quantity * b_holding.avg_cost) + subtotal + buy_fee
            b_holding.quantity += qty
            b_holding.avg_cost = quantize_4(total_cost / b_holding.quantity)
            b_holding.save()

            # C. Buyer Refund Logic
            # Frozen: (limit_price * qty) + fee. Actual: (exec_price * qty) + fee.
            frozen_unit_price = b_order.price + quantize_4(b_order.price * COMMISSION_RATE)
            actual_unit_price = price + quantize_4(price * COMMISSION_RATE)
            refund = (frozen_unit_price - actual_unit_price) * qty
            
            if refund > 0:
                b_order.sim.available_cash += refund
                b_order.sim.save()

            # D1. Create Buyer Audit Trail
            Simulation_Transaction.objects.create(
                sim=b_order.sim,
                symbol=b_order.symbol,
                daily_price=price_rec,
                trade_date=trade_date,
                type='BUY',
                quantity=qty,
                price=price,
                total_amount=subtotal + buy_fee,
                matched_order=b_order,
                opponent_order=s_order,  # Will be None if P2M
                realized_pnl=ZERO
            )

        # ==========================================
        # B. Seller Side Logic (Only if s_order exists)
        # ==========================================
        if s_order:
            # B. Update Seller's Cash
            s_order.sim.available_cash += (subtotal - sell_fee)
            s_order.sim.save()

            cost_at_order_time = s_order.avg_cost_snapshot or ZERO
            
            # Realized PnL = (Current Execution Price - Original Cost) * Quantity - Fee
            realized_pnl = (price - cost_at_order_time) * qty - sell_fee
            print("DEBUG SELL >>>", price, cost_at_order_time, qty, realized_pnl)

            # D2. Create Seller Audit Trail
            Simulation_Transaction.objects.create(
                sim=s_order.sim,
                symbol=s_order.symbol,
                daily_price=price_rec,
                trade_date=trade_date,
                type='SELL',
                quantity=qty,
                price=price,
                total_amount=subtotal - sell_fee,
                matched_order=s_order,
                opponent_order=b_order,  # Will be None if P2M
                realized_pnl=realized_pnl
            )

        # ==========================================
        # E. Update Orders Status (Support Partial Fills)
        # ==========================================
        for order in [b_order, s_order]:
            if order: # Skip if the order is None (Market side in P2M)
                order.filled_quantity += qty
                if order.filled_quantity >= order.quantity:
                    order.status = TradeOrder.OrderStatus.FILLED
                else:
                    order.status = TradeOrder.OrderStatus.PARTIAL
                order.save()

@login_required
def advance_simulation_date(request, sim_id=None):
    """
    Global System Clock Controller.
    Advances the GlobalSimulationState and triggers the P2P matching engine.
    """
    from datetime import timedelta
    from django.db import transaction

    with transaction.atomic():
        # 1. Fetch and Lock the Global State
        global_state = GlobalSimulationState.objects.select_for_update().first()
        if not global_state:
            return JsonResponse({"success": False, "error": "Global state not initialized."})

        current_date = global_state.current_global_date
        target_next_date = current_date + timedelta(days=1)

        # 2. Find the next valid trading date (skip weekends/holidays)
        next_market_record = DailyPrice.objects.filter(
            trade_date__gte=target_next_date
        ).order_by('trade_date').first()

        if not next_market_record:
            # If no more data in DB, we cannot advance
            return JsonResponse({"success": False, "error": "End of historical data reached."})

        new_date = next_market_record.trade_date

        # 3. TRIGGER MATCHING ENGINE (Crucial Step)
        # We match orders based on the NEW date's market boundaries.
        # This simulates the market opening and processing the order queue.
        matches_executed = internal_matching_engine(new_date)

        # 4. Update Global State
        global_state.current_global_date = new_date
        global_state.save()

        # 5. POST-MARKET SETTLEMENT: Update NAV for ALL active simulations
        # We process simulations in chunks if you have many users to avoid memory timeout.
        active_simulations = Simulation.objects.filter(status=Simulation.Status.ACTIVE)
        
        for sim in active_simulations:
            # Calculate valuation based on the new closing prices
            new_nav, mkt_val = calculate_nav_optimized(sim, new_date)
            
            # Update simulation record
            sim.current_nav = new_nav
            sim.current_virtual_date = new_date
            sim.save()

            # 6. Record NAV History for UI Charts
            Simulation_NAV_History.objects.update_or_create(
                sim=sim, 
                record_date=new_date,
                defaults={
                    'nav': new_nav, 
                    'cash': sim.available_cash, 
                    'market_value': mkt_val
                }
            )

    # Return summary or redirect
    return HttpResponseRedirect(reverse("index"))
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
    """
    Generates a performance report for a specific simulation.
    Synchronized with the simulation's internal virtual clock.
    """
    # Use select_for_update or simply get as it's a read-heavy view
    sim = Simulation.objects.get(id=sim_id, user=request.user)
    
    # CRITICAL: Use virtual date, not real-world today
    report_date = sim.current_virtual_date
    
    # Calculate state based on virtual date
    total_nav, mkt_val = calculate_nav_optimized(sim, report_date)
    
    # Fetch holdings and calculate value based on simulation price logic
    raw_holdings = Simulation_Holding.objects.filter(sim=sim).exclude(quantity=0).select_related('symbol')
    
    processed_holdings = []
    for h in raw_holdings:
        price_rec = get_market_price(h.symbol, report_date)
        current_price = price_rec.close_price if price_rec else h.symbol.current_price
        
        processed_holdings.append({
            "symbol": h.symbol,
            "quantity": h.quantity,
            "avg_cost": h.avg_cost,
            "current_price": current_price,
            "market_value": quantize_4(h.quantity * current_price)
        })
    
    # Performance Metrics
    profit_loss = total_nav - sim.initial_cash
    roi = (profit_loss / sim.initial_cash * 100) if sim.initial_cash > 0 else 0
    
    history = Simulation_NAV_History.objects.filter(sim=sim).order_by('record_date')
    
    return render(request, "stock/report.html", {
        "sim": sim,
        "holdings": processed_holdings,
        "nav_history": history,
        "stats": {
            "roi": round(roi, 2),
            "total_nav": total_nav,
            "cash": sim.available_cash,
            "report_date": report_date
        }
    })

@login_required
def stock_detail(request, symbol):
    """
    Stock Detail View: Displays financial reports, historical price trends, 
    and the user's current holdings based on the GLOBAL simulation clock.
    """
    from django.shortcuts import get_object_or_404
    
    # 1. Fetch company basic info
    company = get_object_or_404(Company, symbol=symbol)
    
    # 2. Get the GLOBAL simulation date (The Master Clock)
    global_state = GlobalSimulationState.objects.first()
    if global_state:
        reference_date = global_state.current_global_date
        is_market_open = global_state.is_market_open
    else:
        # Fallback for safety
        reference_date = datetime.strptime("2026-03-02", "%Y-%m-%d").date()
        is_market_open = True
    
    # 3. Get the active simulation account for the current user
    active_sim = Simulation.objects.filter(user=request.user).order_by('-created_at').first()
    
    # 4. Fetch price history: ONLY records on or before the GLOBAL virtual today
    # Prevents data leaks in the historical table and charts.
   
    
    price_history_qs = DailyPrice.objects.filter(
        symbol=company,
        trade_date__lte=reference_date
    ).order_by('-trade_date')[:30]
    price_history = list(price_history_qs)[::-1]

    
    yesterday_price_rec = DailyPrice.objects.filter(
        symbol=company,
        trade_date__lt=reference_date  
    ).order_by('-trade_date').first()

    
    if yesterday_price_rec:
        current_sim_price = yesterday_price_rec.close_price
    elif price_history:
        current_sim_price = price_history[-1].close_price
    else:
        current_sim_price = company.current_price
    # -----------------------
    # 5. Fetch financial reports
    financial_reports = Financials.objects.filter(
        symbol=company,
        report_date__lte=reference_date
    ).order_by('-report_date')


    # We sort by date ascending for the chart (left to right)
    chart_qs = financial_reports.order_by('report_date')
    
    # Extract dates and ratios into lists
    report_dates = [f.report_date.strftime('%Y-%m') for f in chart_qs]
    debt_ratios = [float(f.debt_asset_ratio) for f in chart_qs]
    current_ratios = [float(f.current_ratio) for f in chart_qs]
    quick_ratios = [float(f.quick_ratio) for f in chart_qs]

    # Serialize to JSON strings for the template's JavaScript
    chart_dates_json = json.dumps(report_dates)
    debt_ratios_json = json.dumps(debt_ratios)
    current_ratios_json = json.dumps(current_ratios)
    quick_ratios_json = json.dumps(quick_ratios)
   

    # 6. (Optional New Feature) Fetch Pending Orders for this stock
    # This allows users to see the current "Market Depth"
    pending_orders = TradeOrder.objects.filter(
        symbol=company,
        status='PENDING'
    ).order_by('-price') # Show highest buy/sell prices
    yesterday_rec = DailyPrice.objects.filter(
        symbol=company,
        trade_date__lt=reference_date
    ).order_by('-trade_date').first()

    if yesterday_rec:
        current_sim_price = yesterday_rec.close_price
    elif price_history:

        current_sim_price = price_history[0].close_price
    else:

        current_sim_price = company.current_price


    print(f"DEBUG >>> GlobalDate: {reference_date} | FinalPrice: {current_sim_price}")
    # Check if the user currently holds this stock
    user_holding = None
    if active_sim:
        user_holding = Simulation_Holding.objects.filter(
            sim=active_sim, 
            symbol=company
        ).first()
    return render(request, "stock/detail.html", {
        "company": company,
        "current_price": current_sim_price, 
        "financials": financial_reports,
        "history": price_history,
        "holding": user_holding,
        "sim": active_sim,
        "virtual_today": reference_date,
        "is_market_open": is_market_open,
        "pending_orders": pending_orders,
        "chart_dates_json": chart_dates_json,
        "debt_ratios_json": debt_ratios_json,
        "current_ratios_json": current_ratios_json,
        "quick_ratios_json": quick_ratios_json,
    })

@login_required
def stock_history_full(request, symbol):
    """
    Dedicated view for historical price data.
    Provides a deep dive into price movements while enforcing the 
    simulation's virtual date boundary to prevent data leaks.
    """
    from django.shortcuts import get_object_or_404
    
    # 1. Fetch company basic info (Returns 404 if symbol not found)
    company = get_object_or_404(Company, symbol=symbol)
    
    # 2. Get the active simulation context for the current user
    active_sim = Simulation.objects.filter(user=request.user).order_by('-created_at').first()
    
    # 3. Determine the "Time Machine" boundary
    # If no simulation is active, default to current real-world date
    reference_date = active_sim.current_virtual_date if active_sim else timezone.now().date()
    
    # 4. Fetch extended price history (limited to 100 entries)
    # CRITICAL: Added trade_date__lte filter to hide "future" market data
    price_history = DailyPrice.objects.filter(
        symbol=company,
        trade_date__lte=reference_date
    ).order_by('-trade_date')[:100]
    
    # 5. Render the historical data page within the simulation context
    return render(request, "stock/history_page.html", {
        "company": company,
        "history": price_history,
        "sim": active_sim,
        "reference_date": reference_date
    })

@login_required
def portfolio_view(request):
    """
    Omni-Simulator Adapter: Calculates P&L and Market Values synchronized with 
    the Global Master Clock (simulation date) for the new portfolio template.
    Now includes automated NAV history tracking for the equity curve.
    """
    # Retrieve the most recent active simulation instance for the current user
    active_sim = Simulation.objects.filter(user=request.user).order_by('-created_at').first()
    
    # Initialize summary variables
    total_stock_value = Decimal('0.00')
    processed_holdings = []

    if active_sim:
        virtual_today = active_sim.current_virtual_date
        
        # 1. Fetch raw holdings and join with Company model for metadata
        raw_holdings = Simulation_Holding.objects.filter(
            sim=active_sim
        ).exclude(quantity=0).select_related('symbol')

        # 2. Iterate through holdings to calculate values (This loop remains exactly as you wrote it)
        for h in raw_holdings:
            price_rec = get_market_price(h.symbol, virtual_today)
            hist_price = price_rec.close_price if price_rec else Decimal('0.0000')
            
            mkt_val = h.quantity * hist_price
            pnl = (hist_price - h.avg_cost) * h.quantity
            if h.avg_cost != 0:
                pnl_percent = ((hist_price - h.avg_cost) / abs(h.avg_cost) * 100)
            else:
                pnl_percent = 0
            
            total_stock_value += mkt_val
            
            processed_holdings.append({
                "symbol": h.symbol.symbol,
                "company_name": h.symbol.full_name,
                "quantity": h.quantity,
                "avg_cost": h.avg_cost,
                "current_price": hist_price,
                "market_value": mkt_val,
                "pnl": pnl,
                "pnl_percent": pnl_percent,
            })

        # 3. Finalize global financial snapshot
        # CRITICAL FIX: We use the optimized engine to get total_assets to include frozen cash/shares.
        # We still use the total_stock_value from the loop above to maintain your logic flow.
        total_assets, _ = calculate_nav_optimized(active_sim, virtual_today)
        
        total_pnl = total_assets - active_sim.initial_cash
        pnl_rate = (total_pnl / active_sim.initial_cash * 100) if active_sim.initial_cash > 0 else 0

        # 4. Persistence: Ensure a NAV history record exists for the current virtual date
        from .models import Simulation_NAV_History
        Simulation_NAV_History.objects.update_or_create(
            sim=active_sim,
            record_date=virtual_today,
            defaults={
                'nav': total_assets,
                'cash': active_sim.available_cash,
                'market_value': total_stock_value
            }
        )

        # 5. Retrieval: Get all historical points for the chart
        nav_history_qs = Simulation_NAV_History.objects.filter(
            sim=active_sim
        ).order_by('record_date')

        chart_labels = [h.record_date.strftime("%m-%d") for h in nav_history_qs]
        chart_values = [float(h.nav) for h in nav_history_qs]

        return render(request, "stock/portfolio.html", {
            "holdings_detailed": processed_holdings,
            "sim": active_sim,
            "total_assets": total_assets,
            "total_stock_value": total_stock_value,
            "total_pnl": total_pnl,
            "pnl_percent": pnl_rate,
            "chart_labels": chart_labels,
            "chart_values": chart_values,
        })
    
    return render(request, "stock/portfolio.html", {"holdings_detailed": []})

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

# ==========================================
# 6. GLOBAL ERROR HANDLERS (Professional Redundancy)
# ==========================================

def custom_404(request, exception):
    """
    Handle Page Not Found (e.g., user types a wrong stock URL)
    """
    return render(request, "errors/404.html", status=404)

def custom_500(request):
    """
    Handle Internal Server Errors (e.g., database lock timeout)
    """
    return render(request, "errors/500.html", status=500)