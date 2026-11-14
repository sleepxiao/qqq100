/**
 * 额度展示与统计的纯函数集合。
 *
 * 数据来自两个销售渠道，额度口径一致（基金公司按「每个基金账户」统一规定），
 * 差异体现在「该渠道当前能不能买」：
 *   tt  = 天天基金
 *   ali = 支付宝（蚂蚁基金）
 */

const CHANNELS = [
  { key: 'tt', name: '天天基金', short: '天天' },
  { key: 'ali', name: '支付宝', short: '支付宝' },
];

const STATUS_META = {
  open: { label: '开放申购', short: '开放', tone: 'good' },
  limited: { label: '限额申购', short: '限额', tone: 'limited' },
  suspended: { label: '暂停申购', short: '暂停', tone: 'muted' },
  closed: { label: '封闭期', short: '封闭', tone: 'muted' },
  unavailable: { label: '未代销', short: '未代销', tone: 'muted' },
};

/** 2026-11-13T00:00:00Z → 2026-11-13 */
function dateOnly(value) {
  if (!value) return '';
  return String(value).slice(0, 10);
}

/** 带时区时间 → 北京时间 "11-13 21:10" */
function beijingTime(value) {
  if (!value) return '';
  const s = String(value);
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})/);
  if (!m) return dateOnly(value);
  const base = Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]);
  const off = s.match(/(Z|[+-]\d{2}:?\d{2})$/);
  let utc;
  if (!off) {
    utc = base - 8 * 3600 * 1000;
  } else if (off[1] === 'Z') {
    utc = base;
  } else {
    const sign = off[1][0] === '-' ? -1 : 1;
    const hh = parseInt(off[1].slice(1, 3), 10);
    const mm = parseInt(off[1].slice(-2), 10);
    utc = base - sign * (hh * 60 + mm) * 60000;
  }
  const d = new Date(utc + 8 * 3600 * 1000);
  const pad = n => (n < 10 ? '0' + n : '' + n);
  return pad(d.getUTCMonth() + 1) + '-' + pad(d.getUTCDate()) + ' ' +
    pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes());
}

/** 额度数字 → 展示文本 */
function quotaText(quota) {
  if (quota === null || quota === undefined || quota === '') return '';
  const n = Number(quota);
  if (!isFinite(n)) return '';
  if (n >= 10000) {
    const w = n / 10000;
    return (w % 1 === 0 ? w : w.toFixed(1)) + '万';
  }
  return n % 1 === 0 ? String(n) : String(parseFloat(n.toFixed(2)));
}

/** 基金名称精简 */
function splitName(name) {
  let s = String(name || '');
  const mid = s.match(/[）)]\s*([A-Z])(?=[\s(（]|人民币|美元|$)/);
  const tail = s.match(/([A-Z])\s*$/);
  const share = mid ? mid[1] : tail ? tail[1] : '';

  s = s
    .replace(/[（(]\s*QDII(?:\s*-\s*LOF)?\s*[）)]/g, '')
    .replace(/美元现汇|美元现钞|人民币/g, '')
    .replace(/纳斯达克\s*100/g, '纳指100')
    .replace(/发起式联接|发起联接/g, '联接')
    .replace(/指数发起式|指数发起/g, '指数')
    .replace(/[（(]\s*[）)]/g, '')
    .replace(/[（(]\s*([A-Z])\s*[）)]/g, '$1')
    .replace(/\s*[A-Z]\s*$/, '')
    .trim();

  if (!s) s = String(name || '');
  return { title: s, share, hasShare: !!share };
}

function num(v) {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(v);
  return isFinite(n) ? n : null;
}

/** 指数点位格式化：28289.19 → 28,289.19 */
function formatIndexPoint(n) {
  if (n === null || n === undefined || !isFinite(n)) return '';
  const s = Number(n).toFixed(2);
  const parts = s.split('.');
  return parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ',') + '.' + parts[1];
}

/**
 * 指数行 → 展示对象。
 * dir 决定配色：按国内习惯，涨用红、跌用绿。
 */
function toIndex(row) {
  if (!row) return null;
  const pct = num(row.pct);
  const close = num(row.close);
  if (pct === null || close === null) return null;

  const dir = pct > 0 ? 'up' : pct < 0 ? 'down' : 'flat';
  const arrow = dir === 'up' ? '▲' : dir === 'down' ? '▼' : '—';
  return {
    name: row.index_name || '纳斯达克100',
    date: dateOnly(row.data_date),
    close: close,
    closeText: formatIndexPoint(close),
    pct,
    pctText: (pct > 0 ? '+' : '') + pct.toFixed(2) + '%',
    arrow,
    dir,
    word: dir === 'up' ? '涨' : dir === 'down' ? '跌' : '平',
  };
}

/**
 * 单个渠道的展示信息
 * status: open/limited/suspended/closed/unavailable
 * @param {string} channel 'tt' | 'ali'
 */
function channelView(status, quota, channel) {
  const st = STATUS_META[status] ? status : 'unavailable';
  const meta = STATUS_META[st];
  const q = num(quota);
  const isAli = channel === 'ali';

  if (st === 'open') {
    // 支付宝的 open 只代表「正常销售」，额度仍受基金公司单日上限约束
    if (isAli && q !== null && q > 0) {
      return channelView('limited', q, channel);
    }
    return {
      status: st, statusLabel: meta.label, quota: q,
      label: '不限', unit: '无单日上限', tone: 'good', buyable: true, hasAmount: false,
    };
  }
  if (st === 'limited') {
    return {
      status: st, statusLabel: meta.label, quota: q,
      label: q === null ? '限大额' : quotaText(q),
      unit: q === null ? '未披露额度' : (isAli ? '单日上限' : '单日上限'),
      tone: q === null ? 'mid' : q >= 100 ? 'good' : q >= 10 ? 'mid' : 'low',
      buyable: true,
      hasAmount: q !== null,
    };
  }
  if (st === 'suspended') {
    return {
      status: st, statusLabel: isAli ? '暂停销售' : meta.label, quota: null,
      label: '暂停', unit: '不可申购', tone: 'muted', buyable: false, hasAmount: false,
    };
  }
  if (st === 'closed') {
    return {
      status: st, statusLabel: meta.label, quota: null,
      label: '封闭', unit: '封闭期', tone: 'muted', buyable: false, hasAmount: false,
    };
  }
  return {
    status: 'unavailable', statusLabel: meta.label, quota: null,
    label: '未代销', unit: '该渠道不销售', tone: 'muted', buyable: false, hasAmount: false,
  };
}

/** 数据库行 → 展示对象（含两个渠道） */
function toItem(row) {
  const fullName = row.fund_name || row.name || '';
  const name = splitName(fullName);
  const currency = row.currency || 'CNY';
  const quota = num(row.quota);

  // 天天基金：tt_status；支付宝：ali_status
  let ttStatus = row.tt_status;
  if (!ttStatus) {
    // 兼容接入渠道字段之前的历史数据
    ttStatus = row.status === 'closed' ? 'closed' : row.status;
  }
  const tt = channelView(ttStatus,
    row.tt_quota !== undefined && row.tt_quota !== null ? row.tt_quota : quota, 'tt');
  const ali = channelView(row.ali_status || 'unavailable',
    row.ali_quota !== undefined && row.ali_quota !== null ? row.ali_quota : quota, 'ali');

  const anyBuyable = tt.buyable || ali.buyable;

  return {
    code: row.fund_code,
    name: fullName,
    title: name.title,
    share: name.hasShare ? name.share : '',
    company: row.company || '',
    currency,
    symbol: currency === 'USD' ? '$' : '¥',
    quota,
    nav: row.nav === null || row.nav === undefined ? '' : Number(row.nav).toFixed(4),
    minAmount: row.min_amount === null || row.min_amount === undefined ? '' : quotaText(row.min_amount),
    tradeDate: dateOnly(row.trade_date),
    updatedAt: beijingTime(row.updated_at),
    tt,
    ali,
    // 详情页用
    rawStatus: row.raw_status || '',
    aliRaw: row.ali_raw || '',
    aliMin: row.ali_min === null || row.ali_min === undefined ? '' : quotaText(row.ali_min),
    anyBuyable,
  };
}

/** 排序：该渠道可买在前，额度高的在前 */
function sortItems(items, channel) {
  const ch = channel || 'tt';
  return items.slice().sort((a, b) => {
    const va = a[ch];
    const vb = b[ch];
    if (va.buyable !== vb.buyable) return va.buyable ? -1 : 1;
    const qa = va.quota === null ? -1 : va.quota;
    const qb = vb.quota === null ? -1 : vb.quota;
    if (qb !== qa) return qb - qa;
    return a.code < b.code ? -1 : 1;
  });
}

/** 同一只基金的不同份额（A/C/E/I…）共享同一个单日限额，用于去重 */
function productKey(item) {
  return (item.company || '') + '|' + (item.title || item.name || '');
}

/**
 * 按渠道汇总。
 *
 * totalQuota = 「把可申购的基金当天全部各买一遍」的合计额度。
 * 由于同一只基金的 A/C/E 等份额共享单日累计限额，这里按基金去重，
 * 各份额取最大额度，避免重复计入导致合计虚高。
 * 可申购但未披露额度的（不限上限）无法计入合计，单独计数。
 */
function summarize(items, channel) {
  const ch = channel || 'tt';
  const total = items.length;
  const buyableItems = items.filter(i => i[ch].buyable);
  const buyable = buyableItems.length;

  const byProduct = {};
  buyableItems.forEach(i => {
    const k = productKey(i);
    const q = i[ch].quota;
    if (!(k in byProduct)) {
      byProduct[k] = q;
    } else if (q !== null && (byProduct[k] === null || q > byProduct[k])) {
      byProduct[k] = q;
    }
  });

  const productQuotas = Object.keys(byProduct).map(k => byProduct[k]);
  const quotas = productQuotas.filter(v => v !== null && v > 0);
  const sum = quotas.reduce((a, b) => a + b, 0);
  const max = quotas.length ? Math.max.apply(null, quotas) : 0;
  const avg = quotas.length ? sum / quotas.length : 0;
  const unlimited = productQuotas.filter(v => v === null).length;
  const notSold = items.filter(i => i[ch].status === 'unavailable').length;
  return {
    total,
    buyable,
    blocked: total - buyable - notSold,
    notSold,
    totalQuota: quotas.length ? quotaText(Math.round(sum * 100) / 100) : '—',
    totalQuotaRaw: Math.round(sum * 100) / 100,
    maxQuota: quotas.length ? quotaText(max) : '—',
    maxQuotaRaw: max,
    avgQuota: quotas.length ? quotaText(Math.round(avg * 10) / 10) : '—',
    unlimited,
    funds: quotas.length,
    countedFunds: quotas.length,
  };
}

module.exports = {
  CHANNELS, STATUS_META,
  dateOnly, beijingTime, quotaText, splitName, formatIndexPoint,
  channelView, toItem, toIndex, sortItems, summarize,
};
