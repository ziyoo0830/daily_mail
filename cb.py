#!/usr/bin/env python
# -*- coding: utf-8 -*-

import xcsc_tushare as ts
import pandas as pd
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from datetime import datetime, timedelta

# ============ 1. 配置区域 ============
# Tushare 配置
# TOKEN = '5b7f9a4551a1dd0e378ae2a7522e2ebd3d3c2e873caed0e9a4668066'
TOKEN = '9ff9956bd08ab359df39e121be6abf60a1de590891ab833aa3156b2d'
SERVER = 'http://116.128.206.39:7172'

# 邮箱配置 
MAIL_CONFIG = {
    'smtp_server': 'smtp.qq.com',  # 例如: smtp.qq.com, smtp.163.com
    'smtp_port': 465,              # SSL端口通常为465
    'user': '260319029@qq.com',   # 发件人邮箱
    'password': 'tofijpcsxefvbghg',  # 邮箱授权码
    'receiver': 'ziyoo0830@163.com' # 收件人邮箱
}

# 初始化 Tushare
ts.set_token(TOKEN)
pro = ts.pro_api(server=SERVER)

def get_offset_date(days_offset):
    target_date = datetime.now() + timedelta(days=days_offset)
    return target_date.strftime('%Y%m%d')

def is_today_trading_day(today):
    try:
        df = pro.trade_cal(start_date=today, end_date=today, is_open='1')
        
        return not df.empty
    except Exception as e:
        print(f"查询交易日历失败: {e}")
        return False

# ============ 2. 数据获取函数 ============

def get_cb_basic():
    """获取可转债基本信息"""
    df = pro.cb_basic(fields="ts_code,bond_short_name,stk_code,remain_size,maturity_date,conv_end_date,conv_price,newest_rating,delist_date")
    df['delist_date'] = pd.to_datetime(df['delist_date'])
    df['conv_end_date'] = pd.to_datetime(df['conv_end_date'])
    today = pd.Timestamp.today().normalize()
    # 筛选未到期、未退市、有余额的转债
    df_filtered = df[
        ((df['delist_date'] >= today) | (df['delist_date'].isna())) & 
        (df['remain_size'] > 0) & 
        (df['conv_end_date'] > today)
    ].copy()
    return df_filtered

def get_cb_daily(day):
    """获取可转债日线行情"""
    # df = pro.cb_daily(trade_date='20260410')
    df = pro.cb_daily(trade_date=day)
    return df[['ts_code', 'pre_close', 'close', 'vol', 'amount']]

def get_stock_daily(day):
    """获取正股日线行情"""
    # df = pro.daily(trade_date='20260410') 
    df = pro.daily(trade_date=day) 
    return df[['ts_code', 'close']].rename(columns={'close': 'stk_close'})

def get_bond_redem_pr(day):
    """获取赎回信息"""
    # df = pro.bond_redem_pr(start_date='20240101')
    df = pro.bond_redem_pr(start_date=day)
    return df

def get_cb_call():
    """获取强赎公告信息"""
    df = pro.cb_call(fields=['ts_code', 'call_type', 'is_call', 'ann_date', 'call_date', 'call_price'])
    if not df.empty:
        df['ann_date'] = pd.to_datetime(df['ann_date'])
        df_sorted = df.sort_values(by='ann_date', ascending=False)
        df_latest = df_sorted.drop_duplicates(subset=['ts_code'], keep='first')
        return df_latest
    return df

# ============ 3. 数据处理与计算 ============

def merge_dataframes(day):
    """合并所有数据表"""
    df_basic = get_cb_basic()
    df_cb_daily = get_cb_daily(day)
    df_stock_daily = get_stock_daily(day) 
    df_redem = get_bond_redem_pr(day)
    df_call = get_cb_call()
    
    # 以基本信息为主表合并
    df_merged = pd.merge(df_basic, df_cb_daily, on='ts_code', how='left')
    
    # 合并正股数据
    df_merged = pd.merge(df_merged, df_stock_daily, left_on='stk_code', right_on='ts_code', how='left', suffixes=('', '_stk'))
    if 'ts_code_stk' in df_merged.columns:
        df_merged.drop(columns=['ts_code_stk'], inplace=True)

    # 合并赎回信息
    df_merged = pd.merge(df_merged, df_redem, on='ts_code', how='left')
    
    # 合并强赎公告
    if df_call is not None and not df_call.empty:
        df_merged = pd.merge(df_merged, df_call, on='ts_code', how='left', suffixes=('', '_call'))
    
    return df_merged

def calculate_premium(df):
    """计算转股价值和溢价率"""
    # 转股价值 = 正股价格 / 转股价 * 100
    df['convert_value'] = df['stk_close'] / df['conv_price'] * 100
    
    # 转股溢价率 = (转债价格 - 转股价值) / 转股价值 * 100%
    df['premium_rate'] = round((df['close'] - df['convert_value']) / df['convert_value'] * 100, 2)
    
    return df

def send_email_report(df_result):
    """
    发送邮件报告 - 去除日期横杠版
    """
    if df_result.empty:
        print("Result empty, no email sent.")
        return

    # 1. 数据预处理
    show_cols = [
        'bond_short_name', 'ts_code', 'premium_rate', 'close', 
        'remain_size', 'convert_value', 'maturity_date', 'conv_end_date', 
        'is_call', 'ann_date', 'call_date', 'call_price'
    ]
    
    mail_df = df_result[show_cols].copy()
    
    # 格式化日期列
    date_cols = ['maturity_date', 'conv_end_date', 'ann_date', 'call_date']
    for col in date_cols:
        if col in mail_df.columns:
            # 转为字符串 -> 去除横杠 -> 将 NaT 替换为空字符串
            # 结果示例: 2026-04-12 变为 20260412
            mail_df[col] = mail_df[col].astype(str).str.replace('-', '', regex=False).replace('NaT', '')

    # 格式化数值
    mail_df['remain_size'] = (mail_df['remain_size'] / 100000000).map('{:.2f}B'.format)
    mail_df['close'] = mail_df['close'].map('{:.2f}'.format)
    mail_df['premium_rate'] = mail_df['premium_rate'].map('{:.2f}%'.format)
    mail_df['convert_value'] = mail_df['convert_value'].map('{:.2f}'.format)
    mail_df['call_price'] = mail_df['call_price'].map('{:.2f}'.format)
    
    mail_df['ts_code'] = mail_df['ts_code'].astype(str).str[:6]
    '''
    col_names = {
        'bond_short_name': 'Name', 
        'ts_code': 'Code', 
        'close': 'Price',
        'premium_rate': 'Premium', 
        'remain_size': 'Size', 
        'convert_value': 'ConvValue',
        'maturity_date': 'MaturityDate', 
        'conv_end_date': 'ConvEndDate', 
        'is_call': 'CallStatus', 
        'ann_date': 'AnnDate', 
        'call_date': 'CallDate', 
        'call_price': 'CallPrice'
    }'''
    col_names = {
        'bond_short_name': '名称', 
        'ts_code': '代码', 
        'close': '价格',
        'premium_rate': '溢价率', 
        'remain_size': '余额', 
        'convert_value': '转股价值',
        'maturity_date': '到期日', 
        'conv_end_date': '到期转股日', 
        'is_call': '公告', 
        'ann_date': '公告日期', 
        'call_date': '转股日', 
        'call_price': '赎回价'
    }
    mail_df.rename(columns=col_names, inplace=True)

    # 2. 构建 HTML 表格 (转置处理)
    html_table = mail_df.set_index('名称').T.to_html(header=True, index=True, border=1)
    
    # 邮件正文内容
    html_content = f"""
    <html>
    <head>
        <style>
            table, th, td {{ border: 1px solid black; border-collapse: collapse; padding: 8px; text-align: center; font-family: sans-serif; font-size: 14px; }}
            th {{ background-color: #f2f2f2; }}
            h2 {{ color: #333; }}
        </style>
    </head>
    <body>
        <h2>Daily CB Screening Report ({datetime.now().strftime('%Y-%m-%d')})</h2>
        <p>Found <b>{len(df_result)}</b> convertible bonds matching criteria.</p>
        <p>Criteria: Premium<=30%, Price<=130, Size 100M-500M</p>
        <hr>
        {html_table}
        <p><i>Note: Data for reference only.</i></p>
    </body>
    </html>
    """

    # 3. 发送邮件
    try:
        msg = MIMEMultipart()
        
        msg['From'] = MAIL_CONFIG['user']
        msg['To'] = MAIL_CONFIG['receiver']
        msg['Subject'] = f"CB Daily Report - {datetime.now().strftime('%Y%m%d')}"
        
        msg.attach(MIMEText(html_content, 'html', 'utf-8'))
        
        # 连接 SMTP 服务器
        server = smtplib.SMTP_SSL(MAIL_CONFIG['smtp_server'], MAIL_CONFIG['smtp_port'])
        server.login(MAIL_CONFIG['user'], MAIL_CONFIG['password'])
        server.sendmail(MAIL_CONFIG['user'], [MAIL_CONFIG['receiver']], msg.as_string())
        server.quit()
        
        print("✅ Email sent successfully!")
        
    except Exception as e:
        print(f"❌ Failed to send email: {str(e)}")

# ============ 5. 主程序入口 ============

if __name__ == "__main__":

    # today = datetime.now().strftime('%Y%m%d')
    today = get_offset_date(-1)
    if is_today_trading_day(today):
        print(f"今天是交易日 {today}")
        # 1. 获取与合并数据
        final_df = merge_dataframes(today)
        
        # 2. 计算指标
        final_df = calculate_premium(final_df)
        
        # 3. 数据清洗与筛选
        # 去除空值
        df_clean = final_df.dropna(subset=['premium_rate', 'close', 'remain_size'])
        
        # 设定筛选条件
        condition_premium = df_clean['premium_rate'] <= 30
        condition_price = df_clean['close'] <= 130
        condition_size = (df_clean['remain_size'] >= 100000000) & (df_clean['remain_size'] <= 500000000)
        
        # 执行筛选
        result_df = df_clean[condition_premium & condition_price & condition_size].copy()
        result_df.sort_values(by='premium_rate', ascending=True, inplace=True)
        
        # 4. 输出结果
        print(f"\n🔍 本地筛选结果：共找到 {len(result_df)} 只符合条件的转债")
        
        if not result_df.empty:
            # 控制台简单打印
            print(result_df[['bond_short_name', 'ts_code', 'premium_rate', 'close', 
            'remain_size', 'convert_value', 'maturity_date', 'conv_end_date', 
            'is_call', 'ann_date', 'call_date', 'call_price']].to_string(index=False))
            
            
            # 发送邮件
            send_email_report(result_df)
        else:
            print("当前无符合条件转债。")
    else:
        print(f"今天不是交易日 {today}")
    