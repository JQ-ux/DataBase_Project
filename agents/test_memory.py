import os
import django
import sys

# 1. 强制将项目根目录添加到系统路径
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

# 2. 设置 Django 配置模块
# 这里的 'capstone.settings' 对应你刚刚发给我的文件夹结构
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'capstone.settings') 

# 3. 启动 Django
try:
    django.setup()
    print("--- [System] Django 环境启动成功 ---")
except Exception as e:
    print(f"--- [Error] Django 启动失败: {e} ---")
    sys.exit(1)

# 4. 导入你的向量库类
from agents.memory import VectorMemory

def test():
    print("--- [Action] 正在初始化向量库并加载模型 (all-MiniLM-L6-v2) ---")
    try:
        mem = VectorMemory()
        
        print("--- [Action] 正在从数据库读取财务数据并构建知识库... ---")
        mem.build_knowledge_base()
        
        if mem.index.ntotal == 0:
            print("--- [Warning] 知识库为空！请检查数据库 Financials 表是否有数据 ---")
            return

        # 执行一次检索测试
        query = "请根据财务数据分析一下负债率高的股票"
        print(f"--- [Test] 模拟查询: {query} ---")
        result = mem.query(query, k=2)
        print(f"--- [Result] 找回的相关财务背景如下: \n{result}")
        
    except Exception as e:
        print(f"--- [Fatal Error] 测试过程崩溃: {e} ---")

if __name__ == "__main__":
    test()