/* ============================================================
   CMS 核心工具层：API / Toast / 确认弹窗 / Popover / Loading /
   骨架屏 / 主题 / G2 图表封装
   ============================================================ */
window.CMS = (function(){
  const esc = (s) => String(s??'').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const qs = (params) => Object.entries(params||{}).filter(([k,v])=>v!==''&&v!=null).map(([k,v])=>encodeURIComponent(k)+'='+encodeURIComponent(v)).join('&');

  /* ---------- 顶部进度条（loadingbar：请求/跳转时推进，出错变红） ---------- */
  let lbTimer=null, lbProg=0, lbCount=0;
  function lbEl(){
    let el=document.getElementById('cms-loadingbar');
    if(!el){ el=document.createElement('div'); el.id='cms-loadingbar'; el.innerHTML='<div class="lb-bar"></div>'; document.body.appendChild(el); }
    return el;
  }
  function barStart(){
    lbCount++;
    const el=lbEl(); el.classList.remove('done','error'); el.classList.add('run');
    const bar=el.querySelector('.lb-bar');
    lbProg=Math.max(lbProg*0.6, 10 + Math.random()*10);
    bar.style.width=lbProg+'%';
    if(!lbTimer) lbTimer=setInterval(()=>{
      lbProg=Math.min(lbProg+Math.random()*6, 90);
      bar.style.width=lbProg+'%';
    }, 280);
  }
  function barEnd(ok=true){
    lbCount=Math.max(0, lbCount-1);
    if(lbCount>0) return;
    if(lbTimer){ clearInterval(lbTimer); lbTimer=null; }
    const el=lbEl(); el.querySelector('.lb-bar').style.width='100%';
    el.classList.add(ok?'done':'error');
    setTimeout(()=>{ el.classList.remove('run','done','error'); el.querySelector('.lb-bar').style.width='0%'; lbProg=0; }, ok?400:700);
  }

  /* ---------- API ---------- */
  const api = async (url, options={}) => {
    const token = localStorage.getItem('cms_token') || '';
    barStart();
    let res;
    try {
      res = await fetch(url, {
        ...options,
        headers: {'Content-Type':'application/json', 'Authorization':'Bearer '+token, ...(options.headers||{})},
      });
    } catch(e) {
      barEnd(false);
      return {code:50001, msg:'网络连接失败'};
    }
    /* 侧栏「响应耗时」显示本次请求自己的耗时（X-Response-Time 响应头），
       不是 PerfStats 滑动窗口平均值 —— 两个口径不同，不可混用 */
    try {
      const rt = res.headers.get('X-Response-Time');
      const ms = parseFloat(rt);
      if (isFinite(ms)) {
        const el = document.getElementById('nav-resp-time');
        if (el) {
          el.textContent = (ms >= 100 ? ms.toFixed(0) : ms.toFixed(1)) + ' ms';
          el.title = '本次请求的服务端响应耗时（不含网络传输）';
        }
      }
    } catch (e) {}
    let data;
    const raw = await res.text().catch(()=>'');
    try { data = JSON.parse(raw); }
    catch(e) {
      const snippet = String(raw).replace(/<[^>]+>/g,'').trim().slice(0,120);
      barEnd(false);
      return {code:50001, msg: res.ok ? (snippet||'服务返回了无法识别的内容') : `请求失败（HTTP ${res.status}）${snippet?'：'+snippet:''}`};
    }
    if (data.code === 10001) { barEnd(false); logout(true); throw new Error('登录已失效'); }
    barEnd(data.code === 0);
    return data;
  };
  const post = (url, body) => api(url, {method:'POST', body: JSON.stringify(body||{})});

  /* ---------- Toast ---------- */
  const TOAST_ICON = {success:'bi-check-circle-fill', error:'bi-x-circle-fill', warning:'bi-exclamation-triangle-fill', info:'bi-info-circle-fill'};
  /* 需求（2026-11-24）：弹窗是原生 <dialog>（top layer），普通 z-index 无法盖过 —— toast 容器用
     Popover API 进入 top layer，并且每次弹 toast 时重新 showPopover 置顶（top layer 后进者在上） */
  const raiseToasts=()=>{
    try{
      const box=document.getElementById('toasts');
      if(box && 'showPopover' in box){
        if(box.matches(':popover-open')) box.hidePopover();
        box.showPopover();
      }
    }catch(e){}
  };
  try{
    const ts=document.getElementById('toasts');
    if(ts && 'showPopover' in ts && !ts.matches(':popover-open')) ts.showPopover();
  }catch(e){}
  const toast = (msg, type='success') => {
    const t = TOAST_ICON[type]||TOAST_ICON.success;
    const el = document.createElement('div');
    el.className = `toast align-items-center ${type==='error'?'error':type}`;
    el.innerHTML = `<div class="toast-body"><i class="bi ${t}"></i><span>${esc(String(msg))}</span></div>`;
    const box = document.getElementById('toasts');
    if (!box) return;
    raiseToasts();
    box.appendChild(el);
    const inst = new bootstrap.Toast(el, {delay:2600});
    el.addEventListener('hidden.bs.toast', ()=>{ el.remove(); inst.dispose(); });
    inst.show();
  };

  /* 需求（2026-11-24）：统一去掉浏览器默认必填验证气泡（校验统一走自定义表单逻辑 + toast） */
  document.addEventListener('invalid',(e)=>{ e.preventDefault(); }, true);

  /* ---------- 全局 Loading ---------- */
  let loadingCount = 0;
  function showLoading(text){
    loadingCount++;
    const el = document.getElementById('global-loading');
    if (el){ el.classList.add('show'); }
  }
  function hideLoading(force){
    loadingCount = Math.max(0, loadingCount-1);
    if (force) loadingCount = 0;
    if (loadingCount===0){ setTimeout(function(){ const el=document.getElementById('global-loading'); if(el) el.classList.remove('show'); }, 500); }
  }
  /* 按钮 loading */
  function btnLoading(btn, on){
    if(!btn) return;
    if(on) btn.classList.add('is-loading'); else btn.classList.remove('is-loading');
  }

  /* ---------- 确认弹窗（Promise） ---------- */
  const CONF_ICON = {danger:'bi-exclamation-triangle', warning:'bi-exclamation-circle', info:'bi-info-circle', question:'bi-question-lg'};
  let confirmResolve = null;
  function confirm(opts){
    if(typeof opts==='string') opts = {text:opts};
    opts = opts||{};
    const type = opts.type||'question';
    const modalEl = document.getElementById('confirm-modal');
    document.getElementById('confirm-icon').className = 'confirm-icon '+type;
    document.getElementById('confirm-icon').innerHTML = `<i class="bi ${CONF_ICON[type]||CONF_ICON.question}"></i>`;
    document.getElementById('confirm-title').textContent = opts.title||'请确认';
    const textEl = document.getElementById('confirm-text');
    textEl.innerHTML = opts.html ? opts.html : esc(opts.text||'确定要执行此操作吗？');
    const okBtn = document.getElementById('confirm-ok');
    // Ant Design 规范：危险操作红色按钮，其余一律蓝色主按钮；按钮不带图标
    okBtn.className = 'btn btn-loading '+(type==='danger'?'btn-solid theme-danger':'btn-solid theme-primary');
    okBtn.textContent = opts.okText||'确定';
    const cancelBtn = document.getElementById('confirm-cancel');
    cancelBtn.style.display = opts.hideCancel ? 'none' : '';
    cancelBtn.textContent = opts.cancelText||'取消';
    return new Promise(resolve=>{
      confirmResolve = resolve;
      const inst = bootstrap.Dialog.getOrCreateInstance(modalEl);
      // 清理旧监听
      const onOk = async ()=>{
        btnLoading(okBtn,true);
        let result = true;
        if(typeof opts.onConfirm==='function'){
          try{ result = await opts.onConfirm(); }catch(e){ result=false; toast(e.message||'操作失败','error'); }
        }
        btnLoading(okBtn,false);
        inst.hide();
        finish(!!result);
      };
      const onCancel = ()=>{ inst.hide(); finish(false); };
      const onHidden = ()=>{ if(confirmResolve!==null) finish(false); };
      function finish(v){ if(confirmResolve){ const r=confirmResolve; confirmResolve=null; r(v); }
        okBtn.onclick=null; cancelBtn.onclick=null; modalEl.removeEventListener('hidden.bs.dialog',onHidden); }
      okBtn.onclick = onOk;
      cancelBtn.onclick = onCancel;
      modalEl.addEventListener('hidden.bs.dialog', onHidden, {once:true});
      inst.show();
    });
  }

  /* ---------- Popover ---------- */
  function initPopovers(){
    document.querySelectorAll('[data-bs-toggle="popover"]').forEach(el=>{
      if(!bootstrap.Popover) return;
      if(el._bsPopover) return;
      el._bsPopover = new bootstrap.Popover(el,{trigger:'hover focus',placement:el.dataset.bsPlacement||'bottom'});
    });
  }

  /* ---------- 骨架屏 ---------- */
  function skeletonStats(n=8){
    return `<div class="stats-grid">${Array.from({length:n},()=>`<div class="sk-stat skeleton"></div>`).join('')}</div>`;
  }
  function skeletonTable(rows=8, cols=6){
    return `<div class="card-box">
      <div class="crud-toolbar"><div class="sk-line skeleton w40" style="width:150px"></div><div class="sk-line skeleton" style="width:90px"></div><div class="sk-line skeleton" style="width:90px"></div></div>
      ${Array.from({length:rows},()=>`<div class="sk-row skeleton"></div>`).join('')}</div>`;
  }
  function skeletonCharts(){
    return `<div class="chart-grid"><div class="chart-box"><div class="sk-line skeleton w40"></div><div class="sk-chart skeleton" style="margin-top:16px"></div></div>
      <div class="chart-box"><div class="sk-line skeleton w60"></div><div class="sk-chart skeleton" style="margin-top:16px"></div></div></div>`;
  }

  /* ---------- 统一表格分页（pyui-pager：统计 + 每页条数 + 页码 + 跳转） ---------- */
  function renderPager(el, opts){
    if(!el) return;
    const {page=1, size=15, total=0, onGo, onSize} = opts||{};
    const pages = Math.max(1, Math.ceil(total/size));
    const cur = Math.min(Math.max(1,page), pages);
    const from = total===0 ? 0 : (cur-1)*size+1;
    const to = Math.min(total, cur*size);
    /* 页码窗口：1 … (cur-2..cur+2) … last，layui 风格 */
    const nums=[];
    const push=(n,cls,label)=>nums.push(`<span class="${cls}" data-go="${n}">${label||n}</span>`);
    if(pages<=8){ for(let i=1;i<=pages;i++) push(i, i===cur?'pp-num active':'pp-num'); }
    else{
      push(1, cur===1?'pp-num active':'pp-num');
      const s=Math.max(2,cur-2), e=Math.min(pages-1,cur+2);
      if(s>2) nums.push('<span class="pp-dots">…</span>');
      for(let i=s;i<=e;i++) push(i, i===cur?'pp-num active':'pp-num');
      if(e<pages-1) nums.push('<span class="pp-dots">…</span>');
      push(pages, cur===pages?'pp-num active':'pp-num');
    }
    el.innerHTML=`<div class="pyui-pager">
      <div class="pp-info">显示第 ${from} 到 ${to} 条记录，总共 ${total} 条记录
        <span class="pp-size">每页显示 <select data-pp-size>${sizeOptions(size)}</select> 条记录</span></div>
      <div class="pp-pages">
        <span class="pp-btn ${cur<=1?'disabled':''}" data-go="${cur-1}">上一页</span>
        ${nums.join('')}
        <span class="pp-btn ${cur>=pages?'disabled':''}" data-go="${cur+1}">下一页</span>
        <span class="pp-jump"><input type="text" data-pp-jump value="${cur}" aria-label="跳转页码"><button type="button" class="pp-go" data-pp-go>跳转</button></span>
      </div></div>`;
    el.querySelectorAll('[data-go]').forEach(b=>b.onclick=()=>{
      const p=+b.dataset.go;
      if(b.classList.contains('disabled')||p<1||p>pages||p===cur) return;
      onGo && onGo(p);
    });
    const sel=el.querySelector('[data-pp-size]');
    if(sel) sel.onchange=()=>{ onSize && onSize(+sel.value); };
    const jumpInput=el.querySelector('[data-pp-jump]'), jumpBtn=el.querySelector('[data-pp-go]');
    const doJump=()=>{ const p=parseInt(jumpInput.value,10); if(!p||p<1||p>pages){ jumpInput.value=cur; return; } onGo && onGo(p); };
    if(jumpBtn) jumpBtn.onclick=doJump;
    if(jumpInput) jumpInput.onkeydown=(e)=>{ if(e.key==='Enter'){ e.preventDefault(); doJump(); } };
  }
  function sizeOptions(size){
    return [10,15,20,30,50,100].map(n=>`<option value="${n}" ${n===size?'selected':''}>${n}</option>`).join('');
  }
  function applyTheme(t){
    t = t || localStorage.getItem('cms_theme') || 'light';
    document.body.className = 'theme-'+t;
    const icon = document.querySelector('#theme-toggle i');
    if(icon) icon.className = t==='light'?'bi bi-moon-stars':'bi bi-sun';
  }
  function toggleTheme(){
    const t = document.body.classList.contains('theme-dark') ? 'light' : 'dark';
    localStorage.setItem('cms_theme',t);
    applyTheme(t);
    // 通知 G2 图表重绘以适配主题
    document.dispatchEvent(new CustomEvent('cms:themechange',{detail:{theme:t}}));
    return t;
  }

  /* ---------- 退出 ---------- */
  const logout = (expired=false) => {
    localStorage.removeItem('cms_token');
    const app=document.getElementById('app'), login=document.getElementById('login-page');
    if(app) app.style.display='none';
    if(login) login.style.display='flex';
    location.hash='login';
    if (expired) setTimeout(()=>toast('登录已失效，请重新登录','warning'),100);
  };

  /* ---------- G2 图表封装 ---------- */
  /* 记录容器引用：窗口缩放时按容器实际宽度重设画布，避免旧 canvas 宽度撑开页面 */
  const charts = [];
  let _chartResizeTimer = null;
  function resizeCharts(){
    charts.forEach(entry=>{
      const chart = entry.chart || entry;
      const el = entry.el;
      if(!chart || !el || typeof chart.changeSize!=='function') return;
      const w = Math.floor(el.clientWidth || el.getBoundingClientRect().width || 0);
      if(w <= 0) return;                       // 隐藏容器跳过，避免算出 0 宽画布
      try{ chart.changeSize(w, entry.height || 250); }catch(e){}
    });
  }
  window.addEventListener('resize',()=>{
    clearTimeout(_chartResizeTimer);
    _chartResizeTimer = setTimeout(resizeCharts, 120);
  });
  /* AntV 数据可视化色板（Ant Design 规范） */
  const ANT_PALETTE = ['#5B8FF9','#5AD8A6','#5D7092','#F6BD16','#E8684A','#6DC8EC','#9270CA','#FF9D4D'];
  function chartTheme(){
    const dark = document.body.classList.contains('theme-dark');
    // 对齐 Ant Design 中性色 token
    return {
      text:dark?'rgba(255,255,255,.65)':'rgba(0,0,0,.65)',
      axisLine:dark?'#424242':'#d9d9d9',
      grid:dark?'rgba(253,253,253,.12)':'rgba(5,5,5,.06)',
      tooltipBg:dark?'#1f1f1f':'#ffffff',
      primary:dark?'#4096ff':'#1677ff',
    };
  }
  function disposeCharts(){ charts.splice(0).forEach(x=>{ try{(x.chart||x).destroy();}catch(e){} }); }
  /* 面积趋势图 */
  function areaChart(container, data, color){
    if(!window.G2) return;
    const th=chartTheme();
    const chart = new G2.Chart({container, autoFit:true, height:250, padding:[16,20,40,44],
      appendPadding:0});
    chart.data(data);
    chart.scale('value',{nice:true});
    chart.axis('date',{line:{style:{stroke:th.axisLine}},tickLine:null,label:{style:{fill:th.text,fontSize:11}}});
    chart.axis('value',{line:null,tickLine:null,grid:{line:{style:{stroke:th.grid,lineDash:[3,3]}}},label:{style:{fill:th.text,fontSize:11}}});
    const c = color || th.primary;
    chart.tooltip({showCrosshairs:true, crosshairs:{type:'x',line:{style:{stroke:c,lineDash:[4,4]}}},
      domStyles:{'g2-tooltip':{background:th.tooltipBg,color:th.text,boxShadow:'0 6px 16px -8px rgba(0,0,0,.16),0 9px 28px 0 rgba(0,0,0,.08)',borderRadius:'8px'}}});
    chart.area().position('date*value').color(c).style({fillOpacity:.15}).animate({appear:{animation:'fadeIn',duration:700}});
    chart.line().position('date*value').color(c).size(2.5).shape('smooth').animate({appear:{animation:'waveIn',duration:800}});
    chart.point().position('date*value').color(c).size(3).shape('circle').style({stroke:th.tooltipBg,lineWidth:2});
    chart.render(); charts.push({chart, el:(container && container.nodeType ? container : document.getElementById(container)), height:250});
  }
  /* 环形分布图 */
  function pieChart(container, data){
    if(!window.G2) return;
    const th=chartTheme();
    const chart = new G2.Chart({container, autoFit:true, height:250, padding:[10,10,10,10]});
    chart.data(data);
    chart.coordinate('theta',{radius:.82, innerRadius:.6});
    chart.tooltip({domStyles:{'g2-tooltip':{background:th.tooltipBg,color:th.text,boxShadow:'0 6px 16px -8px rgba(0,0,0,.16),0 9px 28px 0 rgba(0,0,0,.08)',borderRadius:'8px'}}});
    chart.legend({position:'right',itemName:{style:{fill:th.text,fontSize:12}},marker:{symbol:'circle'}});
    chart.interval().position('value').color('type',ANT_PALETTE)
      .adjust('stack').style({lineWidth:2,stroke:th.tooltipBg})
      .label('type',{offset:-14,style:{fill:th.tooltipBg,fontSize:11,fontWeight:600}})
      .animate({appear:{animation:'waveIn',duration:800}});
    chart.render(); charts.push({chart, el:(container && container.nodeType ? container : document.getElementById(container)), height:250});
  }
  /* 柱状图 */
  function columnChart(container, data, color){
    if(!window.G2) return;
    const th=chartTheme();
    const chart = new G2.Chart({container, autoFit:true, height:250, padding:[16,20,40,44]});
    chart.data(data);
    chart.scale('value',{nice:true});
    chart.axis('name',{line:{style:{stroke:th.axisLine}},tickLine:null,label:{style:{fill:th.text,fontSize:11}}});
    chart.axis('value',{line:null,tickLine:null,grid:{line:{style:{stroke:th.grid,lineDash:[3,3]}}},label:{style:{fill:th.text,fontSize:11}}});
    chart.tooltip({domStyles:{'g2-tooltip':{background:th.tooltipBg,color:th.text,boxShadow:'0 6px 16px -8px rgba(0,0,0,.16),0 9px 28px 0 rgba(0,0,0,.08)',borderRadius:'8px'}}});
    chart.interval().position('name*value').color(color||th.primary)
      .style({radius:[4,4,0,0]})
      .animate({appear:{animation:'growInY',duration:700}});
    chart.render(); charts.push({chart, el:(container && container.nodeType ? container : document.getElementById(container)), height:250});
  }


  /* 管理员密码规则（正则 + 文案可配置），带缓存 */
  let _pwdRule = null;
  const PWD_RULE_DEFAULT = {
    regex: "^(?=.{8,50}$)(?:(?=.*[0-9])(?=.*[A-Za-z])|(?=.*[0-9])(?=.*[^A-Za-z0-9\\s])|(?=.*[A-Za-z])(?=.*[^A-Za-z0-9\\s]))\\S+$",
    tip: "密码必须由数字、字母、特殊字符中的至少两类组成，长度 8-50 位，不能包含空格"
  };
  const getPasswordRule = async () => {
    if (_pwdRule) return _pwdRule;
    try {
      const r = await api('/api/admin/password-rule');
      if (r && r.code === 0 && r.data && r.data.regex) _pwdRule = r.data;
    } catch (e) {}
    _pwdRule = _pwdRule || PWD_RULE_DEFAULT;
    return _pwdRule;
  };
  const clearPasswordRule = () => { _pwdRule = null; };
  const checkPassword = (pwd, rule) => {
    try { return new RegExp(rule.regex).test(pwd || ''); } catch (e) { return false; }
  };
  return {api, post, toast, confirm, esc, qs, showLoading, hideLoading, btnLoading, barStart, barEnd,
    initPopovers, skeletonStats, skeletonTable, skeletonCharts, applyTheme, toggleTheme,
    logout, disposeCharts, chartTheme, areaChart, pieChart, columnChart, renderPager,
    getPasswordRule, clearPasswordRule, checkPassword};
})();
