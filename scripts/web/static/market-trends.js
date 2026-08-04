(function(global){
  'use strict';

  var state = {
    view: 'market',
    period: 90,
    metric: 'change_pct',
    ma5: true,
    ma20: false,
    selectedIndustry: null,
    industryPeriod: '20',  // 行业看板时间窗口:'5'|'20',驱动排序键(d5/d20)与条形图
    primaryIndex: null,   // 当前聚焦指数 id(null=第一个可见);点图例标签切换,驱动 tooltip/光点/成交量/MA
    hiddenSeries: {},  // {seriesId: true} 隐藏的指数线,点图例右侧眼睛切换
    personalFilter: 'all',     // 'all'=全部自选 | 'holdings'=仅持仓
    personalSort: 'd90',       // 排序键:d1/d30/d90/d180
    loading: false,
    lastData: null,
    chartModel: null
  };

  var VIEW_META = {
    market: {
      title: '市场趋势',
      icon: 'activity',
      empty: '指数趋势待接入',
      detail: '沪深300、标普500、恒生科技指数和自选股等权指数会在这里显示。'
    },
    industry: {
      title: '行业趋势',
      icon: 'layers-3',
      empty: '行业时间序列待接入',
      detail: '当前仅展示行业资金流摘要，不把排行数据伪装成趋势线。'
    },
    personal: {
      title: '个人趋势',
      icon: 'user-round',
      empty: '暂无本地行情缓存',
      detail: '去自选股页刷新行情后，这里会显示组合或自选股等权走势。'
    }
  };

  var COLORS = {
    personal: '#dc2626',
    personalAlt: '#2563eb',
    ma5: '#f59e0b',
    ma20: '#8b5cf6'
  };

  var INDEX_CARD_META = [
    {id: 'csi300', market: 'A股', label: '沪深300'},
    {id: 'sp500', market: '美股', label: '标普500'},
    {id: 'hstech', market: '港股', label: '恒生科技指数'},
    {id: 'watch_equal', market: '自选股', label: '自选股等权指数'}
  ];

  function esc(s){
    if(global.escapeHtml) return global.escapeHtml(s);
    return String(s == null ? '' : s).replace(/[&<>"']/g, function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
    });
  }

  function num(v){
    var n = Number(v);
    return isFinite(n) ? n : 0;
  }

  function metricNumber(v){
    if(v == null) return null;
    var n = Number(v);
    return isFinite(n) ? n : null;
  }

  function hasMetricValue(v){
    return metricNumber(v) != null;
  }

  function setHTML(id, html){
    var el = document.getElementById(id);
    if(el) el.innerHTML = html;
  }

  function refreshIcons(){
    if(global.refreshIcons) global.refreshIcons();
  }

  function updateActive(selector, attr, value){
    document.querySelectorAll(selector).forEach(function(btn){
      btn.classList.toggle('active', String(btn.getAttribute(attr)) === String(value));
    });
  }

  function mount(){
    bindEvents();
    updateControls();
    loadCurrent(false);
    return {
      reload: function(){ loadCurrent(true); }
    };
  }

  function bindEvents(){
    document.addEventListener('click', function(e){
      var viewBtn = e.target.closest('[data-trend-view]');
      if(viewBtn){
        state.view = viewBtn.dataset.trendView || 'market';
        state.hiddenSeries = {};  // 切视图时清空隐藏状态(不同视图的 series 不同)
        updateControls();
        loadCurrent(false);
        return;
      }

      var periodBtn = e.target.closest('[data-trend-period]');
      if(periodBtn){
        state.period = Number(periodBtn.dataset.trendPeriod) || 90;
        updateControls();
        loadCurrent(false);
        return;
      }

      var metricBtn = e.target.closest('[data-trend-metric]');
      if(metricBtn){
        state.metric = metricBtn.dataset.trendMetric || 'change_pct';
        updateControls();
        render(state.lastData || buildEmptyData(state.view));
        return;
      }

      var maBtn = e.target.closest('[data-trend-ma]');
      if(maBtn){
        var key = maBtn.dataset.trendMa;
        if(key === 'ma5') state.ma5 = !state.ma5;
        if(key === 'ma20') state.ma20 = !state.ma20;
        maBtn.classList.toggle('active', !!state[key]);
        maBtn.setAttribute('aria-pressed', state[key] ? 'true' : 'false');
        render(state.lastData || buildEmptyData(state.view));
        return;
      }

      // 图例眼睛按钮:点击隐藏/显示对应指数线(stopPropagation 避免触发外层聚焦)
      var visBtn = e.target.closest('[data-toggle-visibility]');
      if(visBtn){
        var sid = visBtn.dataset.toggleVisibility;
        if(state.hiddenSeries[sid]) delete state.hiddenSeries[sid];
        else state.hiddenSeries[sid] = true;
        render(state.lastData || buildEmptyData(state.view));
        return;
      }

      // 图例标签主体:点击设为聚焦指数(tooltip/光点/成交量/MA 跟随)
      var focusBtn = e.target.closest('[data-focus-series]');
      if(focusBtn){
        state.primaryIndex = focusBtn.dataset.focusSeries;
        render(state.lastData || buildEmptyData(state.view));
        return;
      }

      // 行业看板时间窗口切换(5日/20日):改排序键 + 重渲(不重新拉数据)
      var indPeriodBtn = e.target.closest('[data-industry-period]');
      if(indPeriodBtn){
        state.industryPeriod = indPeriodBtn.dataset.industryPeriod || '20';
        render(state.lastData || buildEmptyData('industry'));
        return;
      }

      // 个人看板:筛选(全部/仅持仓) + 排序方式
      var pFilter = e.target.closest('[data-personal-filter]');
      if(pFilter){
        state.personalFilter = pFilter.dataset.personalFilter || 'all';
        render(state.lastData || buildEmptyData('personal'));
        return;
      }
      var pSort = e.target.closest('[data-personal-sort]');
      if(pSort){
        state.personalSort = pSort.dataset.personalSort || 'd90';
        render(state.lastData || buildEmptyData('personal'));
        return;
      }

      var industryBtn = e.target.closest('[data-industry-select]');
      if(industryBtn){
        state.selectedIndustry = industryBtn.dataset.industrySelect || null;
        render(state.lastData || buildEmptyData('industry'));
        return;
      }

      if(e.target.closest('#mk-trend-refresh')){
        loadCurrent(true);
      }
    });
    // 排序下拉 change 事件(select 不能用 click)
    document.addEventListener('change', function(e){
      var sel = e.target.closest('[data-personal-sort-sel]');
      if(sel){
        state.personalSort = sel.value || 'd90';
        render(state.lastData || buildEmptyData('personal'));
      }
    });
  }

  function updateControls(){
    updateActive('[data-trend-view]', 'data-trend-view', state.view);
    updateActive('[data-trend-period]', 'data-trend-period', state.period);
    updateActive('[data-trend-metric]', 'data-trend-metric', state.metric);
    var ma5 = document.querySelector('[data-trend-ma="ma5"]');
    var ma20 = document.querySelector('[data-trend-ma="ma20"]');
    if(ma5){ ma5.classList.toggle('active', state.ma5); ma5.setAttribute('aria-pressed', state.ma5 ? 'true' : 'false'); }
    if(ma20){ ma20.classList.toggle('active', state.ma20); ma20.setAttribute('aria-pressed', state.ma20 ? 'true' : 'false'); }
  }

  async function loadCurrent(force){
    if(state.loading) return;
    state.loading = true;
    var upd = document.getElementById('mk-trend-updated');
    if(upd) upd.textContent = '加载中...';
    try{
      if(state.view === 'personal') {
        render(await loadPersonalData());
      } else if(state.view === 'industry') {
        render(await loadIndustryData(force));
      } else {
        render(await loadMarketData(force));
      }
    } catch(e) {
      render(buildEmptyData(state.view, '加载失败:' + e.message));
    } finally {
      state.loading = false;
    }
  }

  function buildEmptyData(view, reason){
    var meta = VIEW_META[view] || VIEW_META.market;
    return {
      view: view,
      title: meta.title,
      series: [],
      summary: [],
      updated_at: '',
      stale: false,
      empty_reason: reason || meta.empty,
      empty_detail: meta.detail,
      empty_icon: meta.icon
    };
  }

  async function loadMarketData(force){
    var cacheKey = 'trend_market_' + state.period;
    var cached = global.KB_QUOTE_CACHE && global.KB_QUOTE_CACHE.get(cacheKey);
    var payload = cached && cached.data;
    if(payload && !hasCurrentMarketCards(payload)){
      payload = null;
      cached = null;
      if(global.KB_QUOTE_CACHE && global.KB_QUOTE_CACHE.clear) global.KB_QUOTE_CACHE.clear(cacheKey);
    }
    if(payload && !hasMarketBreadthSummary(payload)){
      payload = null;
      cached = null;
      if(global.KB_QUOTE_CACHE && global.KB_QUOTE_CACHE.clear) global.KB_QUOTE_CACHE.clear(cacheKey);
    }
    if(!payload || force){
      var r = await fetch('/api/market/trends?days=' + encodeURIComponent(state.period) + (force ? '&force=1' : ''));
      if(r.status === 503) return buildEmptyData('market', '行情模块不可用');
      payload = await r.json();
      if(payload && payload.ok && global.KB_QUOTE_CACHE) global.KB_QUOTE_CACHE.set(cacheKey, payload);
    }
    if(!payload || !payload.ok){
      return buildEmptyData('market', (payload && payload.error) || VIEW_META.market.empty);
    }
    return {
      view: 'market',
      title: payload.title || VIEW_META.market.title,
      series: payload.series || [],
      index_cards: payload.cards || [],
      summary: payload.summary || [],
      updated_at: payload.updated_at || '',
      stale: !!(payload.stale || (cached && !cached.fresh)),
      refreshing: !!payload.refreshing,
      empty_reason: VIEW_META.market.empty,
      empty_detail: VIEW_META.market.detail,
      empty_icon: VIEW_META.market.icon
    };
  }

  function hasCurrentMarketCards(payload){
    var cards = payload && payload.cards;
    if(!Array.isArray(cards)) return false;
    return INDEX_CARD_META.every(function(meta){
      return cards.some(function(card){ return card && card.id === meta.id; });
    });
  }

  function hasMarketBreadthSummary(payload){
    var expected = ['上涨/下跌家数', '全市场收益中位数', '创20日新高/新低', '涨停/跌停数量'];
    var summary = payload && payload.summary;
    if(!Array.isArray(summary) || summary.length < expected.length) return false;
    return expected.every(function(label){
      return summary.some(function(item){ return item && item.label === label; });
    });
  }

  async function loadIndustryData(force){
    var cacheKey = 'trend_industry_8_' + state.period;
    var cached = global.KB_QUOTE_CACHE && global.KB_QUOTE_CACHE.get(cacheKey);
    var payload = cached && cached.data;
    if(!payload || force){
      var r = await fetch('/api/market/trends/industry?days=' + encodeURIComponent(state.period) + '&top_n=8' + (force ? '&force=1' : ''));
      if(r.status === 503) return buildEmptyData('industry', '行情功能不可用');
      payload = await r.json();
      if(payload && payload.ok && global.KB_QUOTE_CACHE) global.KB_QUOTE_CACHE.set(cacheKey, payload);
    }
    if(!payload || !payload.ok) return loadIndustryFundData(force, payload && payload.error);

    var series = payload.series || [];
    if(series.length && !series.some(function(s){ return s.id === state.selectedIndustry; })){
      state.selectedIndustry = series[0].id;
    }
    return {
      view: 'industry',
      title: payload.title || VIEW_META.industry.title,
      series: series,
      heatmap: payload.heatmap || [],
      summary: payload.summary || [],
      updated_at: payload.updated_at || '',
      stale: !!(payload.stale || (cached && !cached.fresh)),
      refreshing: !!payload.refreshing,
      empty_reason: VIEW_META.industry.empty,
      empty_detail: VIEW_META.industry.detail,
      empty_icon: VIEW_META.industry.icon
    };
  }

  async function loadIndustryFundData(force, reason){
    var cacheKey = 'trend_industry_fund_today';
    var cached = global.KB_QUOTE_CACHE && global.KB_QUOTE_CACHE.get(cacheKey);
    var payload = cached && cached.data;
    if(!payload || force){
      var r = await fetch('/api/market/fund-flow?indicator=' + encodeURIComponent('今日')
        + '&sector_type=' + encodeURIComponent('行业资金流') + '&top_n=8');
      if(r.status === 503) return buildEmptyData('industry', '行情功能不可用');
      payload = await r.json();
      if(payload && payload.ok && global.KB_QUOTE_CACHE) global.KB_QUOTE_CACHE.set(cacheKey, payload);
    }
    if(!payload || !payload.ok) return buildEmptyData('industry', reason || '行业趋势暂不可用');
    var inflow = payload.inflow || [];
    var outflow = payload.outflow || [];
    var sumIn = sumAmounts(inflow, false);
    var sumOut = sumAmounts(outflow, true);
    var net = sumIn - sumOut;
    return {
      view: 'industry',
      title: '行业趋势',
      series: [],
      updated_at: payload.updated_at || '',
      stale: !!(payload.stale || (cached && !cached.fresh)),
      empty_reason: VIEW_META.industry.empty,
      empty_detail: VIEW_META.industry.detail,
      empty_icon: VIEW_META.industry.icon,
      summary: [
        chip('主力净额', fmtMoney(net), net),
        chip('最强流入', inflow[0] ? inflow[0].name + ' ' + fmtMoney(inflow[0].amount) : '—', inflow[0] && inflow[0].amount),
        chip('最强流出', outflow[0] ? outflow[0].name + ' ' + fmtMoney(outflow[0].amount) : '—', outflow[0] && outflow[0].amount),
        chip('排行样本', (inflow.length + outflow.length) + ' 个', 0)
      ],
      aux_html: renderFundPreview(inflow, outflow)
    };
  }

  async function loadPersonalData(){
    var quoteRes = await fetch('/api/market/quote-cache');
    var quoteData = quoteRes.ok ? await quoteRes.json() : {items: []};
    var marketRes = await fetch('/api/market?kind=watchlist');
    var marketData = marketRes.ok ? await marketRes.json() : {items: []};
    return buildPersonalData(quoteData.items || [], marketData.items || [], quoteData.available);
  }

  function buildPersonalData(quotes, marketItems, available){
    var byId = {};
    marketItems.forEach(function(it){ byId[it.id] = it; });
    var stocks = [];
    quotes.forEach(function(q){
      if(!q || !q.ok || !Array.isArray(q.kline) || q.kline.length < 2) return;
      var item = byId[q.market_id] || {};
      var pts = q.kline.map(normalizeKlinePoint).filter(function(p){ return p.date && isFinite(p.close); });
      if(pts.length < 2) return;
      var cost = num(item.cost_price || q.cost_price);
      var shares = num(item.shares || q.shares);
      stocks.push({
        id: q.market_id,
        label: q.title || item.title || q.code || '自选股',
        market: item.market || q.market || '',
        code: item.ticker || q.code || '',
        allPoints: pts,           // 全部 K 线(算多周期收益用)
        cost: cost,
        shares: shares,
        isHolding: cost > 0 && shares > 0,
        returns: {
          d1:   periodReturn(pts, 1),
          d30:  periodReturn(pts, 30),
          d90:  periodReturn(pts, 90),
          d180: periodReturn(pts, 180)
        }
      });
    });

    if(!stocks.length){
      var empty = buildEmptyData('personal', available === false ? '行情功能不可用' : VIEW_META.personal.empty);
      empty.summary = [
        chip('可用缓存', '0 只', 0),
        chip('当前周期', state.period + ' 日', 0),
        chip('走势类型', '待生成', 0)
      ];
      return empty;
    }

    // 4 个指标卡:各周期盈利股占比
    var periods = [['d1','当日盈利股占比'], ['d30','30日盈利股占比'], ['d90','90日盈利股占比'], ['d180','180日盈利股占比']];
    var cards = periods.map(function(p){
      var ratio = profitRatio(stocks, p[0]);
      return {key: p[0], label: p[1], val: ratio};
    });

    return {
      view: 'personal',
      title: '个人趋势',
      stocks: stocks,
      cards: cards,
      holdingsCount: stocks.filter(function(s){ return s.isHolding; }).length,
      updated_at: newestQuoteTime(quotes),
      stale: quotes.some(function(q){ return q && q.stale; }),
      summary: [
        chip('自选股', stocks.length + ' 只', 0),
        chip('持仓', stocks.filter(function(s){ return s.isHolding; }).length + ' 只', 0),
        chip('当日盈利占比', fmtPct(cards[0].val), cards[0].val),
        chip('90日盈利占比', fmtPct(cards[2].val), cards[2].val)
      ]
    };
  }

  // 从 K 线末尾往回取 days 天的收益率。(end - start) / start * 100
  function periodReturn(points, days){
    if(!points || points.length < 2) return null;
    var end = points[points.length - 1].close;
    var idx = Math.max(0, points.length - 1 - days);
    var start = points[idx].close;
    if(!start) return null;
    return (end - start) / start * 100;
  }

  // 盈利股占比(收益 > 0 的占有效股票的比例),返回百分比
  function profitRatio(stocks, key){
    var valid = stocks.filter(function(s){ return s.returns[key] != null; });
    if(!valid.length) return 0;
    var profit = valid.filter(function(s){ return s.returns[key] > 0; }).length;
    return Math.round(profit / valid.length * 100);
  }

  function normalizeKlinePoint(row){
    return {
      date: String(row.date || row.trade_date || ''),
      close: num(row.close || row.price),
      change_pct: num(row.change_pct),
      volume: num(row.volume || row.volume_shares),
      amount: num(row.amount)
    };
  }

  function buildPortfolioSeries(stocks){
    var map = {};
    stocks.forEach(function(stock){
      stock.points.forEach(function(p){
        if(!map[p.date]) map[p.date] = {date: p.date, value: 0, cost: 0, volume: 0, amount: 0};
        map[p.date].value += p.close * stock.shares;
        map[p.date].cost += stock.cost * stock.shares;
        map[p.date].volume += p.volume;
        map[p.date].amount += p.amount;
      });
    });
    var points = Object.keys(map).sort().map(function(date){
      var d = map[date];
      var ret = d.cost ? (d.value - d.cost) / d.cost * 100 : 0;
      return {date: date, close: round(ret, 3), change_pct: round(ret, 3), volume: d.volume, amount: d.amount};
    });
    return {id: 'portfolio', label: '持仓组合收益', color: COLORS.personal, points: points};
  }

  function buildEqualWeightSeries(stocks){
    var map = {};
    stocks.forEach(function(stock){
      var base = stock.points[0] && stock.points[0].close;
      if(!base) return;
      stock.points.forEach(function(p){
        if(!map[p.date]) map[p.date] = {date: p.date, ret: 0, count: 0, volume: 0, amount: 0};
        map[p.date].ret += (p.close - base) / base * 100;
        map[p.date].count += 1;
        map[p.date].volume += p.volume;
        map[p.date].amount += p.amount;
      });
    });
    var points = Object.keys(map).sort().map(function(date){
      var d = map[date];
      var ret = d.count ? d.ret / d.count : 0;
      return {date: date, close: round(ret, 3), change_pct: round(ret, 3), volume: d.volume, amount: d.amount};
    });
    return {id: 'equal', label: '自选股等权走势', color: COLORS.personalAlt, points: points};
  }

  function prepareTrendData(data){
    if(!data || data._activityReady) return data;
    (data.series || []).forEach(function(series){
      decorateActivity(series.points || []);
    });
    data._activityReady = true;
    return data;
  }

  function decorateActivity(points){
    var recentAmounts = [];
    points.forEach(function(p){
      var amount = metricNumber(p.amount);
      var avg = average(recentAmounts);
      p.avg_amount_20 = avg;
      p.activity = avg && amount != null ? round(amount / avg, 3) : null;
      if(amount != null && amount > 0){
        recentAmounts.push(amount);
        if(recentAmounts.length > 20) recentAmounts.shift();
      }
    });
  }

  function average(values){
    if(!values.length) return null;
    return values.reduce(function(sum, v){ return sum + v; }, 0) / values.length;
  }

  function render(data){
    data = prepareTrendData(data || buildEmptyData(state.view));
    state.lastData = data;
    state.chartModel = null;
    if(data.view === 'market') renderIndexCards(data.index_cards || []);
    var upd = document.getElementById('mk-trend-updated');
    if(upd){
      var text = data.updated_at ? ('更新于 ' + data.updated_at) : data.title;
      if(data.stale) text += '（缓存）';
      if(data.refreshing) text += '（刷新中）';
      upd.textContent = text;
    }
    // industry 视图:隐藏顶部周期行(行业看板有自己的 5/20 日切换)
    var periodRow = document.getElementById('mk-trend-period-row');
    if(periodRow) periodRow.style.display = (data.view === 'industry') ? 'none' : '';
    if(data.view === 'personal' && data.stocks){
      setHTML('mk-trend-canvas', renderPersonalDashboard(data));
    } else if(data.view === 'industry' && data.series && data.series.length){
      setHTML('mk-trend-canvas', renderIndustryBoard(data));
    } else if(data.series && data.series.length){
      setHTML('mk-trend-canvas', renderChart(data));
      bindHover();
    } else {
      setHTML('mk-trend-canvas', renderEmpty(data));
    }
    // industry / personal 看板自带 footer,不再用 summary chip 行
    if(data.view !== 'industry' && data.view !== 'personal'){
      setHTML('mk-trend-summary', renderSummary(data.summary || []));
    } else {
      setHTML('mk-trend-summary', '');
    }
    refreshIcons();
  }

  function renderIndexCards(cards){
    var byId = {};
    (cards || []).forEach(function(card){
      if(card && card.id) byId[card.id] = card;
    });
    INDEX_CARD_META.forEach(function(meta){
      var root = document.querySelector('[data-index-card="' + meta.id + '"]');
      if(!root) return;
      var card = byId[meta.id] || {};
      var name = root.querySelector('.mk-index-name');
      var val = root.querySelector('[data-index-val]');
      var chg = root.querySelector('[data-index-chg]');
      if(name){
        name.innerHTML = '<span>' + esc(card.market || meta.market) + '</span><b>' + esc(card.label || meta.label) + '</b>';
      }
      if(val) val.textContent = isFinite(Number(card.value)) ? fmtIndexValue(card.value) : '—';
      if(chg){
        var hasChange = isFinite(Number(card.change_pct));
        if(hasChange){
          var pctNum = Number(card.change_pct);
          var up = pctNum >= 0;
          var chgCls = up ? 'up' : 'down';
          var arrow = up ? '▲' : '▼';
          // 与自选股卡片一致:箭头 + 涨幅(去负号,靠箭头表方向)单独变色,
          // 日期用 muted 独立 span 不跟着变色
          var chgHtml = '<span class="mk-index-chg-pct ' + chgCls + '">' + arrow + ' ' + fmtPct(Math.abs(pctNum)).replace('+','') + '</span>';
          if(card.updated_at) chgHtml += '<span class="mk-index-chg-date">' + esc(shortDate(card.updated_at)) + '</span>';
          chg.innerHTML = chgHtml;
          chg.classList.remove('muted');
        } else {
          chg.innerHTML = '';
          chg.textContent = card.updated_at ? shortDate(card.updated_at) : '等待行情';
          chg.classList.toggle('muted', !card.updated_at);
        }
      }
    });
  }

  // ===== 个人趋势:热力图看板(指标卡 + 收益热力图 + 右侧辅助区) =====
  function renderPersonalDashboard(data){
    var stocks = data.stocks || [];
    // 筛选:全部 / 仅持仓
    var filtered = state.personalFilter === 'holdings'
      ? stocks.filter(function(s){ return s.isHolding; })
      : stocks.slice();
    // 排序:按选定周期收益降序(null 排末尾)
    var sk = state.personalSort;
    filtered.sort(function(a, b){
      var va = a.returns[sk], vb = b.returns[sk];
      if(va == null && vb == null) return 0;
      if(va == null) return 1;
      if(vb == null) return -1;
      return vb - va;
    });

    var html = '<div class="mk-personal-dashboard">'
      // —— 左侧主区:指标卡 + 热力图 ——
      + '<div class="mk-personal-main">'
      + renderPersonalCards(data.cards || [])
      + renderPersonalHeatmap(filtered)
      + '</div>'
      // —— 右侧辅助区 ——
      + '<aside class="mk-personal-rail">'
      + renderPersonalSidebar(data, filtered, stocks)
      + '</aside>'
      + '</div>';
    return html;
  }

  function renderPersonalCards(cards){
    var PERIOD_LABELS = {d1:'当日', d30:'30日', d90:'90日', d180:'180日'};
    return '<div class="mk-index-grid mk-personal-cards">'
      + cards.map(function(c){
          var pct = c.val;
          var cls = pct >= 55 ? 'up' : (pct >= 45 ? 'neutral' : 'down');
          var conclusion = pct >= 55 ? '短期偏强' : (pct >= 45 ? (PERIOD_LABELS[c.key] || '') + '中性' : (PERIOD_LABELS[c.key] || '') + '偏弱');
          return '<div class="mk-index-card mk-personal-card ' + cls + '">'
            + '<div class="mk-index-name"><b>' + esc(c.label) + '</b></div>'
            + '<div class="mk-index-val">' + pct + '%</div>'
            + '<div class="mk-index-chg mk-index-chg-pct ' + cls + '">' + esc(conclusion) + '</div>'
          + '</div>';
        }).join('')
      + '</div>';
  }

  function renderPersonalHeatmap(stocks){
    if(!stocks.length) return '<div class="mk-trend-empty"><strong>暂无符合条件的自选股</strong></div>';
    var PERIODS = [['d1','当日'], ['d30','30日'], ['d90','90日'], ['d180','180日']];
    // 表头
    var head = '<thead><tr><th class="mk-hm-name-th">股票</th>'
      + PERIODS.map(function(p){ return '<th>' + esc(p[1]) + '</th>'; }).join('')
      + '</tr></thead>';
    // 行
    var rows = stocks.map(function(s){
      var cells = PERIODS.map(function(p){
        var r = s.returns[p[0]];
        if(r == null) return '<td class="mk-hm-cell muted">—</td>';
        var cls = r > 0 ? 'up' : (r < 0 ? 'down' : '');
        var intensity = Math.min(Math.abs(r) / 20, 1);  // 0-20% 映射到 0-1 深度
        return '<td class="mk-hm-cell ' + cls + '" style="--hi:' + intensity.toFixed(2) + '">'
          + '<span>' + fmtPct(r) + '</span></td>';
      }).join('');
      var codeTag = s.code ? '<span class="mk-hm-code muted">' + esc(s.code) + '</span>' : '';
      var holdIcon = s.isHolding ? '<i data-lucide="briefcase" class="mk-hm-hold-ico"></i>' : '';
      return '<tr class="mk-hm-row" data-stock-id="' + esc(s.id) + '">'
        + '<td class="mk-hm-name">' + holdIcon + '<a href="/market/' + esc(s.id) + '">' + esc(s.label) + '</a>' + codeTag + '</td>'
        + cells
      + '</tr>';
    }).join('');
    return '<div class="mk-heatmap-wrap">'
      + '<div class="mk-heatmap-head"><b>自选股收益热力图</b>'
        + '<span class="mk-heatmap-legend muted"><i class="mk-leg-down"></i>亏损<i class="mk-leg-up"></i>盈利</span>'
      + '</div>'
      + '<div class="mk-heatmap-scroll"><table class="mk-heatmap-table">' + head + '<tbody>' + rows + '</tbody></table></div>'
    + '</div>';
  }

  function renderPersonalSidebar(data, filtered, allStocks){
    // —— 卡 1:筛选与说明 ——
    var filterAll = state.personalFilter === 'all';
    var sortOpts = [['d90','按90日收益'], ['d180','按180日收益'], ['d30','按30日收益'], ['d1','按当日收益']];
    var filterHtml = '<div class="mk-pfilter-seg">'
      + '<button type="button" class="mk-pfilter-btn' + (filterAll ? ' active' : '') + '" data-personal-filter="all">全部自选</button>'
      + '<button type="button" class="mk-pfilter-btn' + (!filterAll ? ' active' : '') + '" data-personal-filter="holdings">仅持仓</button>'
      + '</div>'
      + '<select class="filter-select mk-pfilter-sort" data-personal-sort-sel>'
      + sortOpts.map(function(o){ return '<option value="' + o[0] + '"' + (state.personalSort === o[0] ? ' selected' : '') + '>' + esc(o[1]) + '</option>'; }).join('')
      + '</select>'
      + '<p class="mk-pfilter-hint muted">点击个股可查看详情页</p>';

    // —— 卡 2:组合观察(动态总结) ——
    var obsLines = [];
    var d1Ratio = data.cards[0] ? data.cards[0].val : 0;
    var d90Ratio = data.cards[2] ? data.cards[2].val : 0;
    var d180Ratio = data.cards[3] ? data.cards[3].val : 0;
    if(d1Ratio >= 55) obsLines.push('短期盈利股占比较高(' + d1Ratio + '%),但90日维度仍偏分化');
    if(d180Ratio < 45) obsLines.push('长期亏损面较大(' + d180Ratio + '%),需关注下行趋势股');
    if(d90Ratio > 0 && d180Ratio > 0 && d90Ratio - d180Ratio > 15) obsLines.push('近期回暖但长期仍弱,反弹持续性待观察');
    if(!obsLines.length) obsLines.push('各周期盈利占比相对均衡,组合整体平稳');
    var obsHtml = obsLines.map(function(l){ return '<p class="mk-obs-line">' + esc(l) + '</p>'; }).join('');

    // —— 卡 3:关注风险(180日最弱 Top 3) ——
    var riskStocks = allStocks.filter(function(s){ return s.returns.d180 != null; })
      .sort(function(a, b){ return a.returns.d180 - b.returns.d180; })
      .slice(0, 3);
    var riskHtml = riskStocks.length ? riskStocks.map(function(s){
      return '<a class="mk-risk-item" href="/market/' + esc(s.id) + '">'
        + '<span class="mk-risk-name">' + esc(s.label) + '</span>'
        + '<span class="mk-risk-pct down">' + fmtPct(s.returns.d180) + '</span>'
      + '</a>';
    }).join('') : '<p class="muted">暂无数据</p>';

    return '<div class="mk-rail-card mk-personal-card-section">'
        + '<h3 class="mk-rail-title">筛选与说明</h3>'
        + filterHtml
      + '</div>'
      + '<div class="mk-rail-card mk-personal-card-section">'
        + '<h3 class="mk-rail-title">组合观察</h3>'
        + obsHtml
      + '</div>'
      + '<div class="mk-rail-card mk-personal-card-section">'
        + '<h3 class="mk-rail-title">关注风险<span class="muted" style="font-weight:400;font-size:var(--fs-xs)"> 180日最弱</span></h3>'
        + riskHtml
      + '</div>';
  }

  function renderEmpty(data){
    return '<div class="mk-trend-empty">'
      + '<div class="mk-trend-empty-main">'
        + '<i data-lucide="' + esc(data.empty_icon || 'line-chart') + '"></i>'
        + '<strong>' + esc(data.empty_reason || '暂无数据') + '</strong>'
        + '<span>' + esc(data.empty_detail || '') + '</span>'
      + '</div>'
      + (data.aux_html || '')
    + '</div>';
  }

  function renderChart(data){
    var el = document.getElementById('mk-trend-canvas');
    var W = Math.min(960, Math.max(360, (el && el.clientWidth) || 760));
    var H = 330, padL = 52, padR = 18, padT = 18, padB = 28;
    var priceH = 220, volH = 52, gap = 18;
    var chartW = W - padL - padR;
    var series = data.series || [];
    var visibleSeries = series.filter(function(s){ return !state.hiddenSeries[s.id]; });
    var allValues = [];
    visibleSeries.forEach(function(s){
      s.points.forEach(function(p){
        var v = pointValue(p);
        if(hasMetricValue(v)) allValues.push(metricNumber(v));
      });
    });
    if(series.length && !visibleSeries.length) return renderEmpty(buildEmptyData(data.view, '所有指数已隐藏,点击图例恢复'));
    if(!allValues.length) return renderEmpty(buildEmptyData(data.view, '暂无可绘制数据'));
    var scale = chartScale(data, allValues);
    var minV = scale.min;
    var maxV = scale.max;
    var range = maxV - minV || 1;

    function xAt(i, n){ return padL + (n <= 1 ? 0 : i / (n - 1) * chartW); }
    function yAt(v){
      var plotted = scale.fixed ? Math.max(minV, Math.min(maxV, v)) : v;
      return padT + (maxV - plotted) / range * priceH;
    }

    var primary = visibleSeries.find(function(s){ return s.id === state.primaryIndex; })
            || visibleSeries[0] || series[0];  // 优先匹配聚焦指数;回退第一个可见;再回退第一个
    var primaryVals = primary.points.map(pointValue);
    var volMax = Math.max.apply(null, primary.points.map(function(p){ return p.volume || 0; })) || 1;
    var volBase = padT + priceH + gap + volH;
    var svg = '<svg class="mk-trend-svg" width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H + '">';
    svg += '<rect x="0" y="0" width="' + W + '" height="' + H + '" rx="8" fill="transparent"/>';

    scale.ticks.forEach(function(gv){
      var gy = yAt(gv);
      var gridCls = scaleBaselineClass(scale, gv) || 'mk-trend-grid';
      svg += '<line x1="' + padL + '" y1="' + gy.toFixed(1) + '" x2="' + (W-padR) + '" y2="' + gy.toFixed(1) + '" class="' + gridCls + '"/>';
      svg += '<text x="' + (padL-8) + '" y="' + (gy+3).toFixed(1) + '" text-anchor="end" class="mk-trend-axis">' + esc(formatValue(gv)) + '</text>';
    });

    primary.points.forEach(function(p, i){
      var bw = Math.max(2, chartW / primary.points.length * 0.55);
      var x = xAt(i, primary.points.length);
      var vh = Math.max(1, (p.volume || 0) / volMax * volH);
      var y = volBase - vh;
      svg += '<rect x="' + (x-bw/2).toFixed(1) + '" y="' + y.toFixed(1) + '" width="' + bw.toFixed(1) + '" height="' + vh.toFixed(1) + '" class="mk-trend-vol"/>';
    });
    svg += '<line x1="' + padL + '" y1="' + volBase + '" x2="' + (W-padR) + '" y2="' + volBase + '" class="mk-trend-grid"/>';

    visibleSeries.forEach(function(s){
      svg += linePath(s.points.map(pointValue), s.points, xAt, yAt, s.color, s.label, 'mk-trend-line');
    });
    if(state.ma5) svg += maPath(primaryVals, primary.points, 5, xAt, yAt, COLORS.ma5, 'MA5');
    if(state.ma20) svg += maPath(primaryVals, primary.points, 20, xAt, yAt, COLORS.ma20, 'MA20');

    var n = primary.points.length;
    if(n){
      var first = primary.points[0], mid = primary.points[Math.floor((n-1)/2)], last = primary.points[n-1];
      [[first,0,'start'],[mid,Math.floor((n-1)/2),'middle'],[last,n-1,'end']].forEach(function(d){
        svg += '<text x="' + xAt(d[1], n).toFixed(1) + '" y="' + (H-8) + '" text-anchor="' + d[2] + '" class="mk-trend-axis">' + esc(shortDate(d[0].date)) + '</text>';
      });
      var lastVal = pointValue(last);
      if(hasMetricValue(lastVal)){
        var lastX = xAt(n-1, n), lastY = yAt(metricNumber(lastVal));
        svg += '<circle cx="' + lastX.toFixed(1) + '" cy="' + lastY.toFixed(1) + '" r="4" fill="' + primary.color + '"/>';
        svg += '<text x="' + (lastX-6).toFixed(1) + '" y="' + (lastY-8).toFixed(1) + '" text-anchor="end" class="mk-trend-last" fill="' + esc(metricToneColor(lastVal)) + '">' + esc(formatValue(lastVal)) + '</text>';
      }
    }

    svg += '<line id="mk-trend-cross-x" class="mk-trend-cross" x1="0" x2="0" y1="' + padT + '" y2="' + volBase + '" hidden/>';
    svg += '<circle id="mk-trend-cross-dot" class="mk-trend-cross-dot" cx="0" cy="0" r="4" hidden/>';
    svg += '<rect class="mk-trend-plot" x="' + padL + '" y="' + padT + '" width="' + chartW + '" height="' + (priceH + gap + volH) + '" fill="transparent"/>';
    svg += '</svg>';

    state.chartModel = {
      padL: padL, padT: padT, chartW: chartW, priceH: priceH, volBase: volBase,
      points: primary.points, values: primaryVals, yAt: yAt, xAt: xAt, color: primary.color
    };
    // 控件行:指数图例 + 周期 + 指标 + MA 合并到同一 flex 容器(从左到右流式排列)
    return '<div class="mk-trend-controls">'
      + '<div class="mk-trend-legend">' + renderLegend(data) + '</div>'
      + renderToolbar()
      + '</div>'
      + '<div class="mk-trend-chart-wrap">' + svg + '<div class="mk-trend-tooltip" id="mk-trend-tooltip" hidden></div></div>';
  }

  // 工具栏:指标 / 均线(周期选择留在 market.html 静态位,不放这里)。
  // 与图例同处一行,事件委托走全局 document 监听(data-trend-metric/ma)。
  function renderToolbar(){
    function segBtn(attr, val, label, active, extra){
      return '<button class="mk-fund-btn' + (active ? ' active' : '') + '"'
        + ' ' + attr + '="' + val + '" type="button"'
        + (extra || '') + '>' + label + '</button>';
    }
    var metricSeg = '<div class="mk-fund-seg" role="group" aria-label="走势图指标">'
      + segBtn('data-trend-metric', 'change_pct', '累计涨跌', state.metric === 'change_pct')
      + segBtn('data-trend-metric', 'activity', '成交活跃度', state.metric === 'activity')
      + '</div>';
    var maSeg = '<div class="mk-fund-seg" role="group" aria-label="均线">'
      + segBtn('data-trend-ma', 'ma5', 'MA5', state.ma5, ' aria-pressed="' + (state.ma5 ? 'true' : 'false') + '"')
      + segBtn('data-trend-ma', 'ma20', 'MA20', state.ma20, ' aria-pressed="' + (state.ma20 ? 'true' : 'false') + '"')
      + '</div>';
    return '<div class="mk-trend-toolbar">' + metricSeg + maSeg + '</div>';
  }

  function renderIndustryBoard(data){
    var series = (data.series || []);
    var selected = findSelectedIndustry(data);
    if(!series.length || !selected) return renderEmpty(buildEmptyData('industry', '暂无可绘制数据'));

    // 排序键:industryPeriod '5'→d5,'20'→d20(回退 sort_value)
    var periodKey = state.industryPeriod === '5' ? 'd5' : 'd20';
    function industryValue(s){
      var sm = s.summary || {};
      if(periodKey === 'd5') return num(sm.d5);
      return num(sm.d20 != null ? sm.d20 : s.sort_value);
    }
    var ranked = series.map(function(s){
      var v = industryValue(s);
      var last = (s.points || [])[s.points.length - 1] || {};
      return { s: s, value: v, today: num(last.change_pct) };
    }).sort(function(a, b){ return b.value - a.value; });
    var maxAbs = Math.max.apply(null, ranked.map(function(r){ return Math.abs(r.value); }).concat([0.01]));

    return '<div class="mk-ind-board">'
      + renderIndustryHeader()
      + renderIndustryCards(selected)
      + renderIndustryBars(ranked, selected, maxAbs)
      + renderIndustryFooter(selected)
      + '<div class="mk-trend-tooltip" id="mk-trend-tooltip" hidden></div>'
    + '</div>';
  }

  // 看板头部:标题 + 副标题 + 时间切换(5日/20日)
  function renderIndustryHeader(){
    var p = state.industryPeriod;
    function pBtn(val, label){
      return '<button class="mk-fund-btn' + (p === val ? ' active' : '') + '" data-industry-period="' + val + '" type="button">' + label + '</button>';
    }
    return '<div class="mk-ind-header">'
      + '<div class="mk-ind-header-main">'
        + '<h3 class="mk-ind-title"><i data-lucide="layers-3"></i> 行业模块</h3>'
        + '<p class="mk-ind-sub muted">查看当前市场中最强与最弱的行业方向</p>'
      + '</div>'
      + '<div class="mk-fund-seg mk-ind-period" role="group" aria-label="行业时间窗口">'
        + pBtn('5', '5日') + pBtn('20', '20日')
      + '</div>'
    + '</div>';
  }

  // 4 张指标卡:选中行业的 5日强弱 / 20日强弱 / 上涨占比(今日涨跌近似)/ 成交活跃度
  function renderIndustryCards(selected){
    var sm = selected.summary || {};
    var last = (selected.points || [])[selected.points.length - 1] || {};
    var d5 = num(sm.d5), d20 = num(sm.d20 != null ? sm.d20 : selected.sort_value);
    var today = num(last.change_pct);
    var turnover = num(sm.turnover);

    function card(icon, title, valText, conclusion, tone){
      return '<div class="mk-ind-card" data-tone="' + tone + '">'
        + '<div class="mk-ind-card-head"><i data-lucide="' + icon + '"></i><span>' + esc(title) + '</span></div>'
        + '<div class="mk-ind-card-val">' + esc(valText) + '</div>'
        + '<div class="mk-ind-card-conc">' + esc(conclusion) + '</div>'
      + '</div>';
    }
    // tone: up=红(强)/ down=绿(弱)/ warn=橙(震荡)/ muted=灰
    var d5Tone = d5 > 0 ? 'up' : (d5 < 0 ? 'down' : 'warn');
    var d5Conc = d5 > 0 ? '短期走强' : (d5 < 0 ? '短期走弱' : '短期平稳');
    var d20Tone = d20 > 3 ? 'up' : (d20 < -3 ? 'down' : 'warn');
    var d20Conc = d20 > 3 ? '趋势延续' : (d20 < -3 ? '趋势转弱' : '区间震荡');
    var upTone = today > 0 ? 'up' : (today < 0 ? 'down' : 'warn');
    var upConc = today > 0 ? '内部普涨' : (today < 0 ? '内部普跌' : '涨跌各半');
    var actTone = turnover > 0 ? (turnover > 3 ? 'up' : 'warn') : 'muted';
    var actVal = turnover > 0 ? fmtPct(turnover) : '—';
    var actConc = turnover > 3 ? '资金活跃' : (turnover > 0 ? '成交正常' : '成交清淡');

    return '<div class="mk-ind-cards">'
      + card('zap', '5日相对强弱', fmtPct(d5), d5Conc, d5Tone)
      + card('trending-up', '20日相对强弱', fmtPct(d20), d20Conc, d20Tone)
      + card('bar-chart-3', '上涨股票占比(估)', fmtPct(today), upConc, upTone)
      + card('activity', '成交活跃度', actVal, actConc, actTone)
    + '</div>';
  }

  // 横向条形排名图:行业按 value 降序,正=红条向右,负=绿条向左,0 轴居中
  function renderIndustryBars(ranked, selected, maxAbs){
    var rows = ranked.map(function(r, i){
      var v = r.value;
      var pct = Math.min(50, Math.abs(v) / maxAbs * 50);  // 0轴居中,左右各占50%
      var dir = v >= 0 ? 'pos' : 'neg';
      var isActive = r.s.id === selected.id;
      // 条形定位:正收益从中间向右延伸,负收益从中间向左延伸
      var barStyle = v >= 0
        ? 'left:50%;width:' + pct.toFixed(1) + '%'
        : 'right:50%;width:' + pct.toFixed(1) + '%';
      return '<div class="mk-ind-bar-row' + (isActive ? ' active' : '') + '" data-industry-select="' + esc(r.s.id) + '">'
        + '<span class="mk-ind-rank">' + (i + 1) + '</span>'
        + '<span class="mk-ind-name">' + esc(r.s.label) + '</span>'
        + '<div class="mk-ind-bar-track">'
          + '<div class="mk-ind-bar-axis"></div>'
          + '<div class="mk-ind-bar ' + dir + '" style="' + barStyle + '" title="' + esc(r.s.label) + ': ' + esc(fmtPct(v)) + '"></div>'
        + '</div>'
        + '<span class="mk-ind-val ' + dir + '">' + esc(fmtPct(v)) + '</span>'
      + '</div>';
    }).join('');
    return '<div class="mk-ind-bars">'
      + '<div class="mk-ind-bars-title"><i data-lucide="bar-chart-3"></i> 行业相对收益排名</div>'
      + '<div class="mk-ind-bar-list">' + rows + '</div>'
    + '</div>';
  }

  // 底部说明:选中行业的领涨股 + 强弱判定
  function renderIndustryFooter(selected){
    var sm = selected.summary || {};
    var lead = sm.lead_stock ? (esc(sm.lead_stock) + (sm.lead_stock_change_pct ? ' ' + esc(fmtPct(sm.lead_stock_change_pct)) : '')) : '—';
    var strength = sm.strength || '—';
    return '<div class="mk-ind-footer muted">'
      + '<span><b>当前选中:</b>' + esc(selected.label) + '</span>'
      + '<span><b>领涨股:</b>' + lead + '</span>'
      + '<span><b>趋势:</b>' + esc(strength) + '</span>'
    + '</div>';
  }


  function chartScale(data, values){
    var fixed = data.view === 'market' && state.metric === 'change_pct';
    if(fixed){
      var maxAbs = Math.max.apply(null, values.map(function(v){ return Math.abs(v); }));
      // 向上取整到 10 的倍数(最小 10):保留「对称于 0 + 整齐刻度」的原意,
      // 但不再封顶 20 —— 收益超过 20% 时 Y 轴自动扩到 ±30/±50,折线不被截断。
      var limit = Math.max(10, Math.ceil(maxAbs / 10) * 10);
      return {
        fixed: true,
        baseline: 0,
        baselineClass: 'mk-trend-zero',
        min: -limit,
        max: limit,
        ticks: [-limit, -limit / 2, 0, limit / 2, limit]
      };
    }
    if(state.metric === 'activity'){
      var maxActivity = Math.max.apply(null, values);
      var maxTick = Math.max(2, Math.ceil(maxActivity * 2) / 2);
      var ticks = [0, round(maxTick * 0.25, 2), round(maxTick * 0.5, 2), round(maxTick * 0.75, 2), maxTick];
      if(!ticks.some(function(t){ return Math.abs(t - 1) < 0.0001; })) ticks.push(1);
      ticks = ticks.sort(function(a, b){ return a - b; }).filter(function(t, i, arr){
        return i === 0 || Math.abs(t - arr[i - 1]) > 0.0001;
      });
      return {
        fixed: false,
        baseline: 1,
        baselineClass: 'mk-trend-neutral',
        min: 0,
        max: maxTick,
        ticks: ticks
      };
    }
    var minV = Math.min.apply(null, values);
    var maxV = Math.max.apply(null, values);
    var range = maxV - minV || 1;
    minV -= range * 0.08;
    maxV += range * 0.08;
    range = maxV - minV || 1;
    var ticks = [];
    for(var g = 0; g <= 4; g++) ticks.push(minV + range * g / 4);
    return {fixed: false, min: minV, max: maxV, ticks: ticks};
  }

  function scaleBaselineClass(scale, value){
    if(scale.baseline == null) return '';
    return Math.abs(value - scale.baseline) < 0.0001 ? (scale.baselineClass || 'mk-trend-zero') : '';
  }

  function renderIndustryDetail(s){
    var points = s.points || [];
    var last = points[points.length - 1] || {};
    var sm = s.summary || {};
    var lead = sm.lead_stock ? sm.lead_stock + (sm.lead_stock_change_pct != null ? ' ' + fmtPct(sm.lead_stock_change_pct) : '') : (sm.strength || '—');
    return '<div class="mk-industry-detail-head">'
        + '<span>选中行业</span><strong>' + esc(s.label) + '</strong>'
        + '<b class="' + trendClass(s.sort_value) + '">' + esc(fmtPct(s.sort_value || 0)) + '</b>'
      + '</div>'
      + renderIndustrySparkline(s)
      + '<div class="mk-industry-mini">'
        + '<span><b>' + esc(fmtPct(last.change_pct || 0)) + '</b><em>今日</em></span>'
        + '<span><b>' + esc(fmtPct(sm.d5 || 0)) + '</b><em>近5日</em></span>'
        + '<span><b>' + esc(fmtPct(sm.d20 || 0)) + '</b><em>近20日</em></span>'
        + '<span><b>' + esc(lead) + '</b><em>领涨/方向</em></span>'
      + '</div>';
  }

  function renderIndustrySparkline(s){
    var points = s.points || [];
    if(points.length < 2) return '<div class="mk-industry-spark-empty">暂无走势</div>';
    var W = 328, H = 132, padL = 30, padR = 12, padT = 14, padB = 24;
    var chartW = W - padL - padR, chartH = H - padT - padB;
    var values = points.map(industryPointValue).filter(hasMetricValue).map(metricNumber);
    if(!values.length) return '<div class="mk-industry-spark-empty">暂无走势</div>';
    var minV = Math.min.apply(null, values), maxV = Math.max.apply(null, values);
    var range = maxV - minV || 1;
    minV -= range * 0.12;
    maxV += range * 0.12;
    range = maxV - minV || 1;
    function xAt(i, n){ return padL + (n <= 1 ? 0 : i / (n - 1) * chartW); }
    function yAt(v){ return padT + (maxV - v) / range * chartH; }
    var svg = '<svg class="mk-industry-spark-svg" width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H + '">';
    for(var g = 0; g <= 2; g++){
      var gv = minV + range * g / 2;
      var gy = yAt(gv);
      svg += '<line x1="' + padL + '" y1="' + gy.toFixed(1) + '" x2="' + (W - padR) + '" y2="' + gy.toFixed(1) + '" class="mk-trend-grid"/>';
    }
    var pointVals = points.map(industryPointValue);
    svg += linePath(pointVals, points, xAt, yAt, s.color, s.label, 'mk-trend-line');
    if(state.ma5) svg += maPath(pointVals, points, 5, xAt, yAt, COLORS.ma5, 'MA5');
    if(state.ma20) svg += maPath(pointVals, points, 20, xAt, yAt, COLORS.ma20, 'MA20');
    var last = points[points.length - 1];
    var lastValue = industryPointValue(last);
    if(hasMetricValue(lastValue)){
      svg += '<circle cx="' + xAt(points.length - 1, points.length).toFixed(1) + '" cy="' + yAt(metricNumber(lastValue)).toFixed(1) + '" r="4" fill="' + esc(s.color) + '"/>';
      svg += '<text x="' + (W - padR) + '" y="' + (H - 7) + '" text-anchor="end" class="mk-trend-axis">' + esc(formatValue(lastValue)) + '</text>';
    }
    svg += '</svg>';
    return '<div class="mk-industry-spark">' + svg + '</div>';
  }

  function findSelectedIndustry(data){
    var series = data.series || [];
    if(!series.length) return null;
    var selected = series.find(function(s){ return s.id === state.selectedIndustry; });
    if(!selected){
      selected = series[0];
      state.selectedIndustry = selected.id;
    }
    return selected;
  }

  function heatmapDates(data){
    var dates = {};
    (data.heatmap || []).forEach(function(cell){
      if(cell.date) dates[cell.date] = true;
    });
    (data.series || []).forEach(function(series){
      (series.points || []).forEach(function(point){
        if(point.date) dates[point.date] = true;
      });
    });
    return Object.keys(dates).sort();
  }

  function industryHeadLabels(dates){
    if(!dates.length) return [];
    var idxs = [0, Math.floor((dates.length - 1) / 2), dates.length - 1];
    var seen = {};
    return idxs.filter(function(i){ if(seen[i]) return false; seen[i] = true; return true; })
      .map(function(i){ return {date: dates[i], col: (i + 1) + ' / span 1'}; });
  }

  function industryPointValue(p){
    if(state.metric === 'activity') return hasMetricValue(p.activity) ? metricNumber(p.activity) : null;
    return num(p.close != null ? p.close : p.value);
  }

  function industryMetricScale(data){
    var vals = [];
    (data.series || []).forEach(function(series){
      (series.points || []).forEach(function(point){
        var v = industryPointValue(point);
        if(hasMetricValue(v)) vals.push(metricNumber(v));
      });
    });
    if(!vals.length){
      (data.heatmap || []).forEach(function(cell){
        var v = industryPointValue(cell);
        if(hasMetricValue(v)) vals.push(metricNumber(v));
      });
    }
    if(state.metric === 'activity'){
      var above = 0, below = 0;
      vals.forEach(function(v){
        above = Math.max(above, v - 1);
        below = Math.max(below, 1 - v);
      });
      return {activity: true, above: above || 1, below: below || 1};
    }
    var maxV = vals.length ? Math.max.apply(null, vals.map(function(v){ return Math.abs(v); })) : 1;
    return maxV || 1;
  }

  function industryCellStyle(value, scale){
    if(!hasMetricValue(value)) return 'background:var(--c-surface-2);';
    if(state.metric === 'activity'){
      var active = metricNumber(value);
      if(active >= 1){
        var highRatio = Math.min(1, (active - 1) / ((scale && scale.above) || 1));
        var highPct = Math.round(18 + highRatio * 62);
        return 'background:color-mix(in srgb, #2563eb ' + highPct + '%, var(--c-surface-2));';
      }
      var lowRatio = Math.min(1, (1 - active) / ((scale && scale.below) || 1));
      var lowPct = Math.round(8 + lowRatio * 24);
      return 'background:color-mix(in srgb, var(--c-text-muted) ' + lowPct + '%, var(--c-surface-2));';
    }
    var ratio = Math.min(1, Math.abs(num(value)) / (scale || 1));
    var pct = Math.round(12 + ratio * 70);
    if(value > 0){
      return 'background:color-mix(in srgb, #dc2626 ' + pct + '%, var(--c-surface-2));';
    }
    if(value < 0){
      return 'background:color-mix(in srgb, #16a34a ' + pct + '%, var(--c-surface-2));';
    }
    return 'background:var(--c-surface-2);';
  }

  function metricHeatClass(value){
    if(!hasMetricValue(value)) return '';
    if(state.metric === 'activity') return metricNumber(value) >= 1 ? ' active-volume' : ' quiet-volume';
    return value > 0 ? ' up' : (value < 0 ? ' down' : '');
  }

  function renderIndustryScale(){
    if(state.metric === 'activity'){
      return '<div class="mk-industry-scale"><span>低</span><i class="activity-low"></i><i class="activity-mid"></i><i class="activity-high"></i><span>高</span></div>';
    }
    return '<div class="mk-industry-scale"><span>弱</span><i class="down"></i><i></i><i class="up"></i><span>强</span></div>';
  }

  function industrySummary(data){
    var s = findSelectedIndustry(data);
    if(!s) return data.summary || [];
    var sm = s.summary || {};
    return [
      chip('选中行业', s.label, s.sort_value || 0),
      chip('近5日', fmtPct(sm.d5 || 0), sm.d5 || 0),
      chip('近20日', fmtPct(sm.d20 || 0), sm.d20 || 0),
      chip('波动率', fmtPct(sm.volatility || 0), 0)
    ];
  }

  function trendClass(v){
    return num(v) > 0 ? 'up' : (num(v) < 0 ? 'down' : '');
  }

  function renderLegend(data){
    var series = data.series || [];
    var visible = series.filter(function(s){ return !state.hiddenSeries[s.id]; });
    // 当前聚焦指数:匹配 state.primaryIndex;失配(被隐藏)时回退第一个可见(与 renderChart 同逻辑)
    var currentPrimary = (visible.find(function(s){ return s.id === state.primaryIndex; }) || visible[0] || series[0] || {}).id;
    var parts = [];
    series.forEach(function(s){
      var hidden = !!state.hiddenSeries[s.id];
      var active = (s.id === currentPrimary) && !hidden;
      parts.push('<span class="mk-trend-legend-btn' + (hidden ? ' is-hidden' : '') + (active ? ' is-active' : '') + '">'
        + '<button type="button" class="legend-focus"'
        + ' data-focus-series="' + esc(s.id) + '"'
        + ' title="点此聚焦该指数(图表 tooltip 跟随)"'
        + ' aria-pressed="' + (active ? 'true' : 'false') + '">'
        + '<i style="--lc:' + esc(s.color) + '"></i>'
        + '<span class="legend-label">' + esc(s.label) + '</span>'
        + '</button>'
        + '<button type="button" class="legend-vis"'
        + ' data-toggle-visibility="' + esc(s.id) + '"'
        + ' aria-pressed="' + (hidden ? 'false' : 'true') + '"'
        + ' title="' + (hidden ? '显示该线' : '隐藏该线') + '">'
        + '<i data-lucide="' + (hidden ? 'eye-off' : 'eye') + '"></i>'
        + '</button>'
        + '</span>');
    });
    if(state.ma5) parts.push('<span class="mk-trend-legend-ma"><i style="--lc:' + COLORS.ma5 + '"></i>MA5</span>');
    if(state.ma20) parts.push('<span class="mk-trend-legend-ma"><i style="--lc:' + COLORS.ma20 + '"></i>MA20</span>');
    return parts.join('');
  }

  function linePath(values, points, xAt, yAt, color, label, cls){
    var path = '';
    values.forEach(function(v, i){
      if(!hasMetricValue(v)) return;
      v = metricNumber(v);
      var cmd = path ? ' L ' : 'M ';
      path += cmd + xAt(i, points.length).toFixed(1) + ',' + yAt(v).toFixed(1);
    });
    if(!path) return '';
    return '<path d="' + path + '" class="' + cls + '" stroke="' + esc(color) + '"><title>' + esc(label) + '</title></path>';
  }

  function maPath(values, points, size, xAt, yAt, color, label){
    var out = [];
    for(var i = 0; i < values.length; i++){
      if(i + 1 < size){ out.push(null); continue; }
      var sum = 0;
      var ok = true;
      for(var j = i - size + 1; j <= i; j++){
        if(!hasMetricValue(values[j])){ ok = false; break; }
        sum += metricNumber(values[j]);
      }
      out.push(ok ? sum / size : null);
    }
    var path = '';
    out.forEach(function(v, i){
      if(v == null || !isFinite(v)) return;
      path += (path ? ' L ' : 'M ') + xAt(i, points.length).toFixed(1) + ',' + yAt(v).toFixed(1);
    });
    return path ? '<path d="' + path + '" class="mk-trend-ma" stroke="' + color + '"><title>' + label + '</title></path>' : '';
  }

  function bindHover(){
    var canvas = document.getElementById('mk-trend-canvas');
    var plot = canvas && canvas.querySelector('.mk-trend-plot');
    var tip = document.getElementById('mk-trend-tooltip');
    var line = document.getElementById('mk-trend-cross-x');
    var dot = document.getElementById('mk-trend-cross-dot');
    var svg = canvas && canvas.querySelector('.mk-trend-svg');
    var model = state.chartModel;
    if(!plot || !tip || !line || !dot || !svg || !model) return;

    plot.addEventListener('mousemove', function(e){
      var rect = svg.getBoundingClientRect();
      var scaleX = Number(svg.getAttribute('viewBox').split(' ')[2]) / rect.width;
      var x = (e.clientX - rect.left) * scaleX;
      var rel = Math.max(0, Math.min(1, (x - model.padL) / model.chartW));
      var idx = Math.round(rel * (model.points.length - 1));
      var p = model.points[idx];
      var value = model.values[idx];
      var cx = model.xAt(idx, model.points.length);
      line.hidden = false;
      line.setAttribute('x1', cx.toFixed(1));
      line.setAttribute('x2', cx.toFixed(1));
      if(hasMetricValue(value)){
        var cy = model.yAt(metricNumber(value));
        dot.hidden = false;
        dot.setAttribute('cx', cx.toFixed(1));
        dot.setAttribute('cy', cy.toFixed(1));
        dot.setAttribute('fill', model.color);
      } else {
        dot.hidden = true;
      }
      tip.hidden = false;
      tip.innerHTML = renderPointTooltip(p, value);
      var left = Math.min(Math.max(8, e.clientX - rect.left + 12), rect.width - 150);
      var top = Math.max(8, e.clientY - rect.top - 82);
      tip.style.left = left + 'px';
      tip.style.top = top + 'px';
    });
    plot.addEventListener('mouseleave', function(){
      line.hidden = true;
      dot.hidden = true;
      tip.hidden = true;
    });
  }

  function bindIndustryHover(){
    var canvas = document.getElementById('mk-trend-canvas');
    var tip = document.getElementById('mk-trend-tooltip');
    if(!canvas || !tip) return;

    canvas.querySelectorAll('[data-industry-cell]').forEach(function(cell){
      cell.addEventListener('mousemove', function(e){
        var rect = canvas.getBoundingClientRect();
        tip.hidden = false;
        tip.innerHTML = '<b>' + esc(cell.dataset.label || '') + ' · ' + esc(cell.dataset.date || '') + '</b>'
          + '<span>' + esc(metricLabel()) + ': ' + esc(cell.dataset.value || '') + '</span>'
          + '<span>日涨跌: ' + esc(cell.dataset.change || '') + '</span>'
          + '<span>当日成交额: ' + esc(cell.dataset.amount || '') + '</span>'
          + '<span>20日均额: ' + esc(cell.dataset.avgAmount || '') + '</span>';
        var left = Math.min(Math.max(8, e.clientX - rect.left + 12), rect.width - 172);
        var top = Math.max(8, e.clientY - rect.top - 82);
        tip.style.left = left + 'px';
        tip.style.top = top + 'px';
      });
      cell.addEventListener('mouseleave', function(){
        tip.hidden = true;
      });
    });
  }

  function renderSummary(items){
    if(!items.length) return '';
    return items.map(function(it){
      var cls = it.trend > 0 ? ' up' : (it.trend < 0 ? ' down' : '');
      return '<div class="mk-trend-chip' + cls + '"><span>' + esc(it.label) + '</span><b>' + esc(it.value) + '</b></div>';
    }).join('');
  }

  function renderFundPreview(inflow, outflow){
    function rows(items, cls){
      return items.slice(0, 3).map(function(it){
        return '<div class="mk-trend-rank-row ' + cls + '"><span>' + esc(it.name) + '</span><b>' + esc(fmtMoney(it.amount)) + '</b></div>';
      }).join('');
    }
    return '<div class="mk-trend-rank">'
      + '<div><strong>流入</strong>' + rows(inflow || [], 'up') + '</div>'
      + '<div><strong>流出</strong>' + rows(outflow || [], 'down') + '</div>'
      + '</div>';
  }

  function renderPointTooltip(p, value){
    var html = '<b>' + esc(p.date) + '</b>'
      + '<span>' + esc(metricLabel()) + ': ' + esc(formatValue(value)) + '</span>';
    if(state.metric !== 'activity'){
      html += '<span>成交活跃度: ' + esc(fmtActivity(p.activity)) + '</span>';
    }
    html += '<span>当日成交额: ' + esc(fmtAmountYuan(p.amount)) + '</span>'
      + '<span>20日均额: ' + esc(fmtAmountYuan(p.avg_amount_20)) + '</span>';
    return html;
  }

  function pointValue(p){
    if(state.metric === 'activity') return hasMetricValue(p.activity) ? metricNumber(p.activity) : null;
    return p.close || 0;
  }

  function formatValue(v){
    if(state.metric === 'activity') return fmtActivity(v);
    return fmtPct(v);
  }

  function metricLabel(){
    if(state.metric === 'activity') return '成交活跃度';
    return '累计涨跌';
  }

  function metricToneColor(v){
    if(state.metric === 'activity') return num(v) >= 1 ? '#2563eb' : '#64748b';
    return num(v) >= 0 ? '#dc2626' : '#16a34a';
  }

  function fmtActivity(v){
    if(!hasMetricValue(v)) return '—';
    return metricNumber(v).toFixed(2) + 'x';
  }

  function fmtAmountYuan(v){
    if(!hasMetricValue(v) || num(v) <= 0) return '—';
    return (num(v) / 100000000).toFixed(2) + '亿';
  }

  function formatVolume(v){
    var n = Math.abs(num(v));
    if(n >= 100000000) return (v / 100000000).toFixed(2) + '亿';
    if(n >= 10000) return (v / 10000).toFixed(2) + '万';
    return String(Math.round(v || 0));
  }

  function fmtIndexValue(v){
    var n = Number(v);
    if(!isFinite(n)) return '—';
    return n.toLocaleString('zh-CN', {
      minimumFractionDigits: n >= 1000 ? 0 : 2,
      maximumFractionDigits: 2
    });
  }

  function fmtMoney(v){
    var n = num(v);
    var sign = n > 0 ? '+' : (n < 0 ? '−' : '');
    return sign + Math.abs(n).toFixed(2) + '亿';
  }

  function fmtPct(v){
    var n = num(v);
    var sign = n > 0 ? '+' : '';
    return sign + n.toFixed(2) + '%';
  }

  function chip(label, value, trend){
    return {label: label, value: value, trend: num(trend)};
  }

  function sumAmounts(items, abs){
    var total = 0;
    (items || []).forEach(function(i){ total += abs ? Math.abs(num(i.amount)) : num(i.amount); });
    return total;
  }

  function delta(points, n){
    if(points.length < 2) return 0;
    var idx = Math.max(0, points.length - 1 - n);
    return points[points.length - 1].close - points[idx].close;
  }

  function volatility(points){
    if(points.length < 3) return 0;
    var diffs = [];
    for(var i = 1; i < points.length; i++) diffs.push(points[i].close - points[i-1].close);
    var avg = diffs.reduce(function(a,b){ return a+b; }, 0) / diffs.length;
    var variance = diffs.reduce(function(a,b){ return a + Math.pow(b - avg, 2); }, 0) / diffs.length;
    return Math.sqrt(variance);
  }

  function newestQuoteTime(quotes){
    var times = (quotes || []).map(function(q){ return q && q.updated_at; }).filter(Boolean).sort();
    return times.length ? times[times.length - 1] : '';
  }

  function shortDate(s){
    return String(s || '').slice(5) || s;
  }

  function round(v, digits){
    var m = Math.pow(10, digits || 2);
    return Math.round(num(v) * m) / m;
  }

  global.KBMarketTrends = { mount: mount };
})(window);
