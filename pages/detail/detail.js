const { cloud } = require('../../utils/cloud');
const { toItem, dateOnly, quotaText } = require('../../utils/quota');

const HISTORY_DAYS = 45;

Page({
  data: {
    viewState: 'loading',
    errorText: '',
    code: '',
    title: '',
    fullName: '',
    company: '',
    share: '',
    symbol: '¥',
    nav: '',
    minAmount: '',
    tradeDate: '',
    updatedAt: '',
    // 两个渠道的展示
    tt: { label: '—', unit: '', tone: 'muted', hasAmount: false, statusLabel: '' },
    ali: { label: '—', unit: '', tone: 'muted', hasAmount: false, statusLabel: '' },
    aliMin: '',
    rawStatus: '',
    aliRaw: '',
    history: [],
    axisStart: '',
    axisEnd: '',
    changeText: '',
    changeTone: 'flat',
    recordCount: 0,
    hasHistory: false,
  },

  onLoad(options) {
    const code = (options && options.code) || '';
    this.setData({ code });
    wx.setNavigationBarTitle({ title: '额度详情' });
    this.loadData(code);
  },

  async loadData(code) {
    if (!code) {
      this.setData({ viewState: 'error', errorText: '缺少基金代码' });
      return;
    }
    try {
      const { data, error } = await cloud.database
        .from('fund_quota_daily')
        .select('trade_date, fund_name, company, currency, status, quota, quota_text, min_amount, ' +
          'nav, raw_status, updated_at, tt_status, tt_quota, ali_status, ali_quota, ali_min, ali_raw')
        .eq('fund_code', code)
        .order('trade_date', { ascending: true })
        .limit(HISTORY_DAYS);
      if (error) throw error;
      if (!data || !data.length) {
        this.setData({ viewState: 'empty', errorText: '还没有这只基金的额度记录' });
        return;
      }

      const latestRow = data[data.length - 1];
      const item = toItem(latestRow);
      const history = data.map(r => ({
        date: dateOnly(r.trade_date),
        quota: r.quota === null || r.quota === undefined ? null : Number(r.quota),
        status: r.tt_status || r.status,
      }));

      const quotas = history.map(h => (h.quota === null ? 0 : h.quota));
      const max = Math.max.apply(null, quotas.concat([1]));
      const bars = history.slice(-30).map((h, idx, arr) => {
        const v = h.quota === null ? 0 : h.quota;
        return {
          date: h.date.slice(5),
          label: v > 0 ? quotaText(v) : '—',
          h: v > 0 ? Math.max(8, Math.round((v / max) * 100)) : 6,
          active: idx === arr.length - 1,
          suspended: h.status === 'suspended' || h.status === 'closed',
        };
      });

      // 与上一条记录比较额度变化
      let changeText = '';
      let changeTone = 'flat';
      if (history.length >= 2) {
        const cur = history[history.length - 1].quota;
        const prev = history[history.length - 2].quota;
        if (cur !== null && prev !== null && cur !== prev) {
          const diff = cur - prev;
          changeText = '较上次 ' + (diff > 0 ? '+' : '−') + quotaText(Math.abs(diff)) + ' 元';
          changeTone = diff > 0 ? 'up' : 'down';
        } else if (cur !== null && prev === null) {
          changeText = '上次是暂停状态，本次恢复可申购';
          changeTone = 'up';
        }
      }

      this.setData({
        viewState: 'ready',
        title: item.title,
        fullName: item.name,
        company: item.company,
        share: item.share,
        symbol: item.symbol,
        nav: item.nav,
        minAmount: latestRow.min_amount === null || latestRow.min_amount === undefined
          ? '—' : quotaText(latestRow.min_amount),
        tradeDate: item.tradeDate,
        updatedAt: item.updatedAt,
        tt: {
          label: item.tt.label,
          unit: item.tt.unit,
          tone: item.tt.tone,
          hasAmount: item.tt.hasAmount,
          statusLabel: item.tt.statusLabel,
        },
        ali: {
          label: item.ali.label,
          unit: item.ali.unit,
          tone: item.ali.tone,
          hasAmount: item.ali.hasAmount,
          statusLabel: item.ali.statusLabel,
        },
        aliMin: item.aliMin,
        rawStatus: item.rawStatus,
        aliRaw: item.aliRaw,
        history: bars,
        axisStart: bars.length ? bars[0].date : '',
        axisEnd: bars.length ? bars[bars.length - 1].date : '',
        changeText,
        changeTone,
        recordCount: history.length,
        hasHistory: bars.length > 1,
      });
    } catch (err) {
      this.setData({
        viewState: 'error',
        errorText: (err && (err.message || err.hint)) || '网络异常，请稍后重试',
      });
    }
  },

  handleRetry() {
    this.setData({ viewState: 'loading' });
    this.loadData(this.data.code);
  },

  copyCode() {
    wx.setClipboardData({ data: this.data.code });
  },
});
