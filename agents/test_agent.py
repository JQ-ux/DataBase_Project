# agents/test_agent.py
import os
import django
import sys

# 1. Django 环境初始化
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'capstone.settings') 
django.setup()

from agents.brain import FinancialBrain
# --- 修改这里 ---
from django.contrib.auth import get_user_model
User = get_user_model() 
# ----------------

def main():
    print("--- [System] 正在唤醒 Ada-Finance Agent... ---")
    brain = FinancialBrain(model_name="qwen2.5:7b")
    
    # 获取你数据库里的第一个用户
    test_user = User.objects.first()
    
    if not test_user:
        print("--- [Error] 数据库中没有用户，请先运行 python manage.py createsuperuser 创建一个 ---")
        return

    print(f"--- [User] 识别到自定义测试用户: {test_user.username} ---")
    
    # 测试问题
    question = "根据我现在的持仓，结合财报数据，帮我分析一下其中的风险点。"
    print(f"--- [Query] 用户提问: {question} ---")
    
    print("--- [Agent] 正在思考并检索数据 (请耐心等待 Ollama 响应)... ---")
    answer = brain.think(test_user, question)
    
    print("\n" + "="*50)
    print("Ada-Finance 助手的分析报告：")
    print(answer)
    print("="*50)

if __name__ == "__main__":
    main()