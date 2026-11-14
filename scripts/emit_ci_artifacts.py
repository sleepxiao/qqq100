#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 sync.py 的 snapshot JSON 转成可提交到仓库的发布产物。

CI 与本地共用同一份产物，保证两边口径完全一致：

  data/latest.json    完整快照（rows + index + generated_at）
  data/part1..N.sql   拆片后的基金额度 upsert，逐片执行避开语句长度限制
  data/market.sql     纳指100 行情 upsert（本次未抓到指数时不生成，并删除旧文件）

用法：
  python scripts/emit_ci_artifacts.py scripts/out/snapshot-2026-11-14.json --out data
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import sync  # noqa: E402  复用 emit_sql / emit_market_sql，避免两套拼接逻辑


def split_sql(text, parts):
    """按 VALUES 行列表切分，保证每片都是语法完整的独立 INSERT。"""
    head, rest = text.split(" VALUES\n", 1)
    body, tail = rest.rsplit("\nON CONFLICT", 1)
    rows = body.split(",\n")
    size = (len(rows) + parts - 1) // parts
    chunks = []
    for i in range(parts):
        chunk = rows[i * size:(i + 1) * size]
        if not chunk:
            break
        chunks.append(head + " VALUES\n" + ",\n".join(chunk) + "\nON CONFLICT" + tail)
    return chunks


def write(path, content):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("snapshot", help="sync.py 产出的 snapshot-YYYY-MM-DD.json")
    ap.add_argument("--out", default="data", help="产物目录，默认 data")
    ap.add_argument("--parts", type=int, default=3, help="upsert 拆成几片，默认 3")
    args = ap.parse_args()

    with open(args.snapshot, encoding="utf-8") as f:
        payload = json.load(f)

    rows = payload["rows"]
    trade_date = payload["trade_date"]
    index = payload.get("index")

    os.makedirs(args.out, exist_ok=True)

    write(os.path.join(args.out, "latest.json"),
          json.dumps(payload, ensure_ascii=False, separators=(",", ":")))

    tmp = os.path.join(args.out, "_upsert.tmp.sql")
    sync.emit_sql(rows, trade_date, tmp)
    with open(tmp, encoding="utf-8") as f:
        sql_text = f.read()
    os.remove(tmp)

    chunks = split_sql(sql_text, max(1, args.parts))
    for i, chunk in enumerate(chunks, 1):
        write(os.path.join(args.out, "part%d.sql" % i), chunk)

    # 清理上一轮遗留的多余分片，避免旧数据混入本次入库
    stale = len(chunks) + 1
    while True:
        p = os.path.join(args.out, "part%d.sql" % stale)
        if not os.path.exists(p):
            break
        os.remove(p)
        stale += 1

    market_path = os.path.join(args.out, "market.sql")
    if index:
        sync.emit_market_sql(index, market_path)
    elif os.path.exists(market_path):
        os.remove(market_path)  # 旧指数会让页面显示过期涨跌幅，宁可缺不可错

    buyable = [r for r in rows if r.get("tt_status") in ("open", "limited")]
    ali_buyable = [r for r in rows if r.get("ali_status") == "open"]

    print("trade_date=%s" % trade_date)
    print("total=%d" % len(rows))
    print("tt_buyable=%d" % len(buyable))
    print("ali_buyable=%d" % len(ali_buyable))
    print("parts=%d" % len(chunks))
    if index:
        print("index=%s close=%s pct=%+.2f%%" % (
            index.get("data_date"), index.get("close"), index.get("pct") or 0))
    else:
        print("index=missing")
    print("quota_max=%s" % max((r.get("quota") or 0) for r in rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
