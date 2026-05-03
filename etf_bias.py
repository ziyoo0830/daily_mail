#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETF乖离率分析工具 - 邮件表格版（图片本地保存）
功能：动态获取场内ETF，智能筛选，计算20日乖离率，邮件仅发送彩色表格，图表本地保存
"""

# ================= 导入区域 =================
import xcsc_tushare as ts
import pandas as pd
import numpy as np
import talib as ta
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import os
import re
import logging
import warnings
from datetime import datetime, timedelta
from typing import Optional, List, Dict
# 邮件相关导入
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# ================= 配置常量 =================
class Config:
    TOKEN = '9ff9956bd08ab359df39e121be6abf60a1de590891ab833aa3156b2d'
    SERVER = 'http://116.128.206.39:7172'
    
    LOOKBACK_YEARS = 3.0
    MA_PERIOD = 20
    DAYS_OFFSET = 4
    
    OUTLIER_METHOD = 'winsorize'
    WINSORIZE_LIMITS = (0.02, 0.98)
    ROLLING_WINDOW = 252
    
    EXPORT_DIR = "./etf_bias_charts"  # 🆕 本地图片保存目录
    LOG_FORMAT = "%(asctime)s %(message)s"
    LOG_LEVEL = logging.INFO
    FONT_CANDIDATES = ['SimHei', 'Microsoft YaHei', 'KaiTi', 'FangSong']
    
    EMAIL_CONFIG = {
        "sender": "260319029@qq.com",
        "auth_code": "tofijpcsxefvbghg",
        "receiver": "ziyoo0830@163.com",
        "smtp_server": "smtp.qq.com",
        "smtp_port": 465,
        "send_enabled": True
    }
    
    WEEKDAY_EXECUTION = [0, 1, 2, 3, 4, 5, 6]

# ================= 全局初始化 =================
warnings.filterwarnings("ignore")
np.seterr(divide='ignore', invalid='ignore')
logging.basicConfig(level=Config.LOG_LEVEL, format=Config.LOG_FORMAT)

# ================= 工具函数 =================
def setup_font() -> bool:
    for font in Config.FONT_CANDIDATES:
        try:
            plt.rcParams['font.sans-serif'] = [font]
            plt.rcParams['axes.unicode_minus'] = False
            fig, ax = plt.subplots()
            ax.set_title("测试")
            plt.close(fig)
            return True
        except:
            continue
    logging.warning("⚠️ 中文字体未生效")
    return False

def get_offset_date(days_offset: int) -> str:
    return (datetime.now() + timedelta(days=days_offset)).strftime('%Y%m%d')

def is_trading_day(date_str: str, pro) -> bool:
    try:
        df = pro.trade_cal(start_date=date_str, end_date=date_str, is_open='1')
        return not df.empty
    except Exception as e:
        logging.warning(f"查询交易日历失败: {e}")
        return False

def is_execution_day() -> bool:
    return datetime.now().weekday() in Config.WEEKDAY_EXECUTION

def safe_filename(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', '', name.strip()) or "etf"

def get_position_desc(pct: float) -> str:
    if pct < 5: return "极低位"
    elif pct < 20: return "低位区"
    elif pct < 50: return "中低位"
    elif pct < 80: return "中高位"
    elif pct < 95: return "高位区"
    else: return "极高位"

def get_row_style(pct: float) -> str:
    if pct < 5: return 'style="background:#c8e6c9;"'
    elif pct < 20: return 'style="background:#e8f5e9;"'
    elif pct < 50: return 'style="background:#e3f2fd;"'
    elif pct < 80: return 'style="background:#fff9c4;"'
    elif pct < 95: return 'style="background:#ffebee;"'
    else: return 'style="background:#ffcdd2;"'

# ================= 邮件发送函数（仅表格） =================
def send_bias_email(results: List[Dict], config: Dict) -> bool:
    try:
        msg = MIMEMultipart()
        msg['From'] = config['sender']
        msg['To'] = config['receiver']
        msg['Subject'] = f"📊 ETF乖离率日报 {datetime.now().strftime('%Y-%m-%d')}"
        
        html = f"""
        <html><head><style>
            body {{ font-family:Microsoft YaHei,sans-serif; font-size:13px; line-height:1.5; }}
            h3 {{ color:#2E86AB; margin:0 0 15px 0; }}
            table {{ border-collapse:collapse; width:100%; margin:10px 0; }}
            th {{ background:#f5f5f5; padding:8px; text-align:left; border:1px solid #ddd; }}
            td {{ padding:6px 8px; border:1px solid #eee; }}
        </style></head><body>
        <h3>📈 场内ETF乖离率分析报告</h3>
        <p><b>分析时间：</b>{datetime.now().strftime('%Y-%m-%d %H:%M')}<br>
        <b>分析周期：</b>近{Config.LOOKBACK_YEARS}年 | <b>均线周期：</b>{Config.MA_PERIOD}日<br>
        <b>异常值处理：</b>{Config.OUTLIER_METHOD.upper()}</p>
        """
        
        html += "<h4>🎯 关键信号（按历史分位正序｜🟢极低 🟡中枢 🔴极高）</h4>"
        html += "<table><tr><th>ETF名称</th><th>代码</th><th>乖离度</th><th>历史分位</th><th>位置</th><th>均值</th><th>标准差</th><th>±2σ区间</th></tr>"
        
        sorted_results = sorted(results, key=lambda x: x['current_position'])
        for r in sorted_results:
            pos_desc = get_position_desc(r['current_position'])
            sigma2_low = r['bias_mean'] - 2 * r['bias_std']
            sigma2_high = r['bias_mean'] + 2 * r['bias_std']
            row_style = get_row_style(r['current_position'])
            
            html += f"<tr {row_style}>"
            html += f"<td>{r['name']}</td><td>{r['code'][:6]}</td>"
            html += f"<td>{r['bias_processed']:+.2f}%</td><td>{r['current_position']:.1f}%</td><td>{pos_desc}</td>"
            html += f"<td>{r['bias_mean']:+.2f}%</td><td>{r['bias_std']:.2f}%</td>"
            html += f"<td>[{sigma2_low:+.2f}%, {sigma2_high:+.2f}%]</td></tr>"
        html += "</table>"
        html += "<p style='color:#999;font-size:11px;margin-top:20px;border-top:1px solid #eee;padding-top:10px;'>※ 自动化报告 | 数据源: Tushare Pro | 仅供参考</p></body></html>"
        
        msg.attach(MIMEText(html, 'html', 'utf-8'))
        
        with smtplib.SMTP_SSL(config['smtp_server'], config['smtp_port']) as server:
            server.login(config['sender'], config['auth_code'])
            server.sendmail(config['sender'], [config['receiver']], msg.as_string())
        
        logging.info(f"✉️ 邮件发送成功 → {config['receiver']} (含{len(results)}条记录)")
        return True
    except Exception as e:
        logging.error(f"❌ 邮件发送失败: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return False


def clean_benchmark(benchmark: str) -> str:
    """清洗benchmark字段：1)去括号内容 2)去*95%+后缀 3)指数收益率→指数"""
    if not benchmark or not isinstance(benchmark, str):
        return benchmark
    
    # 1. 尾部是)，去除最后一个(及其中间内容
    if benchmark.rstrip().endswith(')'):
        idx = benchmark.rfind('(')
        if idx != -1:
            benchmark = benchmark[:idx].rstrip()
    
    # 2. 包含*95%+，截断该标记及之后内容
    if '*95%+' in benchmark:
        benchmark = benchmark.split('*95%+')[0].rstrip()
    
    # 3. 尾部"指数收益率"替换为"指数"
    if benchmark.rstrip().endswith('指数收益率'):
        benchmark = benchmark.rstrip()[:-5] + '指数'
    
    return benchmark.strip()
    
def fetch_etf_list(pro) -> Dict[str, str]:
    try:
        df = pro.fund_basic(market='E')
        if df is None or df.empty: return {}

        df = df[df['status'] == 'L'].copy()
        for col in ['delist_date', 'due_date', 'benchmark', 'm_fee', 'c_fee', 'issue_amount']:
            if col in df.columns: df[col] = df[col].replace('', np.nan)

        df = df[df['delist_date'].isna()]
        df = df[df['due_date'].isna()]
        df = df[df['benchmark'].notna()]
        
        # df['benchmark'] = df['benchmark'].str.strip()
        df['benchmark'] = df['benchmark'].apply(clean_benchmark)
        df = df[df['benchmark'] != '']
        df = df[df['invest_type'] == '被动指数型']
        df['m_fee'] = pd.to_numeric(df['m_fee'], errors='coerce').fillna(10)
        df['c_fee'] = pd.to_numeric(df['c_fee'], errors='coerce').fillna(10)
        df['issue_amount'] = pd.to_numeric(df['issue_amount'], errors='coerce').fillna(0)
        df['total_fee'] = df['m_fee'] + df['c_fee']

        df = df.sort_values(by=['benchmark', 'total_fee', 'issue_amount'], ascending=[True, True, False])
        df.to_excel('a.xlsx')
        df_best = df.drop_duplicates(subset=['benchmark'], keep='first')

        etf_dict = dict(zip(df_best['ts_code'], df_best['name']))
        logging.info(f"✅ 筛选完成: 原始 {len(df)} -> 最终 {len(etf_dict)} 只ETF")
        return etf_dict
    except Exception as e:
        logging.error(f"❌ 获取ETF列表失败: {e}")
        return {}

# ================= 核心分析类 =================
class BiasAnalyzer:
    def __init__(self, token: str, server: str, 
                 lookback_years: float = Config.LOOKBACK_YEARS, 
                 ma_period: int = Config.MA_PERIOD):
        self.pro = ts.pro_api(server=server, token=token)
        self.lookback_days = int(lookback_years * 365.25) + 15
        self.lookback_years = lookback_years
        self.ma_period = ma_period
        self.results: List[Dict] = []

    def _get_date_range(self, offset_days: int = 1) -> tuple:
        end = datetime.now() - timedelta(days=offset_days)
        start = end - timedelta(days=self.lookback_days)
        return end.strftime("%Y%m%d"), start.strftime("%Y%m%d")

    def fetch_data(self, code: str) -> Optional[pd.DataFrame]:
        end, start = self._get_date_range()
        try:
            df = self.pro.fund_daily(ts_code=code, start_date=start, end_date=end, fields="ts_code,trade_date,close")
            if df is not None and not df.empty:
                return df.sort_values("trade_date").reset_index(drop=True)
            return None
        except Exception as e:
            logging.warning(f"❌ {code} 获取失败: {e}")
            return None

    @staticmethod
    def compute_bias(df: pd.DataFrame, ma_period: int) -> Optional[pd.DataFrame]:
        if df is None or len(df) < ma_period + 30: return None
        df = df.copy()
        df["ma_20"] = ta.MA(df["close"].values.astype(np.float64), ma_period)
        df["bias_20"] = (df["close"] - df["ma_20"]) / df["ma_20"] * 100
        df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
        return df.dropna(subset=["bias_20"])

    @staticmethod
    def handle_outliers(bias_series: pd.Series, method: str = 'winsorize') -> pd.Series:
        if method == 'none' or len(bias_series) < 30: return bias_series
        elif method == 'winsorize':
            return bias_series.clip(lower=bias_series.quantile(Config.WINSORIZE_LIMITS[0]), upper=bias_series.quantile(Config.WINSORIZE_LIMITS[1]))
        elif method == 'robust':
            median, mad = bias_series.median(), (bias_series - bias_series.median()).abs().median()
            return bias_series.clip(lower=median - 3*mad, upper=median + 3*mad)
        elif method == 'rolling':
            return bias_series.rolling(window=Config.ROLLING_WINDOW, min_periods=30).apply(
                lambda x: x.clip(lower=x.quantile(0.02), upper=x.quantile(0.98)).iloc[-1] if len(x) >= 30 else x.iloc[-1])
        return bias_series

    @staticmethod
    def analyze_bias(df: pd.DataFrame, code: str, name: str, outlier_method: str = Config.OUTLIER_METHOD) -> Dict:
        bias_raw = df["bias_20"]
        bias_processed = BiasAnalyzer.handle_outliers(bias_raw, outlier_method)
        q = bias_processed.quantile([0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95])
        return {
            "code": code, "name": name,
            "current_bias": round(df.iloc[-1]["bias_20"], 2),
            "bias_processed": round(bias_processed.iloc[-1], 2),
            "max_bias_raw": round(bias_raw.max(), 2), "min_bias_raw": round(bias_raw.min(), 2),
            "max_bias": round(bias_processed.max(), 2), "min_bias": round(bias_processed.min(), 2),
            "bias_mean": round(bias_processed.mean(), 2), "bias_median": round(bias_processed.median(), 2),
            "bias_std": round(bias_processed.std(), 2),
            "bias_p05": round(q[0.05], 2), "bias_p10": round(q[0.10], 2),
            "bias_p25": round(q[0.25], 2), "bias_p50": round(q[0.50], 2),
            "bias_p75": round(q[0.75], 2), "bias_p90": round(q[0.90], 2),
            "bias_p95": round(q[0.95], 2),
            "current_position": round((bias_processed <= bias_processed.iloc[-1]).mean() * 100, 1),
            "outlier_method": outlier_method,
            "df": df[["trade_date", "close", "bias_20"]],
            "bias_processed_series": bias_processed
        }

    def run(self, etf_dict: Dict[str, str], export_dir: Optional[str] = None) -> List[Dict]:
        logging.info(f"⏳ 开始分析近 {self.lookback_years} 年的 {self.ma_period} 日乖离率...")
        logging.info(f"🔧 异常值处理: {Config.OUTLIER_METHOD}")
        
        for i, (code, name) in enumerate(etf_dict.items(), 1):
            if i % 50 == 0: logging.info(f"📊 进度: {i}/{len(etf_dict)}")
            raw = self.fetch_data(code)
            if raw is None: continue
            df = self.compute_bias(raw, self.ma_period)
            if df is None: continue
            self.results.append(self.analyze_bias(df, code, name, Config.OUTLIER_METHOD))
            if export_dir:
                self._plot_bias(self.results[-1], export_dir)
        
        self._print_summary()
        return self.results

    def _plot_bias(self, result: Dict, export_dir: str) -> Optional[str]:
        df = result["df"]
        bias_series = result.get("bias_processed_series", result["df"]["bias_20"])
        code_short = result["code"][:6]
        name = result["name"]
        
        fig, ax = plt.subplots(figsize=(12, 5), dpi=100)
        ax.plot(df["trade_date"], bias_series, label="乖离率(处理后)", color="#2E86AB", linewidth=1)
        if result["outlier_method"] != 'none':
            # ax.plot(df["trade_date"], df["bias_20"], label="原始", color="#CCCCCC", linewidth=0.5, alpha=0.4)
            ax.plot(df["trade_date"], df["bias_20"], label="原始", color="#E67E22", linewidth=1.0, alpha=0.7)
        
        ax.axhline(y=0, color="gray", linestyle="--", linewidth=0.5, alpha=0.5, label="0轴")
        ax.axhline(y=result["bias_mean"], color="#A23B72", linestyle=":", linewidth=0.8, label="均值")
        ax.axhline(y=result["bias_processed"], color="#F18F01", linestyle="-", linewidth=1.5, label="当前")
        
        for pct_val, color, alpha in [(result['bias_p10'], '#90CAF9', 0.3), (result['bias_p25'], '#4FC3F7', 0.4),
                                      (result['bias_p50'], '#FFB300', 0.6), (result['bias_p75'], '#EF9A9A', 0.4),
                                      (result['bias_p90'], '#E57373', 0.3)]:
            ax.axhline(y=pct_val, color=color, linestyle=':', linewidth=0.6, alpha=alpha)
        
        mean, std = result["bias_mean"], result["bias_std"]
        ax.fill_between(df["trade_date"], mean-2*std, mean+2*std, color="#E53935", alpha=0.08, label="±2σ")
        ax.fill_between(df["trade_date"], mean-std, mean+std, color="#81C784", alpha=0.15, label="±1σ")
        
        method_tag = {'winsorize':f'[W{Config.WINSORIZE_LIMITS[0]*100:.0f}-{Config.WINSORIZE_LIMITS[1]*100:.0f}%]'}
        ax.set_title(f"{code_short} {name} - BIAS{Config.MA_PERIOD} {method_tag.get(result['outlier_method'], '')}", fontsize=10, pad=8)
        ax.set_ylabel("乖离率(%)", fontsize=9)
        ax.grid(True, linestyle=":", alpha=0.3)
        
        stats_text = (f"当前:{result['bias_processed']:+.2f}% | 分位:{result['current_position']:.1f}% | 均值:{result['bias_mean']:+.2f}%\n"
                      f"─────────────────────────────\n"
                      f"Max:{result['max_bias']:+.2f}%  │  P75:{result['bias_p75']:+.2f}%\n"
                      f"P90:{result['bias_p90']:+.2f}%  │  P50:{result['bias_p50']:+.2f}%\n"
                      f"P25:{result['bias_p25']:+.2f}%  │  P10:{result['bias_p10']:+.2f}%\n"
                      f"Min:{result['min_bias']:+.2f}%  │   σ:{result['bias_std']:.2f}%")
        ax.text(0.02, 0.98, stats_text, transform=ax.transAxes, fontsize=7,
                verticalalignment='top', horizontalalignment='left',
                bbox=dict(boxstyle='round,pad=0.4', facecolor='#f5f5f5', alpha=0.92, edgecolor='#999', linewidth=0.5))
        
        ax.legend(loc='upper right', fontsize=6, framealpha=0.9, ncol=2)
        
        total = len(df)
        interval = 1 if total <= 200 else 2 if total <= 400 else 3
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=interval))
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=25, ha='right', fontsize=6)
        
        os.makedirs(export_dir, exist_ok=True)
        date_str = datetime.now().strftime('%Y%m%d')
        save_path = os.path.join(export_dir, f"bias_{safe_filename(name)}_{code_short}_{date_str}.png")
        plt.savefig(save_path, dpi=100, bbox_inches="tight")
        plt.close()
        return save_path

    def _print_summary(self):
        if not self.results: return
        print(f"\n📊 ETF乖离率分析完成 | 有效标的:{len(self.results)} | 方法:{Config.OUTLIER_METHOD}")
        extreme = [r for r in self.results if abs(r['bias_processed']-r['bias_mean']) > 1.8*r['bias_std']]
        if extreme:
            print("🎯 极端信号:", ", ".join([f"{r['name']}({r['bias_processed']:+.1f}%)" for r in extreme[:5]]))

# ================= 主入口 =================
def main():
    if not is_execution_day():
        logging.info(f"⏭️ 今天星期{datetime.now().weekday()+1}不在执行列表{Config.WEEKDAY_EXECUTION}中，跳过")
        return
    
    today = get_offset_date(-Config.DAYS_OFFSET)
    ts.set_token(Config.TOKEN)
    pro = ts.pro_api(server=Config.SERVER)
    
    if not is_trading_day(today, pro):
        logging.info(f"⏭️ {today} 非交易日，跳过")
        return
    
    etf_dict = fetch_etf_list(pro)
    if not etf_dict:
        logging.warning("⚠️ 未获取到有效ETF，退出")
        return

    analyzer = BiasAnalyzer(Config.TOKEN, Config.SERVER)
    results = analyzer.run(etf_dict, export_dir=Config.EXPORT_DIR)
    
    if Config.EMAIL_CONFIG.get("send_enabled") and results:
        logging.info("📧 发送表格邮件...")
        send_bias_email(results, Config.EMAIL_CONFIG)

if __name__ == '__main__':
    setup_font()
    main()