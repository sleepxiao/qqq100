#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把抓取产物转成小程序可直接 wx.request 的静态接口。

产物（默认 public/api/）：
  latest.json            当日全部基金 + 最新一条指数行情
  history/<code>.json    单只基金最近 N 天记录，供详情页画柱状图

静态方案没有数据库，历史只能靠一份累积文件。--history 指向的 history.json
按日期累积，每次运行把当天数据合并进去，只保留最近 KEEP_DAYS 天。

用法：
  python scripts/publish_static.py --source data/latest.json --out public
  python scripts/publish_static.py --upload --out public      # 需 COS 凭证
"""
import argparse
import json
import os
import sys

KEEP_DAYS = 90
HISTORY_LIMIT = 45

# 抓取产物里的字段名 → 小程序期望的字段名
RENAME = {"code": "fund_code", "name": "fund_name"}


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def dump_json(path, payload):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    return os.path.getsize(path)


def normalize(row, trade_date, updated_at):
    """补齐小程序侧字段名，保留原始字段以免下游还要判断。"""
    out = dict(row)
    for src, dst in RENAME.items():
        if src in row and dst not in out:
            out[dst] = row[src]
    out["trade_date"] = trade_date
    if not out.get("updated_at"):
        out["updated_at"] = updated_at
    return out


def merge_history(history, trade_date, rows):
    dates = history.setdefault("dates", {})
    dates[trade_date] = rows
    # 按日期倒序保留最近 KEEP_DAYS 天
    keep = sorted(dates.keys(), reverse=True)[:KEEP_DAYS]
    history["dates"] = {d: dates[d] for d in sorted(keep)}
    history["updated_at"] = rows[0].get("updated_at") if rows else history.get("updated_at")
    return history


def build(payload, out_dir, history):
    trade_date = payload.get("trade_date")
    generated_at = payload.get("generated_at")
    rows = [normalize(r, trade_date, generated_at) for r in payload.get("rows") or []]

    latest = {
        "trade_date": trade_date,
        "generated_at": generated_at,
        "rows": rows,
        "index": payload.get("index"),
    }
    api_dir = os.path.join(out_dir, "api")
    size = dump_json(os.path.join(api_dir, "latest.json"), latest)

    # 单只基金历史
    by_code = {}
    for day in sorted(history.get("dates", {}).keys()):
        for r in history["dates"][day]:
            code = r.get("fund_code")
            if code:
                by_code.setdefault(code, []).append(r)

    hist_dir = os.path.join(api_dir, "history")
    total = 0
    for code, items in by_code.items():
        rows_slice = items[-HISTORY_LIMIT:]
        total += dump_json(os.path.join(hist_dir, code + ".json"),
                           {"code": code, "rows": rows_slice})

    return {
        "trade_date": trade_date,
        "rows": len(rows),
        "latest_bytes": size,
        "funds": len(by_code),
        "history_bytes": total,
    }


def upload(local_dir, env_id, secret_id, secret_key):
    """把 public/api 传到静态托管桶（COS），域名即静态托管默认域名。"""
    try:
        from qcloud_cos import CosConfig, CosS3Client  # noqa: F401
    except ImportError:
        print("缺少依赖：pip install cos-python-sdk-v5", file=sys.stderr)
        return 1

    # 静态托管的桶名是固定的 <前缀>-<envId>-<appId>
    bucket = os.environ.get("TCB_STATIC_BUCKET", "").strip()
    region = os.environ.get("TCB_REGION", "ap-shanghai").strip()
    if not bucket:
        print("缺少 TCB_STATIC_BUCKET", file=sys.stderr)
        return 2

    config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Scheme="https")
    client = CosS3Client(config)

    root = os.path.join(local_dir, "api")
    uploaded = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            abs_path = os.path.join(dirpath, name)
            key = "api/" + os.path.relpath(abs_path, root).replace(os.sep, "/")
            with open(abs_path, "rb") as f:
                client.put_object(
                    Bucket=bucket, Body=f, Key=key,
                    ContentType="application/json",
                    CacheControl="max-age=300",
                )
            uploaded += 1
    print("已上传 %d 个文件到 %s" % (uploaded, bucket))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="data/latest.json", help="抓取产物 latest.json")
    ap.add_argument("--out", default="public", help="静态站点输出目录")
    ap.add_argument("--history", default="data/history.json", help="按日期累积的历史文件")
    ap.add_argument("--upload", action="store_true", help="上传到静态托管（需 COS 凭证）")
    args = ap.parse_args()

    payload = load_json(args.source)
    if not payload or not payload.get("rows"):
        print("产物为空或不存在：%s" % args.source, file=sys.stderr)
        return 2

    history = load_json(args.history, default={"dates": {}})
    trade_date = payload["trade_date"]
    generated_at = payload.get("generated_at")
    rows = [normalize(r, trade_date, generated_at) for r in payload["rows"]]
    history = merge_history(history, trade_date, rows)

    os.makedirs(os.path.dirname(args.history) or ".", exist_ok=True)
    with open(args.history, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, separators=(",", ":"))

    stat = build(payload, args.out, history)
    print("trade_date=%s rows=%d latest=%.1fKB funds=%d history=%.1fKB" % (
        stat["trade_date"], stat["rows"], stat["latest_bytes"] / 1024.0,
        stat["funds"], stat["history_bytes"] / 1024.0))

    if args.upload:
        secret_id = os.environ.get("TCB_SECRET_ID", "").strip()
        secret_key = os.environ.get("TCB_SECRET_KEY", "").strip()
        env_id = os.environ.get("TCB_ENV_ID", "").strip()
        if not (secret_id and secret_key and env_id):
            print("跳过上传：未配置 TCB_SECRET_ID / TCB_SECRET_KEY / TCB_ENV_ID")
            return 0
        return upload(args.out, env_id, secret_id, secret_key)
    return 0


if __name__ == "__main__":
    sys.exit(main())
