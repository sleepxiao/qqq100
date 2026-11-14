// 云数据库访问层
//
// 页面里用的是这套链式写法：
//   cloud.database.from('fund_quota_daily').select('a, b').eq('trade_date', d)
//     .order('trade_date', { ascending: false }).limit(1)
// 这里把它映射到微信云开发（wx.cloud）上，保持接口形状不变，
// 所以页面文件不需要改动一行。
const { envId } = require('./config');

// 小程序端单次 get 最多返回 20 条，超过要分页循环取
const PAGE_LIMIT = 20;
// 分页循环的安全阀，防止 limit 写得过大时把请求打爆
const SAFE_LIMIT = 2000;

if (!wx.cloud) {
  throw new Error('当前基础库不支持云开发，请把调试基础库调到 2.2.3 以上');
}

wx.cloud.init({ env: envId, traceUser: false });

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

async function execute(state) {
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
  database: {
    from: createQuery,
  },
};

module.exports = { cloud };
