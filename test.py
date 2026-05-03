#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
指数乖离率+布林带分析工具 - 纯内存邮件版
功能：计算多指数20日乖离率+242日布林带，支持异常值处理，双图表纯内存生成并内嵌邮件
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
import re
import logging
import warnings
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from scipy import stats
from io import BytesIO
# 邮件相关导入
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email import encoders

# ================= 配置常量 =================
class Config:
    """全局配置常量"""
    TOKEN = '9ff9956bd08ab359df39e121be6abf60a1de590891ab833aa3156b2d'
    SERVER = 'http://116.128.206.39:7172'
    
    # 分析参数
    LOOKBACK_YEARS = 3.0
    MA_PERIOD = 20
    BOLL_PERIOD = 60  # 🆕 布林带周期
    BOLL_STD = 2       # 🆕 布林带标准差倍数
    DAYS_OFFSET = 4
    
    # 🎯 异常值处理配置
    OUTLIER_METHOD = 'winsorize'
    WINSORIZE_LIMITS = (0.02, 0.98)
    ROLLING_WINDOW = 252
    
    # 输出配置
    LOG_FORMAT = "%(asctime)s %(message)s"
    LOG_LEVEL = logging.INFO
    FONT_CANDIDATES = ['SimHei', 'Microsoft YaHei', 'KaiTi', 'FangSong']
    
    # 📧 邮件配置
    EMAIL_CONFIG = {
        "sender": "260319029@qq.com",
        "auth_code": "tofijpcsxefvbghg",
        "receiver": "ziyoo0830@163.com",
        "smtp_server": "smtp.qq.com",
        "smtp_port": 465,
        "send_enabled": True,
        "img_width": 500,
        "img_dpi": 100
    }
    
    # 📅 执行日期配置 (0=周一, 6=周日)
    WEEKDAY_EXECUTION = [1, 3, 6]
    
    # 🆕 图表类型配置（可选：['bias'], ['boll'], ['bias','boll']）
    CHART_TYPES = ['bias', 'boll']

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
            logging.info(f"✅ 已加载字体: {font}")
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
    return re.sub(r'[<>:"/\\|?*]', '', name.strip()) or "index"

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

def send_bias_email(results: List[Dict], image_data: Dict[str, bytes], config: Dict) -> bool:
    """发送乖离率+布林带分析结果邮件（纯内存图片内嵌）"""
    try:
        msg = MIMEMultipart('related')
        msg['From'] = config['sender']
        msg['To'] = config['receiver']
        msg['Subject'] = f"📊 指数乖离率+布林带日报 {datetime.now().strftime('%Y-%m-%d')}"
        
        html = f"""
        <html><head><style>
            body {{ font-family:Microsoft YaHei,sans-serif; font-size:13px; line-height:1.5; }}
            h3 {{ color:#2E86AB; margin:0 0 15px 0; }}
            h4 {{ color:#F18F01; margin:25px 0 10px 0; border-left:4px solid #F18F01; padding-left:10px; }}
            table {{ border-collapse:collapse; width:100%; margin:10px 0; }}
            th {{ background:#f5f5f5; padding:8px; text-align:left; border:1px solid #ddd; }}
            td {{ padding:6px 8px; border:1px solid #eee; }}
            .chart-item {{ margin:15px 0; padding:10px; border:1px solid #eee; border-radius:4px; }}
            .chart-title {{ font-weight:bold; color:#333; margin-bottom:8px; }}
            .stats {{ color:#666; font-size:11px; }}
            .pct-grid {{ display:inline-grid; grid-template-columns:repeat(4,1fr); gap:4px 12px; font-size:10px; }}
        </style></head><body>
        <h3>📈 指数乖离率+布林带分析报告</h3>
        <p><b>分析时间：</b>{datetime.now().strftime('%Y-%m-%d %H:%M')}<br>
        <b>分析周期：</b>近{Config.LOOKBACK_YEARS}年 | <b>均线周期：</b>{Config.MA_PERIOD}日 | <b>布林周期：</b>{Config.BOLL_PERIOD}日<br>
        <b>异常值处理：</b>{Config.OUTLIER_METHOD.upper()}</p>
        """
        
        # 1. 关键信号表格
        html += "<h4>🎯 关键信号（按历史分位正序｜🟢极低 🟡中枢 🔴极高）</h4>"
        html += "<table><tr><th>指数</th><th>代码</th><th>乖离度</th><th>历史分位</th><th>位置</th><th>均值</th><th>标准差</th><th>±2σ区间</th></tr>"
        
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
        
        # 2. 双图表展示
        html += "<h4>📊 图表分析（按历史分位顺序）</h4>"
        for r in sorted_results:
            code_short = r['code'][:6]
            pos_desc = get_position_desc(r['current_position'])
            color_mark = "🟢" if r['current_position'] < 20 else "🔴" if r['current_position'] >= 80 else "🟡"
            
            # ── 图表1: 乖离率 ──
            if 'bias' in Config.CHART_TYPES and f"{code_short}_bias" in image_data:
                cid = f"chart_{code_short}_bias"
                img = MIMEImage(image_data[f"{code_short}_bias"], 'png')
                img.add_header('Content-ID', f'<{cid}>')
                img.add_header('Content-Disposition', 'inline', filename=f"{code_short}_bias.png")
                msg.attach(img)
                
                pct_html = f"""
                <div class='pct-grid'>
                    <span>Max: {r['max_bias']:+.2f}%</span><span>Min: {r['min_bias']:+.2f}%</span>
                    <span>P10: {r['bias_p10']:+.2f}%</span><span>P25: {r['bias_p25']:+.2f}%</span>
                    <span>P50: {r['bias_p50']:+.2f}%</span><span>P75: {r['bias_p75']:+.2f}%</span>
                    <span>P90: {r['bias_p90']:+.2f}%</span><span>σ: {r['bias_std']:.2f}%</span>
                </div>
                """
                html += f"<div class='chart-item'>"
                html += f"<div class='chart-title'>{color_mark} {r['name']}({code_short}) · BIAS{Config.MA_PERIOD}</div>"
                html += f"<img src='cid:{cid}' style='width:{config.get('img_width', 500)}px; height:auto; border:1px solid #ddd;'>"
                # html += f"<div class='stats' style='margin:4px 0 6px 0;'>当前:{r['bias_processed']:+.2f}% | 分位:{r['current_position']:.1f}%({pos_desc})</div>"
                # html += pct_html
                html += "</div>"
            
            # ── 图表2: 布林带 ──
            if 'boll' in Config.CHART_TYPES and f"{code_short}_boll" in image_data:
                cid = f"chart_{code_short}_boll"
                img = MIMEImage(image_data[f"{code_short}_boll"], 'png')
                img.add_header('Content-ID', f'<{cid}>')
                img.add_header('Content-Disposition', 'inline', filename=f"{code_short}_boll.png")
                msg.attach(img)
                
                # 计算布林带位置描述
                boll_mid = r.get('boll_mid', 0)
                boll_upper = r.get('boll_upper', 0)
                boll_lower = r.get('boll_lower', 0)
                current_price = r.get('current_price', 0)
                if boll_upper > boll_lower and current_price > 0:
                    boll_pos = (current_price - boll_lower) / (boll_upper - boll_lower) * 100
                    if boll_pos < 20: boll_desc = "接近下轨🟢"
                    elif boll_pos > 80: boll_desc = "接近上轨🔴"
                    else: boll_desc = "通道中部🟡"
                else:
                    boll_desc = "数据不足"
                
                html += f"<div class='chart-item' style='margin-top:10px;'>"
                html += f"<div class='chart-title'>📈 {r['name']}({code_short}) · {Config.BOLL_PERIOD}日布林带 [{boll_desc}]</div>"
                html += f"<img src='cid:{cid}' style='width:{config.get('img_width', 500)}px; height:auto; border:1px solid #ddd;'>"
                html += f"</div>"
        
        html += "<p style='color:#999;font-size:11px;margin-top:20px;border-top:1px solid #eee;padding-top:10px;'>※ 自动化报告 | 数据源: Tushare Pro | 仅供参考</p></body></html>"
        msg.attach(MIMEText(html, 'html', 'utf-8'))
        
        with smtplib.SMTP_SSL(config['smtp_server'], config['smtp_port']) as server:
            server.login(config['sender'], config['auth_code'])
            server.sendmail(config['sender'], [config['receiver']], msg.as_string())
        
        logging.info(f"✉️ 邮件发送成功 → {config['receiver']} (含{len(image_data)}张内存图表)")
        return True
    except Exception as e:
        logging.error(f"❌ 邮件发送失败: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return False

# ================= 指数数据 =================
INDEX_DATA: Dict[str, List[str]] = {
    "000001.SH": ["上证指数", "上证综合指数"], "000015.SH": ["红利指数", "上证红利指数"],
    "000016.SH": ["上证50", "上证50指数"], "000300.SH": ["沪深300", "沪深300指数"],
    "000683.SH": ["科创生物", "上证科创板生物医药指数"], "000685.SH": ["科创芯片", "上证科创板芯片指数"],
    "000688.SH": ["科创50", "上证科创板50成份指数"], "000690.SH": ["科创成长", "上证科创板成长指数"],
    "000692.SH": ["科创新能", "上证科创板新能源主题指数"], "000698.SH": ["科创100", "上证科创板100指数"],
    "000819.SH": ["有色金属", "中证申万有色金属指数"], "000823.SH": ["800有色", "中证800有色金属指数"],
    "000827.SH": ["中证环保", "中证环保产业指数"], "000852.SH": ["中证1000", "中证1000指数"],
    "000903.SH": ["中证100", "中证100指数"], "000905.SH": ["中证500", "中证小盘500指数"],
    "000906.SH": ["中证800", "中证800指数"], "000913.SH": ["300医药", "沪深300医药卫生指数"],
    "000914.SH": ["300金融", "沪深300金融地产指数"], "000915.SH": ["沪深300信息", "沪深300信息技术指数"],
    "000916.SH": ["沪深300电信", "沪深300通信服务指数"], "000932.SH": ["800消费", "中证主要消费指数"],
    "000933.SH": ["800医药", "中证医药卫生指数"], "000934.SH": ["800金地", "中证金融地产指数"],
    "000935.SH": ["800信息", "中证信息技术指数"], "000936.SH": ["800通信", "中证通信服务指数"],
    "000937.SH": ["800公用", "中证公用事业指数"], "000985.SH": ["中证全指", "中证全指指数"],
    "000989.SH": ["全指可选", "中证全指可选消费指数"], "000991.SH": ["全指医药", "中证全指医药卫生指数"],
    "000992.SH": ["金融地产", "中证全指金融地产指数"], "000993.SH": ["全指信息", "中证全指信息技术指数"],
    "000994.SH": ["全指通信", "中证全指通信业务指数"], "000995.SH": ["全指公用", "中证全指公用事业指数"],
    "931838.SH": ["煤炭产业", "中证煤炭产业指数"], "931845.SH": ["生猪产业", "中证生猪产业指数"],
    "398003.SZ": ["国证芯片", "国证半导体芯片"], "399001.SZ": ["深证成指", "深证成份指数"],
    "399006.SZ": ["创业板指", "创业板指数"], "399018.SZ": ["创业创新", "创业板创新指数"],
    "399101.SZ": ["中小综指", "中小企业综合指数"], "399102.SZ": ["创业板综", "创业板综合指数"],
    "399106.SZ": ["深证综指", "深证综合指数"], "399275.SZ": ["创医药", "创业板医药卫生指数"],
    "399276.SZ": ["创科技", "创业板科技指数"], "399283.SZ": ["机器人50", "深证机器人50指数"],
    "399284.SZ": ["AI 50", "深证人工智能50指数"], "399295.SZ": ["创价值", "创业板低波价值指数"],
    "399296.SZ": ["创成长", "创业板动量成长指数"], "399300.SZ": ["沪深300", "沪深300指数"],
    "399303.SZ": ["国证2000", "国证2000指数"], "399310.SZ": ["国证A50", "国证A50指数"],
    "399311.SZ": ["国证1000", "国证1000指数"], "399321.SZ": ["国证红利", "国证红利指数"],
    "399324.SZ": ["深证红利", "深证红利指数"], "399363.SZ": ["国证算力", "国证算力基础设施主题指数"],
    "399372.SZ": ["大盘成长", "巨潮大盘成长"], "399373.SZ": ["大盘价值", "巨潮大盘价值"],
    "399374.SZ": ["中盘成长", "巨潮中盘成长"], "399375.SZ": ["中盘价值", "巨潮中盘价值"],
    "399376.SZ": ["小盘成长", "巨潮小盘成长"], "399377.SZ": ["小盘价值", "巨潮小盘价值"],
    "399417.SZ": ["新能源车", "国证新能源车指数"], "399436.SZ": ["绿色煤炭", "国证绿色煤炭指数"],
    "399437.SZ": ["证券龙头", "国证证券龙头指数"], "399438.SZ": ["绿色电力", "国证绿色电力指数"],
    "399928.SZ": ["800能源", "中证能源指数"], "399971.SZ": ["中证传媒", "中证传媒指数"],
    "399967.SZ": ["中证军工", "中证军工指数"], "399975.SZ": ["证券公司", "中证全指证券公司指数"],
    "399976.SZ": ["CS新能车", "中证新能源汽车指数"], "399986.SZ": ["中证银行", "中证银行指数"],
    "399987.SZ": ["中证酒", "中证酒指数"], "399989.SZ": ["中证医疗", "中证医疗指数"],
    "399990.SZ": ["煤炭等权", "中证煤炭等权指数"], "399991.SZ": ["一带一路", "中证一带一路主题指数"],
    "399997.SZ": ["中证白酒", "中证白酒指数"], "399998.SZ": ["中证煤炭", "中证煤炭指数"]
}
INDICES = list(INDEX_DATA.keys())

# ================= 核心分析类 =================
class BiasAnalyzer:
    def __init__(self, token: str, server: str, 
                 lookback_years: float = Config.LOOKBACK_YEARS, 
                 ma_period: int = Config.MA_PERIOD):
        self.pro = ts.pro_api(server=server, token=token)
        self.lookback_days = int(lookback_years * 365.25) + 15
        self.lookback_years = lookback_years
        self.ma_period = ma_period
        self.index_data: Dict[str, List[str]] = {}
        self.results: List[Dict] = []

    def set_indices(self, indices: Dict[str, List[str]]) -> 'BiasAnalyzer':
        self.index_data = indices
        return self

    def _get_date_range(self, offset_days: int = 1) -> tuple:
        end = datetime.now() - timedelta(days=offset_days)
        start = end - timedelta(days=self.lookback_days)
        return end.strftime("%Y%m%d"), start.strftime("%Y%m%d")

    def fetch_data(self, code: str) -> Optional[pd.DataFrame]:
        end, start = self._get_date_range()
        try:
            df = self.pro.index_daily(ts_code=code, start_date=start, end_date=end, fields="ts_code,trade_date,close")
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
        
        # 🆕 计算布林带相关数据（用于邮件展示）
        close_series = df["close"].astype(float)
        if len(close_series) >= Config.BOLL_PERIOD:
            boll_mid = close_series.rolling(window=Config.BOLL_PERIOD).mean().iloc[-1]
            boll_std = close_series.rolling(window=Config.BOLL_PERIOD).std().iloc[-1]
            boll_upper = boll_mid + Config.BOLL_STD * boll_std
            boll_lower = boll_mid - Config.BOLL_STD * boll_std
            current_price = close_series.iloc[-1]
        else:
            boll_mid = boll_upper = boll_lower = current_price = np.nan
        
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
            "bias_processed_series": bias_processed,
            # 🆕 布林带数据
            "current_price": round(current_price, 2) if not np.isnan(current_price) else None,
            "boll_mid": round(boll_mid, 2) if not np.isnan(boll_mid) else None,
            "boll_upper": round(boll_upper, 2) if not np.isnan(boll_upper) else None,
            "boll_lower": round(boll_lower, 2) if not np.isnan(boll_lower) else None,
        }

    def _plot_bollinger(self, result: Dict) -> Optional[bytes]:
        """绘制收盘价与242日布林带图表（返回PNG字节流）"""
        df = result["df"].copy()
        code_short = result["code"][:6]
        name = result["name"]
        
        # 计算242日布林带
        window = Config.BOLL_PERIOD
        if len(df) < window + 10:
            return None
            
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df = df.dropna(subset=["close"])
        if len(df) < window:
            return None
            
        df["boll_mid"] = df["close"].rolling(window=window).mean()
        df["boll_std"] = df["close"].rolling(window=window).std()
        df["boll_upper"] = df["boll_mid"] + Config.BOLL_STD * df["boll_std"]
        df["boll_lower"] = df["boll_mid"] - Config.BOLL_STD * df["boll_std"]
        
        fig, ax = plt.subplots(figsize=(12, 5), dpi=Config.EMAIL_CONFIG.get('img_dpi', 100))
        
        # 绘制价格与布林带
        ax.plot(df["trade_date"], df["close"], label="收盘价", color="#2E86AB", linewidth=1)
        ax.plot(df["trade_date"], df["boll_mid"], label=f"中轨({window}MA)", color="#F18F01", linewidth=0.8, linestyle="--")
        ax.plot(df["trade_date"], df["boll_upper"], label=f"上轨(+{Config.BOLL_STD}σ)", color="#E53935", linewidth=0.6, alpha=0.7)
        ax.plot(df["trade_date"], df["boll_lower"], label=f"下轨(-{Config.BOLL_STD}σ)", color="#43A047", linewidth=0.6, alpha=0.7)
        
        # 填充布林带区域
        ax.fill_between(df["trade_date"], df["boll_lower"], df["boll_upper"], 
                       color="#90CAF9", alpha=0.15, label="布林通道")
        
        # 当前价格标记
        current_price = df.iloc[-1]["close"]
        current_date = df.iloc[-1]["trade_date"]
        ax.scatter([current_date], [current_price], color="#F18F01", s=30, zorder=5, 
                  label=f"当前: {current_price:.2f}")
        
        # 标题与标签
        ax.set_title(f"{code_short} {name} - 收盘价与{window}日布林带", fontsize=10, pad=8)
        ax.set_ylabel("价格", fontsize=9)
        ax.grid(True, linestyle=":", alpha=0.3)
        
        # 统计信息文本框
        if not np.isnan(df["boll_std"].iloc[-1]) and df["boll_std"].iloc[-1] != 0:
            boll_width = df["boll_upper"].iloc[-1] - df["boll_lower"].iloc[-1]
            boll_pct = (current_price - df["boll_mid"].iloc[-1]) / df["boll_std"].iloc[-1]
            stats_text = (f"当前价:{current_price:.2f} | 中轨:{df['boll_mid'].iloc[-1]:.2f}\n"
                          f"上轨:{df['boll_upper'].iloc[-1]:.2f} | 下轨:{df['boll_lower'].iloc[-1]:.2f}\n"
                          f"带宽:{boll_width:.2f}({boll_width/current_price*100:.1f}%) | 位置:{boll_pct:+.2f}σ")
        else:
            stats_text = f"当前价:{current_price:.2f} | 布林带计算中..."
            
        ax.text(0.02, 0.98, stats_text, transform=ax.transAxes, fontsize=7,
                verticalalignment='top', horizontalalignment='left',
                bbox=dict(boxstyle='round,pad=0.4', facecolor='#f5f5f5', alpha=0.92, edgecolor='#999', linewidth=0.5))
        
        ax.legend(loc='upper left', fontsize=6, framealpha=0.9, ncol=2)
        
        # 日期格式
        total = len(df)
        interval = 1 if total <= 200 else 2 if total <= 400 else 3
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=interval))
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=25, ha='right', fontsize=6)
        
        # 保存到内存
        buf = BytesIO()
        plt.savefig(buf, format='png', dpi=Config.EMAIL_CONFIG.get('img_dpi', 100), bbox_inches="tight")
        plt.close()
        buf.seek(0)
        return buf.read()

    def _plot_bias(self, result: Dict) -> Optional[bytes]:
        """绘制乖离率图表（返回PNG字节流，不写盘）"""
        df = result["df"]
        bias_series = result.get("bias_processed_series", result["df"]["bias_20"])
        code_short = result["code"][:6]
        name = result["name"]
        safe_name = safe_filename(name)
        
        fig, ax = plt.subplots(figsize=(12, 5), dpi=Config.EMAIL_CONFIG.get('img_dpi', 100))
        ax.plot(df["trade_date"], bias_series, label="乖离率(处理后)", color="#2E86AB", linewidth=1)
        if result["outlier_method"] != 'none':
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
        
        # 🆕 保存到内存缓冲
        buf = BytesIO()
        plt.savefig(buf, format='png', dpi=Config.EMAIL_CONFIG.get('img_dpi', 100), bbox_inches="tight")
        plt.close()
        buf.seek(0)
        return buf.read()

    def run(self, codes: List[str]) -> tuple:
        """执行分析，返回 (结果列表, 内存图片字典{code_short_type: bytes})"""
        logging.info(f"⏳ 开始分析近 {self.lookback_years} 年的 {self.ma_period} 日乖离率...")
        logging.info(f"🔧 异常值处理: {Config.OUTLIER_METHOD}")
        logging.info(f"📊 图表类型: {Config.CHART_TYPES}")
        
        image_data = {}  # 键格式: "{code_short}_bias" / "{code_short}_boll"
        
        for code in codes:
            name = self.index_data.get(code, [code, code])[0]
            raw = self.fetch_data(code)
            if raw is None: continue
            df = self.compute_bias(raw, self.ma_period)
            if df is None: continue
            
            result = self.analyze_bias(df, code, name, Config.OUTLIER_METHOD)
            self.results.append(result)
            
            # 🆕 生成乖离率图
            if 'bias' in Config.CHART_TYPES:
                img_bias = self._plot_bias(result)
                if img_bias:
                    image_data[f"{code[:6]}_bias"] = img_bias
            
            # 🆕 生成布林带图
            if 'boll' in Config.CHART_TYPES:
                img_boll = self._plot_bollinger(result)
                if img_boll:
                    image_data[f"{code[:6]}_boll"] = img_boll
        
        self._print_summary()
        return self.results, image_data

    def _print_summary(self):
        if not self.results: return
        print(f"\n📊 乖离率分析完成 | 指数:{len(self.results)} | 方法:{Config.OUTLIER_METHOD}")
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
    pro_check = ts.pro_api(server=Config.SERVER)
    
    if not is_trading_day(today, pro_check):
        logging.info(f"⏭️ {today} 非交易日，跳过")
        return
    
    analyzer = BiasAnalyzer(Config.TOKEN, Config.SERVER).set_indices(INDEX_DATA)
    results, image_data = analyzer.run(codes=INDICES)
    
    if Config.EMAIL_CONFIG.get("send_enabled") and results and image_data:
        logging.info(f"📧 发送邮件 ({len(image_data)}张内存图表)...")
        send_bias_email(results, image_data, Config.EMAIL_CONFIG)

if __name__ == '__main__':
    setup_font()
    main()