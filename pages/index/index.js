const { cloud } = require('../../utils/cloud');
const { CHANNELS, toItem, toIndex, sortItems, summarize, dateOnly, beijingTime } = require('../../utils/quota');

const PAGE_SIZE = 300;

function todayInBeijing() {
  const now = new Date();
  const t = new Date(now.getTime() + (now.getTimezoneOffset() + 480) * 60000);
  const pad = n => (n < 10 ? '0' + n : '' + n);
  return t.getFullYear() + '-' + pad(t.getMonth() + 1) + '-' + pad(t.getDate());
}

Page({
  data: {
    viewState: 'loading',
    errorText: '',
    dateText: '',
    updateNote: '',
    syncTime: '',
    stale: false,
    channels: CHANNELS,
    channel: 'tt',
    channelName: '天天基金',
    currencySymbol: '¥',
    index: null,
    counts: { tt: 0, ali: 0 },
    stats: {
      total: 0, buyable: 0, blocked: 0, notSold: 0,
      totalQuota: '—', maxQuota: '—', avgQuota: '—', unlimited: 0, countedFunds: 0,
    },
    items: [],
    currency: 'CNY',
    onlyBuyable: false,
    emptyHint: '',
    refreshing: false,
  },

  onLoad() {
    this.rawRows = [];
    this.loadData();
  },

  onPullDownRefresh() {
    this.loadData(true).then(() => wx.stopPullDownRefresh());
  },

  /**
   * @param {boolean} silent 静默刷新（不显示全屏 loading）
   */
  async loadData(silent) {
    if (!silent) {
      this.setData({ viewState: 'loading', errorText: '' });
    }
    try {
      const latest = await this.fetchLatestDate();
      if (!latest) {
        this.setData({
          viewState: 'empty',
          emptyHint: '云端还没有额度数据，等待每日 12:00 的同步任务写入后即可查看。',
          updateNote: '尚未同步',
          stale: false,
        });
        return;
      }

      const rows = await this.fetchRows(latest);
      if (!rows.length) {
        this.setData({
          viewState: 'empty',
          emptyHint: '这一天的数据还在同步中，请稍后再试。',
        });
        return;
      }

      const indexRow = await this.fetchIndex();
      this.rawRows = rows.map(toItem);
      const updates = rows.map(r => r.updated_at).filter(Boolean).sort();
      const lastUpdate = updates.length ? beijingTime(updates[updates.length - 1]) : '';
      const isToday = dateOnly(latest) === todayInBeijing();

      this.setData({
        viewState: 'ready',
        dateText: dateOnly(latest),
        syncTime: lastUpdate,
        index: toIndex(indexRow),
        updateNote: lastUpdate ? '每日 12:00 自动更新 · 本次同步 ' + lastUpdate : '每日 12:00 自动更新',
        stale: !isToday,
      });
      this.applyFilter();
    } catch (err) {
      this.setData({
        viewState: 'error',
        errorText: (err && (err.message || err.hint)) || '网络异常，请稍后重试',
      });
    }
  },

  async fetchLatestDate() {
    const { data, error } = await cloud.database
      .from('fund_quota_daily')
      .select('trade_date')
      .order('trade_date', { ascending: false })
      .limit(1);
    if (error) throw error;
    if (!data || !data.length) return null;
    return dateOnly(data[0].trade_date);
  },

  async fetchRows(tradeDate) {
    const { data, error } = await cloud.database
      .from('fund_quota_daily')
      .select('fund_code, fund_name, company, share_class, currency, status, quota, quota_text, ' +
        'min_amount, nav, trade_date, raw_status, updated_at, tt_status, tt_quota, ' +
        'ali_status, ali_quota, ali_min, ali_raw')
      .eq('trade_date', tradeDate)
      .limit(PAGE_SIZE);
    if (error) throw error;
    return data || [];
  },

  /**
   * 最近一个已收盘交易日的纳指100行情。
   * 属于辅助信息，读取失败时返回 null，不影响额度主流程。
   */
  async fetchIndex() {
    try {
      const { data, error } = await cloud.database
        .from('market_snapshot')
        .select('index_code, index_name, data_date, close, change_amount, pct, quote_at')
        .order('data_date', { ascending: false })
        .limit(1);
      if (error) throw error;
      return data && data.length ? data[0] : null;
    } catch (err) {
      return null;
    }
  },

  applyFilter() {
    const { currency, onlyBuyable, channel } = this.data;
    const pool = this.rawRows.filter(i => i.currency === currency);
    let items = pool;
    if (onlyBuyable) items = items.filter(i => i[channel].buyable);

    // 把当前渠道的展示字段摊平，便于 WXML 直接渲染
    items = sortItems(items, channel).map(i => {
      const v = i[channel];
      const other = channel === 'tt' ? i.ali : i.tt;
      const hasDiff = other.buyable !== v.buyable;
      return Object.assign({}, i, {
        statusLabel: v.statusLabel,
        quotaLabel: v.label,
        quotaUnit: v.unit,
        tone: v.tone,
        hasAmount: v.hasAmount,
        buyable: v.buyable,
        chStatus: v.status,
        hasDiff,
        diffText: hasDiff
          ? (channel === 'tt' ? '支付宝' : '天天基金') + other.statusLabel
          : '',
      });
    });

    const counts = {
      tt: pool.filter(i => i.tt.buyable).length,
      ali: pool.filter(i => i.ali.buyable).length,
    };

    this.setData({
      items,
      stats: summarize(pool, channel),
      counts,
      channelName: channel === 'ali' ? '支付宝' : '天天基金',
      currencySymbol: currency === 'USD' ? '$' : '¥',
      emptyHint: '当前筛选下没有基金，换个条件试试。',
    });
  },

  onChannel(e) {
    const channel = e.currentTarget.dataset.ch;
    if (channel === this.data.channel) return;
    this.setData({ channel });
    this.applyFilter();
  },

  onCurrency(e) {
    const currency = e.currentTarget.dataset.cur;
    if (currency === this.data.currency) return;
    this.setData({ currency });
    this.applyFilter();
  },

  toggleBuyable() {
    this.setData({ onlyBuyable: !this.data.onlyBuyable });
    this.applyFilter();
  },

  /** 手动刷新当日额度：重新查询云端最新快照 */
  async handleRefresh() {
    if (this.data.refreshing) return;
    this.setData({ refreshing: true });
    try {
      // 静态方案下快照会缓存，刷新前先失效，否则拿到的还是上一次的结果
      if (cloud.invalidate) cloud.invalidate();
      await this.loadData(true);
      if (this.data.viewState === 'ready') {
        const tip = this.data.stale
          ? '今日数据未同步 · 最新 ' + this.data.dateText
          : '已是最新 · ' + this.data.syncTime;
        wx.showToast({ title: tip, icon: 'none', duration: 1800 });
      } else if (this.data.viewState === 'empty') {
        wx.showToast({ title: '云端暂无数据', icon: 'none' });
      } else {
        wx.showToast({ title: '刷新失败', icon: 'none' });
      }
    } catch (err) {
      wx.showToast({ title: '刷新失败', icon: 'none' });
    } finally {
      this.setData({ refreshing: false });
    }
  },

  openDetail(e) {
    const { code, name } = e.currentTarget.dataset;
    wx.navigateTo({
      url: '/pages/detail/detail?code=' + code + '&name=' + encodeURIComponent(name || ''),
    });
  },

  handleRetry() {
    this.loadData();
  },
});
