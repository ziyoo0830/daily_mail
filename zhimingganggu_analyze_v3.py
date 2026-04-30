#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
港股超跌选股系统 (修复版)
逻辑说明：筛选近一年跌幅 > 30% 的标的 -> 训练XGBoost模型 -> 计算风险点位 -> 发送邮件
修复重点：修正止盈/止损位计算逻辑，确保 止盈 > 现价 > 止损
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import xcsc_tushare as ts
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from opencc import OpenCC
# import akshare as ak
import xgboost as xgb
import smtplib
import os

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from email.utils import formataddr

import matplotlib.pyplot as plt
from io import BytesIO
from email.mime.image import MIMEImage

# ============================================
# 1. 配置中心 (Configuration)
# ============================================
class Config:
    # --- Token & API ---
    TOKEN = '5b7f9a4551a1dd0e378ae2a7522e2ebd3d3c2e873caed0e9a4668066'
    SERVER = 'http://116.128.206.39:7172'
    
    # --- 邮件配置 ---
    EMAIL_HOST = 'smtp.qq.com'
    EMAIL_PORT = 465
    EMAIL_USER = '260319029@qq.com'
    EMAIL_PASS = 'tofijpcsxefvbghg' # 授权码
    EMAIL_RECEIVER = ['ziyoo0830@163.com']
    
    # --- 筛选参数 ---
    DROP_THRESHOLD = -0.90  # 30%跌幅
    MIN_AMOUNT = 1e6       # 流动性阈值
    LOOKBACK_DAYS = 365    # 回溯天数
    
    # --- 交易策略参数 ---
    STRATEGY_PARAMS = {
        'lookback': 250,
        'cma_period': 20,
        'stop_loss_mult': 2.5,
        'take_profit_ratio': 2.0,
        'ml_threshold': 0.55,
        'atr_period': 14  # calc_risk_levels 函数需要这个键
    }

# 初始化全局对象
ts.set_token(Config.TOKEN)
pro = ts.pro_api(server=Config.SERVER)
converter = OpenCC('t2s')


# ============================================
# 2. 工具函数 (Utilities)
# ============================================
def get_offset_date(days_offset):
    """获取偏移日期字符串"""
    target_date = datetime.now() + timedelta(days=days_offset)
    return target_date.strftime('%Y%m%d')

def clean_numeric(series):
    """安全转换为数值"""
    return pd.to_numeric(series, errors='coerce')


# ============================================
# 3. 数据获取模块 (Data Acquisition)
# ============================================
def fetch_stock_list():
    """
    获取港股列表（优先本地缓存，失败则接口获取）
    Returns:
        pd.DataFrame: 包含代码和名称的港股列表
    """
    cache_file = 'zhimingganggu.xlsx'
    
    try:
        # 尝试从接口获取
        print("尝试从接口获取港股数据...")
        df = ak.stock_hk_famous_spot_em()
        df.to_excel(cache_file, index=False)
        print(f"✅ 接口获取成功并缓存至 {cache_file}")
        return df
    except Exception as e:
        print(f"❌ 接口获取失败: {e}，尝试读取本地缓存...")
    
    # 尝试读取本地
    if os.path.exists(cache_file):
        try:
            df = pd.read_excel(cache_file, dtype=str)
            print(f"✅ 从本地 {cache_file} 读取成功")
            return df
        except Exception as e:
            print(f"❌ 读取本地文件失败: {e}")
    
    raise Exception("无法获取港股列表数据，请检查网络或接口")

def get_data_safe_tushare(symbol, days):
    """
    安全获取Tushare日线数据
    (保留原逻辑，仅做封装)
    """
    try:
        code_num = symbol.split('.')[0]
        ts_code = str(code_num).zfill(5) + ".HK"
        request_days = 600
        end_date = pd.Timestamp.now().strftime('%Y%m%d')
        start_date = (pd.Timestamp.now() - pd.Timedelta(days=request_days)).strftime('%Y%m%d')
        
        df = pro.hk_daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
        # print(df)
        if df is None or df.empty:
            return None
            
        required_cols = ['trade_date', 'open', 'high', 'low', 'close', 'vol']
        if not all(col in df.columns for col in required_cols):
            return None
            
        df = df.sort_values('trade_date').reset_index(drop=True)
        if len(df) >= 60:
            return df.tail(days).reset_index(drop=True)
        else:
            return None
    except Exception as e:
        print(e)
        return None


# ============================================
# 4. 核心策略模块 (Core Strategy)
# ============================================

def scan_drop_from_high(hk_list):
    """
    超跌筛选器：筛选近一年高点下跌超过阈值的股票
    (保留原逻辑)
    """
    results = []
    today = get_offset_date(-1)
    start_date = get_offset_date(-Config.LOOKBACK_DAYS)
    
    for _, row in hk_list.iterrows():
        ts_code = str(row['代码']) + ".HK"
        name = row['名称']
        try:
            df = pro.hk_daily(ts_code=ts_code, start_date=start_date, end_date=today)
            if len(df) < 100:
                continue
                
            df['close'] = clean_numeric(df['close'])
            df['amount'] = clean_numeric(df['amount'])
            df = df.dropna(subset=['close', 'amount']).sort_values('trade_date')
            
            if len(df) < 100:
                continue
                
            high_1y = df['close'].max()
            current = df['close'].iloc[-1]
            avg_amount = df['amount'].tail(30).mean()
            drop = (high_1y - current) / high_1y
            
            if drop >= Config.DROP_THRESHOLD and avg_amount >= Config.MIN_AMOUNT:
                high_date = df[df['close'] == high_1y]['trade_date'].iloc[-1]
                results.append({
                    'ts_code': ts_code,
                    'name': converter.convert(name),
                    'close': round(current, 3),
                    'high_1y': round(high_1y, 3),
                    'drop': f'{drop * 100:.1f}%',
                    'high_date': high_date,
                    'avg_amount_30d': f'{avg_amount / 1e4:.0f}万',
                    'scan_date': today
                })
        except:
            continue
    return pd.DataFrame(results)

# ============================================
# 【优化版】机器学习特征构建（港股专用）
# ============================================
def prepare_ml_features_enhanced(df):
    """优化：港股专用特征集 + 稳健目标变量"""
    data = df.copy()
    # 清洗数据
    drop_cols = ['ts_code', 'trade_date', 'name']
    for col in drop_cols:
        if col in data.columns:
            data.drop(columns=[col], inplace=True)
    data.columns = [col.lower() for col in data.columns]

    # 统一数值化
    c = clean_numeric(data['close'])
    h = clean_numeric(data['high'])
    l = clean_numeric(data['low'])
    v = clean_numeric(data['vol'])
    amount = clean_numeric(data.get('amount', pd.Series(dtype='float64')))

    # 剔除无效行
    valid_mask = c.notna() & h.notna() & l.notna() & v.notna()
    data = data.loc[valid_mask].reset_index(drop=True)
    if len(data) < 60:
        return pd.DataFrame(), []

    # 重新赋值
    c, h, l, v = [x.loc[valid_mask] for x in [c, h, l, v]]

    # ==================== 基础指标 ====================
    data['ret_1d'] = c.pct_change(1)
    data['ret_5d'] = c.pct_change(5)  # 短期动量
    data['ret_20d'] = c.pct_change(20)  # 中期动量
    data['ma_5'] = c.rolling(5).mean()
    data['ma_20'] = c.rolling(20).mean()
    data['ma_60'] = c.rolling(60).mean()
    data['dist_ma20'] = (c - data['ma_20']) / (data['ma_20'] + 1e-9)
    data['dist_ma60'] = (c - data['ma_60']) / (data['ma_60'] + 1e-9)

    # ==================== ATR / 波动率 ====================
    tr = pd.concat([h-l, (h-c.shift(1)).abs(), (l-c.shift(1)).abs()], axis=1).max(axis=1)
    data['atr'] = tr.rolling(14).mean()
    data['atr_ratio'] = data['atr'] / c  # 标准化波动率（港股核心）
    data['volatility_10'] = data['ret_1d'].rolling(10).std()
    data['volatility_20'] = data['ret_1d'].rolling(20).std()

    # ==================== 量能特征（港股超重要） ====================
    data['vol_ma5'] = v.rolling(5).mean()
    data['vol_ma20'] = v.rolling(20).mean()
    data['vol_ratio_5'] = v / (data['vol_ma5'] + 1e-9)
    data['vol_ratio_20'] = v / (data['vol_ma20'] + 1e-9)
    data['amt_20d'] = amount.rolling(20).mean()

    # ==================== RSI / 超跌反转 ====================
    delta = c.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    data['rsi'] = 100 - (100 / (1 + rs))
    data['rsi_rank'] = data['rsi'].rolling(60).rank(pct=True)  # 相对强弱

    # ==================== 【优化目标】预测未来5日正向收益 ====================
    data['fwd_ret_5'] = data['ret_1d'].shift(-5).rolling(5).sum()
    data['target'] = (data['fwd_ret_5'] > 0.02).astype(int)  # >2%为正样本

    # 剔除缺失值
    data.dropna(inplace=True)
    if len(data) < 50:
        return pd.DataFrame(), []

    # 特征列表（剔除未来信息）
    exclude = ['target', 'fwd_ret_5', 'open', 'high', 'low', 'close', 'vol', 'amount', 'ret_1d']
    feature_cols = [col for col in data.columns if col not in exclude]
    return data, feature_cols

def train_and_predict_enhanced(df, params):
    """训练 XGBoost 模型 (保留原逻辑)"""
    if len(df) < 100:
        return 0.5, "数据不足"
        
    try:
        ml_data, feature_cols = prepare_ml_features_enhanced(df)
    except Exception as e:
        return 0.5, f"特征错误:{str(e)}"
        
    if len(ml_data) < 80 or len(feature_cols) < 3:
        return 0.5, "有效特征不足"
        
    X = ml_data[feature_cols]
    y = ml_data['target']
    split_idx = int(len(X) * 0.8)
    X_train, X_val = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_val = y.iloc[:split_idx], y.iloc[split_idx:]
    
    model = xgb.XGBClassifier(
        n_estimators=100, max_depth=4, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8, eval_metric='logloss',
        random_state=42, verbosity=0, use_label_encoder=False
    )
    
    try:
        model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
        last_row = X.iloc[[-1]]
        prob_up = model.predict_proba(last_row)[0][1]
        return prob_up, "OK"
    except Exception as e:
        return 0.5, f"ML Error: {str(e)}"

def calc_risk_levels(df, params):
    """
    计算风险点位 (修复版)
    逻辑优化：
    1. 确保止损位严格小于当前价格。
    2. 使用更稳健的支撑位参考（如近期低点），而非单纯依赖20日高点回撤。
    3. 防止除零错误和负数风险。
    """
    c = clean_numeric(df['close'])
    h = clean_numeric(df['high'])
    l = clean_numeric(df['low'])
    
    # 确保数据对齐且非空
    valid_idx = c.notna() & h.notna() & l.notna()
    if valid_idx.sum() < 20:
        return None, None, None
        
    c = c[valid_idx].reset_index(drop=True)
    h = h[valid_idx].reset_index(drop=True)
    l = l[valid_idx].reset_index(drop=True)
    
    cur_price = c.iloc[-1]
    
    # 1. 计算 ATR
    prev_c = c.shift(1)
    tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    atr = tr.rolling(params['atr_period']).mean().iloc[-1]
    
    if pd.isna(atr) or atr <= 0:
        return None, None, None

    # 2. 确定动态止损位 (Stop Loss)
    # 策略：取以下两者的最小值作为止损基准，确保止损在合理支撑位下方
    # A. 基于近期波动率的硬性止损：现价 - N * ATR
    hard_stop = cur_price - (atr * params['stop_loss_mult'])
    
    # B. 基于技术形态的支撑止损：近20日最低价
    recent_low_20 = l.tail(20).min()
    
    # 最终止损位：取两者中较低者（更保守，更安全），但必须低于现价
    final_stop = min(hard_stop, recent_low_20)
    
    # 【关键修复】强制约束：止损位必须低于当前价格
    # 如果计算出的止损 >= 现价，说明模型失效或数据异常，强制设置为现价下方 2*ATR
    if final_stop >= cur_price:
        final_stop = cur_price - (2 * atr)
        
    # 再次检查，确保止损不为负且合理
    if final_stop <= 0:
        final_stop = cur_price * 0.9 # 兜底：最多亏10%

    # 3. 计算止盈位 (Take Profit)
    risk_amount = cur_price - final_stop
    
    # 【关键修复】防止风险金额为0或负数
    if risk_amount <= 0:
        risk_amount = cur_price * 0.05 # 兜底风险幅度设为5%
        
    target_profit = cur_price + (risk_amount * params['take_profit_ratio'])
    
    return round(final_stop, 3), round(target_profit, 3), round(atr, 3)

# ============================================
# 【优化版】AI评分逻辑（港股超跌专用）
# ============================================
def analyze_full_strategy(symbol, df):
    """
    优化点：
    1. 港股风控硬过滤
    2. 动态AI评分（0-100）
    3. 趋势+量能+AI+风险 四维度加权
    4. 高分标的必须满足：低波动+高流动性+底部企稳
    """
    try:
        # 数据清洗
        df = df.copy()
        for col in ['close', 'high', 'low', 'vol', 'amount']:
            df[col] = clean_numeric(df[col])
        df = df.dropna().reset_index(drop=True)
        if len(df) < 60:
            return None

        c = df['close'].values
        v = df['vol'].values
        cur_price = c[-1]
        current_volume = v[-1]

        # ==================== 【港股风控：硬门槛】 ====================
        avg_amt_20 = df['amount'].tail(20).mean()
        if cur_price < 0.5:  # 仙股过滤
            return None
        if avg_amt_20 < 5e5:  # 流动性过滤
            return None
        if df['close'].pct_change().tail(10).std() > 0.15:  # 异常波动过滤
            return None

        # ==================== 基础指标 ====================
        ma20 = df['close'].rolling(20).mean().iloc[-1]
        ma60 = df['close'].rolling(60).mean().iloc[-1]
        vol_ma5 = df['vol'].rolling(5).mean().iloc[-1]
        is_vol_up = current_volume > vol_ma5 * 1.2
        is_above_ma20 = cur_price > ma20
        is_trend_up = (ma20 > ma60) and is_above_ma20

        # ==================== AI预测（优化后） ====================
        ml_prob, ml_msg = train_and_predict_enhanced(df, Config.STRATEGY_PARAMS)

        # ==================== 【核心：优化AI评分逻辑】 ====================
        score = 50  # 基准分
        signals = []

        # 1. 趋势分（20分）
        if is_trend_up:
            score += 20
            signals.append("趋势企稳")
        elif is_above_ma20:
            score += 8
            signals.append("站上短期均线")

        # 2. 量能分（15分）
        if is_vol_up:
            score += 15
            signals.append("放量异动")

        # 3. AI预测分（35分 → 动态加权）
        if ml_msg == "OK":
            ai_score = int(ml_prob * 35)
            score += ai_score
            signals.append(f"AI胜率:{ml_prob:.1%}")

            # AI强信号额外奖励
            if ml_prob >= 0.75:
                score += 10
                signals.append("AI强力看多")
            elif ml_prob >= 0.65:
                score += 5
                signals.append("AI看多")
            elif ml_prob <= 0.40:
                score -= 20
                signals.append("AI看空预警")
        else:
            signals.append("AI模型异常")

        # 4. 风险惩罚（超跌股核心）
        drop_20d = (c[-20] - cur_price) / c[-20]
        if drop_20d > 0.4:  # 20日暴跌>40%，不建议抄底
            score -= 25
            signals.append("暴跌风险")
        elif drop_20d > 0.2:
            score -= 10
            signals.append("短期超跌")

        # 5. 底部企稳加分
        if cur_price > df['close'].tail(10).max() and len(df) > 30:
            score += 10
            signals.append("底部突破")

        # 分数封顶/保底
        score = max(0, min(100, score))

        # ==================== 交易信号 ====================
        stop_loss, take_profit, atr_val = calc_risk_levels(df, Config.STRATEGY_PARAMS)
        
        # 【新增】如果风控计算失败，直接跳过该标的
        if stop_loss is None or take_profit is None:
            return None
            
        # 【新增】二次校验：确保止盈 > 现价 > 止损
        if not (take_profit > cur_price > stop_loss):
            # 如果逻辑依然混乱，给予极低分或直接过滤
            # 这里选择给予低分并标记异常，以便人工复核
            score -= 50 
            signals.append("风控参数异常")
            rr_ratio = 0.1 # 设置极低的盈亏比
        else:
            rr_ratio = (take_profit - cur_price) / (cur_price - stop_loss)

        # 盈亏比过滤
        if rr_ratio < 1.5:
            score -= 15
            signals.append(f"盈亏比不足({rr_ratio:.2f})")

        # 操作建议
        action = "观望"
        if score >= 85:
            action = "重点关注"
        elif score >= 75:
            action = "轻仓关注"
        elif score >= 60:
            action = "观察"

        status = "中性"
        if score >= 75:
            status = "优质标的"
        elif score >= 60:
            status = "一般标的"
        else:
            status = "风险偏高"

        return {
            'symbol': symbol,
            'name': '未知',
            'score': int(score),
            'status': status,
            'price': round(cur_price, 3),
            '止损位': round(stop_loss, 3),
            '止盈位': round(take_profit, 3),
            '盈亏比': round(rr_ratio, 2),
            'signals': " | ".join(signals),
            'action': action,
            'ml_prob': round(ml_prob, 3) if ml_msg == 'OK' else 0.0
        }

    except Exception as e:
        # print(f"分析失败 {symbol}: {str(e)}")
        return None


# ============================================
# 5. 通讯模块 (Notification)
# ============================================

# 全局设置：解决中文乱码问题
plt.rcParams['font.sans-serif'] = ['SimHei', 'WenQuanYi Zen Hei', 'PingFang SC', 'Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False  # 解决负号显示问题

def send_email_report(df, subject="📉 港股超跌选股日报"):
    """
    发送包含 DataFrame 内容的 HTML 邮件，并附加格式化后的结果图片
    """
    if df.empty:
        print("⚠️ 结果为空，跳过邮件发送。")
        return

    try:
        msg = MIMEMultipart()
        from_name = "260319029"
        msg['From'] = formataddr((from_name, Config.EMAIL_USER), charset='utf-8')
        msg['To'] = Header(f"管理员 <{Config.EMAIL_RECEIVER[0]}>", 'utf-8')
        msg['Subject'] = Header(f"{subject} {get_offset_date(0)}", 'utf-8')

        # ====================== 原有完整HTML正文（完全保留） ======================
        html_table = df.to_html(index=False, border=1, classes='dataframe')
        email_body = f"""
        <html>
        <head>
        <style>
            table.dataframe {{ font-family: Arial, sans-serif; border-collapse: collapse; width: 100%; }}
            table.dataframe td, table.dataframe th {{ border: 1px solid #ddd; padding: 8px; font-size: 12px; }}
            table.dataframe tr:nth-child(even){{background-color: #f2f2f2;}}
            table.dataframe th {{ padding-top: 12px; padding-bottom: 12px; text-align: left; background-color: #4CAF50; color: white; }}
            h2 {{ color: #333; font-family: sans-serif; }}
        </style>
        </head>
        <body>
            <h2>👋 今日选股结果如下：</h2>
            <p>筛选：近一年高点下跌 ≥ 30% 且 流动性达标</p>
            <p>共发现 <strong>{len(df)}</strong> 只标的。</p>
            {html_table}
            <br>
            <p style="color: gray; font-size: 12px;">此邮件由 Python 自动发送，请勿回复。</p>
        </body>
        </html>
        """
        
        msg.attach(MIMEText(email_body, 'html', 'utf-8'))

        # ====================== 新增：生成格式化结果图片并作为附件 ======================
        # 复制DataFrame并格式化数字，避免修改原始数据
        df_plot = df.copy()
        
        # 统一格式化小数，控制显示位数
        float_cols = ['price', 'high_1y', 'ml_prob', '止损位', '止盈位']
        for col in float_cols:
            if col in df_plot.columns:
                if col == 'ml_prob':
                    df_plot[col] = df_plot[col].apply(lambda x: f"{x:.1%}" if isinstance(x, (int, float)) else x)
                else:
                    df_plot[col] = df_plot[col].apply(lambda x: f"{x:.3f}" if isinstance(x, (int, float)) else x)
        
        # 优化列宽：根据列内容长度动态分配
        fig, ax = plt.subplots(figsize=(20, max(6, len(df_plot) * 0.4)))
        ax.axis('tight')
        ax.axis('off')

        # 构建表格
        table = ax.table(
            cellText=df_plot.values,
            colLabels=df_plot.columns,
            cellLoc='center',
            loc='center',
            colWidths=[0.1, 0.12, 0.06, 0.08, 0.08, 0.08, 0.08, 0.1, 0.08, 0.08, 0.14]  # 动态分配列宽，避免溢出
        )
        table.auto_set_font_size(False)
        table.set_fontsize(9)
        table.scale(1.2, 1.6)

        # 表头样式
        for i in range(len(df_plot.columns)):
            table[(0, i)].set_facecolor('#4CAF50')
            table[(0, i)].set_text_props(weight='bold', color='white')

        # 保存到内存，使用tight_layout确保内容不溢出
        img_buf = BytesIO()
        plt.tight_layout()
        # plt.savefig(img_buf, dpi=150, bbox_inches='tight', format='png')
        plt.savefig(img_buf, dpi=300, bbox_inches='tight', pad_inches=0.1, format='png') 
        img_buf.seek(0)
        plt.close()

        # 图片附件
        img_attach = MIMEImage(img_buf.read(), _subtype='png')
        img_attach.add_header('Content-Disposition', 'attachment', filename='港股选股结果.png')
        msg.attach(img_attach)

        # ====================== 发送邮件 ======================
        server = smtplib.SMTP_SSL(Config.EMAIL_HOST, Config.EMAIL_PORT)
        server.login(Config.EMAIL_USER, Config.EMAIL_PASS)
        server.sendmail(Config.EMAIL_USER, Config.EMAIL_RECEIVER, msg.as_string())
        server.quit()
        print(f"✅ 邮件发送成功！正文+图片附件均已发送")

    except Exception as e:
        print(f"❌ 邮件发送失败：{str(e)}")


# ============================================
# 6. 主程序入口 (Main)
# ============================================
def main():
    print("🚀 开始执行港股超跌选股策略...")
    
    # 1. 获取数据源
    try:
        hk_basic = fetch_stock_list()
    except Exception as e:
        print(f"致命错误：{e}")
        return

    # 2. 初筛：超跌股票
    print(f"📋 共 {len(hk_basic)} 只港股，筛选近一年高点下跌≥{Config.DROP_THRESHOLD*100:.0f}% 的标的...")
    result_df = scan_drop_from_high(hk_basic)
    
    if result_df.empty:
        print("⚠️ 未发现符合条件的标的，发送空报告。")
        send_email_report(result_df, "📭 选股日报：无符合条件标的")
        return

    # 3. 构建名称映射字典
    name_dict = {}
    for _, row in result_df.iterrows():
        code_key = row['ts_code'].split('.')[0]
        name_dict[code_key] = row['name']
        
    # 4. 深度分析
    final_results = []
    for _, row in result_df.iterrows():
        code_full = row['ts_code']
        code_clean = str(code_full).split('.')[0].zfill(5) + ".HK"
        code_key = str(code_full).split('.')[0].zfill(5)
        
        # 新增：取出近一年最高价
        high_1y = row['high_1y']

        df_data = get_data_safe_tushare(code_clean, Config.STRATEGY_PARAMS['lookback'])
        if df_data is not None:
            res = analyze_full_strategy(code_clean, df_data)
            if res:
                res['name'] = name_dict.get(code_key, "未知")
                # 新增：把近一年最高价加入结果
                res['high_1y'] = round(high_1y, 3)
                final_results.append(res)
                print(f"[{len(final_results)}] {res['name']}({code_clean}) -> 评分: {res['score']}")

    # 5. 结果处理与输出
    if final_results:
        final_results.sort(key=lambda x: x['score'], reverse=True)
        df_out = pd.DataFrame(final_results)
        df_renamed = df_out.rename(columns={'score': 'sc', 'symbol': 'code'})
        if 'code' in df_renamed.columns:
            df_renamed['code'] = df_renamed['code'].astype(str).str.replace('.HK', '', regex=False)
        
        # 【修改】输出列加入 high_1y
        cols_to_save = ['code', 'name', 'sc', 'price', 'high_1y', 'ml_prob',
                        'action', 'status', '止损位', '止盈位', 'signals']
        cols_to_save = [col for col in cols_to_save if col in df_renamed.columns]
        
        print(f"✅ 分析完成！共发现 {len(final_results)} 只高分标的。")
        print(f"📊 评分前5名：\n{df_renamed[['name', 'sc', 'high_1y', 'price', 'action']].head().to_string(index=False)}")
        
        # 6. 发送邮件
        send_email_report(df_renamed[cols_to_save], "港股超跌精选报告")
        
    else:
        print("❌ 深度分析未产生任何结果。")

if __name__ == "__main__":
    main()