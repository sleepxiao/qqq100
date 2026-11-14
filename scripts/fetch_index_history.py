#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓取纳斯达克100 自成立以来的完整历史点位。

数据源：纳斯达克指数官网 indexes.nasdaqomx.com 的 /Index/HistoryData 接口。
该接口返回 1985-01-31（基准 125 点）至今的全部交易日 EOD 数据，
是覆盖最完整的公开来源（东财、新浪、nasdaq.com API 都只有近十年）。

产出：
  scripts/out/index_history.json    全量日频数据（date, close）
  scripts/out/index_history_monthly.json  月末采样（用于走势图）
"""
import datetime
import json
import os
import re
import sys
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "out")

BASE = "https://indexes.nasdaqomx.com"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def _request(url, data=None, cookie=None):
    headers = {
        "User-Agent": UA,
        "Referer": BASE + "/Index/History/NDX",
        "Accept": "application/json, text/javascript, */*; q=0.01",
    }
    if cookie:
        headers["Cookie"] = cookie
    if data is not None:
        headers["X-Requested-With"] = "XMLHttpRequest"
        headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
    req = urllib.request.Request(url, data=data, headers=headers)
    return urllib.request.urlopen(req, timeout=180)


def fetch_raw():
    """先访问页面拿 Incapsula cookie，再 POST 历史数据接口。"""
    cookie = ""
    try:
        resp = _request(BASE + "/Index/History/NDX")
        # 仅用于服务端下发 cookie，内容不解析
        resp.read(1024)
        raw_cookie = resp.headers.get_all("Set-Cookie") or []
        cookie = "; ".join(c.split(";")[0] for c in raw_cookie)
    except Exception as exc:  # 拿不到 cookie 也继续试，接口多数情况下无需鉴权
        log("取 cookie 失败（继续尝试）：%s" % exc)

    today = datetime.date.today().isoformat()
    payload = urllib.parse.urlencode(
        {
            "id": "NDX",
            "startDate": "1985-01-01T00:00:00",
            "endDate": "%sT00:00:00" % today,
            "timeOfDay": "EOD",
        }
    ).encode()

    resp = _request(BASE + "/Index/HistoryData", data=payload, cookie=cookie)
    text = resp.read().decode("utf-8", "ignore")
    if not text.rstrip().endswith("}"):
        raise RuntimeError("历史接口返回被截断，长度 %d" % len(text))
    return json.loads(text)


def parse_ms(value):
    """把 /Date(1794546000000)/ 转成 date。"""
    m = re.search(r"(\d+)", str(value))
    if not m:
        return None
    ts = int(m.group(1)) / 1000.0
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).date()


def build_rows(raw):
    rows = []
    for item in raw.get("aaData") or []:
        # 真实点位在 Value 字段；Close/PreviousClose 对指数恒为 null
        value = item.get("Value")
        if value is None:
            continue  # 个别日期尚未结算
        day = parse_ms(item.get("TradeDate") or item.get("TimeStamp"))
        if day is None:
            continue
        rows.append({"date": day.isoformat(), "close": round(float(value), 2)})
    rows.sort(key=lambda r: r["date"])
    # 同一天重复时保留最后一条
    dedup = {}
    for r in rows:
        dedup[r["date"]] = r
    return [dedup[k] for k in sorted(dedup)]


def month_end_sample(rows):
    """每月取最后一个交易日，得到连续的月度序列。"""
    buckets = {}
    for r in rows:
        buckets[r["date"][:7]] = r  # 持续覆盖，最后留下当月最后一天
    out = [buckets[k] for k in sorted(buckets)]
    return out


def main():
    log("拉取纳指100 全历史…")
    raw = fetch_raw()
    rows = build_rows(raw)
    if len(rows) < 1000:
        log("数据异常，仅 %d 条" % len(rows))
        return 1

    log("日频 %d 条：%s → %s" % (len(rows), rows[0]["date"], rows[-1]["date"]))

    monthly = month_end_sample(rows)
    log("月频 %d 条：%s → %s" % (len(monthly), monthly[0]["date"], monthly[-1]["date"]))

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "index_history.json"), "w", encoding="utf-8") as f:
        json.dump({"index": "NDX100", "rows": rows}, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(OUT_DIR, "index_history_monthly.json"), "w", encoding="utf-8") as f:
        json.dump({"index": "NDX100", "rows": monthly}, f, ensure_ascii=False, separators=(",", ":"))

    lo = min(r["close"] for r in rows)
    hi = max(r["close"] for r in rows)
    log("区间 %.2f → %.2f（%.1f 倍）" % (lo, hi, hi / lo))
    return 0


if __name__ == "__main__":
    sys.exit(main())
