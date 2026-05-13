# agents/tools.py
from django.apps import apps
from decimal import Decimal

def get_user_holdings_context(user):
    """
    获取用户的实时持仓摘要，供 Agent 决策
    """
    Simulation = apps.get_model('stock', 'Simulation')
    Simulation_Holding = apps.get_model('stock', 'Simulation_Holding')
    
    active_sim = Simulation.objects.filter(user=user).order_by('-created_at').first()
    
    if not active_sim:
        return "用户当前没有活跃的模拟账户。"
    
    holdings = Simulation_Holding.objects.filter(sim=active_sim).exclude(quantity=0)
    
    if not holdings.exists():
        return f"账户 {active_sim.name} 目前是空仓状态。"
    
    summary = f"账户名称: {active_sim.name}, 余额: {active_sim.available_cash}\n当前持仓:\n"
    for h in holdings:
        summary += f"- {h.symbol.symbol}({h.symbol.full_name}): {h.quantity}股, 成本价: {h.avg_cost}\n"
        
    return summary