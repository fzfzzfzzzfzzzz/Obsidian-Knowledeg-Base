(function(global){
  'use strict';

  var SIM_STATUS = {
    active:   { label:'模拟中', icon:'play-circle', cls:'active' },
    closed:   { label:'已结束', icon:'check-circle', cls:'closed' },
    archived: { label:'已归档', icon:'archive', cls:'archived' }
  };
  var MARKET_LABELS = {SH:'沪', SZ:'深', BJ:'京', HK:'港', US:'美'};
  var MARKET_COLORS = {SH:'#dc2626', SZ:'#f43f5e', BJ:'#ea580c', HK:'#0d9488', US:'#2563eb'};
  var PREFIXES = {
    SH: ['600','601','603','605','688','690','70','11','13','50','51','52','56','58'],
    SZ: ['000','001','002','003','300','301','159','184','128','123'],
    BJ: ['43','83','87','88','92','82']
  };

  function emptyHTML(msg){ return '<div class="empty">' + escapeHtml(msg) + '</div>'; }
  function setHTML(id, html){ var el = document.getElementById(id); if(el) el.innerHTML = html; }
  function refresh(){ if(global.refreshIcons) global.refreshIcons(); }
  function statusMeta(status){ return SIM_STATUS[status] || SIM_STATUS.active; }
  function fmtDate(s){ return s || '—'; }
  function todayInput(){ return new Date().toISOString().slice(0, 10); }

  function parseStoredTicker(stored){
    if(!stored) return {market:'', code:'', label:'', color:''};
    if(stored.indexOf(':') > 0){
      var parts = stored.split(':', 2);
      var market = parts[0].toUpperCase();
      return {market:market, code:parts[1], label:MARKET_LABELS[market] || market, color:MARKET_COLORS[market] || '#64748b'};
    }
    return {market:'', code:stored, label:'', color:''};
  }

  function validateTickerClient(market, code){
    if(!code) return null;
    var m = (market || '').toUpperCase();
    if(['SH','SZ','BJ','HK','US'].indexOf(m) < 0) return '未知市场:'+market;
    if(m === 'US'){
      if(!/^[A-Za-z]{1,5}(\.[A-Za-z]{1,2})?$/.test(code)) return '美股代码应为 1-5 位字母，可含一个点';
      return null;
    }
    if(!/^\d+$/.test(code)) return (MARKET_LABELS[m] || m) + '股代码必须为数字';
    if(m === 'HK') return (code.length >= 1 && code.length <= 5) ? null : '港股代码应为 1-5 位数字';
    if(code.length !== 6) return 'A股代码应为 6 位数字';
    var pfx = PREFIXES[m] || [];
    for(var i = 0; i < pfx.length; i++){ if(code.indexOf(pfx[i]) === 0) return null; }
    return (MARKET_LABELS[m] || m) + '股代码前缀不合法，常见:' + pfx.slice(0, 4).join('/') + '…';
  }

  function tickerTag(it){
    var tk = parseStoredTicker(it.ticker || '');
    if(!tk.code) return '';
    return '<span class="ev-cat-tag mk-ticker-tag" style="--ev:'+(tk.color || '#64748b')+'">'
      + (tk.label ? '<b>'+escapeHtml(tk.label)+'</b> · ' : '')
      + escapeHtml(tk.code)
      + '</span>';
  }

  function posTags(it, labels){
    labels = labels || {
      cost_price:'成本', entry_price:'建仓',
      shares:'股数', target_price:'目标', stop_price:'止损',
      exit_price:'结束'
    };
    var fields = ['cost_price','entry_price','shares','target_price','stop_price','exit_price'];
    var parts = [];
    fields.forEach(function(f){
      var val = (it[f] || '').trim();
      if(!val) return;
      var cls = f === 'target_price' ? ' up' : (f === 'stop_price' ? ' down' : '');
      parts.push('<span class="mk-pos-tag'+cls+'"><b>'+escapeHtml(labels[f] || f)+'</b> '+escapeHtml(val)+'</span>');
    });
    return parts.length ? '<div class="mk-pos-row">'+parts.join('')+'</div>' : '';
  }

  function statusBadge(status){
    var m = statusMeta(status);
    return '<span class="mp-status mp-status-'+m.cls+'"><i data-lucide="'+m.icon+'"></i>'+m.label+'</span>';
  }

  function sectorIcon(sector){
    if(global.taskCatIcon) return taskCatIcon(sector || '金融');
    return '<i data-lucide="layers"></i>';
  }
  function sectorColor(sector){
    if(global.taskCatColor) return taskCatColor(sector || '金融');
    return '#64748b';
  }

  function mount(){
    var simStore = new Map();

    async function loadHoldings(){
      try{
        var r = await fetch('/api/market/personal/holdings');
        var d = await r.json();
        var items = d.items || [];
        renderHoldingStats(items);
        if(!items.length){
          setHTML('mp-holdings-list', emptyHTML('还没有当前持仓。去自选股里填写成本价、股数、目标价或止损价后会出现在这里。'));
          return;
        }
        setHTML('mp-holdings-list', items.map(renderHoldingCard).join(''));
        refresh();
      }catch(e){
        setHTML('mp-holdings-list', emptyHTML('加载失败'));
      }
    }

    function renderHoldingStats(items){
      var withTarget = items.filter(function(it){ return (it.target_price || '').trim(); }).length;
      var withStop = items.filter(function(it){ return (it.stop_price || '').trim(); }).length;
      setHTML('mp-holding-stats',
        '<div class="mp-stat"><span>当前持仓</span><b>'+items.length+'</b></div>'
        + '<div class="mp-stat"><span>有目标价</span><b>'+withTarget+'</b></div>'
        + '<div class="mp-stat"><span>有止损价</span><b>'+withStop+'</b></div>'
      );
    }

    function renderHoldingCard(it){
      var c = sectorColor(it.sector);
      return '<article class="event-card mp-card mp-holding-card" style="--ev:'+c+'">'
        + '<div class="ev-card-header">'
          + '<span class="ev-cat-icon">'+sectorIcon(it.sector)+'</span>'
          + '<div class="ev-card-titles">'
            + '<a class="ev-card-title" href="/market/'+escapeHtml(it.id)+'">'+escapeHtml(it.title || '未命名持仓')+'</a>'
            + '<div class="ev-card-meta">'+tickerTag(it)
              + (it.sector ? '<span class="ev-cat-tag" style="--ev:'+c+'">'+escapeHtml(it.sector)+'</span>' : '')
            + '</div>'
          + '</div>'
        + '</div>'
        + (it.note ? '<div class="ev-note muted">'+escapeHtml(it.note)+'</div>' : '')
        + posTags(it, {cost_price:'成本', shares:'股数', target_price:'目标', stop_price:'止损'})
      + '</article>';
    }

    async function loadSimulations(){
      try{
        var r = await fetch('/api/market/simulations');
        var d = await r.json();
        var items = d.items || [];
        simStore.clear();
        items.forEach(function(it){ simStore.set(it.id, it); });
        renderSimulationStats(items);
        if(!items.length){
          setHTML('mp-sim-list', emptyHTML('还没有模拟盘记录。'));
          return;
        }
        setHTML('mp-sim-list', items.map(renderSimulationCard).join(''));
        refresh();
      }catch(e){
        setHTML('mp-sim-list', emptyHTML('加载失败'));
      }
    }

    function renderSimulationStats(items){
      var active = items.filter(function(it){ return it.status === 'active'; }).length;
      var closed = items.filter(function(it){ return it.status === 'closed'; }).length;
      setHTML('mp-sim-stats',
        '<div class="mp-stat"><span>全部模拟</span><b>'+items.length+'</b></div>'
        + '<div class="mp-stat"><span>模拟中</span><b>'+active+'</b></div>'
        + '<div class="mp-stat"><span>已结束</span><b>'+closed+'</b></div>'
      );
    }

    function renderSimulationCard(it){
      var c = sectorColor(it.sector);
      var body = it.body && it.body !== '（暂无补充）'
        ? '<div class="mj-note muted">'+escapeHtml(it.body)+'</div>'
        : '';
      return '<article class="event-card mp-card mp-sim-card" style="--ev:'+c+'">'
        + '<div class="mp-card-head">'
          + '<div class="ev-card-header">'
            + '<span class="ev-cat-icon">'+sectorIcon(it.sector)+'</span>'
            + '<div class="ev-card-titles">'
              + '<div class="ev-card-title">'+escapeHtml(it.title || '未命名模拟')+'</div>'
              + '<div class="ev-card-meta">'+tickerTag(it)
                + (it.sector ? '<span class="ev-cat-tag" style="--ev:'+c+'">'+escapeHtml(it.sector)+'</span>' : '')
                + '<span class="mj-chip"><i data-lucide="calendar-days"></i>'+escapeHtml(fmtDate(it.entry_date))+'</span>'
              + '</div>'
            + '</div>'
          + '</div>'
          + statusBadge(it.status)
        + '</div>'
        + posTags(it, {entry_price:'建仓', shares:'股数', target_price:'目标', stop_price:'止损', exit_price:'结束'})
        + (it.exit_date ? '<div class="mp-date muted">结束日期: '+escapeHtml(it.exit_date)+'</div>' : '')
        + (it.note ? '<div class="ev-note muted">'+escapeHtml(it.note)+'</div>' : '')
        + body
        + '<div class="mj-card-actions">'
          + '<button class="btn btn-sm btn-ghost" data-sim-action="edit" data-sim-id="'+escapeHtml(it.id)+'"><i data-lucide="edit-3"></i> 编辑</button>'
          + '<button class="btn btn-sm btn-danger" data-sim-action="delete" data-sim-id="'+escapeHtml(it.id)+'"><i data-lucide="trash-2"></i> 删除</button>'
        + '</div>'
      + '</article>';
    }

    function marketOptions(selected){
      var opts = [
        {v:'SH', label:'沪 · A股'},
        {v:'SZ', label:'深 · A股'},
        {v:'BJ', label:'京 · 北交所'},
        {v:'HK', label:'港 · 港股'},
        {v:'US', label:'美 · 美股'}
      ];
      return opts.map(function(o){
        return '<option value="'+o.v+'"'+(selected===o.v?' selected':'')+'>'+escapeHtml(o.label)+'</option>';
      }).join('');
    }

    function statusOptions(selected){
      return ['active','closed','archived'].map(function(s){
        return '<option value="'+s+'"'+(selected===s?' selected':'')+'>'+SIM_STATUS[s].label+'</option>';
      }).join('');
    }

    function openSimulationForm(opts){
      opts = opts || {};
      var isEdit = opts.mode === 'edit';
      var it = opts.item || {};
      var tk = parseStoredTicker(it.ticker || '');
      var market = it.market || tk.market || 'SH';
      var ticker = tk.code || '';
      var formHtml = '<div class="cal-form market-simulation-form">'
        + '<div class="cal-form-field"><label>标题 / 名称 <span class="required">*</span></label>'
        + '<input type="text" id="sim-title" value="'+escapeHtml(it.title||'')+'" maxlength="120" placeholder="如:芯片ETF 短线模拟"></div>'
        + '<div class="cal-form-row2">'
          + '<div class="cal-form-field"><label>市场</label><select id="sim-market">'+marketOptions(market)+'</select></div>'
          + '<div class="cal-form-field"><label>股票代码</label>'
          + '<input type="text" id="sim-ticker" value="'+escapeHtml(ticker)+'" maxlength="12" placeholder="如 600519 / AAPL / 00700">'
          + '<div class="mk-ticker-hint muted" id="sim-ticker-hint"></div></div>'
        + '</div>'
        + '<div class="cal-form-row2">'
          + '<div class="cal-form-field"><label>赛道 / 行业</label>'
          + '<input type="text" id="sim-sector" value="'+escapeHtml(it.sector||'金融')+'" maxlength="30" placeholder="金融 / 科技 / 半导体"></div>'
          + '<div class="cal-form-field"><label>状态</label><select id="sim-status">'+statusOptions(it.status || 'active')+'</select></div>'
        + '</div>'
        + '<div class="cal-form-field"><label>模拟仓位</label>'
        + '<div class="mk-pos-grid">'
          + '<div class="mk-pos-cell"><span class="mk-pos-lbl">建仓价</span><input type="text" id="sim-entry-price" value="'+escapeHtml(it.entry_price||'')+'" inputmode="decimal" placeholder="12.80"></div>'
          + '<div class="mk-pos-cell"><span class="mk-pos-lbl">股数</span><input type="text" id="sim-shares" value="'+escapeHtml(it.shares||'')+'" inputmode="numeric" placeholder="1000"></div>'
          + '<div class="mk-pos-cell"><span class="mk-pos-lbl">目标价</span><input type="text" id="sim-target" value="'+escapeHtml(it.target_price||'')+'" inputmode="decimal" placeholder="15.00"></div>'
          + '<div class="mk-pos-cell"><span class="mk-pos-lbl">止损价</span><input type="text" id="sim-stop" value="'+escapeHtml(it.stop_price||'')+'" inputmode="decimal" placeholder="11.80"></div>'
        + '</div></div>'
        + '<div class="cal-form-row2">'
          + '<div class="cal-form-field"><label>建仓日期</label><input type="date" id="sim-entry-date" value="'+escapeHtml(it.entry_date || todayInput())+'"></div>'
          + '<div class="cal-form-field"><label>结束日期</label><input type="date" id="sim-exit-date" value="'+escapeHtml(it.exit_date || '')+'"></div>'
        + '</div>'
        + '<div class="cal-form-field"><label>结束价格</label><input type="text" id="sim-exit-price" value="'+escapeHtml(it.exit_price||'')+'" inputmode="decimal" placeholder="卖出/结束价"></div>'
        + '<div class="cal-form-field"><label>备注</label><textarea id="sim-note" rows="3" maxlength="1000" placeholder="建仓理由、观察信号、风险点">'+escapeHtml(it.note||'')+'</textarea></div>'
        + '<div class="cal-form-field"><label>补充笔记</label><textarea id="sim-body" rows="3" maxlength="4000" placeholder="复盘、图表链接或后续观察">'+escapeHtml((it.body && it.body !== '（暂无补充）') ? it.body : '')+'</textarea></div>'
        + '<div class="cal-form-actions">'
        + (isEdit ? '<button class="btn btn-danger" id="sim-delete-in-form">删除</button>' : '')
        + '<button class="btn btn-ghost" id="sim-cancel">取消</button>'
        + '<button class="btn btn-primary" id="sim-save">'+(isEdit?'保存':'创建')+'</button></div>'
        + '</div>';

      var overlay = document.getElementById('modalOverlay');
      if(!overlay){ alert('modal 不可用'); return; }
      document.getElementById('modalTitle').textContent = isEdit ? '编辑模拟盘' : '新建模拟盘';
      document.getElementById('modalBody').innerHTML = formHtml;
      document.getElementById('modalActions').innerHTML = '';
      overlay.hidden = false;
      refresh();

      var marketEl = document.getElementById('sim-market');
      var tickerEl = document.getElementById('sim-ticker');
      var hintEl = document.getElementById('sim-ticker-hint');
      function checkTicker(){
        if(!hintEl) return;
        var code = tickerEl.value.trim();
        if(!code){ hintEl.textContent = ''; hintEl.className = 'mk-ticker-hint muted'; return; }
        var err = validateTickerClient(marketEl.value, code);
        if(err){ hintEl.textContent = '✗ ' + err; hintEl.className = 'mk-ticker-hint mk-ticker-err'; }
        else { hintEl.textContent = '✓ 格式正确'; hintEl.className = 'mk-ticker-hint mk-ticker-ok'; }
      }
      marketEl.onchange = checkTicker;
      tickerEl.oninput = checkTicker;
      checkTicker();

      document.getElementById('sim-cancel').onclick = function(){ overlay.hidden = true; };
      document.getElementById('sim-save').onclick = async function(){
        var payload = collectSimulationPayload();
        if(!payload.title){ alert('标题不能为空'); return; }
        if(payload.ticker){
          var clientErr = validateTickerClient(payload.market, payload.ticker);
          if(clientErr){ alert('代码格式错误:\n'+clientErr+'\n\n请检查市场和代码是否匹配。'); return; }
        }
        var btn = this;
        btn.disabled = true;
        btn.textContent = '保存中...';
        try{
          var res = isEdit
            ? await fetch('/api/market/simulations/'+encodeURIComponent(it.id), {method:'PATCH', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)})
            : await fetch('/api/market/simulations', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
          var data = await res.json().catch(function(){ return {}; });
          if(!res.ok){
            alert('保存失败:'+(data.detail||res.status));
            btn.disabled = false;
            btn.textContent = isEdit ? '保存' : '创建';
            return;
          }
          overlay.hidden = true;
          toast(isEdit ? '已保存模拟盘' : '已创建模拟盘', 'success');
          loadSimulations();
        }catch(e){
          alert('网络错误:'+e.message);
          btn.disabled = false;
          btn.textContent = isEdit ? '保存' : '创建';
        }
      };

      if(isEdit){
        var del = document.getElementById('sim-delete-in-form');
        if(del) del.onclick = function(){ deleteSimulation(it); };
      }
      setTimeout(function(){ var el = document.getElementById('sim-title'); if(el) el.focus(); }, 50);
    }

    function collectSimulationPayload(){
      return {
        title: document.getElementById('sim-title').value.trim(),
        market: document.getElementById('sim-market').value,
        ticker: document.getElementById('sim-ticker').value.trim(),
        sector: document.getElementById('sim-sector').value.trim(),
        entry_price: document.getElementById('sim-entry-price').value.trim(),
        shares: document.getElementById('sim-shares').value.trim(),
        entry_date: document.getElementById('sim-entry-date').value.trim(),
        target_price: document.getElementById('sim-target').value.trim(),
        stop_price: document.getElementById('sim-stop').value.trim(),
        status: document.getElementById('sim-status').value,
        exit_price: document.getElementById('sim-exit-price').value.trim(),
        exit_date: document.getElementById('sim-exit-date').value.trim(),
        note: document.getElementById('sim-note').value.trim(),
        body: document.getElementById('sim-body').value.trim()
      };
    }

    async function deleteSimulation(item){
      if(!item) return;
      if(!await confirmModal('确定删除「'+(item.title || '模拟盘')+'」吗？', {title:'删除模拟盘', confirmText:'删除', danger:true})) return;
      try{
        var res = await fetch('/api/market/simulations/'+encodeURIComponent(item.id), {method:'DELETE'});
        if(res.ok){
          var overlay = document.getElementById('modalOverlay');
          if(overlay) overlay.hidden = true;
          toast('已删除模拟盘', 'success');
          loadSimulations();
        } else {
          var d = await res.json().catch(function(){ return {}; });
          toast('删除失败:'+(d.detail||res.status), 'error');
        }
      }catch(e){
        toast('网络错误:'+e.message, 'error');
      }
    }

    document.addEventListener('click', function(e){
      if(e.target.closest('#mp-add-sim')){ openSimulationForm({mode:'create'}); return; }
      var btn = e.target.closest('[data-sim-action]');
      if(!btn) return;
      var item = simStore.get(btn.dataset.simId);
      if(!item){ toast('记录已变化，正在刷新', 'warning'); loadSimulations(); return; }
      if(btn.dataset.simAction === 'edit') openSimulationForm({mode:'edit', item:item});
      else if(btn.dataset.simAction === 'delete') deleteSimulation(item);
    });

    loadHoldings();
    loadSimulations();
    return { loadHoldings: loadHoldings, loadSimulations: loadSimulations, openSimulationForm: openSimulationForm };
  }

  global.KBMarketPersonal = { mount: mount };
})(window);
