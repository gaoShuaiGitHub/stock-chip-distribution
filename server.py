#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票数据API服务器
通过chip_chart.py的逻辑获取数据，提供API给前端
"""
from flask import Flask, request, jsonify
import json
import os
import subprocess
from datetime import datetime

app = Flask(__name__)

def fetch_data(sym, days, proxy="socks5://127.0.0.1:7897"):
    """获取股票数据"""
    if not proxy:
        proxy = "socks5://127.0.0.1:7897"
    
    ys = sym.replace(".US","").replace(".HK","").replace(".SS","").replace(".SZ","")
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ys}?interval=1d&range={days}d"
    
    cmd = f'curl -s --connect-timeout 20 --proxy "{proxy}" -H "User-Agent: Mozilla/5.0" "{url}"'
    tmp = f"/tmp/yf_{ys}.json"
    
    env = dict(os.environ)
    if proxy:
        env["ALL_PROXY"] = proxy
    
    try:
        subprocess.run(cmd + f" -o {tmp}", shell=True, text=True, timeout=30, check=True, env=env)
    except Exception as e:
        print(f"curl failed: {e}")
        return None
    
    try:
        with open(tmp) as f:
            d = json.loads(f.read())
    except Exception as e:
        print(f"json error: {e}")
        return None
    
    r = d.get("chart", {}).get("result", [{}])[0]
    if not r:
        print("no result")
        return None
    
    ts = r["timestamp"]
    q = r["indicators"]["quote"][0]
    
    data = []
    for i in range(len(ts)):
        o = q["open"][i]
        h = q["high"][i]
        l = q["low"][i]
        c = q["close"][i]
        vol = q.get("volume", [0])[i]
        if o is None:
            continue
        dt = datetime.utcfromtimestamp(ts[i]).strftime("%Y-%m-%d")
        data.append({"date": dt, "open": o, "high": h, "low": l, "close": c, "volume": vol})
    
    data.sort(key=lambda x: x["date"])
    return data

def calculate_obv(data):
    """计算OBV"""
    o = 0
    for i, bar in enumerate(data):
        if i > 0:
            p = data[i-1]["close"]
            if bar["close"] > p:
                o += bar["volume"]
            elif bar["close"] < p:
                o -= bar["volume"]
        bar["obv"] = o
    return data

def detect_anomalies(data, vr=2.5, pc=0.08):
    """检测量价异动"""
    if len(data) < 25:
        return []
    
    vols = [x["volume"] for x in data]
    avg = [sum(vols[i-19:i+1])/20 for i in range(19, len(data))]
    res = []
    
    for i, bar in enumerate(data):
        if i < 20 or avg[i-20] == 0:
            continue
        vr2 = bar["volume"] / avg[i-20]
        pc2 = (bar["close"] - data[i-1]["close"]) / data[i-1]["close"]
        if vr2 > vr or abs(pc2) > pc:
            lbls = []
            if vr2 > vr:
                lbls.append(f"放量x{vr2:.1f}")
            if abs(pc2) > pc:
                lbls.append(f"{'+' if pc2 > 0 else ''}{pc2*100:.1f}%")
            res.append({
                "date": bar["date"],
                "close": bar["close"],
                "label": " / ".join(lbls),
                "atype": "放量暴涨" if pc2 > pc else "放量暴跌" if pc2 < -pc else "异常放量"
            })
    return res

def calculate_chip(data, n=10):
    """计算筹码分布"""
    ah = max(x["high"] for x in data)
    al = min(x["low"] for x in data)
    bs = (ah - al) / n
    
    for bar in data:
        h, l, vol = bar["high"], bar["low"], bar["volume"]
        bar["bands"] = [0] * n
        if h != l:
            vp = vol / (h - l)
            for b in range(n):
                lo, hi = al + b * bs, al + (b + 1) * bs
                ol, oh = max(lo, l), min(hi, h)
                if ol < oh:
                    bar["bands"][b] = vp * (oh - ol)
    
    cum = [0] * n
    for bar in data:
        cum = [cum[b] + bar["bands"][b] for b in range(n)]
        bar["cb"] = list(cum)
        tot = sum(cum)
        bar["cp"] = [c / tot * 100 if tot else 0 for c in cum]
    
    return data, al, ah, bs

@app.route('/api/data')
def get_data():
    """获取股票数据的API"""
    symbol = request.args.get('symbol', 'OKLO')
    days = int(request.args.get('days', 365))
    proxy = request.args.get('proxy', 'socks5://127.0.0.1:7897')
    
    # 处理股票代码
    sym = symbol.upper()
    if not any(sym.endswith(x) for x in [".US", ".HK", ".SS", ".SZ"]):
        sym += ".US"
    
    print(f"Fetching data for {sym}, days={days}, proxy={proxy}")
    
    data = fetch_data(sym, days, proxy)
    if not data:
        return jsonify({"error": "Failed to fetch data"}), 500
    
    data = calculate_obv(data)
    anomalies = detect_anomalies(data)
    data, al, ah, bs = calculate_chip(data)
    
    return jsonify({
         "data": data,
         "anomalies": anomalies,
         "al": al,
         "ah": ah,
         "bs": bs
     })

@app.route('/update_data', methods=['POST'])
def update_data():
    """获取股票数据并保存到文件，供前端加载"""
    try:
        data = request.get_json()
        symbol = data.get('symbol', 'OKLO').upper()
        days = int(data.get('days', 365))
        proxy = data.get('proxy', 'socks5://127.0.0.1:7897')
        
        print(f"Updating data for {symbol}, days={days}")
        
        # 处理股票代码
        sym = symbol
        if not any(sym.endswith(x) for x in [".US", ".HK", ".SS", ".SZ"]):
            sym += ".US"
        
        # 获取数据
        stock_data = fetch_data(sym, days, proxy)
        if not stock_data:
            return jsonify({"success": False, "message": "获取股票数据失败"})
        
        # 计算OBV
        stock_data = calculate_obv(stock_data)
        
        # 保存到文件
        data_dir = os.path.join(os.path.dirname(__file__), 'scripts', 'data')
        os.makedirs(data_dir, exist_ok=True)
        file_name = f"{symbol.lower()}_daily.json"
        file_path = os.path.join(data_dir, file_name)
        
        with open(file_path, 'w') as f:
            json.dump(stock_data, f, indent=2)
        
        print(f"Data saved to {file_path}, records: {len(stock_data)}")
        
        return jsonify({
            "success": True,
            "message": f"成功获取 {len(stock_data)} 条数据",
            "symbol": symbol,
            "count": len(stock_data)
        })
        
    except Exception as e:
        print(f"Error in update_data: {e}")
        return jsonify({"success": False, "message": str(e)})

if __name__ == '__main__':
    print("Starting stock data API server on http://localhost:5555")
    app.run(host='0.0.0.0', port=5555, debug=True)