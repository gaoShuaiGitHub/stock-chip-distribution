#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse, json, os, subprocess, sys
from datetime import datetime

def fetch(sym, days, start, proxy):
    if not proxy: proxy = os.environ.get("ALL_PROXY", "socks5://127.0.0.1:7897")
    if not proxy: proxy = os.environ.get("ALL_PROXY", "")
    ys = sym.replace(".US","").replace(".HK","").replace(".SS","").replace(".SZ","")
    url = "https://query2.finance.yahoo.com/v8/finance/chart/%s?interval=1d&range=%dd" % (ys, days)
    cmd = "curl -s --connect-timeout 20 "
    if proxy: cmd += "--proxy \"%s\" " % proxy
    cmd += "-H \"User-Agent: Mozilla/5.0\" \"%s\"" % url
    tmp = "/tmp/yf_" + ys + ".json"
    env = dict(os.environ)
    if proxy: env["ALL_PROXY"] = proxy
    try:
        subprocess.run(cmd+" -o "+tmp, shell=True, text=True, timeout=30, check=True, env=env)
    except: print("curl failed"); sys.exit(1)
    try:
        with open(tmp) as f: d = json.loads(f.read())
    except: print("json error"); sys.exit(1)
    r = d.get("chart",{}).get("result",[{}])[0]
    if not r: print("no result"); sys.exit(1)
    ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    data = []
    for i in range(len(ts)):
        o = q["open"][i]; h = q["high"][i]; l = q["low"][i]
        c = q["close"][i]; vol = q.get("volume",[0])[i]
        if o is None: continue
        dt = datetime.utcfromtimestamp(ts[i]).strftime("%Y-%m-%d")
        data.append({"date":dt,"open":o,"high":h,"low":l,"close":c,"volume":vol})
    if start: data = [x for x in data if x["date"]>=start]
    data.sort(key=lambda x:x["date"])
    return data

def obv(data):
    o = 0
    for i, bar in enumerate(data):
        if i>0:
            p = data[i-1]["close"]
            if bar["close"]>p: o+=bar["volume"]
            elif bar["close"]<p: o-=bar["volume"]
        bar["obv"] = o
    return data

def anomalies(data, vr=2.5, pc=0.08):
    if len(data)<25: return []
    vols = [x["volume"] for x in data]
    avg = [sum(vols[i-19:i+1])/20 for i in range(19,len(data))]
    res = []
    for i, bar in enumerate(data):
        if i<20 or avg[i-20]==0: continue
        vr2 = bar["volume"]/avg[i-20]
        pc2 = (bar["close"]-data[i-1]["close"])/data[i-1]["close"]
        if vr2>vr or abs(pc2)>pc:
            lbls = []
            if vr2>vr: lbls.append("放量x%.1f"%vr2)
            if abs(pc2)>pc: lbls.append(("%s%.1f%%"%(("+" if pc2>0 else ""),pc2*100)))
            res.append({"date":bar["date"],"close":bar["close"],"label":" / ".join(lbls),
                "atype":("放量暴涨" if pc2>pc else "放量暴跌" if pc2<-pc else "异常放量")})
    return res

def chip(data, n=10, method="equal_interval"):
    import numpy as np
    
    # 计算最高价和最低价
    ah = max(x["high"] for x in data)
    al = min(x["low"] for x in data)
    
    # 根据不同方法计算价格区间
    if method == "equal_interval":
        # 等距划分
        breaks = np.linspace(al, ah, n+1)
    elif method == "equal_frequency":
        # 等频划分
        prices = []
        for bar in data:
            if bar["high"] != bar["low"]:
                # 为每个交易日生成价格点
                price_points = np.linspace(bar["low"], bar["high"], 100)
                prices.extend(price_points)
        if prices:
            breaks = np.percentile(prices, np.linspace(0, 100, n+1))
        else:
            breaks = np.linspace(al, ah, n+1)
    elif method == "logarithmic":
        # 对数划分
        if al <= 0:
            # 避免对数计算中的负数
            al = min([x["low"] for x in data if x["low"] > 0], default=0.1)
        log_al = np.log(al)
        log_ah = np.log(ah)
        breaks = np.exp(np.linspace(log_al, log_ah, n+1))
    elif method == "volume_weighted":
        # 成交量加权划分
        price_volume = []
        for bar in data:
            if bar["high"] != bar["low"]:
                # 为每个交易日生成价格点，权重为成交量
                price_points = np.linspace(bar["low"], bar["high"], 100)
                volume_weights = np.full_like(price_points, bar["volume"] / 100)
                price_volume.extend(list(zip(price_points, volume_weights)))
        
        if price_volume:
            prices, weights = zip(*price_volume)
            breaks = np.percentile(prices, np.linspace(0, 100, n+1), weights=weights, method='inverted_cdf')
        else:
            breaks = np.linspace(al, ah, n+1)
    elif method == "standard_deviation":
        # 标准差划分
        prices = []
        for bar in data:
            prices.extend([bar["open"], bar["high"], bar["low"], bar["close"]])
        if prices:
            mean_price = np.mean(prices)
            std_price = np.std(prices)
            # 以均值为中心，向上下扩展标准差
            min_price = max(al, mean_price - 3 * std_price)
            max_price = min(ah, mean_price + 3 * std_price)
            breaks = np.linspace(min_price, max_price, n+1)
        else:
            breaks = np.linspace(al, ah, n+1)
    else:
        # 默认等距划分
        breaks = np.linspace(al, ah, n+1)
    
    # 计算每个交易日在各区间的成交量
    for bar in data:
        h, l, vol = bar["high"], bar["low"], bar["volume"]
        bar["bands"] = [0] * n
        if h != l:
            vp = vol / (h - l)
            for b in range(n):
                lo, hi = breaks[b], breaks[b+1]
                ol, oh = max(lo, l), min(hi, h)
                if ol < oh:
                    bar["bands"][b] = vp * (oh - ol)
    
    # 计算累计筹码和百分比
    cum = [0] * n
    for bar in data:
        cum = [cum[b] + bar["bands"][b] for b in range(n)]
        bar["cb"] = list(cum)
        tot = sum(cum)
        bar["cp"] = [c / tot * 100 if tot else 0 for c in cum]
    
    return data, al, ah, breaks

CSS = """* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0a0e1a; color: #e0e0e0; padding: 20px; max-width: 1400px; margin: 0 auto; }
.controls { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; background: #16213e; border-radius: 14px; padding: 12px 16px; margin-bottom: 14px; border: 1px solid #0f3460; }
.ctrl-group { display: flex; align-items: center; gap: 6px; }
.ctrl-label { font-size: 12px; color: #7a8ba8; font-weight: 600; }
.ctrl-head { font-size: 11px; color: #444; margin-bottom: 6px; font-weight: 600; letter-spacing: 0.5px; }
89| input[type=date], input[type=number], input[type=text] { background: #0f1a2e; border: 1px solid #0f3460; border-radius: 6px; color: #e0e0e0; padding: 5px 8px; font-size: 12px; outline: none; }
90| input[type=date]:focus, input[type=number]:focus, input[type=text]:focus { border-color: #4488ff; }
input[type=number] { width: 60px; }
button { background: #1e3a6e; border: 1px solid #2a5298; color: #e0e0e0; padding: 5px 14px; border-radius: 6px; font-size: 12px; cursor: pointer; font-weight: 600; transition: background 0.2s; }
button:hover { background: #2a5298; }
.btn-reset { background: #1e3a3a; border-color: #2a4a4a; }
.btn-reset:hover { background: #2a4a4a; }
.lg { display: flex; flex-wrap: wrap; gap: 8px; }
.li { display: flex; align-items: center; gap: 6px; cursor: pointer; background: rgba(255,255,255,0.05); padding: 5px 10px; border-radius: 8px; transition: all 0.2s; font-size: 13px; }
.li:hover { background: rgba(255,255,255,0.12); }
.li.inactive { opacity: 0.35; }
.li.disabled { opacity: 0.2; pointer-events: none; }
.ls { width: 14px; height: 14px; border-radius: 3px; flex-shrink: 0; display: inline-block; }
.ll { color: #ccc; }
.lp { color: #fff; font-weight: 600; margin-left: 4px; }
.cb { background: #16213e; border-radius: 14px; padding: 16px; margin-bottom: 14px; border: 1px solid #0f3460; }
.ct { font-size: 13px; color: #7a8ba8; margin-bottom: 10px; font-weight: 600; letter-spacing: 0.5px; }
.bd { background: #51cf66; color: #000; font-size: 10px; padding: 2px 6px; border-radius: 4px; margin-left: 8px; font-weight: 700; }
.tt { background: rgba(0,0,0,0.35); border-radius: 8px; padding: 10px 14px; margin-bottom: 10px; min-height: 60px; font-size: 12px; }
.tt-date { color: #8a9bbf; font-size: 11px; margin-bottom: 6px; }
.tt-row { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.tt-swatch { width: 10px; height: 10px; border-radius: 2px; flex-shrink: 0; display: inline-block; }
.tt-label { color: #aaa; width: 90px; flex-shrink: 0; }
.tt-barbg { flex: 1; background: rgba(255,255,255,0.06); border-radius: 3px; height: 6px; }
.tt-bar { height: 6px; border-radius: 3px; max-width: 100%; }
.tt-pct { color: #fff; font-weight: 600; width: 40px; text-align: right; }
.tt-price { margin-top: 6px; color: #51cf66; font-weight: 600; }
.tt-obv { color: #a78bfa; margin-top: 4px; }
.tt-warn { color: #fbbf24; margin-top: 6px; font-size: 11px; }
.ab { background: #16213e; border-radius: 14px; padding: 16px; margin-bottom: 14px; border: 1px solid #0f3460; overflow-x: auto; }
.at { font-size: 13px; color: #7a8ba8; margin-bottom: 10px; font-weight: 600; }
.tbl { width: 100%; border-collapse: collapse; font-size: 13px; }
.tbl th { color: #7a8ba8; text-align: left; padding: 6px 10px; border-bottom: 1px solid #0f3460; font-weight: 600; }
.tbl td { padding: 7px 10px; border-bottom: 1px solid rgba(255,255,255,0.04); color: #ccc; }
.tbl tr:hover td { background: rgba(255,255,255,0.03); }
.dc { background: #16213e; border-radius: 14px; padding: 16px; border: 1px solid #0f3460; font-size: 12px; line-height: 1.8; color: #7a8ba8; }
.dc strong { color: #e0e0e0; }
.chart-row { display: flex; align-items: stretch; gap: 14px; margin-bottom: 14px; }
.chart-row .cb { flex: 1; margin-bottom: 0; min-height: 200px; }
.chart-row .tt { width: 240px; flex-shrink: 0; min-height: 200px; margin: 0; }
.chart-row canvas { width: 100%; height: 100%; }
"""

def make_js(dates, closes, bcum, blabs, cols, obvs, ano, n_bands):
    L  = json.dumps(dates)
    CP = json.dumps(closes)
    CB = json.dumps(bcum)
    BL = json.dumps(blabs)
    LC = json.dumps(cols)
    OV = json.dumps(obvs)
    AI = json.dumps([x["i"] for x in ano])
    AL = json.dumps([x["l"] for x in ano])
    AC = json.dumps([x["c"] for x in ano])
    NB = str(n_bands)

    cd_parts = []
    for i in range(n_bands):
        cd_parts.append(
            "{label:" + BL + "[" + str(i) + "]+' (percent)',"
            "data:" + CB + "[" + str(i) + "],"
            "borderColor:" + LC + "[" + str(i) + "],"
            "backgroundColor:'transparent',"
            "borderWidth:1.8,"
            "pointRadius:0,"
            "pointHoverRadius:3,"
            "tension:0.25,"
            "fill:false,"
            "yAxisID:'y'}"
        )
    pd = (
        "{label:'收盘价 ($)',"
        "data:" + CP + ","
        "borderColor:'#e0e0e0',"
        "backgroundColor:'rgba(224,224,224,0.06)',"
        "borderWidth:2,"
        "pointRadius:0,"
        "pointHoverRadius:4,"
        "tension:0.25,"
        "fill:true,"
        "yAxisID:'y1',"
        "order:-1}"
    )
    c1_datasets = "[" + ",".join(cd_parts) + "," + pd + "]"

    obv_ds = (
        "[{label:'OBV',"
        "data:" + OV + ","
        "borderColor:'rgba(167,139,250,0.8)',"
        "backgroundColor:'rgba(167,139,250,0.05)',"
        "borderWidth:1.5,"
        "pointRadius:0,"
        "pointHoverRadius:3,"
        "tension:0.3,"
        "fill:true}]"
    )

    js_template = """
var L={L},CP={CP},CB={CB},BL={BL},LC={LC},OV={OV},AI={AI},AL={AL},AC={AC},NB={NB};
var curBandMin=0,curBandMax=NB-1;

// Date range + band range filtering functions
function applyRange(){{
  var sd=document.getElementById('startDate').value;
  var ed=document.getElementById('endDate').value;
  var si=ALL_L.indexOf(sd),ei=ALL_L.indexOf(ed);
  if(si==-1||ei==-1||si>ei){{alert('请选择有效的日期范围');return;}}
  L=ALL_L.slice(si,ei+1);
  CP=ALL_CP.slice(si,ei+1);
  OV=ALL_OV.slice(si,ei+1);
  CB=ALL_CB.map(function(band){{return band.slice(si,ei+1);}});
  redrawCharts();
}}
function resetRange(){{
  document.getElementById('startDate').value=ALL_L[0];
  document.getElementById('endDate').value=ALL_L[ALL_L.length-1];
  L=ALL_L;CP=ALL_CP;OV=ALL_OV;CB=ALL_CB;
  resetBands();
}}
function applyBands(){{
  var bmin=parseInt(document.getElementById('bandMin').value);
  var bmax=parseInt(document.getElementById('bandMax').value);
  if(isNaN(bmin)||isNaN(bmax)||bmin<0||bmax>=NB||bmin>bmax){{
    alert('请输入有效的档位范围 (0-'+(NB-1)+')');return;}}
  curBandMin=bmin;curBandMax=bmax;
  for(var i=0;i<NB;i++){{
    var el=document.getElementById('leg'+i);
    var ds=c1.data.datasets[i];
    if(i>=bmin&&i<=bmax){{
      el.classList.remove('disabled');
      if(!hidden[i])ds.borderWidth=1.8;
    }}else{{
      el.classList.add('disabled');
      ds.borderWidth=0;
    }}
  }}
  c1.update('none');
}}
function resetBands(){{
  document.getElementById('bandMin').value=0;
  document.getElementById('bandMax').value=NB-1;
  curBandMin=0;curBandMax=NB-1;
  for(var i=0;i<NB;i++){{
    var el=document.getElementById('leg'+i);
    var ds=c1.data.datasets[i];
    el.classList.remove('disabled');
    if(!hidden[i])ds.borderWidth=1.8;
  }}
  c1.update('none');
}}
function redrawCharts(){{
  c1.data.labels=L;
  c1.data.datasets.forEach(function(ds,i){{
    if(i<NB)ds.data=CB[i];
  }});
  c1.data.datasets[NB].data=CP;
  c2.data.labels=L;
  c2.data.datasets[0].data=OV;
  c1.update();
  c2.update();
  updateBothPanels(L.length-1);
}}

function updateBothPanels(idx){{
  var li=(idx===undefined||idx<0)?L.length-1:idx;
  var ld=L[li],lc=CP[li],obv=OV[li];
  
  // 显示前前一天的筹码分布（最左侧）
  var li_prev2=li-2;
  if(li_prev2>=0){{
    var ld_prev2=L[li_prev2],lc_prev2=CP[li_prev2];
    var bands_prev2=[];
    for(var b=curBandMin;b<=curBandMax;b++){{bands_prev2.push({{l:BL[b],v:CB[b][li_prev2],c:LC[b],idx:b}});}}
    bands_prev2.sort(function(a,b){{return a.idx-b.idx;}});
    var h_prev2='<div class=tt-date>'+ld_prev2+'</div>';
    for(var i=bands_prev2.length-1;i>=0;i--){{
      var b=bands_prev2[i];
      var pct=parseFloat(b.v).toFixed(1);
      var w=Math.max(3,pct*1.5);
      h_prev2+='<div class=tt-row><span class=tt-swatch style="background:'+b.c+'"></span><span class=tt-label>'+b.l+'</span><div class=tt-barbg><div class=tt-bar style="width:'+w+'%;background:'+b.c+'"></div></div><span class=tt-pct>'+pct+'%</span></div>';
    }}
    h_prev2+='<div class=tt-price>收盘: $'+parseFloat(lc_prev2).toFixed(2)+'</div>';
    document.getElementById('tt1').innerHTML=h_prev2;
  }} else {{
    document.getElementById('tt1').innerHTML='<div class=tt-date>无数据</div>';
  }}
  
  // 显示前一天的筹码分布（中间）
  var li_prev1=li-1;
  if(li_prev1>=0){{
    var ld_prev1=L[li_prev1],lc_prev1=CP[li_prev1];
    var bands_prev1=[];
    for(var b=curBandMin;b<=curBandMax;b++){{bands_prev1.push({{l:BL[b],v:CB[b][li_prev1],c:LC[b],idx:b}});}}
    bands_prev1.sort(function(a,b){{return a.idx-b.idx;}});
    var h_prev1='<div class=tt-date>'+ld_prev1+'</div>';
    for(var i=bands_prev1.length-1;i>=0;i--){{
      var b=bands_prev1[i];
      var pct=parseFloat(b.v).toFixed(1);
      var w=Math.max(3,pct*1.5);
      h_prev1+='<div class=tt-row><span class=tt-swatch style="background:'+b.c+'"></span><span class=tt-label>'+b.l+'</span><div class=tt-barbg><div class=tt-bar style="width:'+w+'%;background:'+b.c+'"></div></div><span class=tt-pct>'+pct+'%</span></div>';
    }}
    h_prev1+='<div class=tt-price>收盘: $'+parseFloat(lc_prev1).toFixed(2)+'</div>';
    document.getElementById('tt3').innerHTML=h_prev1;
  }} else {{
    document.getElementById('tt3').innerHTML='<div class=tt-date>无数据</div>';
  }}
  
  // 显示当天的筹码分布（最右侧）
  var bands=[];
  for(var b=curBandMin;b<=curBandMax;b++){{bands.push({{l:BL[b],v:CB[b][li],c:LC[b],idx:b}});}}
  bands.sort(function(a,b){{return a.idx-b.idx;}});
  var h='<div class=tt-date>'+ld+'</div>';
  for(var i=bands.length-1;i>=0;i--){{
    var b=bands[i];
    var pct=parseFloat(b.v).toFixed(1);
    var w=Math.max(3,pct*1.5);
    h+='<div class=tt-row><span class=tt-swatch style="background:'+b.c+'"></span><span class=tt-label>'+b.l+'</span><div class=tt-barbg><div class=tt-bar style="width:'+w+'%;background:'+b.c+'"></div></div><span class=tt-pct>'+pct+'%</span></div>';
  }}
  h+='<div class=tt-price>收盘: $'+parseFloat(lc).toFixed(2)+'</div>';
  document.getElementById('tt4').innerHTML=h;
  
  // 更新OBV能量潮
  var fi=AI.indexOf(li);
  var extra=fi!==-1?'<div class=tt-warn>&#x26A0; '+AL[fi]+' ($'+AC[fi]+')</div>':'';
  document.getElementById('tt2').innerHTML='<div class=tt-date>'+ld+'</div><div class=tt-obv>OBV: '+Number(obv).toLocaleString()+'</div>'+extra;
}}
function showChipTooltip(ctx){{
  var M=ctx.tooltip;
  if(M.opacity===0){{updateBothPanels(L.length-1);return;}}
  var idx=(M.dataPoints&&M.dataPoints[0])?M.dataPoints[0].dataIndex:L.length-1;
  updateBothPanels(idx);
}}
function showObvTooltip(ctx){{
  var M=ctx.tooltip;
  if(M.opacity===0){{updateBothPanels(L.length-1);return;}}
  var idx=(M.dataPoints&&M.dataPoints[0])?M.dataPoints[0].dataIndex:L.length-1;
  updateBothPanels(idx);
}}
var hidden={{}};
var c1=new Chart(document.getElementById('c1'),{{
type:'line',
data:{{labels:L,datasets:{c1_datasets}}},
options:{{
responsive:true,
interaction:{{mode:'index',intersect:false}},
plugins:{{legend:{{display:false}},tooltip:{{enabled:false,external:showChipTooltip}}}},
scales:{{
x:{{grid:{{color:'rgba(255,255,255,0.03)'}},ticks:{{color:'#555',font:{{size:10}},maxTicksLimit:20}}}},
y:{{min:0,max:100,position:'left',grid:{{color:'rgba(255,255,255,0.04)'}},ticks:{{color:'#777',callback:function(v){{return v+'%';}},font:{{size:10}}}},title:{{display:true,text:'累计筹码占比 (%)',color:'#555',font:{{size:10}}}}}},
y1:{{position:'right',grid:{{drawOnChartArea:false}},ticks:{{color:'#aaa',font:{{size:10}}}},title:{{display:true,text:'收盘价 ($)',color:'#aaa',font:{{size:10}}}}}}
}}
}}
}});
var c2=new Chart(document.getElementById('c2'),{{
type:'line',
data:{{labels:L,datasets:{obv_ds}}},
options:{{
responsive:true,
interaction:{{mode:'index',intersect:false}},
plugins:{{legend:{{display:false}},tooltip:{{enabled:false,external:showObvTooltip}}}},
scales:{{
x:{{grid:{{color:'rgba(255,255,255,0.03)'}},ticks:{{color:'#555',font:{{size:10}},maxTicksLimit:20}}}},
y:{{grid:{{color:'rgba(255,255,255,0.04)'}},ticks:{{color:'#888',font:{{size:10}}}},title:{{display:true,text:'OBV',color:'#a78bfa',font:{{size:10}}}}}}
}}
}}
}});
updateBothPanels(L.length-1);
document.getElementById('c1').addEventListener('mouseleave',function(){{updateBothPanels(L.length-1);}});
document.getElementById('c2').addEventListener('mouseleave',function(){{updateBothPanels(L.length-1);}});
function tk(i){{
var el=document.getElementById('leg'+i);
if(hidden[i]){{delete hidden[i];el.classList.remove('inactive');c1.data.datasets[i].borderWidth=1.8;}}else{{hidden[i]=true;el.classList.add('inactive');c1.data.datasets[i].borderWidth=0;}}
c1.update('none');
}}
var allLegs=document.querySelectorAll('.li');
for(var i=0;i<allLegs.length;i++){{
allLegs[i].addEventListener('dblclick',function(){{
hidden={{}};
var legs=document.querySelectorAll('.li');
for(var j=0;j<legs.length;j++){{legs[j].classList.remove('inactive');}}
for(var k=0;k<NB;k++){{c1.data.datasets[k].borderWidth=1.8;}}
c1.update('none');
}});
}}
"""
    js = js_template.format(
        L=L, CP=CP, CB=CB, BL=BL, LC=LC, OV=OV,
        AI=AI, AL=AL, AC=AC, NB=NB,
        c1_datasets=c1_datasets, obv_ds=obv_ds
    )
    return js

def write_html(data, symbol, al, ah, breaks, anomalies, n_bands, method, outpath):
    dates  = [x["date"]  for x in data]
    closes = [round(x["close"],2) for x in data]
    obvs   = [int(round(x["obv"])) for x in data]
    bcum   = [[round(x["cp"][b],2) for x in data] for b in range(n_bands)]
    blabs  = ["$%.1f-$%.1f"%(breaks[b],breaks[b+1]) for b in range(n_bands)]
    cols   = ["#ff4444","#ff9944","#ffdd44","#44dd44","#44ddaa","#4488ff","#aa44ff","#ff44ff","#ff77aa","#cc9944"]
    mp     = {x["date"]:i for i,x in enumerate(data)}
    ano    = [{"i":mp[a["date"]],"l":a["label"],"c":a["close"]} for a in anomalies if a["date"] in mp]
    ld     = dates[-1]
    lc     = closes[-1]

    leg = "".join(
        '<div class="li" id="leg%d" onclick="tk(%d)">' 
        '<span class="ls" style="background:%s"></span>'
        '<span class="ll">%s</span>'
        '<span class="lp">%.1f%%</span></div>\n' % (i,i,cols[i],blabs[i],bcum[i][-1])
        for i in reversed(range(n_bands))
    )
    arows = "".join(
        '<tr><td>%s</td><td style="color:#ff9944">%s</td><td>$%.2f</td><td>%s</td></tr>\n'
        % (a["date"],a["label"],a["close"],a["atype"])
        for a in anomalies[-10:]
    )

    js_code = make_js(dates, closes, bcum, blabs, cols, obvs, ano, n_bands)

    # Prepare ALL data for client-side filtering
    all_dates  = json.dumps(dates)
    all_closes = json.dumps(closes)
    all_obvs   = json.dumps(obvs)
    all_bcum   = json.dumps(bcum)
    all_blabs  = json.dumps(blabs)
    all_cols   = json.dumps(cols)

    # Stock code input HTML
    stock_input_html = '''<div class="controls">
  <div>
    <div class="ctrl-head">股票代码查询</div>
    <div style="display:flex;gap:10px;align-items:center;">
      <div class="ctrl-group">
        <span class="ctrl-label">股票代码</span>
        <input type="text" id="stockCode" placeholder="输入股票代码（如 OKLO）" style="width:120px;">
      </div>
      <button onclick="queryStock()">查询</button>
    </div>
  </div>
</div>
'''

    # Controls HTML
    controls_html = '''<div class="controls">
  <div>
    <div class="ctrl-head">时间范围</div>
    <div style="display:flex;gap:10px;align-items:center;">
      <div class="ctrl-group">
        <span class="ctrl-label">从</span>
        <input type="date" id="startDate" value="%s">
      </div>
      <div class="ctrl-group">
        <span class="ctrl-label">到</span>
        <input type="date" id="endDate" value="%s">
      </div>
      <button onclick="applyRange()">应用</button>
      <button class="btn-reset" onclick="resetRange()">重置</button>
    </div>
  </div>
  <div style="border-left:1px solid #0f3460;padding-left:12px;">
    <div class="ctrl-head">筹码区间（档位 0-%d）</div>
    <div style="display:flex;gap:10px;align-items:center;">
      <div class="ctrl-group">
        <span class="ctrl-label">从</span>
        <input type="number" id="bandMin" value="0" min="0" max="%d">
      </div>
      <div class="ctrl-group">
        <span class="ctrl-label">到</span>
        <input type="number" id="bandMax" value="%d" min="0" max="%d">
      </div>
      <button onclick="applyBands()">应用</button>
      <button class="btn-reset" onclick="resetBands()">重置</button>
    </div>
  </div>
  <div style="border-left:1px solid #0f3460;padding-left:12px;">
    <div class="ctrl-head">划分方式</div>
    <div style="display:flex;gap:10px;align-items:center;">
      <div class="ctrl-group">
        <span class="ctrl-label">方法</span>
        <select id="distributionMethod" onchange="changeMethod()" style="background: #0f1a2e; border: 1px solid #0f3460; border-radius: 6px; color: #e0e0e0; padding: 5px 8px; font-size: 12px; outline: none;">
          <option value="equal_interval" %s>等距划分</option>
          <option value="equal_frequency" %s>等频划分</option>
          <option value="logarithmic" %s>对数划分</option>
          <option value="volume_weighted" %s>成交量加权划分</option>
          <option value="standard_deviation" %s>标准差划分</option>
        </select>
      </div>
    </div>
  </div>
</div>
''' % (dates[0], dates[-1], n_bands-1, n_bands-1, n_bands-1, n_bands-1, 
        'selected' if method == 'equal_interval' else '',
        'selected' if method == 'equal_frequency' else '',
        'selected' if method == 'logarithmic' else '',
        'selected' if method == 'volume_weighted' else '',
        'selected' if method == 'standard_deviation' else '')

    with open(outpath, "w", encoding="utf-8") as fout:
        fout.write("<!DOCTYPE html>\n")
        fout.write("<html lang=\"zh\">\n")
        fout.write("<head>\n")
        fout.write("<meta charset=\"UTF-8\">\n")
        fout.write("<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n")
        fout.write("<title>%s 筹码分布</title>\n" % symbol)
        chart_js_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chart.umd.min.js")
        if os.path.exists(chart_js_path):
            with open(chart_js_path, "r", encoding="utf-8") as cf:
                chart_js_content = cf.read()
            fout.write("<script>" + chart_js_content + "</script>\n")
        else:
            subprocess.run('curl -s -o "%s" "https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"' % chart_js_path, shell=True, timeout=30)
            if os.path.exists(chart_js_path) and os.path.getsize(chart_js_path) > 1000:
                with open(chart_js_path, "r", encoding="utf-8") as cf:
                    chart_js_content = cf.read()
                fout.write("<script>" + chart_js_content + "</script>\n")
            else:
                fout.write("<script src=\"https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js\"></script>\n")
        fout.write("<style>\n%s</style>\n" % CSS)
        fout.write("</head>\n")
        fout.write("<body>\n")
        # Add stock code input
        fout.write('<div class="controls">\n')
        fout.write('  <div>\n')
        fout.write('    <div class="ctrl-head">股票代码查询</div>\n')
        fout.write('    <div style="display:flex;gap:10px;align-items:center;">\n')
        fout.write('      <div class="ctrl-group">\n')
        fout.write('        <span class="ctrl-label">股票代码</span>\n')
        fout.write('        <input type="text" id="stockCode" placeholder="输入股票代码（如 OKLO）" style="width:120px;">\n')
        fout.write('      </div>\n')
        fout.write('      <button onclick="queryStock()">查询</button>\n')
        fout.write('    </div>\n')
        fout.write('  </div>\n')
        fout.write('</div>\n')
        fout.write(controls_html)
        fout.write("<div style=\"background:#16213e;border-radius:14px;padding:12px 16px;margin-bottom:14px;border:1px solid #0f3460;\"><div style=\"font-size:11px;color:#444;margin-bottom:8px;\">点击图例单独查看，双击恢复全部   |   异动日 = 放量>2.5倍均量 或 涨跌>8%</div><div class=\"lg\">\n")
        fout.write(leg)
        fout.write("</div></div>\n")
        fout.write("<div class=\"chart-row\" style=\"justify-content: space-between;\"><div class=\"tt\" id=\"tt1\" style=\"flex: 1; margin-right: 10px;\"></div><div class=\"tt\" id=\"tt3\" style=\"flex: 1; margin-right: 10px;\"></div><div class=\"tt\" id=\"tt4\" style=\"flex: 1;\"></div></div>\n")
        fout.write("<div class=\"chart-row\"><div class=\"cb\"><div class=\"ct\">筹码累计分布（%） + 收盘价走势（$）<span class=\"bd\">NEW</span></div><canvas id=\"c1\"></canvas></div></div>\n")
        fout.write("<div class=\"chart-row\"><div class=\"cb\"><div class=\"ct\">OBV 能量潮</div><canvas id=\"c2\"></canvas></div><div class=\"tt\" id=\"tt2\"></div></div>\n")
        if anomalies:
            fout.write("<div class=\"ab\"><div class=\"at\">量价异动日（最近 " + str(min(10,len(anomalies))) + " 条） 机构最可能参与的节点</div><table class=\"tbl\"><tr><th>日期</th><th>异动</th><th>收盘价</th><th>类型</th></tr><br>" + arows + "</table></div>\n")
        fout.write("<div class=\"dc\"><strong>读图指南：</strong><br><strong>主图：</strong>左轴（%）累计筹码占比，右轴（$）收盘价（灰粗线）。<br><strong>OBV 副图：</strong>能量潮，跟涨绿/跟跌红；OBV 持续上升 = 资金净流入。<br><strong>异动日：</strong>出现在 OBV tooltip 里（⚠ 标记）。<br><strong>实战：</strong>看当前股价是否在「放量暴涨日收盘价」之上 若长期在之下，说明机构可能已撤退。</div>\n")
        # Store all data globally for client-side filtering
        fout.write("<script>\n")
        fout.write("var ALL_L=" + all_dates + ",ALL_CP=" + all_closes + ",ALL_OV=" + all_obvs + ";\n")
        fout.write("var ALL_CB=" + all_bcum + ",ALL_BL=" + all_blabs + ",ALL_LC=" + all_cols + ";\n")
        fout.write("var NB=" + str(n_bands) + ";\n")
        fout.write("function queryStock() {\n")
        fout.write("  var stockCode = document.getElementById('stockCode').value.trim().toUpperCase();\n")
        fout.write("  if (!stockCode) {\n")
        fout.write("    alert('请输入股票代码');\n")
        fout.write("    return;\n")
        fout.write("  }\n")
        fout.write("  // 构建新的URL，跳转到查询页面\n")
        fout.write("  var url = window.location.href.replace(/[^/]+\.html$/, stockCode + '_chip.html');\n")
        fout.write("  // 尝试加载新页面\n")
        fout.write("  window.location.href = url;\n")
        fout.write("}\n")
        fout.write("function changeMethod() {\n")
        fout.write("  var method = document.getElementById('distributionMethod').value;\n")
        fout.write("  // 构建新的URL，包含新的划分方式\n")
        fout.write("  var url = window.location.href;\n")
        fout.write("  // 提取股票代码\n")
        fout.write("  var match = url.match(/([^/]+)_chip\.html$/);\n")
        fout.write("  if (match) {\n")
        fout.write("    var symbol = match[1];\n")
        fout.write("    // 重新加载页面，使用新的划分方式\n")
        fout.write("    var newUrl = 'http://localhost:8888/' + symbol + '_chip_' + method + '.html';\n")
        fout.write("    window.location.href = newUrl;\n")
        fout.write("  }\n")
        fout.write("}\n")
        fout.write("</script>\n")
        fout.write("<script>" + js_code + "</script>\n")
        fout.write("</body>\n</html>\n")

    print("Saved: " + outpath)
    if anomalies:
        print("\nAnomalies: %d (top 10):" % len(anomalies))
        for a in anomalies[:10]: print("  %s  %-22s  $%.2f  %s" % (a["date"], a["label"], a["close"], a["atype"]))
    print("\nChip distribution (%s $%.2f):" % (ld, lc))
    for b in range(n_bands):
        pct=bcum[b][-1]; bar_str=chr(9608)*int(pct/3)
        print("  $%.1f-$%.1f  %5.1f%%  %s" % (breaks[b], breaks[b+1], pct, bar_str))

def main():
    p=argparse.ArgumentParser()
    p.add_argument("-s","--symbol",required=True)
    p.add_argument("-d","--days",type=int,default=365)
    p.add_argument("--start-date")
    p.add_argument("-o","--output")
    p.add_argument("--proxy")
    p.add_argument("--method",default="equal_interval", choices=["equal_interval", "equal_frequency", "logarithmic", "volume_weighted", "standard_deviation"])
    a=p.parse_args()
    sym=a.symbol.upper()
    if not any(sym.endswith(x) for x in [".US",".HK",".SS",".SZ"]): sym += ".US"
    days=a.days
    
    data=fetch(sym,days,a.start_date,a.proxy)
    if not data: print("No data"); sys.exit(1)
    data=obv(data)
    ano=anomalies(data)
    
    # 为所有划分方式生成HTML文件
    methods = ["equal_interval", "equal_frequency", "logarithmic", "volume_weighted", "standard_deviation"]
    for method in methods:
        data_copy = data.copy()
        data_copy,al,ah,breaks=chip(data_copy,10,method)
        ofn=a.output or sym.replace(".US","" )+"_chip_"+method+".html"
        write_html(data_copy,sym.replace(".US","").replace(".HK","").replace(".SS","").replace(".SZ",""),al,ah,breaks,ano,10,method,ofn)

if __name__=="__main__": main()