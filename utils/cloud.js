// 数据访问层（单入口）
//
// 页面里统一用这套链式写法：
//   cloud.database.from('fund_quota_daily').select('a, b').eq('trade_date', d)
//     .order('trade_date', { ascending: false }).limit(1)
//
// 底层有两种实现，由 config.mode 决定，页面一行都不用改：
//   static —— wx.request 拉静态托管上的 JSON，在内存里完成筛选/排序/截断
//   cloud  —— 微信云开发文档型数据库（wx.cloud.database），需要环境已绑定小程序
const { envId, mode, staticBase } = require('./config');

// 小程序端单次 get 最多返回 20 条，超过要分页循环取
const PAGE_LIMIT = 20;
// 分页循环的安全阀，防止 limit 写得过大时把请求打爆
const SAFE_LIMIT = 2000;

/* ------------------------------ 静态 JSON 模式 ------------------------------ */

// latest.json 一次会话内只拉一次，首页三个查询共用
let latestPromise = null;

function fetchJson(url, optional) {
  return new Promise((resolve, reject) => {
    wx.request({
      url,
      method: 'GET',
      dataType: 'json',
      timeout: 15000,
      success(res) {
        if (res.statusCode === 200 && res.data) resolve(res.data);
        else if (res.statusCode === 404 && optional) resolve(null);
        else reject(new Error('数据请求失败（HTTP ' + res.statusCode + '）'));
      },
      fail(err) {
        reject(new Error((err && err.errMsg) || '网络异常，请稍后重试'));
      },
    });
  });
}

function loadLatest() {
  if (!latestPromise) {
    latestPromise = fetchJson(staticBase + '/api/latest.json').catch(err => {
      latestPromise = null; // 失败不缓存，下次重试
      throw err;
    });
  }
  return latestPromise;
}

function dayKey(v) {
  return v === null || v === undefined ? '' : String(v).slice(0, 10);
}

function sortRows(rows, orderBy) {
  if (!orderBy) return rows;
  const { column, ascending } = orderBy;
  return rows.slice().sort((a, b) => {
    const x = a[column];
    const y = b[column];
    if (x === y) return 0;
    // 日期是 ISO 字符串，直接比较即可；null 一律排在后面
    if (x === null || x === undefined) return 1;
    if (y === null || y === undefined) return -1;
    const less = x < y;
    return ascending ? (less ? -1 : 1) : (less ? 1 : -1);
  });
}

async function executeStatic(state) {
  try {
    if (state.table === 'market_snapshot') {
      const snap = await loadLatest();
      const doc = snap && snap.index;
      return { data: doc ? [doc] : [], error: null };
    }

    let rows;
    const code = state.where.fund_code;
    if (code) {
      // 详情页：只取这只基金的历史，单独一个文件，省流量。
      // 文件不存在说明这只基金从没被记录过，按空结果处理，交给页面展示空态。
      const res = await fetchJson(staticBase + '/api/history/' + code + '.json', true);
      rows = (res && res.rows) || [];
    } else {
      const snap = await loadLatest();
      rows = (snap && snap.rows) || [];
      if (state.where.trade_date) {
        const target = dayKey(state.where.trade_date);
        rows = rows.filter(r => dayKey(r.trade_date) === target);
      }
    }

    return { data: sortRows(rows, state.orderBy).slice(0, state.limit), error: null };
  } catch (err) {
    return { data: null, error: err };
  }
}

/* ------------------------------ 云数据库模式 ------------------------------ */

if (mode === 'cloud') {
  if (!wx.cloud) {
    throw new Error('当前基础库不支持云开发，请把调试基础库调到 2.2.3 以上');
  }
  wx.cloud.init({ env: envId, traceUser: false });
}

/** 'a, b, c' → { a: true, b: true, c: true } */
function parseFields(fields) {
  if (!fields) return null;
  const projection = {};
  String(fields)
    .split(',')
    .map(s => s.trim())
    .filter(Boolean)
    .forEach(name => { projection[name] = true; });
  return Object.keys(projection).length ? projection : null;
}

async function executeCloud(state) {
  try {
    const db = wx.cloud.database();
    const rows = [];
    const hasWhere = Object.keys(state.where).length > 0;
    let skip = 0;

    while (rows.length < state.limit) {
      let ref = db.collection(state.table);
      if (hasWhere) ref = ref.where(state.where);
      if (state.orderBy) {
        ref = ref.orderBy(state.orderBy.column, state.orderBy.ascending ? 'asc' : 'desc');
      }
      if (state.fields) ref = ref.field(state.fields);

      const size = Math.min(PAGE_LIMIT, state.limit - rows.length);
      const res = await ref.skip(skip).limit(size).get();
      const batch = (res && res.data) || [];

      batch.forEach(item => rows.push(item));

      // 不足一页说明已经取完，不必再发请求
      if (batch.length < size) break;
      skip += size;
      if (skip >= SAFE_LIMIT) break;
    }

    return { data: rows, error: null };
  } catch (err) {
    // 保持调用方 `const { data, error } = await ...` 的解构形状
    return { data: null, error: err };
  }
}

/* --------------------------------- 查询构造 -------------------------------- */

function execute(state) {
  return mode === 'static' ? executeStatic(state) : executeCloud(state);
}

function createQuery(table) {
  const state = {
    table,
    where: {},
    orderBy: null,
    limit: 300,
    fields: null,
  };

  const query = {
    select(fields) {
      state.fields = parseFields(fields);
      return query;
    },
    eq(column, value) {
      state.where[column] = value;
      return query;
    },
    order(column, options) {
      state.orderBy = {
        column,
        ascending: !options || options.ascending !== false,
      };
      return query;
    },
    limit(n) {
      const v = Number(n);
      state.limit = v > 0 ? v : 300;
      return query;
    },
    // 让 query 对象可以直接 await
    then(onFulfilled, onRejected) {
      return execute(state).then(onFulfilled, onRejected);
    },
    catch(onRejected) {
      return execute(state).then(v => v, onRejected);
    },
  };

  return query;
}

const cloud = {
  mode,
  database: {
    from: createQuery,
  },
  // 刷新按钮用：清掉静态快照缓存后重新拉
  invalidate() {
    latestPromise = null;
  },
};

module.exports = { cloud };
