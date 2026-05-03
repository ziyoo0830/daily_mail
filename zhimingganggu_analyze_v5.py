#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
港股技术面全量扫描系统
逻辑：获取港股列表 -> 全量技术因子评分 -> 动态风控计算 -> 邮件推送
输出：按 1年回撤幅度(drop_1y) 倒序排列，超跌标的优先
"""
import sys, io, os, smtplib
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import xcsc_tushare as ts
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from opencc import OpenCC
import akshare as ak

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from email.utils import formataddr
from email.mime.image import MIMEImage

import matplotlib.pyplot as plt
from io import BytesIO

# ============================================
# 1. 配置中心
# ============================================
class Config:
    TOKEN = '5b7f9a4551a1dd0e378ae2a7522e2ebd3d3c2e873caed0e9a4668066'
    SERVER = 'http://116.128.206.39:7172'
    
    EMAIL_HOST, EMAIL_PORT = 'smtp.qq.com', 465
    EMAIL_USER = '260319029@qq.com'
    EMAIL_PASS = 'tofijpcsxefvbghg'
    EMAIL_RECEIVER = ['ziyoo0830@163.com']
    
    MIN_AMOUNT = 5e5       # 基础流动性门槛（防无效数据）
    LOOKBACK_DAYS = 365
    
    STRATEGY_PARAMS = {
        'lookback': 250,
        'stop_loss_mult': 2.5,
        'take_profit_ratio': 2.0,
        'atr_period': 14
    }

ts.set_token(Config.TOKEN)
pro = ts.pro_api(server=Config.SERVER)
converter = OpenCC('t2s')

# ============================================
# 2. 工具函数
# ============================================
def get_offset_date(days_offset):
    """获取偏移日期，统一入口"""
    return (datetime.now() + timedelta(days=days_offset)).strftime('%Y%m%d')

def clean_numeric(series):
    return pd.to_numeric(series, errors='coerce')

def is_today_trading_day(today):
    """查询交易日历（A股）"""
    try:
        df = pro.trade_cal(start_date=today, end_date=today, is_open='1')
        return not df.empty
    except Exception as e:
        print(f"查询交易日历失败: {e}")
        return False

# ============================================
# 3. 数据获取
# ============================================
def fetch_stock_list():
    cache = 'zhimingganggu.xlsx'
    try:
        df = ak.stock_hk_famous_spot_em()
        df.to_excel(cache, index=False)
        return df
    except Exception as e:
        if os.path.exists(cache):
            return pd.read_excel(cache, dtype=str)
        raise Exception(f"获取港股列表失败: {e}")

def get_data_safe_tushare(symbol, days):
    try:
        ts_code = str(symbol.split('.')[0]).zfill(5) + ".HK"
        end_dt = pd.Timestamp.now().strftime('%Y%m%d')
        start_dt = (pd.Timestamp.now() - pd.Timedelta(days=600)).strftime('%Y%m%d')
        df = pro.hk_daily(ts_code=ts_code, start_date=start_dt, end_date=end_dt)
        if df is None or df.empty: return None
        df = df.sort_values('trade_date').reset_index(drop=True)
        return df.tail(days).reset_index(drop=True) if len(df) >= 60 else None
    except: return None

# ============================================
# 4. 核心策略 (纯技术面)
# ============================================
def calc_technical_score(df):
    """技术面多因子评分 (0-100)"""
    c, h, l, v = df['close'], df['high'], df['low'], df['vol']
    score, signals = 50, []
    cur = c.iloc[-1]

    # 1. 均线趋势 (25分)
    ma5, ma10, ma20, ma60 = [c.rolling(n).mean().iloc[-1] for n in (5,10,20,60)]
    if cur > ma5 > ma10 > ma20:
        score += 20; signals.append("多头排列")
    elif cur > ma20:
        score += 10; signals.append("站上MA20")
    elif cur < ma60:
        score -= 10; signals.append("受制MA60")

    # 2. 超跌动量 RSI+KDJ (30分)
    delta = c.diff()
    rs = delta.clip(lower=0).rolling(14).mean() / (-delta.clip(upper=0)).rolling(14).mean() + 1e-9
    rsi = (100 - 100/(1+rs)).iloc[-1]
    if rsi <= 35: score += 15; signals.append(f"RSI超跌({rsi:.0f})")
    elif 35 < rsi < 65: score += 10; signals.append(f"RSI修复({rsi:.0f})")
    elif rsi >= 80: score -= 10; signals.append(f"RSI超买({rsi:.0f})")

    low9, high9 = l.rolling(9).min(), h.rolling(9).max()
    rsv = (c - low9) / (high9 - low9 + 1e-9) * 100
    k = rsv.ewm(com=2, adjust=False).mean()
    d = k.ewm(com=2, adjust=False).mean()
    j = 3*k.iloc[-1] - 2*d.iloc[-1]
    if k.iloc[-1] < 25 and j > k.iloc[-1]:
        score += 15; signals.append("KDJ低位金叉")
    elif k.iloc[-1] > 80:
        score -= 5; signals.append("KDJ高位")

    # 3. 量价配合 (20分)
    vol_ma5, vol_ma20 = v.rolling(5).mean().iloc[-1], v.rolling(20).mean().iloc[-1]
    ret = c.pct_change().iloc[-1]
    if ret > 0 and v.iloc[-1] > vol_ma5*1.5:
        score += 15; signals.append("放量上涨")
    elif ret < 0 and v.iloc[-1] < vol_ma20*0.8:
        score += 10; signals.append("缩量回调")
    elif ret < 0 and v.iloc[-1] > vol_ma5*1.5:
        score -= 15; signals.append("放量下跌")

    # 4. 形态支撑 (25分)
    std20 = c.rolling(20).std().iloc[-1]
    bb_lower = ma20 - 2*std20
    bb_upper = ma20 + 2*std20
    bb_pos = (cur - bb_lower) / (bb_upper - bb_lower + 1e-9)
    if 0.15 < bb_pos < 0.5:
        score += 15; signals.append("布林中下轨企稳")
    elif bb_pos <= 0.1:
        score += 10; signals.append("触及布林下轨")
    
    if cur > l.tail(20).min() * 1.05:
        score += 10; signals.append("脱离近期低点")

    return max(0, min(100, score)), signals

def calc_risk_levels(df, params):
    """动态风控计算 (止损/止盈/ATR)"""
    c, h, l = clean_numeric(df['close']), clean_numeric(df['high']), clean_numeric(df['low'])
    valid = c.notna() & h.notna() & l.notna()
    if valid.sum() < 20: return None, None, None
    c, h, l = c[valid], h[valid], l[valid]
    cur = c.iloc[-1]

    tr = pd.concat([h-l, (h-c.shift(1)).abs(), (l-c.shift(1)).abs()], axis=1).max(axis=1)
    atr = tr.rolling(params['atr_period']).mean().iloc[-1]
    if pd.isna(atr) or atr <= 0: return None, None, None

    hard_stop = cur - atr * params['stop_loss_mult']
    recent_low = l.tail(20).min()
    stop = min(hard_stop, recent_low)
    if stop >= cur: stop = cur - 2*atr
    if stop <= 0: stop = cur * 0.9

    risk = cur - stop
    if risk <= 0: risk = cur * 0.05
    tp = cur + risk * params['take_profit_ratio']
    return round(stop,3), round(tp,3), round(atr,3)

def analyze_full_strategy(symbol, df):
    """主分析入口"""
    try:
        df = df.copy()
        for col in ['close','high','low','vol','amount']: df[col] = clean_numeric(df[col])
        df = df.dropna().reset_index(drop=True)
        if len(df) < 60: return None

        cur = df['close'].iloc[-1]
        # 基础数据质量过滤
        if cur < 0.5 or df['amount'].tail(20).mean() < Config.MIN_AMOUNT: return None
        if df['close'].pct_change().tail(10).std() > 0.15: return None

        score, signals = calc_technical_score(df)
        sl, tp, atr = calc_risk_levels(df, Config.STRATEGY_PARAMS)
        if sl is None or tp is None: return None

        if not (tp > cur > sl):
            score -= 30; signals.append("风控异常"); rr = 0.1
        else:
            rr = (tp - cur) / (cur - sl)
            if rr < 1.5: score -= 15; signals.append(f"盈亏比低({rr:.2f})")

        score = max(0, min(100, score))
        action = "重点关注" if score>=80 else "轻仓关注" if score>=70 else "观察" if score>=60 else "观望"
        status = "优质" if score>=75 else "一般" if score>=60 else "风险"

        return {
            'symbol': symbol, 'name': '未知', 'score': int(score), 'status': status,
            'price': round(cur,3), '止损位': round(sl,3), '止盈位': round(tp,3),
            '盈亏比': round(rr,2), 'signals': " | ".join(signals), 'action': action
        }
    except: return None

# ============================================
# 5. 邮件推送
# ============================================
plt.rcParams['font.sans-serif'] = ['SimHei','PingFang SC','Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False

def send_email_report(df, subject="📊 港股技术面扫描日报"):
    if df.empty:
        print("⚠️ 结果为空，跳过邮件。"); return
    try:
        msg = MIMEMultipart()
        msg['From'] = formataddr(("260319029", Config.EMAIL_USER), charset='utf-8')
        msg['To'] = Header(f"管理员 <{Config.EMAIL_RECEIVER[0]}>", 'utf-8')
        msg['Subject'] = Header(f"{subject} {get_offset_date(0)}", 'utf-8')

        html = f"""<html><head><style>
        table{{border-collapse:collapse;width:100%;font-family:sans-serif;font-size:12px}}
        th,td{{border:1px solid #ddd;padding:8px;text-align:center}}
        th{{background:#4CAF50;color:white}} tr:nth-child(even){{background:#f9f9f9}}
        </style></head><body>
        <h2>📊 今日技术面全量扫描结果</h2>
        <p>共分析 <strong>{len(df)}</strong> 只标的（纯技术因子+动态风控）</p>
        {df.to_html(index=False, border=0, classes='dataframe')}
        <p style="color:#888;font-size:11px;margin-top:20px">自动发送，仅供参考</p></body></html>"""
        msg.attach(MIMEText(html, 'html', 'utf-8'))

        fig, ax = plt.subplots(figsize=(18, max(5, len(df)*0.35)))
        ax.axis('off')
        tbl = ax.table(cellText=df.values, colLabels=df.columns, cellLoc='center', loc='center')
        tbl.auto_set_font_size(False); tbl.set_fontsize(9); tbl.scale(1.1, 1.5)
        for i in range(len(df.columns)): tbl[(0,i)].set_facecolor('#4CAF50'); tbl[(0,i)].set_text_props(color='white', weight='bold')
        
        buf = BytesIO()
        plt.savefig(buf, dpi=200, bbox_inches='tight', format='png'); buf.seek(0); plt.close()
        img = MIMEImage(buf.read(), _subtype='png')
        img.add_header('Content-Disposition', 'attachment', filename='HK_Tech_Screen.png')
        msg.attach(img)

        with smtplib.SMTP_SSL(Config.EMAIL_HOST, Config.EMAIL_PORT) as srv:
            srv.login(Config.EMAIL_USER, Config.EMAIL_PASS)
            srv.sendmail(Config.EMAIL_USER, Config.EMAIL_RECEIVER, msg.as_string())
        print("✅ 邮件发送成功")
    except Exception as e:
        print(f"❌ 邮件失败: {e}")

# ============================================
# 6. 主流程
# ============================================
def main():
    print("🚀 启动港股技术面全量扫描...")
    try: hk_list = fetch_stock_list()
    except Exception as e: print(f"致命错误: {e}"); return

    print(f"📋 获取到 {len(hk_list)} 只港股，开始全量技术面分析...")
    results = []
    
    for _, r in hk_list.iterrows():
        ts_code = str(r['代码']) + ".HK"
        name = converter.convert(r['名称'])
        
        df = get_data_safe_tushare(ts_code, Config.STRATEGY_PARAMS['lookback'])
        if df is None: continue
            
        # 清洗并计算参考指标
        df['close'] = clean_numeric(df['close'])
        df['amount'] = clean_numeric(df['amount'])
        df = df.dropna(subset=['close','amount']).sort_values('trade_date')
        if len(df) < 60: continue
            
        high_1y = df['close'].max()
        cur_price = df['close'].iloc[-1]
        drop_1y = (high_1y - cur_price) / high_1y  # 👈 数值型回撤
        
        res = analyze_full_strategy(ts_code, df)
        if res:
            res['name'] = name
            res['high_1y'] = round(high_1y, 3)
            res['drop_1y'] = f"{drop_1y:.1%}"      # 👈 显示用：百分比字符串
            res['_drop_num'] = drop_1y              # 👈 排序用：数值型
            results.append(res)
            print(f"  [{len(results)}] {res['name']} | 评分:{res['score']} | 回撤:{res['drop_1y']} | {res['action']}")

    if results:
        # 🔑 核心修改：按回撤幅度倒序排列（超跌优先）
        results.sort(key=lambda x: x['_drop_num'], reverse=True)
        
        df_out = pd.DataFrame(results)
        df_out['code'] = df_out['symbol'].str.replace('.HK','', regex=False)
        cols = ['code','name','score','price','high_1y','drop_1y','action','status','止损位','止盈位','盈亏比','signals']
        send_email_report(df_out[cols], "📈 港股技术面全量精选（按回撤倒序）")
    else:
        print("⚠️ 全量分析未产生有效结果（可能数据不足或流动性未达标）")
        send_email_report(pd.DataFrame(), "📭 技术面扫描无有效标的")

# ============================================
# 7. 入口
# ============================================
if __name__ == "__main__":
    today = get_offset_date(0)
    if is_today_trading_day(today):
        main()
    else:
        print(f"今天不是交易日 {today}，跳过扫描")