#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校验 CI 产出的 latest.json 是否可用（供本地入库前的门禁判断）。

退出码：
  0  数据是「今天」的，可以直接入库
  2  数据是旧的（CI 没跑成功 / 节假日未更新），需要回退到本地抓取
  1  latest.json 缺失或损坏

用法：
  python scripts/check_latest.py            # 默认读 data/latest.json
  python scripts/check_latest.py path.json
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT = os.path.join(os.path.dirname(HERE), "data", "latest.json")
CST = timezone(timedelta(hours=8))


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    if not os.path.exists(path):
        print("MISSING %s" % path)
        return 1

    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as e:  # noqa: BLE001
        print("BROKEN %s" % e)
        return 1

    rows = payload.get("rows") or []
    trade_date = payload.get("trade_date") or ""
    today = datetime.now(CST).date().isoformat()

    tt_buyable = sum(1 for r in rows if r.get("tt_status") in ("open", "limited"))
    ali_buyable = sum(1 for r in rows if r.get("ali_status") == "open")
    index = payload.get("index") or {}

    print("trade_date=%s today=%s" % (trade_date, today))
    print("total=%d" % len(rows))
    print("tt_buyable=%d" % tt_buyable)
    print("ali_buyable=%d" % ali_buyable)
    print("generated_at=%s" % payload.get("generated_at"))
    if index:
        print("index=%s pct=%s" % (index.get("data_date"), index.get("pct")))
    else:
        print("index=missing")

    if not rows:
        print("EMPTY 快照没有基金数据")
        return 2
    if trade_date != today:
        print("STALE 快照不是今天的")
        return 2

    print("OK 可直接入库")
    return 0


if __name__ == "__main__":
    sys.exit(main())
