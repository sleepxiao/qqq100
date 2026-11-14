#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 data/latest.json 写入微信云开发数据库。

由 GitHub Actions 在抓取完成后调用。走的是云开发官方服务端 HTTP API，
不需要云函数、不需要服务器，也不需要本机参与。

所需环境变量（配置在仓库 Secrets 里）：
  WX_APPID      小程序 AppID
  WX_SECRET     小程序 AppSecret
  WX_CLOUD_ENV  云开发环境 ID

三者缺任一则直接跳过并返回 0，这样仓库还没配好 secrets 时 CI 不会天天报红。

用法：
  python scripts/push_to_wxcloud.py                    # 默认读 data/latest.json
  python scripts/push_to_wxcloud.py data/latest.json
  python scripts/push_to_wxcloud.py --dry-run          # 只校验数据，不发请求
"""
import json
import os
import sys
import urllib.parse
import urllib.request

API = "https://api.weixin.qq.com"
QUOTA_COLLECTION = "fund_quota_daily"
MARKET_COLLECTION = "market_snapshot"
BATCH = 100  # 单次 add 的文档数上限（官方上限 1000，留足余量）


def call(path, token, payload, timeout=30):
    url = "%s%s?access_token=%s" % (API, path, urllib.parse.quote(token))
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_token(appid, secret):
    url = ("%s/cgi-bin/token?grant_type=client_credential&appid=%s&secret=%s"
           % (API, appid, secret))
    with urllib.request.urlopen(url, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if not data.get("access_token"):
        raise RuntimeError("换取 access_token 失败：%s" % json.dumps(data, ensure_ascii=False))
    return data["access_token"]


def js(obj):
    """把 Python 对象转成云开发 query 里的 JS/JSON 字面量。"""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def ensure_collection(env, token, name):
    res = call("/tcb/databasecollectionadd", token,
               {"env": env, "collection_name": name})
    code = res.get("errcode", -1)
    if code == 0:
        print("  集合 %s：已创建" % name)
        return
    msg = str(res.get("errmsg", "")).lower()
    if "exist" in msg or "already" in msg:
        print("  集合 %s：已存在" % name)
        return
    # 不直接中断：某些环境对重复创建返回别的错误码，交给后续删除/插入暴露真实问题
    print("  集合 %s：创建返回 errcode=%s %s（继续执行）" % (name, code, res.get("errmsg")))


def delete_by(env, token, collection, where):
    query = '%s.where(%s).remove()' % ("db.collection(%s)" % js(collection), js(where))
    res = call("/tcb/databasedelete", token, {"env": env, "query": query})
    code = res.get("errcode", -1)
    if code == 0:
        return res.get("deleted", 0) or 0
    msg = str(res.get("errmsg", "")).lower()
    if "not exist" in msg or "-502005" in str(code):
        return 0
    raise RuntimeError("删除 %s 失败：%s" % (collection, json.dumps(res, ensure_ascii=False)))


def add_docs(env, token, collection, docs):
    added = 0
    for i in range(0, len(docs), BATCH):
        chunk = docs[i:i + BATCH]
        query = '%s.add({data:%s})' % ("db.collection(%s)" % js(collection), js(chunk))
        res = call("/tcb/databaseadd", token, {"env": env, "query": query})
        if res.get("errcode", -1) != 0:
            raise RuntimeError("写入 %s 失败：%s" % (collection, json.dumps(res, ensure_ascii=False)))
        ids = res.get("id_list") or []
        added += len(ids) if ids else len(chunk)
    return added


def build_quota_docs(payload):
    trade_date = payload["trade_date"]
    updated_at = payload.get("generated_at")
    docs = []
    for r in payload["rows"]:
        docs.append({
            "trade_date": trade_date,
            "fund_code": r.get("code"),
            "fund_name": r.get("name"),
            "company": r.get("company"),
            "share_class": r.get("share_class"),
            "currency": r.get("currency"),
            "status": r.get("status"),
            "quota": r.get("quota"),
            "quota_text": r.get("quota_text"),
            "min_amount": r.get("min_amount"),
            "nav": r.get("nav"),
            "nav_date": r.get("nav_date"),
            "raw_status": r.get("raw_status"),
            "tt_status": r.get("tt_status"),
            "tt_quota": r.get("tt_quota"),
            "ali_status": r.get("ali_status"),
            "ali_quota": r.get("ali_quota"),
            "ali_min": r.get("ali_min"),
            "ali_raw": r.get("ali_raw"),
            "updated_at": updated_at,
        })
    return docs


def build_market_doc(payload):
    index = payload.get("index")
    if not index:
        return None
    return {
        "index_code": index.get("index_code"),
        "index_name": index.get("index_name"),
        "data_date": index.get("data_date"),
        "close": index.get("close"),
        "change_amount": index.get("change_amount"),
        "pct": index.get("pct"),
        "prev_close": index.get("prev_close"),
        "quote_at": index.get("quote_at"),
        "updated_at": payload.get("generated_at"),
    }


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry_run = "--dry-run" in sys.argv
    path = args[0] if args else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "latest.json")

    with open(path, encoding="utf-8") as f:
        payload = json.load(f)

    trade_date = payload["trade_date"]
    quota_docs = build_quota_docs(payload)
    market_doc = build_market_doc(payload)

    print("快照日期 %s，基金 %d 条%s"
          % (trade_date, len(quota_docs),
             "，指数 %s" % market_doc["data_date"] if market_doc else "，无指数"))

    if not quota_docs:
        print("没有基金数据，放弃写入")
        return 1

    if dry_run:
        print("[dry-run] 首条文档示例：%s" % js(quota_docs[0]))
        print("[dry-run] 未发送任何请求")
        return 0

    appid = os.environ.get("WX_APPID", "").strip()
    secret = os.environ.get("WX_SECRET", "").strip()
    env_id = os.environ.get("WX_CLOUD_ENV", "").strip()

    if not (appid and secret and env_id):
        missing = [k for k, v in (("WX_APPID", appid), ("WX_SECRET", secret),
                                  ("WX_CLOUD_ENV", env_id)) if not v]
        print("跳过写入：未配置 %s（配置后即可自动启用）" % "、".join(missing))
        return 0

    token = get_token(appid, secret)
    print("access_token 获取成功")

    ensure_collection(env_id, token, QUOTA_COLLECTION)
    ensure_collection(env_id, token, MARKET_COLLECTION)

    # 云开发没有 upsert，先按当天删干净再插入，保证重跑幂等
    removed = delete_by(env_id, token, QUOTA_COLLECTION, {"trade_date": trade_date})
    print("清理 %s 已有 %d 条" % (QUOTA_COLLECTION, removed))

    added = add_docs(env_id, token, QUOTA_COLLECTION, quota_docs)
    print("写入 %s %d 条" % (QUOTA_COLLECTION, added))

    if market_doc:
        removed_m = delete_by(env_id, token, MARKET_COLLECTION,
                              {"data_date": market_doc["data_date"]})
        if removed_m:
            print("清理 %s 已有 %d 条" % (MARKET_COLLECTION, removed_m))
        add_docs(env_id, token, MARKET_COLLECTION, [market_doc])
        print("写入 %s 1 条（%s）" % (MARKET_COLLECTION, market_doc["data_date"]))

    print("完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
