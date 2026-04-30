import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

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
    "000683.SH": ["科创生物", "上证科创板生物医药指数"], 
    "000685.SH": ["科创芯片", "上证科创板芯片指数"],
    "000688.SH": ["科创50", "上证科创板50成份指数"], 
    "000690.SH": ["科创成长", "上证科创板成长指数"],
    "000692.SH": ["科创新能", "上证科创板新能源主题指数"], 
    "000698.SH": ["科创100", "上证科创板100指数"],
    "000819.SH": ["有色金属", "中证申万有色金属指数"], 
    "000823.SH": ["800有色", "中证800有色金属指数"],
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
                break
        else:
            matplotlib.rcParams['font.sans-serif'] = ['Arial']
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
        self.market_regime = "bull"

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
            return None

    @staticmethod
    def compute_indicators(df: pd.DataFrame) -> Optional[pd.DataFrame]:
        if df is None or len(df) < 60:
            return None
        df = df.copy()
        if 'pct_chg' in df.columns: df.rename(columns={"pct_chg": "pct_change"}, inplace=True)
        if 'volume' in df.columns: df.rename(columns={"volume": "vol"}, inplace=True)
        required = ["close","open","high","low","vol"]
        for col in required:
            if col not in df.columns: return None
            
        c = df["close"].values.astype(np.float64)
        o = df["open"].values.astype(np.float64)
        h = df["high"].values.astype(np.float64)
        l = df["low"].values.astype(np.float64)
        v = df["vol"].values.astype(np.float64)

        for p in [5,10,20,30,60,90,250]:
            df[f"ma_{p}"] = ta.MA(c, p)
        
        df["macd_dif"], df["macd_dea"], df["macd"] = ta.MACD(c, 12, 26, 9)
        k, d = ta.STOCH(h, l, c, fastk_period=9, slowk_period=3, slowd_period=3)
        df["kdj_k"], df["kdj_d"] = k, d
        df["rsi_6"], df["rsi_14"] = ta.RSI(c, 6), ta.RSI(c, 14)
        
        df["boll_up"], df["boll_mid"], df["boll_low"] = ta.BBANDS(c, 20, 2, 2)
        df["atr_14"] = ta.ATR(h, l, c, timeperiod=14)
        df["atr_21"] = ta.ATR(h, l, c, timeperiod=21)
        df["cci"] = ta.CCI(h, l, c, 14)
        
        df["obv"] = ta.OBV(c, v)
        df["obv_ma_20"] = ta.MA(df["obv"].values, 20)
        df["vol_ma_20"] = ta.SMA(v, 20)
        df["adx"] = ta.ADX(h, l, c, timeperiod=14)
        
        df["bias_20"] = (c / df["ma_20"].values - 1) * 100
        df["bias_60"] = (c / df["ma_60"].values - 1) * 100
        
        return df

    def check_market_regime(self):
        raw = self.fetch_data("000300.SH", "ts_code,trade_date,close,high,low,vol", lookback_days=250)
        if raw is None: return "chop"
        df = self.compute_indicators(raw)
        if df is None: return "chop"
        
        last = df.iloc[-1]
        c, ma60 = last["close"], last["ma_60"]
        
        if c > ma60 and ma60 > df["ma_20"].iloc[-5]:
            self.market_regime = "bull"
        else:
            self.market_regime = "bear_chop"

    @staticmethod
    def calculate_risk(df: pd.DataFrame) -> Dict:
        last = df.iloc[-1]
        atr = last["atr_14"]
        ma60 = last["ma_60"]
        price = last["close"]
        
        stop_loss = min(ma60, price - 1.5 * atr)
        tp1 = price + 1.5 * atr
        tp2 = price + 3.0 * atr
        
        return {
            "stop_loss": round(stop_loss, 2),
            "take_profit": round(tp1, 2),
            "take_profit_2": round(tp2, 2),
            "atr": round(atr, 2)
        }

    @staticmethod
    def generate_signals(df: pd.DataFrame, code: str, name: str) -> Dict:
        latest = df.iloc[-1]
        c = latest["close"]   # 提取现价，后面所有返回分支都带上
        ma20, ma60 = latest["ma_20"], latest["ma_60"]
        bias20 = latest["bias_20"]
        
        score, reasons = 0, []

        # 1. 【硬性过滤】趋势未向上，直接淘汰
        if c < ma60:
            return {
                "code": code, "name": name, "score": -50,
                "rating": "★★★ 观望", "action": "趋势向下",
                "reasons": ["位于60日线下方，不做多"],
                "close": c
            }

        # 2. 【硬性过滤】追高拦截
        if bias20 > 6:
            return {
                "code": code, "name": name, "score": -20,
                "rating": "★★★ 回避", "action": "乖离率过高",
                "reasons": [f"偏离20日线{bias20:.1f}%，追高风险极大"],
                "close": c
            }

        # 3. 核心回踩确认
        if -2.5 <= bias20 <= 2.5:
            score += 25
            reasons.append("多头趋势回踩支撑")
        
        # 4. 动量验证
        if latest["rsi_14"] < 30:
            score += 10; reasons.append("RSI超卖反弹")
        elif latest["rsi_14"] < 60:
            score += 5; reasons.append("RSI未过热")
        else:
            score -= 5; reasons.append("RSI偏高")

        # 5. 量价验证
        if not pd.isna(latest["vol_ma_20"]):
            if latest["vol"] < latest["vol_ma_20"] * 0.8:
                score += 5; reasons.append("缩量回踩/抛压轻")
            elif latest["vol"] > latest["vol_ma_20"] * 2.0 and bias20 > 3:
                score -= 10; reasons.append("放量滞涨/警惕")

        # 6. 评级
        if score >= 25:
            rating, action = "★★★ 强烈买入", "分批建仓(回踩确认)"
        elif score >= 15:
            rating, action = "★★ 关注", "轻仓试错"
        elif score < 0:
            rating, action = "★★★ 回避", "观望"
        else:
            rating, action = "观望", "持有"

        return {
            "code": code, "name": name, "score": score,
            "rating": rating, "action": action,
            "reasons": reasons,
            "close": c
        }

    def run(self, codes: List[str], export_csv: Optional[str] = None):
        fields = "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,volume,amount"
        logging.info("⏳ 开始分析...")

        self.check_market_regime()
        regime_penalty = (self.market_regime == "bear_chop")
        regime_desc = "📉 震荡/弱势" if regime_penalty else "📈 趋势正常"
        logging.info(f"市场状态：{regime_desc}")

        self.results = []
        for code in codes:
            name = self.index_data.get(code, [code, code])[0]
            raw = self.fetch_data(code, fields, lookback_days=400)
            if raw is None: continue
            
            df = self.compute_indicators(raw)
            if df is None: continue
            
            signal = self.generate_signals(df, code, name)
            
            if regime_penalty and signal["score"] > 0:
                signal["score"] = int(signal["score"] * 0.7)
                if signal["score"] < 20:
                    signal["rating"], signal["action"] = "★ 关注", "谨慎观察"

            risk_info = self.calculate_risk(df)
            signal["risk"] = risk_info
            
            self.results.append({"signal": signal, "df": df})
            time.sleep(0.05)

        self.results.sort(key=lambda x: x["signal"]["score"], reverse=True)

        if export_csv:
            pd.DataFrame([r["signal"] for r in self.results]).to_csv(export_csv, index=False, encoding="utf-8-sig")
        return self.results

    def get_long_term_data(self, code: str, years: int = 3, min_rows: int = 250) -> Optional[pd.DataFrame]:
        fields = "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,volume,amount"
        raw = self.fetch_data(code, fields, lookback_days=1000)
        if raw is None: return None
        df = self.compute_indicators(raw)
        if df is None: return None
        
        required_plot = ['trade_date', 'close', 'ma_20', 'boll_up', 'boll_mid', 'boll_low', 'rsi_14']
        if not all(col in df.columns for col in required_plot):
            logging.warning(f"{code} 长周期数据缺失绘图所需列，已跳过")
            return None
        return df


# ================= 绘图函数（增强健壮性） =================
def create_price_with_bollinger_chart(df_long: pd.DataFrame, title: str, target_period: int = 60) -> Optional[str]:
    if not MATPLOTLIB_AVAILABLE or df_long is None: return None
    try:
        required = ['trade_date', 'close']
        if not all(col in df_long.columns for col in required):
            return None
        df = df_long.copy().sort_values('trade_date')
        df['date_dt'] = pd.to_datetime(df['trade_date'], format='%Y%m%d')
        c = df['close'].values.astype(np.float64)
        
        period = target_period if len(c) >= target_period else 20
        upper, middle, lower = ta.BBANDS(c, timeperiod=period, nbdevup=2, nbdevdn=2)
        df['boll_mid'], df['boll_up'], df['boll_low'] = middle, upper, lower
        
        fig, ax = plt.subplots(figsize=(12, 6))
        ax.plot(df['date_dt'], c, label='收盘价', color='black', linewidth=1)
        ax.plot(df['date_dt'], df['boll_mid'], label=f'{period}日均线', color='blue', linestyle='--', linewidth=1)
        ax.plot(df['date_dt'], df['boll_up'], label='上轨', color='red', linestyle=':', linewidth=1)
        ax.plot(df['date_dt'], df['boll_low'], label='下轨', color='green', linestyle=':', linewidth=1)
        ax.fill_between(df['date_dt'], df['boll_up'], df['boll_low'], alpha=0.1, color='gray')
        
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        plt.xticks(rotation=45, ha='right')
        
        ax.set_title(f'{title} - 收盘价与{period}日布林带', fontsize=12)
        ax.set_ylabel('价格')
        ax.grid(True, linestyle=':', alpha=0.6)
        ax.legend(loc='best')
        plt.tight_layout()
        
        buffer = io.BytesIO()
        plt.savefig(buffer, format='png', dpi=100, bbox_inches='tight')
        buffer.seek(0)
        img_b64 = base64.b64encode(buffer.read()).decode('utf-8')
        plt.close(fig)
        return img_b64
    except Exception as e:
        logging.warning(f"绘制布林带图失败: {e}")
        if 'fig' in locals(): plt.close(fig)
        return None

def create_static_bias_chart(df_long: pd.DataFrame, title: str) -> Optional[str]:
    if not MATPLOTLIB_AVAILABLE or df_long is None: return None
    try:
        required = ['trade_date', 'close', 'ma_20']
        if not all(col in df_long.columns for col in required):
            return None
        df = df_long.copy().sort_values('trade_date')
        df['date_dt'] = pd.to_datetime(df['trade_date'], format='%Y%m%d')
        bias = (df['close'] / df['ma_20'] - 1) * 100
        
        fig, ax = plt.subplots(figsize=(12, 4))
        ax.plot(df['date_dt'], bias, color='blue', linewidth=1.5, label='20日乖离率(%)')
        ax.axhline(y=0, color='red', linestyle='--', linewidth=1, alpha=0.7)
        ax.axhline(y=5, color='orange', linestyle=':', linewidth=1, alpha=0.5)
        ax.fill_between(df['date_dt'], bias, 0, where=(bias >= 0), color='red', alpha=0.2)
        ax.fill_between(df['date_dt'], bias, 0, where=(bias < 0), color='green', alpha=0.2)
        
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        plt.xticks(rotation=45, ha='right')
        
        ax.set_title(f'{title} - 20日乖离率', fontsize=12)
        ax.set_ylabel('乖离率 (%)')
        ax.grid(True, linestyle=':', alpha=0.6)
        ax.legend(loc='best')
        plt.tight_layout()
        
        buffer = io.BytesIO()
        plt.savefig(buffer, format='png', dpi=100, bbox_inches='tight')
        buffer.seek(0)
        img_b64 = base64.b64encode(buffer.read()).decode('utf-8')
        plt.close(fig)
        return img_b64
    except Exception as e:
        logging.warning(f"绘制乖离率图失败: {e}")
        if 'fig' in locals(): plt.close(fig)
        return None

def create_rsi_chart(df_long: pd.DataFrame, title: str) -> Optional[str]:
    if not MATPLOTLIB_AVAILABLE or df_long is None: return None
    try:
        required = ['trade_date', 'rsi_14']
        if not all(col in df_long.columns for col in required):
            return None
        df = df_long.copy().sort_values('trade_date')
        df['date_dt'] = pd.to_datetime(df['trade_date'], format='%Y%m%d')
        
        fig, ax = plt.subplots(figsize=(12, 3))
        ax.plot(df['date_dt'], df['rsi_14'], label='RSI(14)', color='purple', linewidth=1.5)
        ax.axhline(y=70, color='red', linestyle='--', alpha=0.5, label='超买线')
        ax.axhline(y=30, color='green', linestyle='--', alpha=0.5, label='超卖线')
        ax.set_ylim(0, 100)
        
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        plt.xticks(rotation=45, ha='right')
        
        ax.set_title(f'{title} - RSI相对强弱', fontsize=12)
        ax.grid(True, linestyle=':', alpha=0.6)
        ax.legend(loc='best')
        plt.tight_layout()
        
        buffer = io.BytesIO()
        plt.savefig(buffer, format='png', dpi=100, bbox_inches='tight')
        buffer.seek(0)
        img_b64 = base64.b64encode(buffer.read()).decode('utf-8')
        plt.close(fig)
        return img_b64
    except Exception as e:
        logging.warning(f"绘制RSI图失败: {e}")
        if 'fig' in locals(): plt.close(fig)
        return None


# ================= 邮件发送 =================
def send_email_report(analyzer, results_with_df, config):
    try:
        signals = [item['signal'] for item in results_with_df]
        subject = f"📊 高胜率指数分析报告 - {datetime.datetime.now().strftime('%Y%m%d')}"

        html_body = f"""
        <html><body style="font-family: Arial, 'Microsoft YaHei', sans-serif; font-size: 12px; color: #333;">
        <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin-bottom: 20px;">
            <h3 style="margin: 0 0 10px 0;">📈 指数技术分析简报</h3>
            <p style="margin: 5px 0;">环境判定：<strong>{analyzer.market_regime}</strong> ({'弱势/震荡' if analyzer.market_regime=='bear_chop' else '趋势正常'})</p>
            <p style="margin: 5px 0;">共分析 <strong>{len(signals)}</strong> 个指数</p>
        </div>
        <table border="1" cellspacing="0" cellpadding="5" style="border-collapse: collapse; width: 100%; font-size: 11px;">
            <tr style="background-color: #e9ecef;">
                <th>代码</th><th>名称</th><th>评级</th><th>现价</th><th>止损位</th><th>止盈位</th><th>理由</th>
            </tr>
        """
        for r in signals:
            c = r.get('code', '')[:6]  # 使用 .get 防缺失
            bg = "#ffcccc" if "强烈" in r.get('rating', '') else "#fff3cd" if "关注" in r.get('rating', '') else "#fff"
            r_info = r.get('risk', {})
            close_price = r.get('close', 'N/A')
            reasons_list = r.get('reasons', [])
            reasons_str = '; '.join(reasons_list) if isinstance(reasons_list, list) else str(reasons_list)

            html_body += f"""
            <tr style="background-color: {bg};">
                <td>{c}</td>
                <td>{r.get('name', '')}</td>
                <td><b>{r.get('rating', '')}</b></td>
                <td>{close_price}</td>
                <td style="color:red;">{r_info.get('stop_loss', '')}</td>
                <td style="color:green;">{r_info.get('take_profit', '')}</td>
                <td>{reasons_str}</td>
            </tr>"""
        html_body += "</table><hr>"

        # 图表区域
        for item in results_with_df:
            s = item['signal']
            code = s.get('code', '')
            name = s.get('name', '')
            df_long = analyzer.get_long_term_data(code)
            if df_long is None: 
                continue
            
            if s.get('score', 0) < 10: 
                continue

            img_boll = create_price_with_bollinger_chart(df_long, f"{name} ({code[:6]})")
            img_bias = create_static_bias_chart(df_long, f"{name} ({code[:6]})")
            img_rsi = create_rsi_chart(df_long, f"{name} ({code[:6]})")

            if not any([img_boll, img_bias, img_rsi]):
                continue

            html_body += f"""
            <h3 style="border-bottom: 2px solid #ddd; padding-bottom: 5px;">{code[:6]} {name}</h3>
            <p>策略建议：{s.get('action', '')}</p>
            <div style="display: flex; flex-wrap: wrap; gap: 10px;">
            """
            if img_boll:
                html_body += f'<div><img src="data:image/png;base64,{img_boll}" style="max-width: 48%; height: auto;"></div>'
            if img_bias:
                html_body += f'<div><img src="data:image/png;base64,{img_bias}" style="max-width: 48%; height: auto;"></div>'
            if img_rsi:
                html_body += f'<div><img src="data:image/png;base64,{img_rsi}" style="max-width: 48%; height: auto;"></div>'
            html_body += "</div><br>"

        html_body += "</body></html>"

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = config["sender"]
        msg["To"] = config["receiver"]
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        with smtplib.SMTP_SSL(config["smtp_server"], config["smtp_port"]) as server:
            server.login(config["sender"], config["auth_code"])
            server.sendmail(config["sender"], [config["receiver"]], msg.as_string())
        
        logging.info("✉️ 邮件发送成功")

    except Exception as e:
        # 打印完整堆栈以便定位问题
        logging.error("邮件发送失败，详细错误信息如下：")
        logging.error(traceback.format_exc())


# ================= 主程序 =================
if __name__ == '__main__':
    analyzer = IndexStrategyAnalyzer(TOKEN, SERVER).set_indices(index_data)
    results = analyzer.run(codes=INDICES, export_csv=f"signal_{datetime.datetime.now().strftime('%Y%m%d')}.csv")
    
    for r in results:
        s = r['signal']
        print(f"{s['code']} {s['name']} | {s['rating']} | {s['action']} | 止损:{s['risk']['stop_loss']}")

    send_email_report(analyzer, results, EMAIL_CONFIG)