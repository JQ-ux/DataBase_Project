import faiss
import numpy as np
from sentence_transformers import SentenceTransformer
from django.apps import apps
import os

class VectorMemory:
    def __init__(self):
        # 1. 加载嵌入模型 (all-MiniLM-L6-v2)
        self.encoder = SentenceTransformer('all-MiniLM-L6-v2') 
        
        # 2. 初始化 FAISS 索引 (维度 384)
        self.index = faiss.IndexFlatL2(384)
        
        # 3. 存储原始文本列表，用于检索后还原
        self.metadata = []

    def build_knowledge_base(self, current_sim_date=None):
        """
        核心功能：根据时间限制构建知识库
        current_sim_date: 用户模拟交易盘当前的仿真日期。
        如果提供，则只加载报告日期 <= 该日期的财务数据。
        """
        try:
            Financials = apps.get_model('stock', 'Financials')
            # 基础查询：关联股票代码表
            queryset = Financials.objects.select_related('symbol')
            
            # 【关键创新：时间围栏】
            # 确保 Agent 不会拥有“上帝视角”看到未来的财报
            if current_sim_date:
                queryset = queryset.filter(report_date__lte=current_sim_date)
                print(f"--- [Memory] 正在应用时间过滤：只读取 {current_sim_date} 以前的财报 ---")
            else:
                print("--- [Memory] 未检测到仿真日期，将读取全量历史数据 (仅建议测试使用) ---")
            
            records = queryset.all()
        except LookupError:
            print("--- [Error] 找不到 stock.Financials 模型，请确认 app 名称是否为 stock ---")
            return

        # 每次构建前重置索引和元数据，防止数据残留或重复
        documents = []
        self.metadata = []
        self.index = faiss.IndexFlatL2(384)

        for r in records:
            # 将结构化财务指标转化为自然语言描述
            desc = (
                f"股票代码: {r.symbol.symbol}, 公司名称: {r.symbol.full_name}. "
                f"报告日期: {r.report_date}. "
                f"总营收: {r.total_revenue}, 净利润: {r.net_income}, "
                f"资产负债率: {r.debt_asset_ratio}%, 流动比率: {r.current_ratio}. "
                f"每股收益(EPS): {r.basic_eps}."
            )
            documents.append(desc)
            self.metadata.append(desc)

        if documents:
            # 向量化处理
            embeddings = self.encoder.encode(documents)
            self.index.add(np.array(embeddings).astype('float32'))
            print(f"--- [Memory] 知识库构建完毕，共加载 {len(documents)} 条符合时间条件的记录 ---")
        else:
            print("--- [Warning] 该时间点之前没有任何财务数据记录 ---")

    def query(self, user_query, k=5):
        """
        根据用户问题执行向量检索
        k=5 增加了检索深度，能有效区分 AAPL 和 AAL 等缩写相近的股票
        """
        if self.index.ntotal == 0:
            return "本地知识库中暂无符合当前时间条件的财务信息。"
            
        # 将用户提问转化为向量
        query_vec = self.encoder.encode([user_query])
        
        # 在索引中搜索最相似的 k 个结果
        D, I = self.index.search(np.array(query_vec).astype('float32'), k)
        
        # 还原为文本
        results = [self.metadata[i] for i in I[0] if i != -1]
        return "\n".join(results)