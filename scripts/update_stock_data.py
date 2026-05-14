#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票数据增量更新脚本
从数据源拉取最新数据并增量保存（只保存新增的数据）
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

def fetch(sym, days, proxy=None):
    """从Yahoo Finance获取股票数据"""
    if not proxy:
        proxy = os.environ.get("ALL_PROXY", "socks5://127.0.0.1:7897")
    
    ys = sym.replace(".US", "").replace(".HK", "").replace(".SS", "").replace(".SZ", "")
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ys}?interval=1d&range={days}d"
    cmd = "curl -s --connect-timeout 20 "
    if proxy:
        cmd += f"--proxy \"{proxy}\" "
    cmd += f"-H \"User-Agent: Mozilla/5.0\" \"{url}\""
    tmp = f"/tmp/yf_{ys}.json"
    env = dict(os.environ)
    if proxy:
        env["ALL_PROXY"] = proxy
    
    try:
        subprocess.run(cmd + " -o " + tmp, shell=True, text=True, timeout=30, check=True, env=env)
    except Exception as e:
        print(f"curl failed: {e}", file=sys.stderr)
        return None
    
    try:
        with open(tmp) as f:
            d = json.loads(f.read())
    except Exception as e:
        print(f"json error: {e}", file=sys.stderr)
        return None
    
    r = d.get("chart", {}).get("result", [{}])[0]
    if not r:
        print("no result", file=sys.stderr)
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
        dt = datetime.fromtimestamp(ts[i], timezone.utc).strftime("%Y-%m-%d")
        data.append({
            "date": dt,
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": vol
        })
    
    data.sort(key=lambda x: x["date"])
    return data

def load_existing_data(symbol):
    """加载已保存的数据"""
    data_file = os.path.join(DATA_DIR, f"{symbol.lower()}_daily.json")
    if os.path.exists(data_file):
        try:
            with open(data_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Failed to load existing data: {e}", file=sys.stderr)
            return None
    return None

def save_data(symbol, data):
    """保存数据到文件"""
    data_file = os.path.join(DATA_DIR, f"{symbol.lower()}_daily.json")
    try:
        with open(data_file, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"Data saved to {data_file}")
        return True
    except Exception as e:
        print(f"Failed to save data: {e}", file=sys.stderr)
        return False

def update_stock_data(symbol, days=365, proxy=None):
    """增量更新股票数据"""
    # 处理股票代码
    sym = symbol.upper()
    if not any(sym.endswith(x) for x in [".US", ".HK", ".SS", ".SZ"]):
        sym += ".US"
    
    print(f"Updating data for {sym}")
    
    # 获取最新数据
    new_data = fetch(sym, days, proxy)
    if not new_data:
        print("Failed to fetch new data", file=sys.stderr)
        return False
    
    # 加载已有的数据
    existing_data = load_existing_data(symbol)
    
    if existing_data:
        # 找出已有的日期
        existing_dates = set(item["date"] for item in existing_data)
        print(f"Existing data has {len(existing_data)} records")
        
        # 找出新增的数据
        added_count = 0
        for item in new_data:
            if item["date"] not in existing_dates:
                existing_data.append(item)
                added_count += 1
        
        # 按日期排序
        existing_data.sort(key=lambda x: x["date"])
        
        print(f"Added {added_count} new records")
        
        # 只在有新增数据时保存
        if added_count > 0:
            return save_data(symbol, existing_data)
        else:
            print("No new data to add")
            return True
    else:
        # 没有已有数据，保存全部
        print(f"Saving all {len(new_data)} records")
        return save_data(symbol, new_data)

def main():
    parser = argparse.ArgumentParser(description='增量更新股票数据')
    parser.add_argument('symbol', help='股票代码，如 OKLO, AAPL.US')
    parser.add_argument('--days', type=int, default=365, help='获取数据的天数')
    parser.add_argument('--proxy', help='代理地址，如 socks5://127.0.0.1:7897')
    args = parser.parse_args()
    
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
    
    success = update_stock_data(args.symbol, args.days, args.proxy)
    sys.exit(0 if success else 1)

if __name__ == '__main__':
    main()