import requests
from bs4 import BeautifulSoup
import random
from datetime import datetime, timedelta

BASE_URL = "http://127.0.0.1:8000"

# =========================
# 你给的价格数据（只保留 3-2 到 3-12）
# =========================
PRICE_DATA = {
    "2026-03-02": {
        "AAPL": (260.2, 266.53),
        "TSLA": (388.25, 404.54),
        "NVDA": (174.6306, 183.4501),
        "MSFT": (390.63, 401.19),
        "AMZN": (203.46, 209.73),
    },
    "2026-03-03": {
        "AAPL": (260.13, 265.56),
        "TSLA": (385.39, 396.34),
        "NVDA": (176.9104, 180.8902),
        "MSFT": (392.67, 406.7),
        "AMZN": (202.48, 209.18),
    },
    "2026-03-04": {
        "AAPL": (261.42, 266.15),
        "TSLA": (394.58, 408.33),
        "NVDA": (180.0503, 184.69),
        "MSFT": (400.31, 411.03),
        "AMZN": (210.15, 217.54),
    },
    "2026-03-05": {
        "AAPL": (257.25, 261.56),
        "TSLA": (399.42, 408.62),
        "NVDA": (177.8704, 184.05),
        "MSFT": (404.4, 411.61),
        "AMZN": (215.59, 220.47),
    },
    "2026-03-06": {
        "AAPL": (254.37, 258.77),
        "TSLA": (394.21, 402.35),
        "NVDA": (176.8104, 182.7501),
        "MSFT": (408.51, 413.05),
        "AMZN": (212.53, 217.32),
    },
    "2026-03-09": {
        "AAPL": (253.68, 261.15),
        "TSLA": (381.4, 401.59),
        "NVDA": (175.5505, 182.9001),
        "MSFT": (403.5, 410.21),
        "AMZN": (207.11, 213.82),
    },
    "2026-03-10": {
        "AAPL": (256.95, 262.48),
        "TSLA": (398.19, 406.59),
        "NVDA": (182.0001, 186.4299),
        "MSFT": (402.93, 410.2),
        "AMZN": (212.43, 215.65),
    },
    "2026-03-11": {
        "AAPL": (259.55, 262.13),
        "TSLA": (402.15, 416.38),
        "NVDA": (184.45, 187.62),
        "MSFT": (401.59, 409.01),
        "AMZN": (211.35, 217.0),
    },
    "2026-03-12": {
        "AAPL": (254.18, 258.95),
        "TSLA": (394.65, 406.5),
        "NVDA": (181.75, 184.94),
        "MSFT": (401.71, 406.12),
        "AMZN": (208.15, 211.71),
    },
}

# =========================
# 登录
# =========================
def login(username, password):
    s = requests.Session()

    r = s.get(f"{BASE_URL}/login/")
    soup = BeautifulSoup(r.text, "html.parser")

    csrf = soup.find("input", {"name": "csrfmiddlewaretoken"})
    csrf_token = csrf["value"] if csrf else s.cookies.get("csrftoken")

    data = {
        "username": username,
        "password": password,
        "csrfmiddlewaretoken": csrf_token
    }

    headers = {"Referer": f"{BASE_URL}/login/"}

    r = s.post(f"{BASE_URL}/login/", data=data, headers=headers)

    if "sessionid" in s.cookies:
        print(f"✅ {username} 登录成功")
        return s
    else:
        print(f"❌ {username} 登录失败")
        return None


# =========================
# 获取 sim_id
# =========================
def get_sim_id(session):
    r = session.get(f"{BASE_URL}/api/current_sim/")
    return r.json().get("sim_id")


# =========================
# 下单
# =========================
def trade(session, sim_id, symbol, side, qty, price):
    url = f"{BASE_URL}/api/v1/trades/"

    data = {
        "sim_id": sim_id,
        "symbol": symbol,
        "side": side,
        "quantity": qty,
        "price": price
    }

    r = session.post(url, data=data)

    try:
        return r.json()
    except:
        return {"error": r.text[:100]}


# =========================
# 推进交易日（调用你的按钮接口）
# =========================
def advance_day(session):
    # 修正后的 URL，必须包含 simulation/ 路径
    url = f"{BASE_URL}/simulation/advance/"
    
    r = session.get(f"{BASE_URL}/")
    csrf_token = session.cookies.get("csrftoken")

    data = {
        "csrfmiddlewaretoken": csrf_token
    }
    
    # 发送请求
    r = session.post(url, data=data, allow_redirects=True)
    
    if r.status_code == 200:
        print(f"✅ 成功推进日期！当前页面状态码: {r.status_code}")
    else:
        print(f"❌ 推进失败，状态码: {r.status_code}, 路径: {url}")


# =========================
# 模拟交易（核心）
# =========================
def simulate():
    s1 = login("jinqi", "Jinqi20061001")
    s2 = login("Jinqi", "Jinqi20061001")

    if not s1 or not s2:
        return

    sim1 = get_sim_id(s1)
    sim2 = get_sim_id(s2)

    symbols = ["AAPL", "TSLA", "NVDA", "MSFT", "AMZN"]

    for date_str, day_data in PRICE_DATA.items():
        print(f"\n====== {date_str} ======")

        for session, sim_id, name in [
            (s1, sim1, "jinqi"),
            (s2, sim2, "Jinqi")
        ]:
            for _ in range(random.randint(3, 6)):
                symbol = random.choice(symbols)

                low, high = day_data[symbol]

                # ✅ 关键：价格严格在区间内
                price = round(random.uniform(low, high), 2)

                side = random.choice(["BUY", "SELL"])
                qty = random.choice([10, 20, 30, 50])

                result = trade(session, sim_id, symbol, side, qty, price)

                print(f"{name} -> {side} {symbol} x{qty} @ {price} -> {result}")

        # ✅ 推进到下一天（调用你的前端按钮逻辑）
        advance_day(s1)


# =========================
if __name__ == "__main__":
    simulate()