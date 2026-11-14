#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
纳斯达克100场外基金 · 每日申购额度抓取（天天基金 + 支付宝双渠道）

数据源（均无需鉴权）：
  1. 天天基金 · 基础信息
     https://fundmobapi.eastmoney.com/FundMApi/FundBaseTypeInformation.ashx
     提供 SHORTNAME / JJGS / FTYPE / DWJZ / FSRQ / BUY
  2. 天天基金 · 费率与限额（额度的权威来源）
     https://fundmobapi.eastmoney.com/FundMApi/FundRateInfo.ashx
     SGZT  干净状态文本：开放申购 / 限大额 / 暂停申购 / 封闭期
     MAXSG 单日累计申购限额（元），>=1e10 视为不限
  3. 支付宝（蚂蚁基金）· 产品页
     https://www.fund123.cn/matiaria?fundCode=xxx
     materialInfo.fundBrief.saleStatus        正常申购 / 暂停销售 / 不可售
     materialInfo.fundBrief.purchaseMinMount  起购金额
     （注：fund123.cn 即蚂蚁(杭州)基金销售有限公司官网，别名蚂蚁基金）

关键结论：单日限额由基金公司按「每个基金账户」统一规定，公告中不区分销售
渠道。因此额度数值两渠道共享，真正的渠道差异体现为「能否申购」。

用法：
  python sync.py                # 种子清单抓取
  python sync.py --discover     # 重新发现全部纳指100场外基金
  python sync.py --emit-sql     # 额外输出可入库的 upsert.sql
"""
import json
import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "out")
SEED = os.path.join(HERE, "funds_seed.json")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
CST = timezone(timedelta(hours=8))
EXCHANGE_PREFIX = ("15", "16", "50", "51", "56", "58")
NO_LIMIT = 1e10  # MAXSG 超过此值视为「不限额度」

# 纳斯达克100 指数（东方财富 secid）。注意 100.NDX 是「纳斯达克综合指数」，
# 纳指100 的 secid 是 100.NDX100。
INDEX_SECID = "100.NDX100"
INDEX_CODE = "NDX100"
INDEX_NAME = "纳斯达克100"

_lock = threading.Lock()


def log(*a):
    with _lock:
        print(*a, file=sys.stderr, flush=True)


def http_get(url, timeout=20, retry=2, referer="https://fund.eastmoney.com/"):
    last = None
    for i in range(retry + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": referer})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
            for enc in ("utf-8", "gbk"):
                try:
                    return raw.decode(enc)
                except UnicodeDecodeError:
                    continue
            return raw.decode("utf-8", "ignore")
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(0.5 * (i + 1))
    raise last


def http_get_json(url, **kw):
    return json.loads(http_get(url, **kw))


# ---------------------------------------------------------------- 发现基金清单
def discover():
    found = {}
    for ft in ("zs", "qdii"):
        for pi in range(1, 40):
            url = (
                "https://fund.eastmoney.com/data/rankhandler.aspx?op=ph&dt=kf&ft=%s&rs=&gs=0"
                "&sc=1nzf&st=desc&sd=%s&ed=%s&qdii=&tabSubtype=,,,,,&pi=%d&pn=100&dx=1&v=0.%d"
                % (ft, (date.today() - timedelta(days=365)).isoformat(), date.today().isoformat(), pi, pi)
            )
            try:
                txt = http_get(url)
            except Exception as e:  # noqa: BLE001
                log("排行页失败", ft, pi, e)
                break
            m = re.search(r"datas:\[(.*?)\],allRecords", txt, re.S)
            if not m:
                break
            items = re.findall(r'"(.*?)"', m.group(1))
            if not items:
                break
            for s in items:
                p = s.split(",")
                if len(p) > 1 and ("纳斯达克" in p[1] or "纳指" in p[1]):
                    found[p[0]] = p[1]
            time.sleep(0.15)

    companies = [
        "华安", "广发", "华夏", "易方达", "国泰", "招商", "博时", "天弘", "工银", "嘉实",
        "富国", "景顺长城", "国联安", "前海开源", "西部利得", "中欧", "诺安", "鹏华", "建信",
        "南方", "大成", "万家", "宝盈", "华泰柏瑞", "摩根", "华宝", "汇添富", "银华", "兴证全球",
        "交银", "浦银安盛", "长盛", "宏利", "国海富兰克林", "创金合信", "中银", "平安", "长城",
    ]
    for com in companies:
        for kw in ("纳斯达克100", "纳指100"):
            try:
                url = ("https://fundsuggest.eastmoney.com/FundSearch/api/FundSearchAPI.ashx?m=1&key="
                       + urllib.parse.quote(com + kw))
                d = http_get_json(url, timeout=12)
                for it in d.get("Datas") or []:
                    c, n = it.get("CODE"), it.get("NAME")
                    if c and n and ("纳斯达克" in n or "纳指" in n):
                        found[c] = n
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.03)
    return found


# ---------------------------------------------------------------- 天天基金：两接口
def fetch_tt(code):
    base = http_get_json(
        "https://fundmobapi.eastmoney.com/FundMApi/FundBaseTypeInformation.ashx"
        "?FCODE=%s&deviceid=1&plat=Iphone&product=EFund&version=1" % code
    ).get("Datas") or {}
    rate = http_get_json(
        "https://fundmobapi.eastmoney.com/FundMApi/FundRateInfo.ashx"
        "?FCODE=%s&deviceid=1&plat=Android&product=EFund&version=6.5.5" % code
    ).get("Datas") or {}
    return base, rate


# ---------------------------------------------------------------- 支付宝（蚂蚁基金）
ALI_STATUS = {
    "正常申购": "open",
    "开放申购": "open",
    "暂停销售": "suspended",
    "暂停申购": "suspended",
    "不可售": "unavailable",
    "暂不支持": "unavailable",
}


def fetch_ali(code):
    """返回 (status, min_amount, raw_text)。失败返回 (None, None, None)"""
    try:
        html = http_get("https://www.fund123.cn/matiaria?fundCode=%s" % code,
                        timeout=25, retry=1, referer="https://www.fund123.cn/")
    except Exception as e:  # noqa: BLE001
        log("支付宝页失败", code, e)
        return None, None, None
    m = re.search(r"window\.context\s*=\s*(\{[\s\S]*?\});?\s*</script>", html)
    if not m:
        return None, None, None
    try:
        info = json.loads(m.group(1)).get("materialInfo") or {}
    except json.JSONDecodeError:
        return None, None, None
    brief = info.get("fundBrief") or {}
    raw = (brief.get("saleStatus") or "").strip() or None
    if not raw:
        return "unavailable", None, None
    status = ALI_STATUS.get(raw)
    if status is None:
        if "暂停" in raw or "停止" in raw:
            status = "suspended"
        elif "不可售" in raw or "不支持" in raw:
            status = "unavailable"
        elif "正常" in raw or "开放" in raw:
            status = "open"
        else:
            status = "unavailable"
    def num(v):
        try:
            f = float(str(v).strip())
            return f if f > 0 else None
        except (TypeError, ValueError):
            return None
    return status, num(brief.get("purchaseMinMount")), raw


# ---------------------------------------------------------------- 纳指100 指数行情
def fetch_index():
    """最近一个「已收盘」交易日的纳斯达克100行情。

    盘中时 K 线最后一行是当日进行中的行情，直接取会得到「今日盘中涨跌幅」而非
    「前一日涨跌幅」，所以此时要回退一行。判断依据是行情时间戳 f86：它仍在跟随
    当前时间跳动（差值在几分钟内）即为盘中，停住不动说明已收盘。
    """
    try:
        q = http_get_json(
            "https://push2.eastmoney.com/api/qt/stock/get?secid=%s"
            "&fields=f43,f58,f59,f60,f86,f170&ut=fa5fd1943c7b386f172d6893dbfba10b"
            % INDEX_SECID, referer="https://quote.eastmoney.com/") or {}
        k = http_get_json(
            "https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=%s"
            "&klt=101&fqt=1&lmt=6&end=20500101&fields1=f1,f2,f3,f4"
            "&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
            % INDEX_SECID, referer="https://quote.eastmoney.com/") or {}
    except Exception as e:  # noqa: BLE001
        log("纳指100 行情抓取失败", e)
        return None

    klines = (k.get("data") or {}).get("klines") or []
    if not klines:
        log("纳指100 K线为空")
        return None

    stamp = (q.get("data") or {}).get("f86")
    intraday = False
    try:
        stale = datetime.now(timezone.utc).timestamp() - float(stamp)
        intraday = 0 <= stale < 240
    except (TypeError, ValueError):
        pass
    idx = -2 if (intraday and len(klines) >= 2) else -1

    parts = klines[idx].split(",")
    if len(parts) < 10:
        return None

    def f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    data_date = parts[0]
    close, pct, change = f(parts[2]), f(parts[8]), f(parts[9])
    if not to_date(data_date) or close is None or pct is None:
        return None

    quote_at = None
    try:
        quote_at = datetime.fromtimestamp(float(stamp), timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        pass

    return {
        "index_code": INDEX_CODE,
        "index_name": (q.get("data") or {}).get("f58") or INDEX_NAME,
        "data_date": data_date,
        "close": round(close, 2),
        "change_amount": round(change, 2) if change is not None else None,
        "pct": round(pct, 3),
        "prev_close": round(close - change, 2) if change is not None else None,
        "quote_at": quote_at,
        "intraday_skipped": intraday,
    }


# ---------------------------------------------------------------- 状态解析
QUOTA_RE = re.compile(r"上限\s*([0-9]+(?:\.[0-9]+)?)\s*元")
NAME_RE = re.compile(r"纳斯达克\s*100|纳指\s*100")


def tt_eval(sgzt_clean, maxsg, buy, sgzt_raw):
    """判定天天基金渠道状态 → (status, quota)

    BUY=False 时一律视为暂停：接口的 SGZT 拼接文案里可能残留「单日投资上限X元」
    的过期表述，不可据此认定可买。
    """
    s = (sgzt_clean or "").strip()
    raw = sgzt_raw or ""

    q = None
    try:
        v = float(maxsg)
        if 0 < v < NO_LIMIT:
            q = v
    except (TypeError, ValueError):
        pass
    if q is None:
        m = QUOTA_RE.search(raw)
        if m:
            q = float(m.group(1))
    if q is not None and q < 1:
        q = None  # 0.01 元这类名义额度等同关闭

    if "封闭" in s or "封闭" in raw:
        return "closed", None
    if buy is False:
        return "suspended", None
    if "暂停" in s:
        # BUY 未明确给出时才回退到「暂停但保留小额」的判断
        if buy is None and q:
            return "limited", q
        return "suspended", None
    if "限" in s:
        return "limited", q
    if "开放" in s or "正常" in s:
        return ("limited", q) if q else ("open", None)
    if not s:
        if q:
            return "limited", q
        return "suspended", None
    return "limited", q


def parse_share(name):
    currency = "USD" if ("美元" in name or "现汇" in name or "现钞" in name) else "CNY"
    m = re.search(r"\(QDII\)\s*([A-Z])(?:\(|$|\s)|\(QDII-?LOF\)\s*([A-Z])|([A-Z])\s*(?:人民币|美元)", name)
    share = None
    if m:
        share = next((g for g in m.groups() if g), None)
    if not share:
        m2 = re.search(r"([A-Z])\s*$", name.strip())
        if m2:
            share = m2.group(1)
    return currency, share


def to_num(v):
    try:
        f = float(str(v).replace("%", "").strip())
        return f
    except (TypeError, ValueError):
        return None


def to_date(v):
    s = str(v or "").strip()[:10]
    return s if re.match(r"^\d{4}-\d{2}-\d{2}$", s) else None


# ---------------------------------------------------------------- 单只基金汇总
def collect(code):
    try:
        base, rate = fetch_tt(code)
    except Exception as e:  # noqa: BLE001
        log("天天基金失败", code, e)
        return None
    name = (base.get("SHORTNAME") or "").strip()
    if not base.get("FCODE") or not NAME_RE.search(name.replace(" ", "")):
        return None
    if (base.get("FTYPE") or "") != "指数型-海外股票" and "QDII" not in name:
        return None

    sg_raw = (base.get("SGZT") or "").strip()
    if "场内" in sg_raw:
        return None

    buy = base.get("BUY")
    if isinstance(buy, str):
        buy = buy.lower() not in ("false", "0", "")
    tt_status, tt_quota = tt_eval(rate.get("SGZT"), rate.get("MAXSG"), buy, sg_raw)

    ali_status, ali_min, ali_raw = fetch_ali(code)

    currency, share = parse_share(name)
    # 统一额度：取天天基金披露的单日限额（基金公司按账户统一规定）
    quota = tt_quota
    status_map = {"open": "open", "limited": "limited", "suspended": "suspended", "closed": "closed"}
    status = status_map.get(tt_status, "suspended")

    return {
        "code": code,
        "name": name,
        "company": (base.get("JJGS") or "").strip() or None,
        "share_class": share,
        "currency": currency,
        "status": status,
        "quota": round(quota, 2) if quota is not None else None,
        "quota_text": ("%g元" % quota) if quota is not None else ("暂停" if status == "suspended" else ""),
        "min_amount": to_num(base.get("MINSG")) or to_num(rate.get("MINSG")),
        "nav": to_num(base.get("DWJZ")),
        "nav_date": to_date(base.get("FSRQ")),
        "raw_status": sg_raw or None,
        "tt_status": tt_status,
        "tt_quota": round(tt_quota, 2) if tt_quota is not None and tt_status == "limited" else None,
        "ali_status": ali_status,
        "ali_quota": round(quota, 2) if (quota is not None and ali_status == "open") else None,
        "ali_min": ali_min,
        "ali_raw": ali_raw,
    }


def build(use_discover):
    if use_discover:
        log("正在发现纳指100场外基金清单 ...")
        cand = discover()
        log("候选 %d 只，逐个校验 ..." % len(cand))
    else:
        cand = json.load(open(SEED, encoding="utf-8"))
        log("使用种子清单 %d 只" % len(cand))

    codes = [c for c in sorted(cand) if not c.startswith(EXCHANGE_PREFIX)]
    rows = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        for r in pool.map(collect, codes):
            if r:
                rows.append(r)

    rows.sort(key=lambda r: (
        0 if r["tt_status"] in ("limited", "open") else 2,
        -(r["quota"] or 0),
        r["code"],
    ))
    return rows


# ---------------------------------------------------------------- 入库 SQL
COLS = ("trade_date,fund_code,fund_name,company,share_class,currency,status,quota,"
        "quota_text,min_amount,nav,nav_date,raw_status,tt_status,tt_quota,"
        "ali_status,ali_quota,ali_min,ali_raw")


def emit_sql(rows, trade_date, path):
    def lit(v):
        if v is None:
            return "NULL"
        if isinstance(v, bool):
            return "TRUE" if v else "FALSE"
        if isinstance(v, (int, float)):
            return repr(v)
        return "'" + str(v).replace("'", "''") + "'"

    values = []
    for r in rows:
        values.append("(%s)" % ",".join(lit(x) for x in [
            trade_date, r["code"], r["name"], r["company"], r["share_class"],
            r["currency"], r["status"], r["quota"], r["quota_text"], r["min_amount"],
            r["nav"], r["nav_date"], r["raw_status"], r["tt_status"], r["tt_quota"],
            r["ali_status"], r["ali_quota"], r["ali_min"], r["ali_raw"],
        ]))
    updates = ",".join(
        "%s=EXCLUDED.%s" % (c, c) for c in COLS.split(",")
        if c not in ("trade_date", "fund_code")
    )
    sql = ("INSERT INTO fund_quota_daily (%s) VALUES\n" % COLS
           + ",\n".join(values)
           + "\nON CONFLICT (trade_date,fund_code) DO UPDATE SET "
           + updates + ",updated_at=now();")
    with open(path, "w", encoding="utf-8") as f:
        f.write(sql)
    return path


def emit_market_sql(item, path):
    def lit(v):
        if v is None:
            return "NULL"
        if isinstance(v, (int, float)):
            return repr(v)
        return "'" + str(v).replace("'", "''") + "'"

    sql = (
        "INSERT INTO market_snapshot (index_code,data_date,index_name,close,"
        "change_amount,pct,prev_close,quote_at) VALUES (%s)\n"
        "ON CONFLICT (index_code,data_date) DO UPDATE SET index_name=EXCLUDED.index_name,"
        "close=EXCLUDED.close,change_amount=EXCLUDED.change_amount,pct=EXCLUDED.pct,"
        "prev_close=EXCLUDED.prev_close,quote_at=EXCLUDED.quote_at,updated_at=now();"
        % ",".join(lit(item.get(k)) for k in (
            "index_code", "data_date", "index_name", "close",
            "change_amount", "pct", "prev_close", "quote_at",
        ))
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(sql)
    return path


def main():
    use_discover = "--discover" in sys.argv
    rows = build(use_discover)
    if not rows:
        log("没有抓到任何数据，退出")
        return 1

    index = fetch_index()
    if index:
        log("纳指100 %s 收盘 %s（%+.2f%%）%s"
            % (index["data_date"], index["close"], index["pct"],
               "（盘中，已回退到前一交易日）" if index["intraday_skipped"] else ""))
    else:
        log("纳指100 行情缺失，本次不写入指数数据")

    now = datetime.now(CST)
    trade_date = now.date().isoformat()
    os.makedirs(OUT_DIR, exist_ok=True)
    payload = {
        "trade_date": trade_date,
        "generated_at": now.isoformat(timespec="seconds"),
        "total": len(rows),
        "index": index,
        "rows": rows,
    }
    out = os.path.join(OUT_DIR, "snapshot-%s.json" % trade_date)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    if "--emit-sql" in sys.argv:
        emit_sql(rows, trade_date, os.path.join(OUT_DIR, "upsert-%s.sql" % trade_date))
        if index:
            mpath = os.path.join(OUT_DIR, "market-%s.sql" % trade_date)
            emit_market_sql(index, mpath)
            log("指数入库 SQL: %s" % mpath)

    from collections import Counter
    tt = Counter(r["tt_status"] for r in rows)
    ali = Counter(r["ali_status"] for r in rows)
    log("日期 %s 共 %d 只" % (trade_date, len(rows)))
    log("  天天基金: 可申购 %d（限大额 %d） 暂停 %d 封闭 %d"
        % (tt["open"] + tt["limited"], tt["limited"], tt["suspended"], tt["closed"]))
    log("  支付宝  : 可申购 %d 暂停 %d 不可售 %d"
        % (ali["open"], ali["suspended"], ali["unavailable"]))
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
