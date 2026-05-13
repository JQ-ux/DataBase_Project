# agents/brain.py
import ollama
from django.apps import apps
from .memory import VectorMemory
from .tools import get_user_holdings_context

class FinancialBrain:
    def __init__(self, model_name="qwen2.5:7b"):
        self.model_name = model_name
        # 初始化向量内存对象
        self.memory = VectorMemory()

    def think(self, user, user_query):
        """
        Agent 决策逻辑：对齐 Simulation 模型的真实字段
        """
        # 1. 获取该用户当前活跃的模拟盘信息
        Simulation = apps.get_model('stock', 'Simulation')
        # 根据你的模型，使用 created_at 排序获取最新的模拟盘
        active_sim = Simulation.objects.filter(user=user).order_by('-created_at').first()
        
        # 【对齐你的模型字段】：字段名是 current_virtual_date
        sim_date = None
        if active_sim:
            sim_date = active_sim.current_virtual_date
            print(f"--- [Brain] 识别到仿真日期: {sim_date} ---")

        # 2. 根据仿真日期动态构建向量知识库（实现时间围栏）
        self.memory.build_knowledge_base(current_sim_date=sim_date)
        
        # 3. 获取用户的持仓背景 (来自 tools.py)
        holdings_context = get_user_holdings_context(user)
        
        # 4. 从向量库检索相关的财务指标 (k=5)
        financial_knowledge = self.memory.query(user_query, k=5)
        
        # 5. 构造 Prompt
        system_prompt = f"""
        你是一位名为 'Ada-Finance' 的 AI 投资顾问。
        
        【当前时间背景】: 
        今天是模拟交易中的 {sim_date if sim_date else '当前日期'}。你只能看到此日期及以前的财报。
        
        【参考事实 - 用户当前持仓】:
        {holdings_context}
        
        【参考事实 - 数据库财务详情】:
        {financial_knowledge}
        
        【回答准则】:
        1. 必须引用参考事实中的具体数字（如营收、负债率）来回答。
        2. 若持仓股资产负债率 > 70%，必须发出风险预警。
        3. 语气专业且果断，禁止编造未来数据。
        """
        
        try:
            # 6. 调用 Ollama
            response = ollama.generate(
                model=self.model_name,
                prompt=f"系统指令：{system_prompt}\n\n用户问题：{user_query}"
            )
            return response['response']
        except Exception as e:
            return f"Agent 思考时出错: {str(e)}"