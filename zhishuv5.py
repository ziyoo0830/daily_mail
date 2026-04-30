import xcsc_tushare as ts
import pandas as pd
import numpy as np
import talib as ta
import datetime
import warnings
import logging
import smtplib
import time
import base64
import io
import traceback
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, List, Dict

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    logging.warning("⚠️ matplotlib未安装，静态图表将无法生成")

# ================= 配置区域 =================
TOKEN = '9ff9956bd08ab359df39e121be6abf60a1de590891ab833aa3156b2d'
SERVER = 'http://116.128.206.39:7172'

EMAIL_CONFIG = {
    "sender": "260319029@qq.com",
    "auth_code": "tofijpcsxefvbghg",
    "receiver": "ziyoo0830@163.com",
    "smtp_server": "smtp.qq.com",
    "smtp_port": 465
}

warnings.filterwarnings("ignore")
np.seterr(divide='ignore', invalid='ignore')
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

index_data = {
    "000001.SH": ["上证指数", "上证综合指数"],
    "000015.SH": ["红利指数", "上证红利指数"],
    "000016.SH": ["上证50", "上证50指数"],
    "000300.SH": ["沪深300", "沪深300指数"],
    "000688.SH": ["科创50", "上证科创板50成份指数"],
    "000690.SH": ["科创成长", "上证科创板成长指数"],
    "000852.SH": ["中证1000", "中证1000指数"],
    "000905.SH": ["中证500", "中证小盘500指数"],
    "000906.SH": ["中证800", "中证800指数"],
    "000985.SH": ["中证全指", "中证全指指数"],
    "399001.SZ": ["深证成指", "深证成份指数"],
    "399006.SZ": ["创业板指", "创业板指数"],
    "399101.SZ": ["中小综指", "中小企业综合指数"],
    "399102.SZ": ["创业板综", "创业板综合指数"],
    "399106.SZ": ["深证综指", "深证综合指数"],
    "399296.SZ": ["创成长", "创业板动量成长指数"],
    "399303.SZ": ["国证2000", "国证2000指数"],
}
INDICES = list(index_data.keys())

def setup_matplotlib_chinese():
    if not MATPLOTLIB_AVAILABLE:
        return
    try:
        font_list = ['SimHei', 'Microsoft YaHei', 'WenQuanYi Micro Hei', 'Noto Sans CJK SC', 'DejaVu Sans']
        available_fonts = set([f.name for f in matplotlib.font_manager.fontManager.ttflist])
        for font in font_list:
            if font in available_fonts:
                matplotlib.rcParams['font.sans-serif'] = [font]
                logging.info(f"✅ 已设置matplotlib中文字体: {font}")
                break
        else:
            matplotlib.rcParams['font.sans-serif'] = ['Arial']
            logging.warning("⚠️ 未找到中文字体，图表中的中文可能显示为方框")
        matplotlib.rcParams['axes.unicode_minus'] = False
    except Exception as e:
        logging.warning(f"设置matplotlib字体失败: {e}")

setup_matplotlib_chinese()


class IndexStrategyAnalyzer:
    def __init__(self, token: str, server: str, lookback_days: int = 180):
        self.pro = ts.pro_api(server=server, token=token)
        self.lookback = lookback_days
        self.index_data = {}
        self.results = []

    def set_indices(self, indices: Dict[str, List[str]]):
        self.index_data = indices
        return self

    def _get_date_range(self, offset_days: int = 1, lookback_days: int = None):
        end = datetime.datetime.now() - datetime.timedelta(days=offset_days)
        lb = lookback_days if lookback_days is not None else self.lookback
        start = end - datetime.timedelta(days=lb)
        return end.strftime("%Y%m%d"), start.strftime("%Y%m%d")

    def fetch_data(self, code: str, fields: str, lookback_days: int = None) -> Optional[pd.DataFrame]:
        end, start = self._get_date_range(lookback_days=lookback_days)
        try:
            df = self.pro.index_daily(ts_code=code, start_date=start, end_date=end, fields=fields)
            if df is not None and not df.empty:
                return df.sort_values("trade_date").reset_index(drop=True)
            return None
        except Exception as e:
            logging.warning(f"❌ {code} 获取失败: {e}")
            return None

    @staticmethod
    def compute_indicators(df: pd.DataFrame) -> Optional[pd.DataFrame]:
        """计算完整的技术指标体系"""
        if df is None or len(df) < 60:
            return None
        df = df.copy()
        if 'pct_chg' in df.columns:
            df.rename(columns={"pct_chg": "pct_change"}, inplace=True)
        if 'volume' in df.columns:
            df.rename(columns={"volume": "vol"}, inplace=True)
        required = ["close","open","high","low","vol"]
        for col in required:
            if col not in df.columns:
                logging.error(f"缺少必要列 {col}")
                return None
        c = df["close"].values.astype(np.float64)
        o = df["open"].values.astype(np.float64)
        h = df["high"].values.astype(np.float64)
        l = df["low"].values.astype(np.float64)
        v = df["vol"].values.astype(np.float64)

        # === 趋势指标 ===
        for p in [5,10,20,30,60,90,250]:
            df[f"ma_{p}"], df[f"ema_{p}"] = ta.MA(c, p), ta.EMA(c, p)
        
        # MACD
        df["macd_dif"], df["macd_dea"], df["macd"] = ta.MACD(c, 12, 26, 9)
        
        # === 摆动指标 ===
        # KDJ
        k, d = ta.STOCH(h, l, c, fastk_period=9, slowk_period=3, slowk_matype=0, slowd_period=3, slowd_matype=0)
        df["kdj_k"], df["kdj_d"] = k, d
        df["kdj_j"] = 3 * df["kdj_k"] - 2 * df["kdj_d"]
        
        # RSI
        df["rsi_6"], df["rsi_14"] = ta.RSI(c, 6), ta.RSI(c, 14)
        
        # Williams %R
        df["willr_14"] = ta.WILLR(h, l, c, timeperiod=14)
        
        # === 波动率指标 ===
        # 布林带
        df["boll_up"], df["boll_mid"], df["boll_low"] = ta.BBANDS(c, 20, 2, 2)
        
        # ATR
        df["atr_14"] = ta.ATR(h, l, c, timeperiod=14)
        df["atr_21"] = ta.ATR(h, l, c, timeperiod=21)
        
        # CCI
        df["cci"] = ta.CCI(h, l, c, 14)
        
        # === 成交量指标 ===
        # OBV
        df["obv"] = ta.OBV(c, v)
        df["obv_ma_20"] = ta.MA(df["obv"].values, 20)
        
        # 成交量均线
        df["vol_ma_20"] = ta.SMA(v, 20)
        df["vol_ma_60"] = ta.SMA(v, 60)
        
        # === 趋势强度指标 ===
        # DMI/ADX
        df["plus_di"] = ta.PLUS_DI(h, l, c, timeperiod=14)
        df["minus_di"] = ta.MINUS_DI(h, l, c, timeperiod=14)
        df["adx"] = ta.ADX(h, l, c, timeperiod=14)
        
        # SAR
        df["sar"] = ta.SAR(h, l, acceleration=0.02, maximum=0.2)
        
        # === 动量指标 ===
        # ROC
        df["roc_10"] = ta.ROC(c, timeperiod=10)
        df["roc_20"] = ta.ROC(c, timeperiod=20)
        
        # MOM
        df["momentum_10"] = ta.MOM(c, timeperiod=10)
        
        # === 乖离率 ===
        for period in [5, 10, 20, 60]:
            ma_col = f"ma_{period}"
            if ma_col in df.columns:
                df[f"bias_{period}"] = (c / df[ma_col].values - 1) * 100
        
        # === 其他 ===
        # 真实波动范围
        df["tr"] = ta.TRANGE(h, l, c)
        df["tr_ma_14"] = ta.MA(df["tr"].values, 14)
        
        return df

    @staticmethod
    def generate_signals(df: pd.DataFrame, code: str, name: str) -> Dict:
        latest, prev = df.iloc[-1], df.iloc[-2]
        score, reasons = 0, []
        c, ma20, ma60 = latest["close"], latest["ma_20"], latest["ma_60"]

        # ================= 1. 趋势基础分（降权，防纯动量虚高） =================
        if c > ma20 > ma60:
            score += 12; reasons.append("均线多头")
        elif c > ma60 and ma20 > ma60:
            score += 8; reasons.append("中长期多头")

        # ================= 2. 核心防追高过滤（位置决定一切） =================
        bias20 = (c / ma20 - 1) * 100 if not pd.isna(ma20) else 0
        bias60 = (c / ma60 - 1) * 100 if not pd.isna(ma60) else 0

        # 硬性偏离拦截
        if bias20 > 8:
            score -= 20; reasons.append("严重偏离20日线(>8%)/追高风险极大")
        elif bias20 > 5:
            score -= 12; reasons.append("偏离20日线较多/空间有限")
            
        if bias60 > 22:
            score -= 10; reasons.append("远离60日线/中期透支")

        # 奖励健康回踩（核心优化：只在支撑位附近给高分）
        if c > ma60 and bias20 <= 1.5 and bias20 >= -3.0 and ma20 > ma60:
            score += 18; reasons.append("多头趋势回踩20线/优质低吸位")
        elif abs(bias20) < 1.5 and ma20 > ma60:
            score += 12; reasons.append("均线粘合蓄势/方向选择前夜")

        # ================= 3. 短期涨幅拦截（防脉冲诱多） =================
        if len(df) >= 20:
            ret_10d = (c / df.iloc[-10]["close"] - 1) * 100
            ret_20d = (c / df.iloc[-20]["close"] - 1) * 100
            if ret_10d > 12:
                score -= 12; reasons.append("近10日急涨(>12%)/防冲高回落")
            elif ret_20d > 18:
                score -= 10; reasons.append("近20日涨幅过大/动能透支")

        # ================= 4. 指标协同验证（去伪存真） =================
        # MACD：只给金叉/水上加分，死叉/水下不减分（趋势保护）
        dif, dea = latest["macd_dif"], latest["macd_dea"]
        pdif, pdea = prev["macd_dif"], prev["macd_dea"]
        if dif > dea and pdif <= pdea:
            score += 8; reasons.append("MACD金叉")
        elif dif > 0 and dea > 0:
            score += 4; reasons.append("MACD零轴上方")

        # RSI：严苛超买扣分，鼓励低位修复
        rsi14 = latest["rsi_14"]
        if rsi14 > 78:
            score -= 10; reasons.append("RSI严重超买(>78)")
        elif rsi14 > 65 and bias20 > 3:
            score -= 6; reasons.append("RSI偏高+偏离均线/过热")
        elif 35 < rsi14 < 55 and c > ma60:
            score += 6; reasons.append("RSI修复到位/蓄势充分")

        # 量价配合：天量高位警惕，缩量回踩加分
        vol, vol_ma20 = latest["vol"], latest["vol_ma_20"]
        if not pd.isna(vol_ma20):
            if vol > vol_ma20 * 2.5 and bias20 > 3:
                score -= 10; reasons.append("天量拉升+高位偏离/主力派发嫌疑")
            elif vol < vol_ma20 * 0.6 and abs(bias20) < 3:
                score += 8; reasons.append("缩量回踩/抛压衰竭")

        # ================= 5. 动态评级与操作建议（位置绑定动作） =================
        # 判断当前是“突破”还是“回踩”
        is_pullback = (c > ma60 and bias20 <= 1.5)
        
        if score >= 25:
            if is_pullback:
                rating, action = "★★★ 强烈买入", "重仓布局(回踩确认)"
            else:
                rating, action = "★★ 建议买入", "分批建仓(防追高)"
        elif score >= 15:
            rating, action = "★ 关注", "小仓试错/等回踩"
        elif score <= -10:
            rating, action = "★★★ 回避", "减仓/观望"
        else:
            rating, action = "观望", "持有/等待明确信号"

        return {
            "code": code, "name": name, "score": score,
            "rating": rating, "action": action, "reasons": reasons,
            "close": c
        }

    def run(self, codes: List[str], export_csv: Optional[str] = None):
        fields = "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,volume,amount"
        logging.info(f"⏳ 开始分析 {len(codes)} 个指数...")

        sh_code = "000001.SH"
        market_bull = True
        raw_sh = self.fetch_data(sh_code, fields)
        if raw_sh is not None:
            df_sh = self.compute_indicators(raw_sh)
            if df_sh is not None and len(df_sh) > 0:
                sh_last = df_sh.iloc[-1]
                if sh_last["close"] > sh_last["ma_60"] and sh_last["ma_20"] > sh_last["ma_60"]:
                    market_bull = True
                    logging.info("🌞 大盘状态：多头")
                else:
                    market_bull = False
                    logging.info("🌧️ 大盘状态：非多头（评分打七折）")
            else:
                logging.warning("无法计算上证指数指标，沿用默认看多")
        else:
            logging.warning("上证指数数据获取失败，沿用默认看多")

        self.results = []
        for code in codes:
            name = self.index_data.get(code, [code, code])[0]
            raw = self.fetch_data(code, fields)
            if raw is None:
                continue
            df = self.compute_indicators(raw)
            if df is None:
                continue
            signal = self.generate_signals(df, code, name)
            if not market_bull:
                signal["score"] = int(signal["score"] * 0.7)
                s = signal["score"]
                if s >= 30:
                    signal["rating"], signal["action"] = "★★★ 强烈买入", "重仓出击"
                elif s >= 20:
                    signal["rating"], signal["action"] = "★★ 建议买入", "逢低布局"
                elif s >= 10:
                    signal["rating"], signal["action"] = "★ 关注", "小仓试错"
                elif s <= -5:
                    signal["rating"], signal["action"] = "★★★ 回避", "清仓/空仓"
                else:
                    signal["rating"], signal["action"] = "观望", "持有/等待"
            self.results.append({"signal": signal, "df": df})
            time.sleep(0.05)

        self.results.sort(key=lambda x: x["signal"]["score"], reverse=True)

        if export_csv:
            pd.DataFrame([r["signal"] for r in self.results]).to_csv(export_csv, index=False, encoding="utf-8-sig")
            logging.info(f"💾 结果已保存: {export_csv}")

        return self.results

    def get_long_term_data(self, code: str, years: int = 3, min_rows: int = 250) -> Optional[pd.DataFrame]:
        """
        获取指定指数多年数据，确保至少有 min_rows 条记录。
        逐步扩大自然日回溯范围，最大至 2200 自然日（约6年）。
        """
        fields = "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,volume,amount"
        
        # 初始自然日回溯天数 (基于每年约250交易日，额外加20%缓冲)
        initial_days = int(years * 250 * 1.2)   # 3年 -> 900自然日
        max_days = 2200                         # 扩大到约6年
        step = 100

        for lookback_days in range(initial_days, max_days + 1, step):
            raw = self.fetch_data(code, fields, lookback_days=lookback_days)
            if raw is None:
                continue
            df = self.compute_indicators(raw)
            if df is not None and len(df) >= min_rows:
                logging.info(f"✅ {code} 获取到 {len(df)} 条记录 (回溯{lookback_days}自然日)")
                return df
        
        # 实在不够，返回现有的（可能少于 min_rows）
        raw = self.fetch_data(code, fields, lookback_days=max_days)
        if raw is not None:
            df = self.compute_indicators(raw)
            if df is not None:
                logging.warning(f"⚠️ {code} 仅获取到 {len(df)} 条记录，低于目标 {min_rows}，将使用现有数据")
                return df
        return None


def create_static_bias_chart(df_long: pd.DataFrame, title: str) -> Optional[str]:
    """生成20日乖离率曲线图"""
    if not MATPLOTLIB_AVAILABLE or df_long is None or len(df_long) < 20:
        return None
    try:
        df = df_long.copy()
        df.sort_values('trade_date', inplace=True)
        df['date_dt'] = pd.to_datetime(df['trade_date'], format='%Y%m%d')
        bias = (df['close'] / df['ma_20'] - 1) * 100

        fig, ax = plt.subplots(figsize=(12, 5))
        ax.plot(df['date_dt'], bias, color='blue', linewidth=1.5, label='20日乖离率(%)')
        ax.axhline(y=0, color='red', linestyle='--', linewidth=1, alpha=0.7, label='零轴')
        ax.fill_between(df['date_dt'], bias, 0, where=(bias >= 0), color='red', alpha=0.2, interpolate=True)
        ax.fill_between(df['date_dt'], bias, 0, where=(bias < 0), color='green', alpha=0.2, interpolate=True)

        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        plt.xticks(rotation=45, ha='right')
        ax.set_title(f'{title} - 20日乖离率曲线 (近3年)', fontsize=12)
        ax.set_ylabel('乖离率 (%)')
        ax.set_xlabel('交易日期')
        ax.grid(True, linestyle=':', alpha=0.6)
        ax.legend(loc='best')
        plt.tight_layout()

        buffer = io.BytesIO()
        plt.savefig(buffer, format='png', dpi=100, bbox_inches='tight')
        buffer.seek(0)
        img_base64 = base64.b64encode(buffer.read()).decode('utf-8')
        plt.close(fig)
        return img_base64
    except Exception as e:
        logging.error(f"生成静态乖离率图失败 {title}: {e}")
        return None


def create_price_with_bollinger_chart(df_long: pd.DataFrame, title: str, target_period: int = 60) -> Optional[str]:
    """绘制收盘价 + 布林带"""
    if not MATPLOTLIB_AVAILABLE or df_long is None or len(df_long) < 20:
        logging.warning(f"{title} 数据不足20条，无法生成布林带图")
        return None
    try:
        df = df_long.copy()
        df.sort_values('trade_date', inplace=True)
        df['date_dt'] = pd.to_datetime(df['trade_date'], format='%Y%m%d')
        close = df['close'].values.astype(np.float64)
        data_len = len(close)
        
        # 确定布林带周期
        if data_len >= target_period:
            period = target_period
            logging.info(f"{title} 数据长度 {data_len} >= {target_period}，使用 {period} 日布林带")
        else:
            period = data_len - 1
            if period < 20:
                period = 20
            logging.warning(f"{title} 数据长度 {data_len} < {target_period}，降级使用 {period} 日布林带")
        
        # 计算布林带
        upper, middle, lower = ta.BBANDS(close, timeperiod=period, nbdevup=2, nbdevdn=2, matype=0)
        df['boll_mid'] = middle
        df['boll_up'] = upper
        df['boll_low'] = lower
        
        fig, ax = plt.subplots(figsize=(12, 6))
        ax.plot(df['date_dt'], close, label='收盘价', color='black', linewidth=1)
        ax.plot(df['date_dt'], df['boll_mid'], label=f'{period}日均线（中轨）', color='blue', linestyle='--', linewidth=1)
        ax.plot(df['date_dt'], df['boll_up'], label='上轨 (+2σ)', color='red', linestyle=':', linewidth=1)
        ax.plot(df['date_dt'], df['boll_low'], label='下轨 (-2σ)', color='green', linestyle=':', linewidth=1)
        ax.fill_between(df['date_dt'], df['boll_up'], df['boll_low'], alpha=0.1, color='gray')
        
        # 使用更稀疏的刻度
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        
        plt.xticks(rotation=45, ha='right')
        
        ax.set_title(f'{title} - 收盘价与{period}日布林带', fontsize=12)
        ax.set_ylabel('价格')
        ax.set_xlabel('交易日期')
        ax.grid(True, linestyle=':', alpha=0.6)
        ax.legend(loc='best')
        plt.tight_layout()
        
        buffer = io.BytesIO()
        plt.savefig(buffer, format='png', dpi=100, bbox_inches='tight')
        buffer.seek(0)
        img_base64 = base64.b64encode(buffer.read()).decode('utf-8')
        plt.close(fig)
        return img_base64
    except Exception as e:
        logging.error(f"生成布林带图失败 {title}: {e}")
        return None


def create_atr_chart(df_long: pd.DataFrame, title: str) -> Optional[str]:
    """ATR波动率曲线"""
    if not MATPLOTLIB_AVAILABLE or df_long is None or 'atr_14' not in df_long.columns:
        return None
    try:
        df = df_long.copy()
        df.sort_values('trade_date', inplace=True)
        df['date_dt'] = pd.to_datetime(df['trade_date'], format='%Y%m%d')
        
        fig, ax = plt.subplots(figsize=(12, 4))
        ax.plot(df['date_dt'], df['atr_14'], label='ATR(14)', color='orange', linewidth=1.5)
        ax.fill_between(df['date_dt'], df['atr_14'], alpha=0.3, color='orange')
        
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        plt.xticks(rotation=45, ha='right')
        
        ax.set_title(f'{title} - ATR波动率', fontsize=12)
        ax.set_ylabel('ATR值')
        ax.set_xlabel('交易日期')
        ax.grid(True, linestyle=':', alpha=0.6)
        ax.legend(loc='best')
        plt.tight_layout()
        
        buffer = io.BytesIO()
        plt.savefig(buffer, format='png', dpi=100, bbox_inches='tight')
        buffer.seek(0)
        return base64.b64encode(buffer.read()).decode('utf-8')
    except Exception as e:
        logging.error(f"生成ATR图失败 {title}: {e}")
        return None


def create_obv_chart(df_long: pd.DataFrame, title: str) -> Optional[str]:
    """OBV能量潮曲线"""
    if not MATPLOTLIB_AVAILABLE or df_long is None or 'obv' not in df_long.columns:
        return None
    try:
        df = df_long.copy()
        df.sort_values('trade_date', inplace=True)
        df['date_dt'] = pd.to_datetime(df['trade_date'], format='%Y%m%d')
        
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 7), sharex=True, gridspec_kw={'height_ratios': [2, 1]})
        
        # 上图：价格
        ax1.plot(df['date_dt'], df['close'], label='收盘价', color='black', linewidth=1)
        ax1.set_title(f'{title} - 价格与OBV')
        ax1.set_ylabel('价格')
        ax1.grid(True, linestyle=':', alpha=0.6)
        ax1.legend(loc='best')
        
        # 下图：OBV
        ax2.plot(df['date_dt'], df['obv'], label='OBV', color='blue', linewidth=1)
        ax2.plot(df['date_dt'], df['obv_ma_20'], label='OBV MA20', color='red', linestyle='--', linewidth=1)
        ax2.set_ylabel('OBV')
        ax2.set_xlabel('日期')
        ax2.grid(True, linestyle=':', alpha=0.6)
        ax2.legend(loc='best')
        
        ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
        ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        plt.xticks(rotation=45, ha='right')
        plt.tight_layout()
        
        buffer = io.BytesIO()
        plt.savefig(buffer, format='png', dpi=100, bbox_inches='tight')
        buffer.seek(0)
        return base64.b64encode(buffer.read()).decode('utf-8')
    except Exception as e:
        logging.error(f"生成OBV图失败 {title}: {e}")
        return None


def create_adx_chart(df_long: pd.DataFrame, title: str) -> Optional[str]:
    """ADX趋势强度曲线"""
    if not MATPLOTLIB_AVAILABLE or df_long is None or 'adx' not in df_long.columns:
        return None
    try:
        df = df_long.copy()
        df.sort_values('trade_date', inplace=True)
        df['date_dt'] = pd.to_datetime(df['trade_date'], format='%Y%m%d')
        
        fig, ax = plt.subplots(figsize=(12, 4))
        ax.plot(df['date_dt'], df['adx'], label='ADX', color='purple', linewidth=1.5)
        ax.plot(df['date_dt'], df['plus_di'], label='+DI', color='green', linestyle='--', linewidth=1)
        ax.plot(df['date_dt'], df['minus_di'], label='-DI', color='red', linestyle='--', linewidth=1)
        
        # 添加趋势强度参考线
        ax.axhline(y=25, color='gray', linestyle=':', linewidth=1, alpha=0.7)
        ax.axhline(y=50, color='gray', linestyle=':', linewidth=1, alpha=0.7)
        
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        plt.xticks(rotation=45, ha='right')
        
        ax.set_title(f'{title} - ADX趋势强度', fontsize=12)
        ax.set_ylabel('ADX/DI值')
        ax.set_xlabel('交易日期')
        ax.grid(True, linestyle=':', alpha=0.6)
        ax.legend(loc='best')
        plt.tight_layout()
        
        buffer = io.BytesIO()
        plt.savefig(buffer, format='png', dpi=100, bbox_inches='tight')
        buffer.seek(0)
        return base64.b64encode(buffer.read()).decode('utf-8')
    except Exception as e:
        logging.error(f"生成ADX图失败 {title}: {e}")
        return None


def create_rsi_chart(df_long: pd.DataFrame, title: str) -> Optional[str]:
    """RSI相对强弱指标"""
    if not MATPLOTLIB_AVAILABLE or df_long is None or 'rsi_14' not in df_long.columns:
        return None
    try:
        df = df_long.copy()
        df.sort_values('trade_date', inplace=True)
        df['date_dt'] = pd.to_datetime(df['trade_date'], format='%Y%m%d')
        
        fig, ax = plt.subplots(figsize=(12, 4))
        ax.plot(df['date_dt'], df['rsi_14'], label='RSI(14)', color='blue', linewidth=1.5)
        
        # 添加超买超卖线
        ax.axhline(y=70, color='red', linestyle='--', linewidth=1, alpha=0.7, label='超买线')
        ax.axhline(y=30, color='green', linestyle='--', linewidth=1, alpha=0.7, label='超卖线')
        ax.axhline(y=50, color='gray', linestyle=':', linewidth=1, alpha=0.5)
        
        ax.set_ylim(0, 100)
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        plt.xticks(rotation=45, ha='right')
        
        ax.set_title(f'{title} - RSI相对强弱指标', fontsize=12)
        ax.set_ylabel('RSI值')
        ax.set_xlabel('交易日期')
        ax.grid(True, linestyle=':', alpha=0.6)
        ax.legend(loc='best')
        plt.tight_layout()
        
        buffer = io.BytesIO()
        plt.savefig(buffer, format='png', dpi=100, bbox_inches='tight')
        buffer.seek(0)
        return base64.b64encode(buffer.read()).decode('utf-8')
    except Exception as e:
        logging.error(f"生成RSI图失败 {title}: {e}")
        return None


def send_email_report(analyzer: IndexStrategyAnalyzer, results_with_df: List[Dict], config: Dict):
    """发送邮件，包含完整的技术指标图表"""
    try:
        signals = [item['signal'] for item in results_with_df]
        subject = f"📊 指数策略分析报告 - {datetime.datetime.now().strftime('%Y%m%d')}"

        html_body = f"""
        <html><body style="font-family: Arial, 'Microsoft YaHei', sans-serif; font-size: 11px;">
        <h3 style="font-size: 13px; margin: 10px 0;">📈 指数技术分析简报</h3>
        <p style="margin: 5px 0;">分析时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
        <p style="margin: 5px 0;">共分析 <strong>{len(signals)}</strong> 个指数</p>
        <p style="margin: 5px 0;">🔥 强烈买入: {sum(1 for r in signals if '强烈买入' in r['rating'])} | 
           📈 建议买入: {sum(1 for r in signals if '建议买入' in r['rating'])}</p>
        <hr style="margin: 10px 0;">
        <table border="1" cellspacing="0" cellpadding="4" style="border-collapse: collapse; font-size: 11px; width: 100%;">
            <tr style="background-color: #f2f2f2; font-weight: bold;">
                <th style="padding: 4px;">代码</th><th style="padding: 4px;">名称</th><th style="padding: 4px;">评分</th><th style="padding: 4px;">评级</th><th style="padding: 4px;">信号理由</th>
            </tr>
        """
        for r in signals:
            code_short = r['code'][:6]
            if "强烈买入" in r["rating"]:
                bg_color, txt_color = "#ff4d4d", "#ffffff"
            elif "建议买入" in r["rating"]:
                bg_color, txt_color = "#ffcccc", "#000000"
            elif "关注" in r["rating"]:
                bg_color, txt_color = "#fff3cd", "#000000"
            else:
                bg_color, txt_color = "#ffffff", "#000000"
            html_body += f"""
            <tr style="background-color: {bg_color}; color: {txt_color};">
                <td style="padding: 4px;">{code_short}</td>
                <td style="padding: 4px;">{r['name']}</td>
                <td style="padding: 4px; text-align: center;">{r['score']}</td>
                <td style="padding: 4px;">{r['rating']}</td>
                <td style="padding: 4px;">{'; '.join(r['reasons'])}</td>
            </tr>
            """
        html_body += "</table>"

        html_body += """
        <hr style="margin: 20px 0;">
        <h3 style="font-size: 13px;">📉 技术指标图表（近3年）</h3>
        <p style="font-size: 10px; color: gray;">包含：乖离率、布林带、ATR波动率、OBV资金流向、ADX趋势强度、RSI超买超卖</p>
        """

        for item in results_with_df:
            signal = item['signal']
            code = signal['code']
            name = signal['name']
            short_code = code[:6]

            # 获取长期数据
            df_long = analyzer.get_long_term_data(code, years=3, min_rows=250)
            if df_long is None:
                html_body += f"<p><strong>{short_code} {name}</strong> 无法获取3年数据，图表生成失败</p>"
                continue

            data_len = len(df_long)
            logging.info(f"📊 {code} {name} 历史数据行数: {data_len}")

            # 1. 乖离率图
            img_bias = create_static_bias_chart(df_long, f"{short_code} {name}")
            if img_bias:
                html_body += f"""
                <div style="margin-bottom: 20px; border-top: 1px solid #ddd; padding-top: 10px;">
                    <p><strong>{short_code} {name} - 20日乖离率</strong></p>
                    <img src="data:image/png;base64,{img_bias}" style="max-width: 100%; height: auto;">
                </div>
                """

            # 2. 布林带图
            img_boll = create_price_with_bollinger_chart(df_long, f"{short_code} {name}", target_period=60)
            if img_boll:
                html_body += f"""
                <div style="margin-bottom: 20px; border-top: 1px solid #ddd; padding-top: 10px;">
                    <p><strong>{short_code} {name} - 布林带（60日周期）</strong></p>
                    <img src="data:image/png;base64,{img_boll}" style="max-width: 100%; height: auto;">
                </div>
                """

            # 3. ATR波动率图
            img_atr = create_atr_chart(df_long, f"{short_code} {name}")
            if img_atr:
                html_body += f"""
                <div style="margin-bottom: 20px; border-top: 1px solid #ddd; padding-top: 10px;">
                    <p><strong>{short_code} {name} - ATR波动率</strong></p>
                    <img src="data:image/png;base64,{img_atr}" style="max-width: 100%; height: auto;">
                </div>
                """

            # 4. OBV资金流向图
            img_obv = create_obv_chart(df_long, f"{short_code} {name}")
            if img_obv:
                html_body += f"""
                <div style="margin-bottom: 20px; border-top: 1px solid #ddd; padding-top: 10px;">
                    <p><strong>{short_code} {name} - OBV能量潮</strong></p>
                    <img src="data:image/png;base64,{img_obv}" style="max-width: 100%; height: auto;">
                </div>
                """

            # 5. ADX趋势强度图
            img_adx = create_adx_chart(df_long, f"{short_code} {name}")
            if img_adx:
                html_body += f"""
                <div style="margin-bottom: 20px; border-top: 1px solid #ddd; padding-top: 10px;">
                    <p><strong>{short_code} {name} - ADX趋势强度</strong></p>
                    <img src="data:image/png;base64,{img_adx}" style="max-width: 100%; height: auto;">
                </div>
                """

            # 6. RSI超买超卖图
            img_rsi = create_rsi_chart(df_long, f"{short_code} {name}")
            if img_rsi:
                html_body += f"""
                <div style="margin-bottom: 20px; border-top: 1px solid #ddd; padding-top: 10px;">
                    <p><strong>{short_code} {name} - RSI相对强弱</strong></p>
                    <img src="data:image/png;base64,{img_rsi}" style="max-width: 100%; height: auto;">
                </div>
                """

        html_body += "</body></html>"

        text_body = f"指数策略分析报告\n{'='*60}\n"
        text_body += f"分析时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        text_body += f"共分析 {len(signals)} 个指数\n"
        text_body += f"🔥 强烈买入: {sum(1 for r in signals if '强烈买入' in r['rating'])}\n"
        text_body += f"📈 建议买入: {sum(1 for r in signals if '建议买入' in r['rating'])}\n{'-'*60}\n"
        for r in signals:
            code_short = r['code'][:6]
            text_body += f"{code_short} {r['name']} 评分:{r['score']} {r['rating']}\n"
        text_body += "\n完整技术指标图表已嵌入邮件正文（乖离率、布林带、ATR、OBV、ADX、RSI）。"

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = config["sender"]
        msg["To"] = config["receiver"]
        msg.attach(MIMEText(text_body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        with smtplib.SMTP_SSL(config["smtp_server"], config["smtp_port"]) as server:
            server.login(config["sender"], config["auth_code"])
            server.sendmail(config["sender"], [config["receiver"]], msg.as_string())

        logging.info(f"✉️ 邮件已发送至 {config['receiver']}")
        return True

    except Exception as e:
        logging.error(f"❌ 邮件发送失败: {e}")
        logging.error(traceback.format_exc())
        return False


if __name__ == '__main__':
    analyzer = IndexStrategyAnalyzer(TOKEN, SERVER).set_indices(index_data)
    full_results = analyzer.run(
        codes=INDICES,
        export_csv=f"signal_{datetime.datetime.now().strftime('%Y%m%d')}.csv"
    )

    signals = [item['signal'] for item in full_results]
    print(f"\n📊 共分析 {len(signals)} 个指数")
    print(f"🔥 强烈买入: {sum(1 for r in signals if '强烈买入' in r['rating'])}")
    print(f"📈 建议买入: {sum(1 for r in signals if '建议买入' in r['rating'])}")
    print("-" * 75)
    print(f"{'代码':<8} {'名称':<18} {'评级':<14} {'评分':>5}")
    print("-" * 75)
    for r in signals:
        code_short = r['code'][:6]
        print(f"{code_short:<8} {r['name']:<18} {r['rating']:<14} {r['score']:>5}")

    send_email_report(analyzer, full_results, EMAIL_CONFIG)