#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简单的HTTP服务器，处理股票数据更新请求
"""
import http.server
import socketserver
import json
import os
import subprocess
import urllib.parse
from datetime import datetime

PORT = 5555

class StockDataHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        # 解析URL
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        params = urllib.parse.parse_qs(parsed_url.query)
        
        # 处理API请求
        if path == '/api/data':
            symbol = params.get('symbol', ['OKLO'])[0].upper()
            days = int(params.get('days', [365])[0])
            
            print(f"GET request received: {symbol}, days={days}")
            
            # 读取保存的数据文件
            data_dir = os.path.join(os.path.dirname(__file__), 'scripts', 'data')
            file_name = f"{symbol.lower()}_daily.json"
            file_path = os.path.join(data_dir, file_name)
            
            if os.path.exists(file_path):
                with open(file_path, 'r') as f:
                    stock_data = json.load(f)
                
                # 发送响应
                self.send_response(200)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(stock_data).encode('utf-8'))
            else:
                # 数据文件不存在，返回错误
                self.send_response(404)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({
                    "success": False,
                    "message": "数据文件不存在，请先使用POST请求更新数据"
                }).encode('utf-8'))
        else:
            # 默认响应
            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(b"Stock Data Server is running")
    
    def do_OPTIONS(self):
        # 处理CORS预检请求
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
    
    def do_POST(self):
        try:
            # 读取请求体
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length).decode('utf-8')
            
            # 解析JSON数据
            data = json.loads(post_data)
            symbol = data.get('symbol', 'OKLO').upper()
            days = int(data.get('days', 365))
            
            print(f"Request received: {symbol}, days={days}")
            
            # 调用update_stock_data.py脚本
            script_path = os.path.join(os.path.dirname(__file__), 'scripts', 'update_stock_data.py')
            cmd = f'python3 "{script_path}" {symbol} --days {days} --proxy socks5://127.0.0.1:7897'
            
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
            
            if result.returncode == 0:
                # 读取保存的数据文件
                data_dir = os.path.join(os.path.dirname(__file__), 'scripts', 'data')
                file_name = f"{symbol.lower()}_daily.json"
                file_path = os.path.join(data_dir, file_name)
                
                if os.path.exists(file_path):
                    with open(file_path, 'r') as f:
                        stock_data = json.load(f)
                    
                    response = {
                        "success": True,
                        "message": f"成功获取 {len(stock_data)} 条数据",
                        "symbol": symbol,
                        "count": len(stock_data)
                    }
                else:
                    response = {
                        "success": False,
                        "message": "数据文件未生成"
                    }
            else:
                response = {
                    "success": False,
                    "message": f"脚本执行失败: {result.stderr}"
                }
            
            # 发送响应
            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response).encode('utf-8'))
            
        except Exception as e:
            print(f"Error: {e}")
            self.send_response(500)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                "success": False,
                "message": str(e)
            }).encode('utf-8'))

    def log_message(self, format, *args):
        print(f"[{datetime.now().isoformat()}] {format % args}")

if __name__ == "__main__":
    with socketserver.TCPServer(("", PORT), StockDataHandler) as httpd:
        print(f"Starting simple server on port {PORT}")
        print(f"Server running at http://localhost:{PORT}")
        httpd.serve_forever()