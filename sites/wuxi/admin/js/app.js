/* 后台主程序：菜单 / 多Tab / 仪表盘(G2图表) / 功能页 / 退出确认 / 动画 */
(function(){
  const C = window.CMS;
  const {api, post, toast, confirm, esc, logout, qs, applyTheme, toggleTheme,
    showLoading, hideLoading, btnLoading, skeletonStats, skeletonTable, skeletonCharts, disposeCharts,
    areaChart, pieChart, columnChart, getPasswordRule, clearPasswordRule, checkPassword} = C;
  const tabs=[]; let activeTab='dashboard'; let MENU=[]; let MENU_MAP={}; let BRAND={};
  /* 浏览器标题：${站点名称} - ${当前页面名称} - ${后台名称} */
  const ADMIN_NAME='AI 轻量化管理后台';
  let SITE_NAME='';
  function setTitle(pageName){
    document.title=[SITE_NAME,pageName||'',ADMIN_NAME].filter(Boolean).join(' - ');
  }
  /* 站点名称经公开接口 /api/health 下发；登录前后均可获取，只取一次 */
  async function loadSiteName(){
    if(SITE_NAME) return;
    try{
      const h=await api('/api/health');
      if(h && h.name) SITE_NAME=h.name;
      if(h && h.brand) BRAND=h.brand;
    }catch(e){}
  }

  const SPECIAL = new Set([
    'dashboard','station-generate','station-setting','order-pay-setting',
    'setting-basic','setting-upload','setting-sms','setting-email','tool-seo',
    'setting-security','setting-switch','dev-theme','dev-plugin','dev-content-model','dev-health','content-recycle'
  ]);

  function buildMenu(data){
    MENU=data; MENU_MAP={};
    data.forEach(g=>g.items.forEach(m=>MENU_MAP[m.key]={...m,group:g.name}));
  }
  function renderMenu(filter=''){
    const f=filter.trim().toLowerCase();
    const box=document.getElementById('cms-menu');
    let html='';
    MENU.forEach(g=>{
      const items=g.items.filter(m=>!f||m.name.toLowerCase().includes(f)||m.key.includes(f));
      if(!items.length)return;
      html+=`<div class="nav-group">${esc(g.name)}</div>`;
      items.forEach(m=>html+=`<div class="nav-item" data-key="${m.key}" data-name="${esc(m.name)}" onclick="App.open('${m.key}')" tabindex="0"><i class="bi ${m.icon}"></i><span>${esc(m.name)}</span></div>`);
    });
    box.innerHTML=html||'<div style="padding:24px 12px;color:var(--side-text-2);font-size:13px;text-align:center"><i class="bi bi-search" style="display:block;font-size:24px;margin-bottom:8px"></i>无匹配菜单</div>';
    highlight(activeTab);
  }
  function highlight(key){ document.querySelectorAll('.nav-item').forEach(el=>el.classList.toggle('active',el.dataset.key===key)); }
  function addTab(key,name){ if(!tabs.find(t=>t.key===key))tabs.push({key,name}); activeTab=key; renderTabs(); highlight(key); }
  function renderTabs(){
    document.getElementById('cms-tabs').innerHTML=tabs.map(t=>
      `<div class="tab ${t.key===activeTab?'active':''}" data-key="${t.key}" onclick="App.open('${t.key}')">${esc(t.name)}<span class="close" onclick="event.stopPropagation();App.closeTab('${t.key}')"><i class="bi bi-x"></i></span></div>`
    ).join('');
    // 右键菜单：关闭其他 / 关闭全部
    document.querySelectorAll('#cms-tabs .tab').forEach(el=>{
      el.oncontextmenu=(e)=>{
        e.preventDefault();
        tabCtxMenu(e.clientX, e.clientY, el.dataset.key);
      };
    });
  }
  /* 标签右键菜单（浮动层） */
  function tabCtxMenu(x, y, key){
    let m=document.getElementById('tab-ctx');
    if(m) m.remove();
    m=document.createElement('div');
    m.id='tab-ctx'; m.className='tab-ctx-menu';
    m.innerHTML=`
      <div class="ctx-item" data-act="close"><i class="bi bi-x"></i> 关闭标签</div>
      <div class="ctx-item" data-act="others"><i class="bi bi-x-square"></i> 关闭其他</div>
      <div class="ctx-item" data-act="all"><i class="bi bi-x-octagon"></i> 关闭全部</div>`;
    document.body.appendChild(m);
    const r=m.getBoundingClientRect();
    m.style.left=Math.min(x, window.innerWidth-r.width-8)+'px';
    m.style.top=Math.min(y, window.innerHeight-r.height-8)+'px';
    m.querySelectorAll('.ctx-item').forEach(it=>{
      it.onclick=()=>{
        const act=it.dataset.act;
        if(act==='close') closeTab(key);
        if(act==='others'){ tabs.filter(t=>t.key!==key).forEach(t=>{ const i=tabs.findIndex(x2=>x2.key===t.key); tabs.splice(i,1); }); if(activeTab!==key) open(key); else renderTabs(); }
        if(act==='all'){ openDashboard(); }
        m.remove();
      };
    });
    setTimeout(()=>document.addEventListener('click', ()=>m&&m.remove(), {once:true}), 0);
  }
  function closeTab(key){
    const i=tabs.findIndex(t=>t.key===key);if(i<0)return;tabs.splice(i,1);
    if(activeTab===key){const next=tabs[Math.max(0,i-1)];if(next)open(next.key);else openDashboard();}
    else renderTabs();
  }
  /* 需求：标签全部关闭后回到仪表盘（不允许出现无标签的空白页） */
  function openDashboard(){
    tabs.length=0; disposeCharts();
    document.getElementById('content').innerHTML='';
    renderTabs(); location.hash='dashboard';
    open('dashboard');
  }

  async function open(key){
    if(key==='profile') return openProfile();
    const item=MENU_MAP[key]; if(!item)return;
    setTitle(item.name);
    location.hash=key; addTab(key,item.name);
    disposeCharts();
    const el=document.getElementById('content');
    /* 核心原则（2026-11-24）：App.open 只做全局兜底骨架；谁自带专属骨架，谁主动声明跳过兜底骨架
       （模块在导出对象上置 OWN_SKELETON:true 即视为声明，如 Crud.OWN_SKELETON） */
    const ownSkeleton = key!=='dashboard' && !SPECIAL.has(key) && window.Crud && Crud.OWN_SKELETON;
    if(!ownSkeleton){
      el.innerHTML=skeletonStats() + `<div class="card-box"><div class="sk-line skeleton w40"></div><div class="sk-line skeleton w80"></div><div class="sk-line skeleton w60"></div></div>`;
    }
    try{
      if(key==='dashboard')return renderDashboard(el);
      if(SPECIAL.has(key))return renderSpecial(key,el,item.name);
      window.Crud.open(key,item.name);
    }catch(e){el.innerHTML=`<div class="card-box fg-danger">加载失败：${esc(e.message||e)}</div>`;}
  }

  /* 响应耗时条：与 /api/health 同源（后端 PerfStats 滑动窗口） */
  function perfStrip(p){
    if(!p || !p.count) return '';
    const fmt = v => (v==null? '-' : (v>=100 ? v.toFixed(0) : v.toFixed(1)));
    const values=[fmt(p.avg_ms),fmt(p.p50_ms),fmt(p.p95_ms),fmt(p.p99_ms),fmt(p.max_ms),String(p.count)];
    const labels=['平均响应','P50','P95','P99','最慢','样本数'];
    return `<div class="perf-strip">${values.map((v,i)=>
      `<div class="perf-item"><span class="perf-label">${labels[i]}</span><strong class="perf-value">${esc(v)}${i<5?'<small>ms</small>':''}</strong></div>`).join('')}</div>`;
  }

  /* ============ 仪表盘 ============ */
  async function renderDashboard(el){
    const r=await api('/api/admin/dashboard'); const d=r.data||{}; const s=d.stats||{};
    const badge=document.getElementById('site-badge');
    if(badge && d.site) badge.textContent = d.site.short_name || d.site.name || '当前站点';
    const cards=[
      ['内容总数',s.content,'bi-file-earmark-text','c1'],['已发布',s.publish,'bi-check-circle','c2'],
      ['栏目分类',s.category,'bi-folder','c3'],['留言',s.message,'bi-envelope','c4'],
      ['素材',s.media,'bi-images','c5'],['会员',s.member,'bi-people','c6'],
      // ['订单',s.order,'bi-cart-check','c4'],['评论',s.comment,'bi-chat-dots','c2'],
    ];
    const ms=Object.entries(d.model_stats||{});
    el.innerHTML=`
      <div class="stats-grid">${cards.map(c=>`<div class="stat-card ${c[3]}"><i class="bi ${c[2]} ic"></i><div class="num" data-num="${c[1]??0}">0</div><div class="label">${c[0]}</div></div>`).join('')}</div>
      ${perfStrip(d.perf)}
      <div class="chart-grid">
        <div class="chart-box"><div class="chart-title"><i class="bi bi-activity"></i> 内容发布趋势</div><div class="chart-sub">最近 7 天新增内容统计</div><div class="chart-canvas" id="chart-trend"></div></div>
        <div class="chart-box"><div class="chart-title"><i class="bi bi-pie-chart"></i> 内容模型分布</div><div class="chart-sub">各类型内容占比</div><div class="chart-canvas" id="chart-pie"></div></div>
      </div>
      <div class="dash-grid">
        <div class="card-box"><h5><i class="bi bi-bar-chart"></i> 访问统计</h5>
          <div class="chart-canvas" id="chart-access"></div>
        </div>
        <div class="card-box"><h5><i class="bi bi-clock-history"></i> 最近内容</h5>
          <div class="table-responsive"><table class="table table-sm table-hover"><thead><tr><th>标题</th><th>时间</th></tr></thead><tbody>
          ${(d.recent||[]).map(x=>`<tr><td>${esc(x.title)}</td><td class="text-nowrap">${esc(x.created_at)}</td></tr>`).join('')||'<tr><td colspan="2" class="list-empty">暂无内容</td></tr>'}
          </tbody></table></div>
        </div>
      </div>`;
    countUp();
    renderCharts(d);
    const btn=document.getElementById('dash-refresh');
    if(btn) btn.onclick=()=>{btnLoading(btn,true);open('dashboard').finally(()=>btnLoading(btn,false));};
  }

  function countUp(){
    document.querySelectorAll('.num[data-num]').forEach(el=>{
      const target=+el.dataset.num||0;
      if(window.gsap){
        const obj={n:0};
        gsap.to(obj,{n:target,duration:0.9,ease:'power1.out',
          onUpdate:()=>{el.textContent=Math.round(obj.n);}});
        return;
      }
      const dur=700; const start=performance.now();
      const step=(now)=>{const p=Math.min((now-start)/dur,1);const e=1-Math.pow(1-p,3);
        el.textContent=Math.round(target*e);if(p<1)requestAnimationFrame(step);};
      requestAnimationFrame(step);
    });
  }

  function renderCharts(d){
    if(!window.G2) return;
    try{
      // 趋势数据：优先用后端数据，否则基于内容总数生成演示曲线
      let trend = d.trend;
      if(!trend || !trend.length){
        const base = (d.stats?.content||0);
        const labels=['周一','周二','周三','周四','周五','周六','周日'];
        trend = labels.map((date,i)=>({date, value:Math.max(1,Math.round(base*(0.08+((i*7)%5)*0.03)))}));
      }
      areaChart('chart-trend', trend);
      const ms=Object.entries(d.model_stats||{});
      const pieData = ms.length?ms.map(([type,value])=>({type,value})):[{type:'文章',value:d.stats?.publish||1},{type:'产品',value:d.stats?.content||1}];
      pieChart('chart-pie', pieData);
      /* 访问统计：模型内容数 + 未读留言 + 草稿，柱状图渲染 */
      const st=d.stats||{};
      const accData=[...ms.map(([k,v])=>({name:k,value:v})),{name:'未读留言',value:st.unread??0},{name:'草稿',value:st.draft??0}];
      columnChart('chart-access', accData);
    }catch(e){ console.warn('图表渲染失败',e); }
  }

  /* ============ 健康检查（开发管理） ============ */
  async function renderHealth(el){
    const t0=performance.now();
    const r=await api('/api/admin/health');
    if(r.code!==0){ el.innerHTML=`<div class="card-box fg-danger">健康检查失败：${esc(r.msg||'未知错误')}</div>`; return; }
    const d=r.data||{};
    const clientMs=Math.round((performance.now()-t0)*10)/10;
    const label={ok:'运行正常',warn:'需要关注',error:'存在异常'}[d.status]||'未知';
    const p=d.perf||{};
    const checks=d.checks||[];
    const icon={ok:'bi-check-circle-fill',warn:'bi-exclamation-triangle-fill',error:'bi-x-circle-fill'};
    el.innerHTML=`
      <div class="page-head"><div><h4>健康检查</h4><div class="sub">实时检测 Web 服务、数据库、缓存、磁盘与主题资源状态</div></div>
        <button class="btn btn-solid theme-primary btn-loading" id="health-refresh"><i class="bi bi-arrow-clockwise"></i> 重新检查</button></div>
      <div class="health-summary status-${esc(d.status||'ok')}">
        <div class="health-score"><i class="bi bi-heart-pulse"></i><b>${esc(label)}</b><small>站点综合状态</small></div>
        <div class="health-metrics">
          <div><span>服务端耗时</span><b>${d.response_time_ms ?? '-'}<small> ms</small></b></div>
          <div><span>端到端耗时</span><b>${clientMs}<small> ms</small></b></div>
          <div><span>检查项</span><b>${checks.length}<small> 项</small></b></div>
          <div><span>采样窗口</span><b>${p.count||0}<small> 次</small></b></div>
        </div>
        <div class="health-time">检查时间 ${esc(d.checked_at||'')}</div>
      </div>
      <div class="card-box"><h5><i class="bi bi-clipboard-check"></i> 检查项明细</h5>
        <div class="health-list">${checks.map(c=>`
          <div class="health-item s-${esc(c.status)}">
            <i class="bi ${icon[c.status]||'bi-question-circle-fill'}"></i>
            <div class="hc-body"><b>${esc(c.name)}</b><small>${esc(c.detail)}</small></div>
            <span class="hc-cost">${c.cost_ms ?? '-'} ms</span>
          </div>`).join('')||'<div class="list-empty">暂无检查项</div>'}</div>
      </div>
      <div class="card-box"><h5><i class="bi bi-speedometer2"></i> 响应耗时分布</h5>
        <div class="sub fg-secondary">最近 ${p.count||0} 次请求（滑动窗口），服务端从接收请求到发出响应头的时间</div>
        ${perfStrip(p)}
      </div>
      ${(p.slow||[]).length?`<div class="card-box"><h5><i class="bi bi-exclamation-circle"></i> 慢请求记录</h5>
        <div class="health-list">${p.slow.map(s=>`<div class="health-item s-warn"><i class="bi bi-clock-history"></i>
          <div class="hc-body"><b>${esc(s.path||'-')}</b><small>超过 200ms 阈值</small></div>
          <span class="hc-cost">${s.ms} ms</span></div>`).join('')}</div></div>`:''}`;
    const btn=document.getElementById('health-refresh');
    if(btn) btn.onclick=()=>{btnLoading(btn,true);renderHealth(el).finally(()=>btnLoading(btn,false));};
  }

  /* ============ 特殊功能页 ============ */
  async function renderSpecial(key,el,title){
    switch(key){
      case 'content-recycle': return window.Crud.open(key,'回收站');
      case 'station-generate': return renderGenerate(el);
      case 'station-setting': return renderSettingsForm(el,'站群设置',[
        ['station_switch','站群总开关','switch'],['domain_mode','域名模式','select',['完整域名','二级域名','路径模式']],
        ['title_template','标题模板','text'],['inherit_strategy','继承策略','select',['继承主站','独立配置']],
        ['seo_region','SEO地区词自动拼接','switch'],
      ]);
      case 'order-pay-setting': return renderSettingsForm(el,'支付配置',[
        ['pay_wechat','微信支付','switch'],['pay_alipay','支付宝','switch'],['pay_offline','线下支付','switch'],
        ['pay_wechat_mch','微信商户号','text'],['pay_alipay_app','支付宝 AppID','text'],
      ]);
      case 'setting-basic': return renderSiteSettings(el);
      case 'setting-upload': return renderUploadSettings(el);
      case 'setting-sms': return renderSettingsForm(el,'短信设置',[
        ['sms_gateway','短信网关','text'],['sms_key','AccessKey','text'],['sms_secret','AccessSecret','password'],['sms_sign','短信签名','text'],['sms_tpl','验证码模板','text'],
      ]);
      case 'setting-email': return renderEmailSettings(el);
      case 'setting-security': return renderSecuritySettings(el);
      case 'tool-seo': return renderSeo(el);
      case 'setting-switch': return renderSwitchSettings(el);
      case 'dev-theme': return renderThemes(el);
      case 'dev-plugin': return renderPlugins(el);
      case 'dev-content-model': return renderContentModels(el);
      case 'dev-health': return renderHealth(el);
      default: el.innerHTML=`<div class="card-box"><div class="list-empty"><i class="bi bi-cone-striped"></i>功能建设中</div></div>`;
    }
  }
  function d_theme(){return 'site-theme';}

  async function renderSettingsForm(el,title,fields){
    const r=await api('/api/admin/settings'); const s=r.data||{};
    const renderField=(f)=>{
      const [key,label,type=f[2]||'text',opts]=f; const v=s[key]??'';
      if(type==='switch')return `<div class="col-12"><div class="form-field"><input class="switch" type="checkbox" name="${key}" ${v?'checked':''}><label class="form-label">${esc(label)}</label></div></div>`;
      if(type==='select')return `<div class="col-12"><label class="form-label">${esc(label)}</label><select class="form-control" name="${key}" style="width:100%">${(opts||[]).map(o=>`<option ${v===o?'selected':''}>${esc(o)}</option>`).join('')}</select></div>`;
      return `<div class="col-12"><label class="form-label">${esc(label)}</label><input class="form-control" type="${type}" name="${key}" value="${esc(v)}" style="width:100%"></div>`;
    };
    el.innerHTML=`<div class="page-head"><div><h4>${esc(title)}</h4><div class="sub">配置仅影响当前站点，保存后立即生效</div></div></div>
      <div class="card-box"><form id="setting-form"><div class="row g-3 setting-grid">${fields.map(renderField).join('')}</div>
      <div class="mt-4"><button class="btn btn-solid theme-primary btn-loading" type="submit" id="setting-save"><i class="bi bi-check-lg"></i> 保存配置</button></div></form></div>`;
    document.getElementById('setting-form').onsubmit=async(e)=>{
      e.preventDefault(); const body={}; const btn=document.getElementById('setting-save');
      new FormData(e.target).forEach((v,k)=>body[k]=v);
      e.target.querySelectorAll('input[type=checkbox]').forEach(ch=>body[ch.name]=ch.checked?1:0);
      btnLoading(btn,true);const res=await post('/api/admin/settings',body);btnLoading(btn,false);
      toast(res.msg,res.code===0?'success':'error');
    };
  }

  /* ============ 邮箱配置（SMTP） ============ */
  async function renderEmailSettings(el){
    const r=await api('/api/admin/settings'); const s=r.data||{};
    const field=(k,l,type='text',ph)=>`<div class="col-12"><label class="form-label">${esc(l)}</label><input class="form-control" type="${type}" name="${k}" value="${esc(s[k]??'')}" style="width:100%" ${ph?`placeholder="${esc(ph)}"`:''}></div>`;
    const sslOn=String(s.smtp_ssl??'1')!=='0';
    el.innerHTML=`<div class="page-head"><div><h4>邮箱配置</h4><div class="sub">用于网站表单留言通知邮件发送（对应表单模型中的通知邮箱）</div></div></div>
      <div class="card-box"><form id="email-form"><div class="row g-3 setting-grid">
        ${field('smtp_host','SMTP 服务器','text','如 smtp.exmail.qq.com')}
        ${field('smtp_port','端口','number','SSL 465 / STARTTLS 587')}
        ${field('smtp_username','发件邮箱','text','用于登录 SMTP 并作为发件地址')}
        ${field('smtp_password','SMTP 密码','password','邮箱授权码（非登录密码）')}
        ${field('smtp_sender_name','发件人名称','text','收件人看到的发件人显示名')}
      </div>
      <div class="switch-row" style="margin-top:8px"><div class="switch-info"><b>SSL/TLS 加密</b><small>开启后使用 SSL 连接 SMTP 服务器（通常配合 465 端口），关闭则使用明文/STARTTLS（通常配合 587 端口）</small></div>
        <div class="field-switch"><input class="check" type="checkbox" name="smtp_ssl" id="smtp_ssl" ${sslOn?'checked':''}>
        <label class="form-label" for="smtp_ssl"><span class="sw-text ${sslOn?'on':''}">${sslOn?'已开启':'已关闭'}</span></label></div></div>
      <div class="mt-4 d-flex gap-2">
        <button class="btn btn-solid theme-primary btn-loading" type="submit" id="email-save"><i class="bi bi-check-lg"></i> 保存配置</button>
        <button class="btn btn-default" type="button" id="email-test"><i class="bi bi-send"></i> 测试发送</button>
      </div></form></div>`;
    const collect=()=>{
      const body={}; const f=document.getElementById('email-form');
      new FormData(f).forEach((v,k)=>body[k]=v);
      body.smtp_ssl=document.getElementById('smtp_ssl').checked?1:0;
      return body;
    };
    document.getElementById('email-form').onsubmit=async(e)=>{
      e.preventDefault(); const btn=document.getElementById('email-save');
      btnLoading(btn,true); const res=await post('/api/admin/settings',collect()); btnLoading(btn,false);
      toast(res.msg,res.code===0?'success':'error');
    };
    document.getElementById('email-test').onclick=()=>{
      const conf=collect();
      const modalEl=ensureSimpleModal('email-test-modal','测试发送',`
        <div class="mb-2 fg-secondary small">使用当前填写的配置直接发送测试邮件（无需先保存）。</div>
        <div><label class="form-label">接收邮箱</label><input class="form-control" id="email-test-to" type="email" placeholder="填写一个临时接收邮箱"></div>`,
        async ()=>{
          const to=document.getElementById('email-test-to').value.trim();
          if(!to){ toast('请填写接收邮箱','error'); return false; }
          const res=await post('/api/admin/email/test',{...conf, to});
          toast(res.msg,res.code===0?'success':'error');
          if(res.code===0) bootstrap.Dialog.getInstance(document.getElementById('email-test-modal')).hide();
          return false;
        }, 'modal-def');
      bootstrap.Dialog.getOrCreateInstance(modalEl).show();
    };
  }

  async function renderSiteSettings(el){
    const r=await api('/api/admin/settings'); const s=r.data||{};
    // 一行一个表单项
    const text=(k,l,ph)=>`<div class="col-12 setting-row"><label class="form-label">${l}</label><input class="form-control" name="${k}" value="${esc(s[k]??'')}" ${ph?`placeholder="${ph}"`:''}></div>`;
    const area=(k,l,rows)=>`<div class="col-12 setting-row"><label class="form-label">${l}</label><textarea class="form-control" name="${k}" rows="${rows||3}">${esc(s[k]??'')}</textarea></div>`;
    el.innerHTML=`<div class="page-head"><div><h4>基础设置</h4><div class="sub">站点信息、联系方式、备案信息与 SEO 配置</div></div></div>
      <div class="card-box"><form id="setting-form"><div class="row g-3 setting-grid">
        <div class="col-12 setting-row"><label class="form-label">站点Logo</label><div id="site-logo-slot"></div><input type="hidden" name="site_logo" id="fld-site_logo" value="${esc(s['site_logo']??'')}"></div>
        <div class="col-12 setting-row"><label class="form-label">站点Favicon</label><div id="site-favicon-slot"></div><input type="hidden" name="site_favicon" id="fld-site_favicon" value="${esc(s['site_favicon']??'')}"></div>
        ${text('site_name','站点名称')}
        ${text('site_short_name','站点简称','如：志俞建筑（用于页头/页脚窄位展示）')}
        ${text('site_tagline','宣传标语','如：志存高远 · 俞信于行')}
        ${text('site_city','所在城市','如：杭州')}
        ${text('site_industry','所属行业','如：建筑工程咨询')}
        ${area('site_description','站点简介',3)}
        ${text('site_phone','联系电话')}
        ${text('site_mobile','手机')}
        ${text('site_email','邮箱')}
        ${text('contact','联系人')}
        ${text('site_address','地址')}
        ${text('qq','QQ')}
        <div class="col-12 setting-row"><label class="form-label">微信二维码</label><div id="wechat-qr-slot"></div><input type="hidden" name="wechat_qrcode" id="fld-wechat_qrcode" value="${esc(s['wechat_qrcode']??'')}"></div>
        <div class="col-12 setting-row"><label class="form-label">抖音二维码</label><div id="douyin-qr-slot"></div><input type="hidden" name="douyin_qrcode" id="fld-douyin_qrcode" value="${esc(s['douyin_qrcode']??'')}"></div>
        <div class="col-12 setting-row"><label class="form-label">微博二维码</label><div id="weibo-qr-slot"></div><input type="hidden" name="weibo_qrcode" id="fld-weibo_qrcode" value="${esc(s['weibo_qrcode']??'')}"></div>
        ${text('icp_no','ICP备案号')}
        ${text('police_no','公网安备案号')}
        ${text('site_copyright','版权信息')}
        ${area('stat_code','统计代码','如百度统计 / Google Analytics 脚本',4)}
      </div><div class="mt-4"><button class="btn btn-solid theme-primary btn-loading" type="submit" id="setting-save"><i class="bi bi-check-lg"></i> 保存设置</button></div></form></div>`;
    // 需求：网站关键词/网站描述移入「SEO配置」页；本页上传关闭拖拽，仅保留上传按钮
    const singleUpload=(slot,opts)=>UploadUI.mount(document.getElementById(slot),{...opts});
    singleUpload('site-logo-slot',{
      value:s['site_logo']||'', multiple:false, label:'站点Logo',
      title:'站点Logo', hint:'建议透明底 PNG，高度 ≥ 60px',
      onChange:(v)=>{ document.getElementById('fld-site_logo').value=v||''; }
    });
    singleUpload('site-favicon-slot',{
      value:s['site_favicon']||'', multiple:false, label:'站点Favicon',
      title:'站点Favicon', hint:'建议 64×64 以上 PNG/ICO',
      onChange:(v)=>{ document.getElementById('fld-site_favicon').value=v||''; }
    });
    singleUpload('wechat-qr-slot',{
      value:s['wechat_qrcode']||'', multiple:false,
      onChange:(v)=>{ document.getElementById('fld-wechat_qrcode').value=v||''; }
    });
    singleUpload('douyin-qr-slot',{
      value:s['douyin_qrcode']||'', multiple:false,
      onChange:(v)=>{ document.getElementById('fld-douyin_qrcode').value=v||''; }
    });
    singleUpload('weibo-qr-slot',{
      value:s['weibo_qrcode']||'', multiple:false,
      onChange:(v)=>{ document.getElementById('fld-weibo_qrcode').value=v||''; }
    });
    document.getElementById('setting-form').onsubmit=async(e)=>{
      e.preventDefault();const body={};const btn=document.getElementById('setting-save');new FormData(e.target).forEach((v,k)=>body[k]=v);
      btnLoading(btn,true);const res=await post('/api/admin/settings',body);btnLoading(btn,false);
      toast(res.msg,res.code===0?'success':'error');
    };
  }

  /* ============ 上传设置（驱动可选 + 水印位置） ============ */
  async function renderUploadSettings(el){
    const r=await api('/api/admin/settings'); const s=r.data||{};
    const pr=await api('/api/admin/plugins');
    const cloudPlugins=((pr.data||[]).filter(p=>p.type==='upload'&&p.enabled));
    const WATER_POS=[
      ['top-left','左上'],['top-center','顶部居中'],['top-right','右上'],
      ['middle-left','居左'],['center','正中'],['middle-right','居右'],
      ['bottom-left','左下'],['bottom-center','底部居中'],['bottom-right','右下'],
    ];
    const driverOpts=[{value:'local',label:'本地存储（默认）'}].concat(
      cloudPlugins.map(p=>({value:p.key,label:p.name})));
    const curDriver=s['upload_driver']||'local';
    const row=(k,l,inner)=>`<div class="col-12 setting-row"><label class="form-label">${l}</label>${inner}</div>`;
    el.innerHTML=`<div class="page-head"><div><h4>上传设置</h4><div class="sub">上传驱动、文件限制与水印配置；云存储驱动需在「插件管理」安装并启用对应插件</div></div></div>
      <div class="card-box"><form id="setting-form"><div class="row g-3 setting-grid">
        ${row('upload_driver','上传驱动',`<select class="form-control" name="upload_driver">
          ${driverOpts.map(o=>`<option value="${o.value}" ${curDriver===o.value?'selected':''}>${esc(o.label)}</option>`).join('')}
        </select>
        ${cloudPlugins.length?'':'<div class="form-text fg-secondary">提示：检测到尚未启用云存储插件，安装并启用「阿里云OSS / 腾讯云COS」插件后可在此切换驱动</div>'}`)}
        ${row('upload_ext','允许后缀',`<input class="form-control" name="upload_ext" value="${esc(s['upload_ext']??'jpg,jpeg,png,gif,webp,zip,pdf,docx,xlsx')}">`)}
        ${row('upload_max','大小上限(MB)',`<input type="number" class="form-control" name="upload_max" value="${esc(s['upload_max']??'50')}">`)}
        ${row('upload_quality','图片压缩质量(1-100)',`<input type="number" class="form-control" name="upload_quality" value="${esc(s['upload_quality']??'85')}">`)}
        ${row('upload_watermark','水印文字',`<input class="form-control" name="upload_watermark" value="${esc(s['upload_watermark']??'')}" placeholder="留空表示不添加水印">`)}
        ${row('save_dir_template','存储目录模板',`<input class="form-control" name="save_dir_template" value="${esc(s['save_dir_template']??'{filetype}/{year}{month}/{day}')}">
        <div class="form-text fg-secondary">可用变量：{filetype} {year} {month} {day} {datetime} {timestamp} {rand6} {rand8}；文件名为 md5 哈希值。默认 {filetype}/{year}{month}/{day}<br>示例：{filetype}/{year}{month}/{day} → image/202611/20/202cb962ac59075b964b07152d234b70.jpg</div>`)}
        ${row('water_position','水印位置',`<select class="form-control" name="water_position">
          ${WATER_POS.map(o=>`<option value="${o[0]}" ${(s['water_position']||'bottom-right')===o[0]?'selected':''}>${o[1]}</option>`).join('')}
        </select>
        <div class="water-grid-demo">${WATER_POS.map(o=>`<span class="wg-cell ${o[0]} ${o[0]===(s['water_position']||'bottom-right')?'on':''}" data-wp="${o[0]}" title="${o[1]}"><i class="bi bi-droplet"></i></span>`).join('')}</div>`)}
      </div><div class="mt-4"><button class="btn btn-solid theme-primary btn-loading" type="submit" id="setting-save"><i class="bi bi-check-lg"></i> 保存配置</button></div></form></div>`;
    // 水印位置可视化点选
    el.querySelectorAll('[data-wp]').forEach(c=>c.onclick=()=>{
      el.querySelector('[name=water_position]').value=c.dataset.wp;
      el.querySelectorAll('[data-wp]').forEach(x=>x.classList.toggle('on',x===c));
    });
    document.getElementById('setting-form').onsubmit=async(e)=>{
      e.preventDefault(); const body={}; const btn=document.getElementById('setting-save');
      new FormData(e.target).forEach((v,k)=>body[k]=v);
      btnLoading(btn,true);const res=await post('/api/admin/settings',body);btnLoading(btn,false);
      toast(res.msg,res.code===0?'success':'error');
    };
  }

  /* ============ 安全设置 ============ */
  async function renderSecuritySettings(el){
    const r=await api('/api/admin/settings'); const s=r.data||{};
    const ROWS=[
      ['ip_whitelist','IP 白名单','仅允许白名单内的 IP 访问管理后台'],
      ['operation_audit','操作审计','记录管理员的关键操作日志，支持追溯'],
    ];
    const on=(k)=>String(s[k]??'1')!=='0';
    const capOn=(k)=>String(s[k]??'0')!=='0';
    const numVal=(k,d)=>{const v=parseInt(s[k],10);return Number.isFinite(v)?v:d;};
    const rule=await getPasswordRule();
    // 验证码开关：管理后台 / 用户中心，默认关闭
    const adminCap=capOn('admin_captcha'), userCap=capOn('user_captcha');
    const lockVal=numVal('login_lock',10), ttlVal=numVal('session_ttl',24);
    el.innerHTML=`<div class="page-head"><div><h4>安全设置</h4><div class="sub">验证码开关、登录策略数值与管理员密码规则可编辑，其余安全策略为只读预览</div></div></div>
      <div class="card-box"><div class="row g-0">
        <div class="col-12 switch-row"><div class="switch-info"><b>管理后台验证码</b><small>管理员登录时启用图形验证码校验</small></div>
          <div class="field-switch"><input class="check" type="checkbox" id="cap-admin" ${adminCap?'checked':''}>
          <label class="form-label" for="cap-admin"><span class="sw-text ${adminCap?'on':''}">${adminCap?'已开启':'已关闭'}</span></label></div></div>
        <div class="col-12 switch-row"><div class="switch-info"><b>用户中心验证码</b><small>前台用户注册 / 登录时启用图形验证码校验</small></div>
          <div class="field-switch"><input class="check" type="checkbox" id="cap-user" ${userCap?'checked':''}>
          <label class="form-label" for="cap-user"><span class="sw-text ${userCap?'on':''}">${userCap?'已开启':'已关闭'}</span></label></div></div>
        ${ROWS.map(x=>`<div class="col-12 switch-row"><div class="switch-info"><b>${x[1]}</b><small>${x[2]}</small></div>
          <div class="field-switch"><input class="check" type="checkbox" ${on(x[0])?'checked':''} disabled>
          <label class="form-label"><span class="sw-text ${on(x[0])?'on':''}">${on(x[0])?'已开启':'已关闭'}</span></label></div></div>`).join('')}
      </div></div>
      <div class="card-box mt-3"><div class="p-3">
        <h6 class="mb-3"><i class="bi bi-clock-history"></i> 登录策略</h6>
        <div class="row g-3">
          <div class="md:col-6"><label class="form-label">登录失败锁定(分钟)</label><input type="number" class="form-control" id="sec-login-lock" min="0" max="1440" step="1" value="${lockVal}"></div>
          <div class="md:col-6"><label class="form-label">会话时长(小时)</label><input type="number" class="form-control" id="sec-session-ttl" min="1" max="720" step="1" value="${ttlVal}"></div>
        </div>
        <div class="form-text fg-secondary">登录失败锁定填 0 表示不锁定；会话时长超时后需重新登录。</div>
        <div class="mt-3"><button class="btn btn-solid theme-primary btn-loading" type="button" id="security-num-save"><i class="bi bi-check-lg"></i> 保存登录策略</button></div>
      </div></div>
      <div class="card-box mt-3"><div class="p-3">
        <h6 class="mb-3"><i class="bi bi-shield-lock"></i> 管理员密码规则</h6>
        <div class="row g-3">
          <div class="col-12"><label class="form-label">校验正则</label><input class="form-control code-field" id="pwd-regex" spellcheck="false" value="${esc(rule.regex)}"></div>
          <div class="col-12"><label class="form-label">提示文案</label><input class="form-control" id="pwd-tip" value="${esc(rule.tip)}"></div>
        </div>
        <div class="mt-3"><button class="btn btn-solid theme-primary btn-loading" type="button" id="pwd-rule-save"><i class="bi bi-check-lg"></i> 保存密码规则</button></div>
      </div></div>`;
    const saveRule=document.getElementById('pwd-rule-save');
    if(saveRule) saveRule.onclick=async()=>{
      const regex=document.getElementById('pwd-regex').value.trim();
      const tip=document.getElementById('pwd-tip').value.trim();
      if(!regex||!tip){toast('正则和文案均不能为空','error');return;}
      btnLoading(saveRule,true);
      const res=await post('/api/admin/settings',{admin_pwd_regex:regex,admin_pwd_tip:tip});
      btnLoading(saveRule,false);
      toast(res.msg,res.code===0?'success':'error');
      if(res.code===0) clearPasswordRule();
    };
    const saveNum=document.getElementById('security-num-save');
    if(saveNum) saveNum.onclick=async()=>{
      const lock=parseInt(document.getElementById('sec-login-lock').value,10);
      const ttl=parseInt(document.getElementById('sec-session-ttl').value,10);
      if(!Number.isInteger(lock)||lock<0||lock>1440){toast('登录失败锁定需为 0-1440 的整数','error');return;}
      if(!Number.isInteger(ttl)||ttl<1||ttl>720){toast('会话时长需为 1-720 的整数','error');return;}
      btnLoading(saveNum,true);
      const res=await post('/api/admin/settings',{login_lock:String(lock),session_ttl:String(ttl)});
      btnLoading(saveNum,false);
      toast(res.msg,res.code===0?'success':'error');
    };
    const bindCap=(id,key)=>{
      const box=document.getElementById(id);
      box.onchange=async ()=>{
        const v=box.checked?1:0;
        const res=await post('/api/admin/settings',{[key]:v});
        toast(res.msg,res.code===0?'success':'error');
        if(res.code===0){
          const t=box.closest('.switch-row').querySelector('.sw-text');
          t.textContent=v?'已开启':'已关闭'; t.classList.toggle('on',!!v);
        } else box.checked=!box.checked;
      };
    };
    bindCap('cap-admin','admin_captcha');
    bindCap('cap-user','user_captcha');
  }

  /* ============ 系统开关配置 ============ */
  async function renderSwitchSettings(el){
    const r=await api('/api/admin/settings'); const s=r.data||{};
    const SW=[
      ['menu_station','站群管理','控制「站群管理」整个菜单组的显示'],
      ['menu_member','会员管理','控制「会员管理」整个菜单组的显示'],
      ['menu_order','订单管理','控制「订单与支付」整个菜单组的显示'],
      ['menu_comment','评论管理','控制「评论管理」菜单组的显示'],
      ['menu_dev','开发管理','控制「开发管理」整个菜单组的显示'],
      ['menu_lang','多语言管理','控制多语言管理 / 语言包管理菜单'],
      ['menu_sms','短信设置','控制短信设置菜单'],
      ['menu_email','邮箱配置','控制邮箱配置菜单'],
    ];
    const on=(k)=>String(s[k]??'1')!=='0';
    el.innerHTML=`<div class="page-head"><div><h4>系统开关</h4><div class="sub">关闭后对应菜单将自动隐藏，保存后刷新页面生效</div></div></div>
      <div class="card-box"><form id="switch-form"><div class="row g-0">
        ${SW.map(x=>`<div class="col-12 switch-row"><div class="switch-info"><b>${x[1]}</b><small>${x[2]}</small></div>
          <div class="field-switch"><input class="check" type="checkbox" name="${x[0]}" id="sw-${x[0]}" ${on(x[0])?'checked':''} data-switch="1">
          <label class="form-label" for="sw-${x[0]}"><span class="sw-text">${on(x[0])?'已开启':'已关闭'}</span></label></div></div>`).join('')}
      </div><div class="mt-4"><button class="btn btn-solid theme-primary btn-loading" type="submit" id="switch-save"><i class="bi bi-check-lg"></i> 保存配置</button></div></form></div>`;
    // 开关文案联动
    el.querySelectorAll('[data-switch]').forEach(ch=>{
      const t=ch.closest('.field-switch').querySelector('.sw-text');
      ch.onchange=()=>{t.textContent=ch.checked?'已开启':'已关闭';t.classList.toggle('on',ch.checked);};
    });
    document.getElementById('switch-form').onsubmit=async(e)=>{
      e.preventDefault();const body={};const btn=document.getElementById('switch-save');
      el.querySelectorAll('[data-switch]').forEach(ch=>body[ch.name]=ch.checked?'1':'0');
      btnLoading(btn,true);const res=await post('/api/admin/settings',body);btnLoading(btn,false);
      toast(res.msg,res.code===0?'success':'error');
      if(res.code===0) setTimeout(()=>location.reload(),600);
    };
  }

  /* ============ 插件管理（卡片/列表双视图） ============ */
  function viewState(key, def){ const v=localStorage.getItem(key); return v||def; }
  function viewToggle(key, cur, onChange){
    const wrap=document.createElement('div');
    wrap.className='view-toggle';
    wrap.innerHTML=`<button class="vt-btn ${cur==='card'?'on':''}" data-view="card" title="卡片视图"><i class="bi bi-grid-3x3-gap"></i></button>
      <button class="vt-btn ${cur==='list'?'on':''}" data-view="list" title="列表视图"><i class="bi bi-list-ul"></i></button>`;
    wrap.querySelectorAll('.vt-btn').forEach(b=>b.onclick=()=>{
      localStorage.setItem(key,b.dataset.view); onChange(b.dataset.view);
    });
    return wrap;
  }

  async function renderPlugins(el){
    const view=viewState('plugin_view','card');
    const pr=await api('/api/admin/plugins');
    const plugins=pr.data||[];
    el.innerHTML=`<div class="page-head"><div><h4>插件管理</h4><div class="sub">安装、启用并配置功能插件；云存储插件启用后可在「上传设置」中切换驱动</div></div>
      <div class="head-actions" id="plugin-view-toggle"></div></div>
      <div id="plugin-body"></div>`;
    document.getElementById('plugin-view-toggle').appendChild(
      viewToggle('plugin_view', view, ()=>renderPlugins(el)));
    const body=document.getElementById('plugin-body');
    const statusBadge=(p)=>p.enabled?'<span class="badge bg-success">已启用</span>':
      p.state==='installed'?'<span class="badge-soft">已安装</span>':'<span class="badge bg-secondary">未安装</span>';
    /* 需求：操作按钮统一图标化（title 提示说明用途） */
    const actionBtns=(p)=>p.enabled
      ? `<button class="btn btn-sm btn-subtle theme-secondary" data-act="disable" data-key="${p.key}" title="停用插件"><i class="bi bi-pause-circle"></i></button>
         <button class="btn btn-sm btn-soft-primary" data-cfg="${p.key}" title="插件配置"><i class="bi bi-sliders"></i></button>`
      : p.state==='installed'
      ? `<button class="btn btn-sm btn-solid theme-primary" data-act="enable" data-key="${p.key}" title="启用插件"><i class="bi bi-play-circle"></i></button>
         <button class="btn btn-sm btn-soft-primary" data-cfg="${p.key}" title="插件配置"><i class="bi bi-sliders"></i></button>
         <button class="btn btn-sm btn-subtle theme-secondary fg-danger" data-act="uninstall" data-key="${p.key}" title="卸载插件"><i class="bi bi-trash3"></i></button>`
      : `<button class="btn btn-sm btn-solid theme-success" data-act="install" data-key="${p.key}" title="安装插件"><i class="bi bi-download"></i></button>`;

    if(view==='card'){
      body.innerHTML=`<div class="plugin-grid">${plugins.map(p=>`
        <div class="plugin-card">
          <div class="plugin-top"><span class="plugin-icon" style="background:${p.color}1a;color:${p.color}"><i class="bi ${p.icon}"></i></span>
            <div class="plugin-tt"><h6>${esc(p.name)}</h6><small>v${esc(p.version)} · ${esc(p.author)}</small></div>${statusBadge(p)}</div>
          <p class="plugin-desc">${esc(p.desc)}</p>
          <div class="plugin-meta"><span><i class="bi bi-tag"></i> ${esc(p.category)}</span><span><i class="bi bi-download"></i> ${p.downloads} 次安装</span></div>
          <div class="plugin-actions">${actionBtns(p)}</div>
        </div>`).join('')||'<div class="card-box list-empty">暂无插件</div>'}</div>`;
    } else {
      body.innerHTML=`<div class="card-box"><div class="table-responsive"><table class="table table-hover align-middle">
        <thead><tr><th>插件</th><th>分类</th><th>版本</th><th>作者</th><th>安装量</th><th>状态</th><th style="width:260px">操作</th></tr></thead>
        <tbody>${plugins.map(p=>`<tr>
          <td><div class="d-flex align-items-center gap-2"><span class="plugin-icon sm" style="background:${p.color}1a;color:${p.color}"><i class="bi ${p.icon}"></i></span><b>${esc(p.name)}</b></div></td>
          <td>${esc(p.category)}</td><td>v${esc(p.version)}</td><td>${esc(p.author)}</td><td>${p.downloads}</td><td>${statusBadge(p)}</td>
          <td><div class="d-flex gap-2">${actionBtns(p)}</div></td></tr>`).join('')}</tbody></table></div></div>`;
    }
    body.querySelectorAll('[data-act]').forEach(b=>b.onclick=async ()=>{
      const act=b.dataset.act, key=b.dataset.key;
      const verb={install:'安装',uninstall:'卸载',enable:'启用',disable:'停用'}[act];
      const okd=await C.confirm({type:act==='uninstall'?'warning':'question',title:`${verb}插件`,
        text:`确定要${verb}该插件吗？${act==='uninstall'?'卸载后插件配置将被清除。':''}`,okText:`确认${verb}`});
      if(!okd) return;
      btnLoading(b,true);
      const r=await post('/api/admin/plugins/action',{key,action:act});
      btnLoading(b,false);
      toast(r.msg,r.code===0?'success':'error');
      if(r.code===0) renderPlugins(el);
    });
    body.querySelectorAll('[data-cfg]').forEach(b=>b.onclick=()=>pluginConfigModal(b.dataset.cfg, el));
  }

  async function pluginConfigModal(key, el){
    const r=await api('/api/admin/plugins/config?key='+encodeURIComponent(key));
    if(r.code!==0){ toast(r.msg,'error'); return; }
    const fields=r.data.fields||[], cfg=r.data.config||{};
    if(key==='ai'){ return aiConfigModal(cfg, el); }
    const html=`<form id="plugin-cfg-form"><div class="row g-3">
      ${fields.map(f=>`<div class="md:col-6"><label class="form-label">${esc(f.label)}</label>
        <input class="form-control" type="${f.type==='password'?'password':'text'}" name="${f.key}" value="${esc(cfg[f.key]??'')}" ${f.placeholder?`placeholder="${esc(f.placeholder)}"`:''}></div>`).join('')}
    </div></form>`;
    const modalEl=ensureSimpleModal('plugin-cfg-modal','插件配置',html, async ()=>{
      const body={};
      document.querySelectorAll('#plugin-cfg-form [name]').forEach(i=>body[i.name]=i.value);
      const res=await post('/api/admin/plugins/config',{key,config:body});
      toast(res.msg,res.code===0?'success':'error');
      if(res.code===0){ bootstrap.Dialog.getInstance(document.getElementById('plugin-cfg-modal')).hide(); return true; }
      return false;
    });
    bootstrap.Dialog.getOrCreateInstance(modalEl).show();
  }

  /* AI 插件专属配置：服务商卡片 → 模型下拉(预置+自定义) + API Key + 连通性测试 */
  async function aiConfigModal(cfg, el){
    const pr=await api('/api/admin/ai/providers');
    const providers=pr.data||{};
    const provNames=Object.keys(providers);
    let curProv=provNames.includes(cfg.provider)?cfg.provider:provNames[0];
    const bodyHtml=`
      <form id="ai-cfg-form">
        <div class="cfg-section"><div class="cfg-section-tt"><i class="bi bi-hdd-network"></i> 服务商</div>
          <div class="prov-grid" id="ai-prov-grid">
            ${provNames.map(n=>`<div class="prov-card ${n===curProv?'on':''}" data-prov="${esc(n)}">
              <b>${esc(n)}</b><small>${esc((providers[n]||{}).desc||'')}</small></div>`).join('')}
          </div>
          <div class="cfg-endpoint" id="ai-endpoint"><i class="bi bi-link-45deg"></i> ${esc((providers[curProv]||{}).endpoint||'')}</div>
        </div>
        <div class="cfg-section"><div class="cfg-section-tt"><i class="bi bi-cpu"></i> 模型</div>
          <div class="d-flex gap-2">
            <select class="form-control" id="ai-model-select" style="flex:1"></select>
            <input class="form-control" id="ai-model-custom" placeholder="输入自定义模型 ID" style="display:none;flex:1">
          </div>
          <small class="fg-secondary d-block mt-1">预置常用模型，也可切换「自定义…」手动输入模型 ID</small>
        </div>
        <div class="cfg-section"><div class="cfg-section-tt"><i class="bi bi-key"></i> API Key</div>
          <div class="d-flex gap-2 align-items-start">
            <input class="form-control" type="password" id="ai-api-key" style="flex:1" value="${esc(cfg.api_key??'')}" placeholder="在服务商控制台获取">
            <button class="btn btn-default" id="ai-conn-test" type="button" style="flex:0 0 auto"><i class="bi bi-plug"></i> 连通性测试</button>
          </div>
          <div class="mt-2 small" id="ai-test-result" style="min-height:20px"></div>
        </div>
      </form>`;
    const curVals=()=>{ const sel=document.getElementById('ai-model-select'), cus=document.getElementById('ai-model-custom');
      return {provider:curProv,
      model:(sel.value==='__custom__' ? cus.value.trim() : sel.value.trim()),
      api_key:document.getElementById('ai-api-key').value.trim()};};
    const renderModels=()=>{
      const sel=document.getElementById('ai-model-select'), cus=document.getElementById('ai-model-custom');
      const list=(providers[curProv]||{}).models||[];
      const saved=cfg.model||'';
      const isCustom=saved && !list.includes(saved) && curProv===cfg.provider;
      sel.innerHTML=list.map(m=>`<option ${(!isCustom&&m===saved)?'selected':''}>${esc(m)}</option>`).join('')
        +`<option value="__custom__" ${isCustom?'selected':''}>自定义…</option>`;
      cus.style.display=sel.value==='__custom__'?'':'none';
      if(isCustom) cus.value=saved;
      sel.onchange=()=>{ cus.style.display=sel.value==='__custom__'?'':'none'; };
    };
    const modalEl=ensureSimpleModal('ai-cfg-modal','AI 智能创作 · 服务配置',bodyHtml, async ()=>{
      const v=curVals();
      if(!v.model){ toast('请选择或输入模型','error'); return false; }
      const res=await post('/api/admin/plugins/config',{key:'ai',config:v});
      toast(res.msg,res.code===0?'success':'error');
      if(res.code===0){ bootstrap.Dialog.getInstance(document.getElementById('ai-cfg-modal')).hide(); }
      return false;
    }, 'modal-lg');
    renderModels();
    document.querySelectorAll('#ai-prov-grid .prov-card').forEach(card=>{
      card.onclick=()=>{
        curProv=card.dataset.prov;
        document.querySelectorAll('#ai-prov-grid .prov-card').forEach(c=>c.classList.toggle('on',c===card));
        document.getElementById('ai-endpoint').innerHTML=`<i class="bi bi-link-45deg"></i> ${esc((providers[curProv]||{}).endpoint||'')}`;
        cfg.model=''; renderModels();
      };
    });
    document.getElementById('ai-conn-test').onclick=async ()=>{
      const v=curVals(); const out=document.getElementById('ai-test-result');
      if(!v.model){ toast('请选择或输入模型','error'); return; }
      const btn=document.getElementById('ai-conn-test'); btnLoading(btn,true);
      out.innerHTML='<span class="fg-secondary"><i class="bi bi-arrow-repeat spin"></i> 正在连接服务商…</span>';
      const res=await post('/api/admin/ai/test', v); btnLoading(btn,false);
      out.innerHTML=res.code===0
        ? `<span style="color:var(--color-success)"><i class="bi bi-check-circle-fill"></i> ${esc(res.msg)}</span>`
        : `<span style="color:var(--color-error)"><i class="bi bi-x-circle-fill"></i> ${esc(res.msg)}</span>`;
    };
    bootstrap.Dialog.getOrCreateInstance(modalEl).show();
  }

  function ensureSimpleModal(id, title, bodyHtml, onOk, size){
    let el=document.getElementById(id);
    if(el) el.remove();
    el=document.createElement('dialog');
    el.id=id; el.className='dialog dialog-scrollable '+(size==='modal-sm'?'dialog-sm':(size==='modal-def'?'dialog-def':'dialog-lg'));
    el.innerHTML=`<div class="dialog-header"><h5 class="dialog-title">${esc(title)}</h5><button type="button" class="btn-close" data-bs-dismiss="dialog" aria-label="关闭"></button></div>
      <div class="dialog-body">${bodyHtml}</div>
      <div class="dialog-footer"><button class="btn-subtle theme-secondary" data-bs-dismiss="dialog">取 消</button>
        <button class="btn-solid theme-primary" id="${id}-ok">确 定</button></div>`;
    document.body.appendChild(el);
    el.querySelector('#'+id+'-ok').onclick=async ()=>{
      const btn=el.querySelector('#'+id+'-ok'); btnLoading(btn,true);
      const okd=await onOk(); btnLoading(btn,false);
    };
    return el;
  }

  /* ============ 主题管理（卡片/列表双视图） ============ */
  async function renderThemes(el){
    const view=viewState('theme_view','card');
    const r=await api('/api/admin/themes');
    const themes=r.data||[];
    el.innerHTML=`<div class="page-head"><div><h4>主题管理</h4><div class="sub">切换站点前台主题风格，立即生效</div></div>
      <div class="head-actions" id="theme-view-toggle"></div></div>
      <div id="theme-body"></div>`;
    document.getElementById('theme-view-toggle').appendChild(
      viewToggle('theme_view', view, ()=>renderThemes(el)));
    const body=document.getElementById('theme-body');
    if(view==='card'){
      body.innerHTML=`<div class="theme-grid">${themes.map(t=>`
        <div class="theme-card ${t.active?'active':''}">
          <div class="theme-preview" style="background:linear-gradient(135deg,${t.color} 0%,${t.color}cc 60%,#1f2937 130%)">
            <span class="theme-mock"><i></i><i></i><i></i></span>
            ${t.active?'<span class="theme-active-tag"><i class="bi bi-check-circle-fill"></i> 使用中</span>':''}
          </div>
          <div class="theme-info"><div class="d-flex justify-content-between align-items-center"><h6>${esc(t.name)}</h6><small>v${esc(t.version)}</small></div>
            <p>${esc(t.desc)}</p>
            <div class="theme-foot"><span class="fg-secondary small">${esc(t.author)}</span>
              ${t.active?'<button class="btn btn-sm btn-subtle theme-secondary" disabled title="当前主题"><i class="bi bi-check-circle"></i></button>':`<button class="btn btn-sm btn-solid theme-primary" data-use="${t.key}" title="启用该主题"><i class="bi bi-check-lg"></i></button>`}</div>
          </div>
        </div>`).join('')}</div>`;
    } else {
      body.innerHTML=`<div class="card-box"><div class="table-responsive"><table class="table table-hover align-middle">
        <thead><tr><th>主题</th><th>描述</th><th>版本</th><th>作者</th><th>状态</th><th style="width:120px">操作</th></tr></thead>
        <tbody>${themes.map(t=>`<tr>
          <td><div class="d-flex align-items-center gap-2"><span class="theme-dot" style="background:${t.color}"></span><b>${esc(t.name)}</b></div></td>
          <td>${esc(t.desc)}</td><td>v${esc(t.version)}</td><td>${esc(t.author)}</td>
          <td>${t.active?'<span class="badge bg-success">使用中</span>':'<span class="badge bg-secondary">未启用</span>'}</td>
          <td>${t.active?'<button class="btn btn-sm btn-subtle theme-secondary" disabled title="当前主题"><i class="bi bi-check-circle"></i></button>':`<button class="btn btn-sm btn-solid theme-primary" data-use="${t.key}" title="启用该主题"><i class="bi bi-check-lg"></i></button>`}</td></tr>`).join('')}</tbody></table></div></div>`;
    }
    body.querySelectorAll('[data-use]').forEach(b=>b.onclick=async ()=>{
      btnLoading(b,true);
      const r2=await post('/api/admin/themes/active',{key:b.dataset.use});
      btnLoading(b,false);
      toast(r2.msg,r2.code===0?'success':'error');
      if(r2.code===0) renderThemes(el);
    });
  }

  /* ============ 个人中心 ============ */
  async function openProfile(){
    setTitle('个人中心');
    location.hash='profile'; addTab('profile','个人中心');
    highlight('profile');
    disposeCharts();
    const el=document.getElementById('content');
    el.innerHTML=skeletonStats(4);
    const r=await api('/api/admin/profile');
    if(r.code!==0){ el.innerHTML=`<div class="card-box fg-danger">${esc(r.msg)}</div>`; return; }
    const u=r.data;
    const logs=await api('/api/admin/profile/logs?page=1&size=10');
    const ld=logs.data||{};
    const roleName={super:'超级管理员',admin:'管理员',editor:'内容编辑'}[u.role]||u.role;
    el.innerHTML=`
      <div class="page-head"><div><h4>个人中心</h4><div class="sub">维护个人资料、头像与登录安全信息</div></div></div>
      <div class="profile-grid">
        <div class="card-box profile-left">
          <div class="profile-avatar-wrap">
            <span class="profile-avatar" id="profile-avatar">${u.avatar?`<img src="${esc(u.avatar)}" alt="头像">`:`<i class="bi bi-person-circle"></i>`}</span>
            <button class="btn btn-sm btn-soft-primary" id="avatar-change"><i class="bi bi-camera"></i> 更换头像</button>
            <input type="file" id="avatar-file" accept="image/*" hidden>
          </div>
          <h5 class="profile-name">${esc(u.nickname||u.username)}</h5>
          <span class="badge-soft">${esc(roleName)}</span>
          <div class="profile-meta">
            <div class="mini-stat"><span class="lbl"><i class="bi bi-clock-history"></i> 最后登录</span><span class="val">${esc(u.last_login_at||'—')}</span></div>
          </div>
          <form id="profile-form">
            <div class="mb-3"><label class="form-label">用户名</label><input class="form-control" value="${esc(u.username)}" disabled></div>
            <div class="mb-3"><label class="form-label">昵称</label><input class="form-control" name="nickname" value="${esc(u.nickname||'')}"></div>
            <div class="mb-3"><label class="form-label">手机号</label><input class="form-control" name="mobile" value="${esc(u.mobile||'')}"></div>
            <div class="mb-3"><label class="form-label">新密码</label><input type="password" class="form-control" name="new_password" placeholder="留空表示不修改" autocomplete="new-password"><div class="form-text" id="profile-pwd-tip"></div></div>
            <button class="btn btn-solid theme-primary btn-loading w-100" type="submit" id="profile-save"><i class="bi bi-check-lg"></i> 保存资料</button>
          </form>
        </div>
        <div class="card-box profile-right">
          <h5><i class="bi bi-clock-history"></i> 操作日志</h5>
          <div class="table-responsive"><table class="table table-sm table-hover">
            <thead><tr><th>模块</th><th>操作</th><th>对象</th><th>IP</th><th>时间</th></tr></thead>
            <tbody id="profile-log-body">
              ${(ld.list||[]).map(x=>`<tr><td><span class="badge-soft">${esc(x.module)}</span></td>
                <td>${esc(x.action)}</td><td class="cell-clip" title="${esc(x.target)}">${esc(String(x.target||'—').slice(0,24))}</td>
                <td>${esc(x.ip||'—')}</td><td class="fg-secondary small">${esc(x.created_at||'')}</td></tr>`).join('')
                ||'<tr><td colspan="5" class="list-empty">暂无日志</td></tr>'}
            </tbody></table></div>
          <div id="log-pager"></div>
        </div>
      </div>`;
    // 日志分页（统一 pyui-pager，支持切换每页条数）
    let logPage=ld.page||1; let LOG_SIZE=ld.size||10;
    const renderLogPager=(total)=>C.renderPager(document.getElementById('log-pager'),{
      page:logPage,size:LOG_SIZE,total,
      onGo:(p)=>{ logPage=p; loadLogs(); },
      onSize:(s)=>{ LOG_SIZE=s; logPage=1; loadLogs(); }
    });
    const loadLogs=async ()=>{
      const r2=await api(`/api/admin/profile/logs?page=${logPage}&size=${LOG_SIZE}`);
      const d2=r2.data||{};
      document.getElementById('profile-log-body').innerHTML=(d2.list||[]).map(x=>`<tr><td><span class="badge-soft">${esc(x.module)}</span></td>
        <td>${esc(x.action)}</td><td class="cell-clip">${esc(String(x.target||'—').slice(0,24))}</td>
        <td>${esc(x.ip||'—')}</td><td class="fg-secondary small">${esc(x.created_at||'')}</td></tr>`).join('')
        ||'<tr><td colspan="5" class="list-empty">暂无日志</td></tr>';
      renderLogPager(d2.total||0);
    };
    renderLogPager(ld.total||0);
    getPasswordRule().then(r=>{const tipEl=document.getElementById('profile-pwd-tip');if(tipEl)tipEl.textContent=r.tip;});
    // 资料保存
    document.getElementById('profile-form').onsubmit=async(e)=>{
      e.preventDefault();
      const body={}; new FormData(e.target).forEach((v,k)=>body[k]=v);
      const btn=document.getElementById('profile-save');
      if(body.new_password){
        const rule=await getPasswordRule();
        if(!checkPassword(body.new_password,rule)){toast(rule.tip,'error');return;}
      }
      btnLoading(btn,true);
      const res=await post('/api/admin/profile',body); btnLoading(btn,false);
      toast(res.msg,res.code===0?'success':'error');
    };
    // 更换头像（直接上传保存）
    const avatarFile=document.getElementById('avatar-file');
    document.getElementById('avatar-change').onclick=()=>avatarFile.click();
    avatarFile.onchange=async ()=>{
      const f=avatarFile.files[0]; avatarFile.value='';
      if(!f) return;
      if(!/^image\//.test(f.type)){ toast('请选择图片文件','error'); return; }
      C.showLoading('正在上传头像…');
      try{
        const url=await UploadUI.uploadFile(f);
        C.hideLoading(true);
        const res=await post('/api/admin/profile',{avatar:url});
        if(res.code===0){
          document.getElementById('profile-avatar').innerHTML=`<img src="${esc(url)}" alt="头像">`;
          // 同步右上角头像
          const chip=document.querySelector('.user-chip .avatar');
          if(chip) chip.innerHTML=`<img src="${esc(url)}" alt="">`;
          toast('头像已更新');
        } else toast(res.msg,'error');
      }catch(err){ C.hideLoading(true); toast(err.message||'头像上传失败','error'); }
    };
  }

  /* ============ SEO配置（站点 SEO 信息；Sitemap 为系统功能，见只读说明） ============ */
  async function renderSeo(el){
    const r=await api('/api/admin/settings'); const s=r.data||{};
    const text=(k,l,ph,hint)=>`<div class="col-12 setting-row"><label class="form-label">${l}</label>
      <input class="form-control" name="${k}" value="${esc(s[k]??'')}" placeholder="${esc(ph||'')}">
      ${hint?`<div class="form-text fg-secondary">${hint}</div>`:''}</div>`;
    const area=(k,l,ph,hint,rows)=>`<div class="col-12 setting-row"><label class="form-label">${l}</label>
      <textarea class="form-control" name="${k}" rows="${rows||3}" placeholder="${esc(ph||'')}">${esc(s[k]??'')}</textarea>
      ${hint?`<div class="form-text fg-secondary">${hint}</div>`:''}</div>`;
    el.innerHTML=`<div class="page-head"><div><h4>SEO配置</h4><div class="sub">站点 SEO 信息；网站地图为系统内置功能，由应用实时生成</div></div></div>
      <div class="card-box"><h5 class="d-flex justify-content-between align-items-center"><span><i class="bi bi-search"></i> SEO 信息</span>
        <button class="btn btn-sm btn-solid theme-primary btn-loading" type="button" id="seo-save"><i class="bi bi-check-lg"></i> 保存 SEO 配置</button></h5>
        <div class="row g-3 setting-grid">
          ${text('seo_title','SEO 标题','如：企业名称 - 专注建筑资质服务','页面标题（Title），建议 30 字以内，核心词前置')}
          ${text('seo_keywords','SEO 关键词','如：建筑资质,资质代办,施工资质','多个关键词用英文逗号分隔，建议 3-5 个，总长 100 字以内')}
          ${area('seo_description','SEO 描述','网站服务与优势的简短介绍…','显示在搜索结果摘要中，建议 70-160 字',3)}
        </div>
        <div class="form-text fg-secondary mt-1"><i class="bi bi-info-circle"></i> 未填写时前台自动回落到站点名称 / 站点描述</div>
      </div>
      <div class="card-box"><h5><i class="bi bi-diagram-2"></i> 网站地图（系统功能）</h5>
        <p class="fg-secondary small mb-2">sitemap.xml 由系统按栏目与已发布内容实时动态生成，是唯一对外出口，不落地静态文件、无需后台维护数据。内容或栏目变更后自动生效。</p>
        <a class="btn btn-sm btn-soft-primary" href="/sitemap.xml" target="_blank" rel="noopener"><i class="bi bi-box-arrow-up-right"></i> 查看 sitemap.xml</a>
      </div>`;
    document.getElementById('seo-save').onclick=async()=>{
      const body={}; const btn=document.getElementById('seo-save');
      el.querySelectorAll('[name]').forEach(i=>body[i.name]=i.value);
      btnLoading(btn,true); const res=await post('/api/admin/settings',body); btnLoading(btn,false);
      toast(res.msg,res.code===0?'success':'error');
    };
  }

  async function renderGenerate(el){
    el.innerHTML=`<div class="page-head"><div><h4>批量生成子站点</h4><div class="sub">按地区名称一键生成子站点，继承主站主题与配置</div></div></div>
      <div class="card-box"><h5><i class="bi bi-ui-checks-grid"></i> 生成配置</h5>
        <div class="mb-3"><label class="form-label">子站点名称（逗号分隔）</label>
          <textarea class="form-control" id="gen-names" rows="4" placeholder="例如：南京玄武区, 南京鼓楼区, 苏州工业园区"></textarea></div>
        <div class="row g-3 mb-3">
          <div class="md:col-6"><label class="form-label">命名模板</label><select class="form-control" id="gen-tpl"><option>{地区}站</option><option>{地区}分站</option><option>主站-{地区}</option></select></div>
          <div class="md:col-6"><label class="form-label">继承内容</label><select class="form-control" id="gen-inherit"><option>继承主站栏目与内容</option><option>仅继承栏目结构</option><option>不继承</option></select></div>
        </div>
        <button class="btn btn-solid theme-primary btn-loading" id="gen-run"><i class="bi bi-lightning"></i> 开始生成</button>
      </div>
      <div class="card-box" id="gen-result" style="display:none"></div>`;
    document.getElementById('gen-run').onclick=async()=>{
      const names=document.getElementById('gen-names').value;
      if(!names.trim()){toast('请输入子站点名称','error');return;}
      const btn=document.getElementById('gen-run');btnLoading(btn,true);
      const r=await post('/api/admin/station/generate',{names,template:document.getElementById('gen-tpl').value,inherit:document.getElementById('gen-inherit').value});
      btnLoading(btn,false);
      const box=document.getElementById('gen-result');box.style.display='block';
      box.innerHTML=`<h5><i class="bi bi-check-circle fg-success"></i> 生成结果</h5><div class="alert theme-${r.code===0?'success':'danger'}">${esc(r.msg)}</div><pre class="code-view">${esc(JSON.stringify(r.data||{},null,2))}</pre>`;
      toast(r.msg,r.code===0?'success':'error');
    };
  }

  function renderInfoPage(el,title,icon,subtitle,rows){
    el.innerHTML=`<div class="page-head"><div><h4>${esc(title)}</h4><div class="sub">${esc(subtitle)}</div></div></div>
      <div class="card-box"><h5><i class="bi ${icon}"></i> ${esc(subtitle)}</h5>
        ${rows.map(r=>`<div class="mini-stat"><span class="lbl">${esc(r[0])}</span><span class="val" style="font-size:14px">${esc(r[1])}</span></div>`).join('')}
      </div>`;
  }

  /* ============ 剪贴板：复制文本（Clipboard API + execCommand 兜底） ============ */
  async function copyText(text){
    const val=String(text??'');
    if(!val){ toast('内容为空，无需复制','error'); return false; }
    try{
      if(navigator.clipboard && window.isSecureContext){ await navigator.clipboard.writeText(val); }
      else{
        const ta=document.createElement('textarea');
        ta.value=val; ta.style.cssText='position:fixed;opacity:0;left:-9999px';
        document.body.appendChild(ta); ta.select();
        const done=document.execCommand('copy');
        ta.remove();
        if(!done) throw new Error('copy failed');
      }
      toast('已复制到剪贴板','success');
      return true;
    }catch(e){
      toast('复制失败，请手动复制','error');
      return false;
    }
  }

  /* ============ 开放API：已复用通用 CRUD 页（配置驱动）；此处仅保留行内扩展动作 ============ */
  async function openapiRowAction(action, row){
    if(action==='copy_key'){ copyText(row.app_key||''); return true; }
    if(action==='copy_secret'){ copyText(row.app_secret||''); return true; }
    if(action==='regen'){
      const res=await post('/api/admin/openapi/regen',{id:row.id});
      if(res.code===0){ toast(res.msg,'success'); copyText(res.data.app_secret); window.Crud.load(true); return true; }
      toast(res.msg,'error'); return false;
    }
    return false;
  }

  /* ============ 定时任务（对标宝塔计划任务） ============ */
  /* ============ 定时任务：已复用通用 CRUD 页（配置驱动）；此处保留行内动作与日志弹窗 ============ */
  async function taskRowAction(action, row){
    if(action==='run'){
      const res=await post('/api/admin/cron/run',{id:row.id});
      if(res.code===0){ toast('执行完成','success');
        cronLogModal(row, [ {status:res.data.status, result:res.data.output, run_at:new Date().toLocaleString(), cost:res.data.cost_ms} ]);
        window.Crud.load(true); return true; }
      toast(res.msg,'error'); return false;
    }
    if(action==='log'){
      const res=await api('/api/admin/cron/logs?task_id='+row.id+'&page=1&size=10');
      cronLogModal(row, (res.data||{}).list||[]);
      return true;
    }
    return false;
  }
  function cronLogModal(task, logs){
    const html=`<div class="table-responsive"><table class="table table-sm table-hover">
      <thead><tr><th style="width:150px">执行时间</th><th style="width:80px">状态</th><th style="width:90px">耗时</th><th>输出日志</th></tr></thead>
      <tbody>${(logs||[]).map(l=>{
        const m=/\[耗时 (\d+)ms\]/.exec(l.result||'');
        const out=(l.result||'').replace(/\[耗时 \d+ms\]\n?/,'');
        return `<tr><td class="fg-secondary small">${esc(l.run_at)}</td>
          <td>${l.status==='success'?'<span class="badge bg-success">成功</span>':'<span class="badge bg-danger">失败</span>'}</td>
          <td class="fg-secondary small">${m?m[1]+'ms':'—'}</td>
          <td><pre class="code-view" style="margin:0;max-height:180px">${esc(out)}</pre></td></tr>`;
      }).join('')||'<tr><td colspan="4" class="list-empty">该任务暂无执行日志</td></tr>'}</tbody></table></div>`;
    ensureSimpleModal('cron-log-modal','执行日志 · '+esc(task.name), html, async ()=>true, 'modal-lg');
    bootstrap.Dialog.getOrCreateInstance(document.getElementById('cron-log-modal')).show();
  }

  /* ============ 内容模型：字段管理 ============ */
  const CM_FIELD_TYPES=[['text','单行文本'],['textarea','多行文本'],['editor','富文本'],['password','密码框'],
    ['url','链接地址'],['email','邮箱'],['number','数字'],
    ['image_single','单图'],['image_multi','多图'],['file_single','单文件'],['file_multi','多文件'],
    ['select','下拉选择'],['radio','单选'],['checkbox','多选'],['selectpage','弹窗关联选择'],['tag','标签'],
    ['color','颜色选择器'],['switch','开关'],['date','日期'],['date_range','日期区间'],
    ['datetime','日期时间'],['datetime_range','日期时间区间']];
  const CM_TYPE_ALIAS={image:'image_single', file:'file_single', gallery:'image_multi'};  /* 旧类型显示别名 */
  const CM_OPT_TYPES=['select','radio','checkbox'];  /* 需要配置选项（label/value）的类型 */
  let _cmModels=[];  /* 内容模型缓存（字段弹窗 selectpage 关联模型下拉） */
  async function renderContentModels(el){
    const r=await api('/api/admin/content-model/list');
    const models=(r.data&&r.data.list)||[];
    _cmModels=models;  /* 供字段弹窗「关联模型」下拉使用 */
    if(!models.length){
      el.innerHTML=`<div class="page-head"><div><h4>内容模型</h4><div class="sub">查询、新增、编辑、删除内容模型，并管理其扩展字段</div></div></div>
        <div class="card-box"><div class="list-empty d-flex flex-column align-items-center gap-3" style="padding:50px 0">
          <i class="bi bi-diagram-3" style="font-size:40px;color:var(--color-text-quaternary)"></i>
          <span>暂无内容模型</span>
          <button class="btn btn-sm btn-solid theme-primary" id="cm-new-empty"><i class="bi bi-plus-lg"></i> 新增模型</button>
        </div></div>`;
      document.getElementById('cm-new-empty').onclick=()=>cmModelModal(null,()=>renderContentModels(el));
      return;
    }
    let cur=models[0];
    let showHiddenCols=false;  /* 需求：隐藏列默认收起，右上角按钮动态切换 展示隐藏列 / 收起隐藏列 */
    el.innerHTML=`<div class="page-head"><div><h4>内容模型</h4><div class="sub">左侧查询/新增/编辑/删除内容模型；右侧管理选中模型的扩展字段，字段随内容表单自动渲染</div></div></div>
      <div class="cm-layout">
        <div class="cm-side card-box"><div class="d-flex justify-content-between align-items-center mb-2">
            <h5 class="mb-0"><i class="bi bi-diagram-3"></i> 模型列表</h5>
            <button class="btn btn-sm btn-solid theme-primary" id="cm-model-new" title="新增模型"><i class="bi bi-plus-lg"></i></button>
          </div>
          <div id="cm-list">${models.map(m=>{
            const off=(m.status===0||m.status===false||String(m.status)==='0');
            return `<div class="cm-model ${m.id===cur.id?'on':''} ${off?'off':''}" data-id="${m.id}">
            <i class="bi ${esc(m.icon||'bi-file-earmark')}"></i>
            <div class="cm-model-info"><b>${esc(m.name)}${m.builtin?' <span class="cm-badge-builtin">内置</span>':''} ${off?'<span class="cm-badge-off">已禁用</span>':'<span class="cm-badge-on">已启用</span>'}</b><small>${esc(m.code)} · ${m.fields_count||0} 个字段</small></div>
            <div class="cm-model-acts">
              <button class="table-action-btn" title="编辑模型" data-medit="${m.id}"><i class="bi bi-pencil-square"></i></button>
              <button class="table-action-btn" title="删除模型" data-mdel="${m.id}" ${m.builtin?'disabled title="内置模型不可删除"':''}><i class="bi bi-trash3"></i></button>
            </div></div>`;}).join('')}</div></div>
        <div class="cm-main card-box">
          <div class="d-flex justify-content-between align-items-center mb-2">
            <h5 class="mb-0"><i class="bi bi-list-check"></i> 字段管理：<span id="cm-title">${esc(cur.name)}</span></h5>
            <div class="d-flex gap-2">
              <button class="btn btn-sm btn-soft-primary" id="cm-hidden-toggle"><i class="bi ${showHiddenCols?'bi-arrows-collapse':'bi-arrows-expand'}"></i> ${showHiddenCols?'收起隐藏列':'展示隐藏列'}</button>
              <button class="btn btn-sm btn-solid theme-primary" id="cm-add"><i class="bi bi-plus-lg"></i> 添加字段</button>
            </div>
          </div>
          <div class="table-responsive"><table class="table table-sm table-hover align-middle">
            <thead><tr><th style="width:56px">排序</th><th style="width:150px">字段标识</th><th>字段名称</th><th style="width:110px">类型</th><th style="width:90px">必填</th><th style="width:90px">唯一</th><th style="width:90px">列表显示</th><th style="width:90px">隐藏</th><th style="width:120px">操作</th></tr></thead>
            <tbody id="cm-fields"></tbody>
          </table></div>
          <div class="fg-secondary small"><i class="bi bi-hand-index-thumb"></i> 按住操作列的排序按钮可拖动调整顺序（决定内容表单字段顺序）；标记 <span class="cm-badge-sys">系统</span> 的字段标识/类型固定且不可删除；开启「隐藏」后该字段不在内容表单中显示；开启「唯一」后，添加/编辑内容时校验该字段值不允许重复；所有修改实时保存。</div>
        </div>
      </div>`;
    let fields=[];
    /* 字段定义实时保存：任何修改（增/删/改/排序/开关）后立即提交 */
    const saveFields=async (fieldsData)=>{
      const res=await post('/api/admin/content-model/save-fields',{model_id:cur.id, fields:fieldsData||fields});
      if(res.code!==0){ toast(res.msg,'error'); return false; }
      return true;
    };
    /* 行内开关（列表显示/隐藏）：切换后实时保存 */
    const fieldSwitch=(f,i,key,label)=>{
      const on=f[key]?1:0;
      return `<div class="field-switch"><input class="check" type="checkbox" data-fsw="${i}" data-fkey="${key}" ${on?'checked':''} title="${label}">
        <label class="form-label"><span class="sw-text ${on?'on':''}">${on?'是':'否'}</span></label></div>`;
    };
    const renderFields=()=>{
      const tbody=document.getElementById('cm-fields');
      if(!tbody) return;
      const visible=showHiddenCols?fields:fields.filter(f=>!f.hidden);
      tbody.innerHTML=visible.map((f,i)=>`<tr data-i="${fields.indexOf(f)}" class="${f.hidden?'cm-row-hidden':''}">
        <td><span class="cm-sort-num">${i+1}</span></td>
        <td><code>${esc(f.name)}</code>${f.sys?' <span class="cm-badge-sys">系统</span>':''}</td>
        <td>${esc(f.label)}${f.hidden?' <span class="cm-badge-hidden">隐藏</span>':''}</td>
        <td>${esc((CM_FIELD_TYPES.find(t=>t[0]===(CM_TYPE_ALIAS[f.type]||f.type))||['',f.type||''])[1])}</td>
        <td class="text-center">${f.required?'<i class="bi bi-check-lg fg-success"></i>':'—'}</td>
        <td>${fieldSwitch(f,i,'unique','值唯一')}</td>
        <td>${fieldSwitch(f,i,'list','列表中显示')}</td>
        <td>${fieldSwitch(f,i,'hidden','表单中隐藏')}</td>
        <td><div class="d-flex gap-1">
          <button class="table-action-btn cm-sort-handle" title="按住拖动排序" draggable="true"><i class="bi bi-arrow-down-up"></i></button>
          <button class="table-action-btn" title="编辑" data-fi="${i}"><i class="bi bi-pencil-square"></i></button>
          ${f.sys?'':`<button class="table-action-btn" title="删除" data-fd="${i}"><i class="bi bi-trash3"></i></button>`}
        </div></td></tr>`).join('')||'<tr><td colspan="9" class="list-empty">暂无字段，点击「添加字段」创建</td></tr>';
      tbody.querySelectorAll('[data-fd]').forEach(b=>b.onclick=()=>{
        const i=+b.dataset.fd;
        confirm({type:'danger',title:'删除确认',html:`确定删除字段「<b>${esc(fields[i].label)}</b>」吗？删除后实时保存。`,okText:'确认删除',
          onConfirm:async ()=>{
            fields.splice(i,1); renderFields();
            if(await saveFields()){ toast('已保存'); return true; }
            return false;
          }});
      });
      tbody.querySelectorAll('[data-fi]').forEach(b=>b.onclick=()=>{
        const i=+b.dataset.fi;
        cmFieldModal(fields[i],async (f)=>{
          fields[i]=f; renderFields();
          if(await saveFields(fields)) toast('已保存');
        });
      });
      tbody.querySelectorAll('[data-fsw]').forEach(el=>el.onchange=async ()=>{
        const i=+el.dataset.fsw, key=el.dataset.fkey;
        fields[i][key]=el.checked?1:0;
        const t=el.closest('.field-switch').querySelector('.sw-text');
        t.textContent=el.checked?'是':'否'; t.classList.toggle('on',el.checked);
        renderFields();
        if(await saveFields()) toast('已保存');
      });
      bindFieldDrag(tbody);
    };
    /* 字段行拖动排序：拖动手柄为操作列的排序按钮（cursor:move），dragend 后按 DOM 顺序重排并实时保存 */
    function bindFieldDrag(tbody){
      if(!tbody._dragBound){
        tbody._dragBound=1;
        let dragTr=null;
        tbody.addEventListener('dragover',e=>{
          if(!dragTr) return;
          e.preventDefault();
          const rows=[...tbody.querySelectorAll('tr[data-i]')].filter(r=>r!==dragTr);
          const after=rows.find(r=>e.clientY < r.getBoundingClientRect().top + r.getBoundingClientRect().height/2);
          if(after) tbody.insertBefore(dragTr,after); else tbody.appendChild(dragTr);
        });
        tbody.addEventListener('drop',e=>e.preventDefault());
        tbody._getDrag=()=>dragTr; tbody._setDrag=t=>{dragTr=t;};
      }
      tbody.querySelectorAll('tr[data-i]').forEach(tr=>{
        const handle=tr.querySelector('.cm-sort-handle');
        if(!handle) return;
        handle.addEventListener('dragstart',e=>{ tbody._setDrag(tr); tr.classList.add('cm-dragging'); e.dataTransfer.effectAllowed='move'; });
        handle.addEventListener('dragend',async ()=>{
          tr.classList.remove('cm-dragging');
          const order=[...tbody.querySelectorAll('tr[data-i]')].map(x=>+x.dataset.i);
          if(order.some((v,idx)=>v!==idx)){ fields=order.map(i=>fields[i]); renderFields(); await saveFields(); }
          tbody._setDrag(null);
        });
      });
    }
    const loadFields=async (m)=>{
      cur=m; document.getElementById('cm-title').textContent=m.name;
      document.querySelectorAll('.cm-model').forEach(d=>d.classList.toggle('on',+d.dataset.id===m.id));
      const r2=await api('/api/admin/content-model/fields?model_id='+m.id);
      fields=(r2.data&&r2.data.fields)||[];
      renderFields();
    };
    document.querySelectorAll('.cm-model').forEach(d=>d.onclick=(e)=>{
      if(e.target.closest('[data-medit],[data-mdel]')) return;  // 点操作按钮不切换模型
      loadFields(models.find(m=>m.id===+d.dataset.id));
    });
    // 模型：新增 / 编辑 / 删除
    document.getElementById('cm-model-new').onclick=()=>cmModelModal(null,()=>renderContentModels(el));
    document.querySelectorAll('[data-medit]').forEach(b=>b.onclick=(e)=>{
      e.stopPropagation();
      cmModelModal(models.find(m=>m.id===+b.dataset.medit),()=>renderContentModels(el));
    });
    document.querySelectorAll('[data-mdel]').forEach(b=>b.onclick=async (e)=>{
      e.stopPropagation();
      if(b.disabled) return;
      const m=models.find(x=>x.id===+b.dataset.mdel);
      await confirm({type:'danger',title:'删除确认',
        html:`确定删除内容模型「<b>${esc(m.name)}</b>」吗？该模型的字段定义将一并删除。`,
        okText:'确认删除',
        onConfirm:async ()=>{
          const res=await post('/api/admin/content-model/delete',{ids:[m.id]});
          if(res.code===0){ toast('删除成功'); renderContentModels(el); return true; }
          toast(res.msg,'error'); return false;
        }});
    });
    document.getElementById('cm-add').onclick=()=>cmFieldModal(null,async (f)=>{
      f.sort=fields.length+1;  /* 新字段排序排在末尾 */
      fields.push(f); renderFields();
      if(await saveFields()) toast('已保存');
    });
    /* 隐藏列展示/收起切换（默认收起；隐藏字段自动归入收起状态） */
    document.getElementById('cm-hidden-toggle').onclick=()=>{
      showHiddenCols=!showHiddenCols;
      const b=document.getElementById('cm-hidden-toggle');
      b.innerHTML=`<i class="bi ${showHiddenCols?'bi-arrows-collapse':'bi-arrows-expand'}"></i> ${showHiddenCols?'收起隐藏列':'展示隐藏列'}`;
      renderFields();
    };
    loadFields(cur);
  }
  /* 内容模型：新增/编辑弹窗 */
  function cmModelModal(m, onOk){
    const curIcon=m?.icon||'bi-file-earmark';
    /* status 回显：0/false/'0' 均视为禁用（修复：禁用模型编辑时仍显示启用） */
    const disabled = m && (m.status===0 || m.status===false || String(m.status)==='0');
    const html=`<form id="cmm-form"><div class="row g-3">
      <div class="md:col-6"><label class="form-label">模型名称 <i class="fg-danger">*</i></label>
        <input class="form-control" id="cmm-name" value="${esc(m?.name||'')}" placeholder="如：banner / 新闻" style="width:100%"></div>
      <div class="md:col-6"><label class="form-label">模型标识 <i class="fg-danger">*</i></label>
        <input class="form-control" id="cmm-code" value="${esc(m?.code||'')}" placeholder="如 banner" ${m?'disabled':''} style="width:100%"></div>
      <div class="md:col-6"><label class="form-label">图标</label>
        <div class="icon-pick-field">
          <input type="hidden" id="cmm-icon" value="${esc(curIcon)}">
          <span class="icon-pick-preview"><i class="bi ${esc(curIcon)}" id="cmm-icon-preview"></i></span>
          <button type="button" class="btn btn-soft-primary btn-sm icon-pick-btn" id="cmm-icon-btn"><i class="bi bi-icons"></i> 选择图标</button>
        </div></div>
      <div class="md:col-6"><label class="form-label">状态</label>
        <select class="form-control" id="cmm-status" style="width:100%">
          <option value="1" ${!disabled?'selected':''}>启用</option>
          <option value="0" ${disabled?'selected':''}>禁用</option>
        </select></div>
    </div></form>`;
    const modalEl=ensureSimpleModal('cmm-modal', m?'编辑模型':'新增模型', html, async ()=>{
      const name=document.getElementById('cmm-name').value.trim();
      const code=document.getElementById('cmm-code').value.trim().toLowerCase();
      const icon=document.getElementById('cmm-icon').value||'bi-file-earmark';
      if(!name){ toast('请填写模型名称','error'); return false; }
      if(!code || !/^[a-z][a-z0-9_]{0,31}$/.test(code)){ toast('模型标识需小写字母开头，仅含小写字母/数字/下划线','error'); return false; }
      const res=await post('/api/admin/content-model/save',{id:m?.id||0, name, code, icon, status:+document.getElementById('cmm-status').value});
      if(res.code!==0){ toast(res.msg,'error'); return false; }
      toast('保存成功'); onOk&&onOk();
      bootstrap.Dialog.getInstance(document.getElementById('cmm-modal')).hide();
      return true;
    },'modal-def');
    // 统一图标选择弹窗组件
    const iconBtn=modalEl.querySelector('#cmm-icon-btn');
    if(iconBtn) iconBtn.onclick=()=>{
      const hidden=document.getElementById('cmm-icon');
      window.Form.pickIcon(hidden.value, (val)=>{
        hidden.value=val;
        const pv=document.getElementById('cmm-icon-preview'); if(pv) pv.className='bi '+val;
      });
    };
    bootstrap.Dialog.getOrCreateInstance(modalEl).show();
  }
  function cmFieldModal(f, onOk){
    f=f||{type:'text'};
    if(CM_TYPE_ALIAS[f.type]) f={...f, type:CM_TYPE_ALIAS[f.type]};  /* 旧类型在弹窗中映射为新类型 */
    const isSys=!!f.sys;
    const hasOpts=CM_OPT_TYPES.includes(f.type)&&!isSys;  /* 系统字段选项由后端自动注入（如所属分类取自栏目管理），不提供手动配置 */
    const optRow=(o)=>`<div class="cm-opt-row">
      <input class="form-control form-control-sm cm-opt-label" placeholder="选项名称" value="${esc(o?.label||'')}">
      <input class="form-control form-control-sm cm-opt-value" placeholder="选项值" value="${esc(o?.value||'')}">
      <button type="button" class="table-action-btn" data-optdel title="删除选项"><i class="bi bi-trash3"></i></button></div>`;
    const html=`<form id="cmf-form"><div class="row g-3">
      <div class="md:col-6"><label class="form-label">字段标识 <i class="fg-danger">*</i></label>
        <input class="form-control" id="cmf-name" value="${esc(f.name||'')}" placeholder="如 price / spec / release_date" ${f.name?'disabled':''} style="width:100%">${isSys?'<div class="fg-secondary small mt-1">系统字段：标识与类型固定不可修改</div>':''}</div>
      <div class="md:col-6"><label class="form-label">字段名称 <i class="fg-danger">*</i></label>
        <input class="form-control" id="cmf-label" value="${esc(f.label||'')}" placeholder="如：价格" style="width:100%"></div>
      <div class="md:col-6"><label class="form-label">字段类型</label>
        <select class="form-control" id="cmf-type" ${isSys?'disabled':''} style="width:100%">${CM_FIELD_TYPES.map(t=>`<option value="${t[0]}" ${f.type===t[0]?'selected':''}>${t[1]}</option>`).join('')}</select></div>
      <div class="md:col-6"><label class="form-label">默认值</label>
        <input class="form-control" id="cmf-default" value="${esc(f.default||'')}" style="width:100%"></div>
      <div class="col-12" id="cmf-opts-wrap" style="display:${hasOpts?'block':'none'}">
        <label class="form-label">选项配置 <span class="fg-secondary small">（名称用于显示，值用于保存）</span></label>
        <div id="cmf-opts">${(f.options||[]).map(o=>optRow(o)).join('')}</div>
        <button type="button" class="btn btn-sm btn-soft-primary mt-1" id="cmf-opt-add"><i class="bi bi-plus-lg"></i> 添加选项</button>
      </div>
      <div class="col-12" id="cmf-rel-wrap" style="display:${f.type==='selectpage'?'block':'none'}">
        <label class="form-label">关联模型 <span class="fg-secondary small">（弹窗中从该模型的内容里选择，值保存内容 ID）</span></label>
        <select class="form-control" id="cmf-rel" style="width:100%">
          <option value="">— 请选择关联模型 —</option>
          ${(_cmModels||[]).filter(m=>m.status!==0).map(m=>`<option value="${esc(m.code)}" ${f.rel_model===m.code?'selected':''}>${esc(m.name)}</option>`).join('')}
        </select>
      </div>
      ${isSys&&CM_OPT_TYPES.includes(f.type)?'<div class="col-12"><div class="fg-secondary small"><i class="bi bi-info-circle me-1"></i>系统字段的选项由系统自动生成（所属分类取自栏目管理，状态为发布状态），无需手动配置。</div></div>':''}
      <div class="md:col-3"><div class="cm-field-switch-row"><span class="cm-fs-label">必填字段</span>
        <div class="field-switch"><input class="check" type="checkbox" id="cmf-required" ${f.required?'checked':''}>
          <label class="form-label" for="cmf-required"><span class="sw-text ${f.required?'on':''}">${f.required?'是':'否'}</span></label></div></div></div>
      <div class="md:col-3"><div class="cm-field-switch-row"><span class="cm-fs-label">列表中显示</span>
        <div class="field-switch"><input class="check" type="checkbox" id="cmf-list" ${f.list!==0&&f.list!==false?'checked':''}>
          <label class="form-label" for="cmf-list"><span class="sw-text ${f.list!==0&&f.list!==false?'on':''}">${f.list!==0&&f.list!==false?'是':'否'}</span></label></div></div></div>
      <div class="md:col-3"><div class="cm-field-switch-row"><span class="cm-fs-label">表单中隐藏</span>
        <div class="field-switch"><input class="check" type="checkbox" id="cmf-hidden" ${f.hidden?'checked':''}>
          <label class="form-label" for="cmf-hidden"><span class="sw-text ${f.hidden?'on':''}">${f.hidden?'是':'否'}</span></label></div></div></div>
      <div class="md:col-3"><div class="cm-field-switch-row"><span class="cm-fs-label">值唯一</span>
        <div class="field-switch"><input class="check" type="checkbox" id="cmf-unique" ${f.unique?'checked':''}>
          <label class="form-label" for="cmf-unique"><span class="sw-text ${f.unique?'on':''}">${f.unique?'是':'否'}</span></label></div></div></div>
    </div></form>`;
    const modalEl=ensureSimpleModal('cmf-modal', f.name?'编辑字段':'添加字段', html, async ()=>{
      const name=document.getElementById('cmf-name').value.trim().toLowerCase();
      const label=document.getElementById('cmf-label').value.trim();
      if(!name){ toast('请填写字段标识','error'); return false; }
      if(!/^[a-z][a-z0-9_]{0,31}$/.test(name)){ toast('字段标识非法：小写字母开头，仅含小写字母/数字/下划线','error'); return false; }
      if(!label){ toast('请填写字段名称','error'); return false; }
      const type=document.getElementById('cmf-type').value;
      /* 收集选项配置（label/value 成对有效才收录） */
      const options=[];
      document.querySelectorAll('#cmf-opts .cm-opt-row').forEach(r=>{
        const ol=r.querySelector('.cm-opt-label').value.trim(), ov=r.querySelector('.cm-opt-value').value.trim();
        if(ol&&ov) options.push({label:ol, value:ov});
      });
      if(CM_OPT_TYPES.includes(type) && !f.sys && !options.length){ toast('请至少配置一个选项（名称 + 值）','error'); return false; }
      /* 弹窗关联选择：必须指定关联模型 */
      let rel_model='';
      if(type==='selectpage'){
        rel_model=document.getElementById('cmf-rel').value;
        if(!rel_model){ toast('请选择关联模型','error'); return false; }
      }
      /* 展开原字段对象再覆盖表单值：除 sort 外，任何已有/将来新增的属性（如 placeholder 等扩展属性）都不会丢失 */
      onOk({...f, name,label,type,default:document.getElementById('cmf-default').value,
        required:document.getElementById('cmf-required').checked?1:0,
        list:document.getElementById('cmf-list').checked?1:0,
        hidden:document.getElementById('cmf-hidden').checked?1:0,
        unique:document.getElementById('cmf-unique').checked?1:0,
        sys:f.sys||0, options, rel_model,
        sort:f.sort??0});
      bootstrap.Dialog.getInstance(document.getElementById('cmf-modal')).hide();
      return true;
    },'modal-def');
    // 类型切换：select/radio/checkbox 显示选项配置区；selectpage 显示关联模型区
    const typeSel=modalEl.querySelector('#cmf-type');
    typeSel.onchange=()=>{
      document.getElementById('cmf-opts-wrap').style.display=CM_OPT_TYPES.includes(typeSel.value)?'block':'none';
      document.getElementById('cmf-rel-wrap').style.display=typeSel.value==='selectpage'?'block':'none';
    };
    // 选项行增删
    modalEl.querySelector('#cmf-opt-add').onclick=()=>{
      const wrap=document.getElementById('cmf-opts');
      wrap.insertAdjacentHTML('beforeend',`<div class="cm-opt-row">
        <input class="form-control form-control-sm cm-opt-label" placeholder="选项名称">
        <input class="form-control form-control-sm cm-opt-value" placeholder="选项值">
        <button type="button" class="table-action-btn" data-optdel title="删除选项"><i class="bi bi-trash3"></i></button></div>`);
      bindOptDel();
    };
    const bindOptDel=()=>modalEl.querySelectorAll('[data-optdel]').forEach(b=>b.onclick=()=>b.closest('.cm-opt-row').remove());
    bindOptDel();
    // 开关文字随状态更新
    ['cmf-required','cmf-list','cmf-hidden'].forEach(id=>{
      const el=document.getElementById(id);
      if(el) el.onchange=()=>{ const t=el.closest('.field-switch').querySelector('.sw-text'); t.textContent=el.checked?'是':'否'; t.classList.toggle('on',el.checked); };
    });
    bootstrap.Dialog.getOrCreateInstance(modalEl).show();
  }

  /* ============ 修改密码（独立弹窗） ============ */
  async function changePassword(){
    const rule=await getPasswordRule();
    const formHtml=`<form id="pwd-form" class="text-start" style="margin-top:4px">
      <div class="mb-3"><label class="form-label">原密码</label><input type="password" class="form-control" name="old_password" id="pass-old" autocomplete="current-password"></div>
      <div class="mb-3"><label class="form-label">新密码（${esc(rule.tip)}）</label><input type="password" class="form-control" name="new_password" id="pass-new" autocomplete="new-password"></div>
      <div class="mb-1"><label class="form-label">确认新密码</label><input type="password" class="form-control" name="confirm_password" id="pass-confirm" autocomplete="new-password"></div>
    </form>`;
    const modalEl=ensureSimpleModal('pwd-modal','修改密码',formHtml, async ()=>{
      const oldP=document.getElementById('pass-old')?.value||'';
      const newP=document.getElementById('pass-new')?.value||'';
      const cfm=document.getElementById('pass-confirm')?.value||'';
      if(!oldP||!newP){toast('请填写完整','error');return false;}
      if(!checkPassword(newP,rule)){toast(rule.tip,'error');return false;}
      if(newP!==cfm){toast('两次输入的新密码不一致','error');return false;}
      const r=await post('/api/admin/password',{old_password:oldP,new_password:newP});
      toast(r.msg,r.code===0?'success':'error');
      if(r.code===0) bootstrap.Dialog.getInstance(document.getElementById('pwd-modal')).hide();
      return r.code===0;
    },'modal-sm');
    bootstrap.Dialog.getOrCreateInstance(modalEl).show();
  }

  /* ============ 主题联动 ============ */
  function doThemeToggle(){ toggleTheme(); }
  document.addEventListener('cms:themechange',()=>{ if(activeTab==='dashboard'){ const el=document.getElementById('content'); disposeCharts(); renderDashboard(el); } });

  async function enterApp(nickname){
    await loadSiteName();
    const menuRes=await api('/api/admin/menu');
    if(menuRes.code===0)buildMenu(menuRes.data);
    document.getElementById('login-page').style.display='none';
    document.getElementById('app').style.display='block';
    document.getElementById('admin-name').textContent=nickname||'admin';
    const an2=document.getElementById('admin-name-2');if(an2)an2.textContent=nickname||'admin';
    // 右上角信息：头像 / 上次登录时间（本次登录之前的那次，不带 IP）
    try{
      const me=await api('/api/admin/me');
      if(me.code===0){
        const chip=document.querySelector('.user-chip .avatar');
        const av1=me.data.avatar;
        if(chip && av1) chip.innerHTML=`<img src="${esc(av1)}" alt="">`;
        const av2=document.querySelector('.user-drop-head .avatar-lg');
        if(av2 && av1) av2.innerHTML=`<img src="${esc(av1)}" alt="">`;
        const ll=document.getElementById('drop-last-login');
        if(ll) ll.textContent = me.data.prev_login_at ? `上次登录时间：${me.data.prev_login_at}` : '暂无登录记录';
      }
    }catch(e){}
    renderMenu();
    const hash=location.hash.slice(1)||'dashboard';
    if(hash==='login'){ location.hash='dashboard'; open('dashboard'); return; }
    open(MENU_MAP[hash]?hash:(hash==='profile'?'profile':'dashboard'));
  }

  /* 侧栏底部：仅探测在线状态。
     耗时文本由 core.js 的 api() 根据每次请求响应头 X-Response-Time 更新，
     显示的是本次请求自己的耗时，不是 PerfStats 滑动窗口平均值。 */
  async function refreshNavPerf(){
    try{
      const res=await fetch('/api/health?t='+Date.now(),{cache:'no-store',headers:{'Accept':'application/json'}});
      const dot=document.querySelector('#nav-foot .dot-online');
      if(dot) dot.style.background=res.ok?'':'var(--color-danger)';
    }catch(e){
      const dot=document.querySelector('#nav-foot .dot-online');
      if(dot) dot.style.background='var(--color-danger)';
    }
  }

  async function initApp(){
    applyTheme();
    refreshNavPerf();
    setInterval(refreshNavPerf, 10000);
    C.hideLoading(true);  // 需求：全局 loading——资源就绪后收起遮罩（页面初始即显示）
    document.getElementById('theme-toggle').onclick=doThemeToggle;
    const ttm=document.getElementById('toggle-theme-menu');if(ttm)ttm.onclick=(e)=>{e.preventDefault();doThemeToggle();};
    const sidenav=document.getElementById('cms-sidenav');
    const mask=document.getElementById('mobile-mask');
    const isMobile=()=>window.innerWidth<=768;
    // 恢复折叠菜单状态
    if(!isMobile() && localStorage.getItem('cms_nav_collapsed')==='1') sidenav.classList.add('collapsed');
    const closeMobileNav=()=>{sidenav.classList.remove('open');if(mask)mask.classList.remove('show');};
    /* 需求（2026-11-24）：收起/展开菜单提示按当前状态显示 */
    const syncToggleTip=()=>{
      const btn=document.getElementById('toggle-sidebar'); if(!btn) return;
      const txt=sidenav.classList.contains('collapsed')?'展开菜单':'收起菜单';
      btn.setAttribute('data-bs-title',txt); btn.setAttribute('aria-label',txt);
      try{ const inst=bootstrap.Tooltip.getOrCreateInstance(btn); inst.setContent({'.tooltip-inner':txt}); }catch(e){}
    };
    syncToggleTip();
    document.getElementById('toggle-sidebar').onclick=()=>{
      if(isMobile()){ const open=sidenav.classList.toggle('open'); if(mask)mask.classList.toggle('show',open); }
      else {
        // 折叠菜单（窄条图标模式），非隐藏
        const collapsed=sidenav.classList.toggle('collapsed');
        localStorage.setItem('cms_nav_collapsed', collapsed?'1':'');
        syncToggleTip();
      }
    };
    if(mask) mask.onclick=closeMobileNav;
    // 折叠菜单：hover 图标弹出菜单名浮层（body 级，避免被滚动容器裁剪）
    document.addEventListener('mouseover',(e)=>{
      const item=e.target.closest('.cms-sidenav.collapsed .nav-item');
      let tip=document.getElementById('nav-tip');
      if(!item){ if(tip) tip.style.display='none'; return; }
      if(!tip){ tip=document.createElement('div'); tip.id='nav-tip'; document.body.appendChild(tip); }
      tip.textContent=item.dataset.name||'';
      tip.style.display='block';
      const r=item.getBoundingClientRect();
      tip.style.left=(r.right+10)+'px';
      tip.style.top=Math.max(8, r.top+r.height/2-16)+'px';
    });
    // H5 点击菜单项后自动收起侧栏
    document.getElementById('cms-menu').addEventListener('click',(e)=>{ if(isMobile()&&e.target.closest('.nav-item')) closeMobileNav(); });
    window.addEventListener('resize',()=>{ if(!isMobile()) closeMobileNav(); });
    // hash 路由：地址栏改动（前进/后退/手动输入/分享链接）直达对应页面
    window.addEventListener('hashchange',()=>{
      const key=location.hash.slice(1)||'dashboard';
      if(key==='login') return;            // 登出等场景，登录页自行接管
      if(key===activeTab) return;          // open()/openProfile() 自身写入 hash 触发，避免重复渲染
      if(key==='profile'){ openProfile(); return; }
      if(MENU_MAP[key]) open(key);         // 未知 hash 忽略，不回写不渲染
    });
    const refresh=document.getElementById('btn-refresh');if(refresh)refresh.onclick=()=>{const btn=refresh;btnLoading(btn,true);open(activeTab).finally(()=>btnLoading(btn,false));};
    const clearCache=document.getElementById('btn-clear-cache');
    if(clearCache) clearCache.onclick=()=>{
      confirm({type:'info',title:'清理缓存',text:'将清理本站全部数据缓存，页面资源会重新加载，是否继续？',okText:'确认清理',
        onConfirm: async ()=>{
          const r=await post('/api/admin/cache/clear',{});
          toast(r.code===0?'缓存清理成功，页面即将自动刷新以生效':(r.msg||'清理失败'),r.code===0?'success':'error');
          if(r.code===0) setTimeout(()=>location.reload(),800);
          return r.code===0;
        }
      });
    };
    document.getElementById('logout').onclick=(e)=>{
      e.preventDefault();
      confirm({type:'warning',title:'退出登录',text:'确定要退出当前账号吗？',okText:'确认退出',okTextIcon:'bi-box-arrow-right',
        onConfirm: async ()=>{ logout(); return true; }
      });
    };
    const cp=document.getElementById('change-pass');if(cp)cp.onclick=(e)=>{e.preventDefault();changePassword();};
    const pe=document.getElementById('profile-entry');
    if(pe)pe.onclick=(e)=>{
      e.preventDefault();
      const toggle=pe.closest('.dropdown')?.querySelector('[data-bs-toggle="menu"]');
      const inst=toggle?bootstrap.Menu.getInstance(toggle):null;
      if(inst) inst.hide();
      openProfile();
    };
    document.getElementById('menu-search').oninput=(e)=>renderMenu(e.target.value);
    // 快捷键 ⌘K / Ctrl+K 聚焦搜索
    document.addEventListener('keydown',(e)=>{ if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'){e.preventDefault();document.getElementById('menu-search').focus();} });

    // 登录页增强交互：密码显隐 / 记住账号 / 忘记密码
    const eye=document.getElementById('login-eye');
    if(eye)eye.onclick=()=>{
      const pass=document.getElementById('login-pass');
      const show=pass.type==='password';pass.type=show?'text':'password';
      eye.innerHTML=`<i class="bi bi-${show?'eye-slash':'eye'}"></i>`;
    };
    const forgot=document.getElementById('login-forgot');
    if(forgot)forgot.onclick=(e)=>{e.preventDefault();toast('请联系站点管理员重置密码','info');};
    // 回填已记住的账号
    const savedUser=localStorage.getItem('cms_remember_user');
    const rememberBox=document.getElementById('login-remember');
    if(savedUser){const u=document.getElementById('login-user');if(u)u.value=savedUser;if(rememberBox)rememberBox.checked=true;}

    /* 登录图形验证码：按后端开关显示/隐藏，点击图片刷新（修复：开关开启但登录页无验证码） */
    let captchaState={id:'', enabled:false};
    const capGroup=document.getElementById('captcha-group');
    const capImg=document.getElementById('login-captcha-img');
    const loadCaptcha=async ()=>{
      try{
        const r=await api('/api/admin/captcha');
        const d=r.data||{};
        captchaState={id:d.id||'', enabled:!!d.enabled};
        capGroup.style.display=captchaState.enabled?'':'none';
        if(capImg) capImg.innerHTML=d.svg||'';
        const inp=document.getElementById('login-captcha'); if(inp) inp.value='';
      }catch(e){ capGroup.style.display='none'; }
    };
    if(capImg) capImg.onclick=loadCaptcha;

    document.getElementById('login-form').onsubmit=async(e)=>{
      e.preventDefault();
      const btn=document.getElementById('login-btn');btnLoading(btn,true);
      const username=document.getElementById('login-user').value;
      const body={username,password:document.getElementById('login-pass').value};
      if(captchaState.enabled){
        body.captcha_id=captchaState.id;
        body.captcha_code=document.getElementById('login-captcha').value;
      }
      const r=await post('/api/admin/login',body);
      btnLoading(btn,false);
      if(r.code===0){
        localStorage.setItem('cms_token',r.data.token);
        if(rememberBox?.checked)localStorage.setItem('cms_remember_user',username);
        else localStorage.removeItem('cms_remember_user');
        enterApp(r.data.nickname);
      }
      else{
        toast(r.msg,'error');
        if(captchaState.enabled) loadCaptcha();  // 验证码一次性：失败或过期自动刷新
      }
    };
    const token=localStorage.getItem('cms_token');
    if(token){
      const r=await api('/api/admin/me');
      if(r.code===0){await enterApp(document.getElementById('admin-name').textContent);return;}
      logout();
    }
    document.getElementById('login-page').style.display='flex';
    location.hash='login';
    loadCaptcha();  // 登录页显示时拉取验证码（后端按开关返回 enabled 决定是否展示）
    /* 品牌信息（brand.py 单一来源，经 /api/health 下发） */
    try{
      const h=await api('/api/health');
      if(h && h.name) SITE_NAME=h.name;
      if(h.brand){
        BRAND=h.brand;
        setTitle('登录');
        const lh=document.querySelector('.lh-title');
        if(lh) lh.innerHTML=(esc(BRAND.login_title||BRAND.name||'AI 轻量化管理后台')).replace('管理后台','<span>管理后台</span>');
        const ld=document.querySelector('.lh-desc');
        if(ld) ld.textContent=BRAND.login_desc||'';
        const ls=document.querySelector('.lh-site');
        if(ls && BRAND.login_site) ls.innerHTML=`<i class="bi bi-globe2"></i> ${esc(BRAND.login_site)}`;
        const nn=document.querySelector('.nav-brand-text strong');
        if(nn && BRAND.name) nn.textContent=BRAND.name;
        const ns=document.querySelector('.nav-slogan');
        if(ns && BRAND.slogan) ns.textContent=BRAND.slogan;
        const lcd=document.querySelector('.login-desc');
        if(lcd) lcd.innerHTML=`${esc(BRAND.slogan||'AI 轻量化管理后台')}<span class="login-ver">${esc(BRAND.version||'')}</span>`;
      }
    }catch(e){}
  }

  window.App={open,closeTab,renderMenu,doThemeToggle,copyText,openapiRowAction,taskRowAction};

  /* ============ AI 添加（AI 插件启用后，内容列表页注入） ============ */
  window.AiAdd=(function(){
    let st={checked:0, enabled:false};
    const MODES=[
      {v:'url', name:'链接采集', desc:'输入文章 URL，抓取内容后由 AI 重新撰写', icon:'bi-link-45deg'},
      {v:'prompt', name:'提示词生成', desc:'输入自定义提示词，AI 按要求生成内容', icon:'bi-magic'},
      {v:'site', name:'根据当前网站生成', desc:'基于站点信息、分类与已有内容智能撰写', icon:'bi-globe2'},
    ];
    async function isEnabled(force){
      if(!force && Date.now()-st.checked<30000) return st.enabled;
      try{ const r=await api('/api/admin/ai/status'); st={checked:Date.now(), enabled:!!(r.data&&r.data.enabled)}; }
      catch(e){ st={checked:Date.now(), enabled:false}; }
      return st.enabled;
    }
    /* 在内容列表「添加」按钮旁注入 AI 添加按钮 */
    async function inject(resource, addBtn){
      if(!addBtn || !['article','product','case'].includes(resource)) return;
      if(!(await isEnabled())) return;
      if(document.getElementById('btn-ai-add')) return;
      const b=document.createElement('button');
      b.className='btn btn-sm btn-default'; b.id='btn-ai-add'; b.type='button';
      b.innerHTML='<i class="bi bi-robot"></i> AI 添加';
      b.onclick=()=>open(resource, ()=>{});
      addBtn.after(b);
    }
    function open(modelKey, cb){
      ensureSimpleModal('ai-add-modal','AI 添加',`
        <div class="ai-add-form">
          <div class="ai-modes">${MODES.map((m,i)=>`
            <label class="ai-mode ${i===0?'on':''}" data-mode="${m.v}">
              <input type="radio" name="ai-mode" value="${m.v}" ${i===0?'checked':''} style="display:none">
              <i class="bi ${m.icon}"></i>
              <div class="ai-mode-tt"><b>${m.name}</b><small>${m.desc}</small></div>
            </label>`).join('')}</div>
          <div class="ai-input-area mt-3">
            <div data-area="url" style="display:none"><label class="form-label">文章链接</label>
              <input class="form-control" id="ai-url-input" placeholder="https://example.com/article"></div>
            <div data-area="prompt" style="display:none"><label class="form-label">生成提示词</label>
              <textarea class="form-control" id="ai-prompt-input" rows="4" placeholder="例：写一篇关于公司新产品发布会的新闻稿，突出节能特性"></textarea></div>
            <div data-area="site" style="display:none"><label class="form-label">补充要求（可选）</label>
              <textarea class="form-control" id="ai-site-input" rows="2" placeholder="例：围绕 latest 产品写一篇行业趋势分析"></textarea></div>
          </div>
          <div class="ai-result mt-3" id="ai-result" style="display:none">
            <label class="form-label">标题（可修改）</label>
            <input class="form-control" id="ai-title-out">
            <label class="form-label mt-2">正文（可修改）</label>
            <textarea class="form-control" id="ai-content-out" rows="8"></textarea>
          </div>
          <div class="mt-3 d-flex align-items-center gap-3 flex-wrap">
            <div class="d-flex align-items-center gap-2">
              <label class="form-label mb-0">发布：</label>
              <label class="form-label"><input type="radio" name="ai-pub" value="now" checked> 立即发布</label>
              <label class="form-label ms-2"><input type="radio" name="ai-pub" value="scheduled"> 定时发布</label>
            </div>
            <input type="datetime-local" id="ai-publish-at" class="form-control" style="width:220px;display:none">
          </div>
        </div>`,
        async ()=>false, 'modal-lg');
      const modal=document.getElementById('ai-add-modal');
      const foot=modal.querySelector('.dialog-footer');
      foot.innerHTML=`<button class="btn btn-subtle theme-secondary" data-bs-dismiss="dialog">取消</button>
        <button class="btn btn-solid theme-primary" id="ai-gen"><i class="bi bi-stars"></i> 生成内容</button>
        <button class="btn btn-solid theme-success" id="ai-pub-btn" style="display:none"><i class="bi bi-send"></i> 发布</button>`;
      // 模式切换
      modal.querySelectorAll('.ai-mode').forEach(l=>{
        l.onclick=()=>{
          modal.querySelectorAll('.ai-mode').forEach(x=>x.classList.remove('on')); l.classList.add('on');
          l.querySelector('input').checked=true;
          const v=l.dataset.mode;
          modal.querySelectorAll('[data-area]').forEach(a=>a.style.display=a.dataset.area===v?'':'none');
        };
      });
      // 发布选项联动
      modal.querySelectorAll('[name=ai-pub]').forEach(r=>r.onchange=()=>{
        document.getElementById('ai-publish-at').style.display=
          modal.querySelector('[name=ai-pub]:checked').value==='scheduled'?'':'none';
      });
      let generated=false;
      document.getElementById('ai-gen').onclick=async ()=>{
        const mode=modal.querySelector('[name=ai-mode]:checked').value;
        const input={url:'ai-url-input',prompt:'ai-prompt-input',site:'ai-site-input'}[mode];
        const val=document.getElementById(input)?document.getElementById(input).value.trim():'';
        const btn=document.getElementById('ai-gen'); btnLoading(btn,true);
        btn.textContent='AI 生成中…';
        const res=await post('/api/admin/ai/generate',{mode, input:val, model_key:modelKey});
        btnLoading(btn,false); btn.innerHTML='<i class="bi bi-stars"></i> 重新生成';
        if(res.code!==0){ toast(res.msg,'error'); return; }
        document.getElementById('ai-result').style.display='';
        document.getElementById('ai-title-out').value=res.data.title;
        document.getElementById('ai-content-out').value=res.data.content;
        document.getElementById('ai-pub-btn').style.display='';
        generated=true;
        toast('生成完成，可修改后发布','success');
      };
      document.getElementById('ai-pub-btn').onclick=async ()=>{
        if(!generated){ toast('请先生成内容','error'); return; }
        const pubType=modal.querySelector('[name=ai-pub]:checked').value;
        const pubAt=document.getElementById('ai-publish-at').value;
        if(pubType==='scheduled' && !pubAt){ toast('请选择定时发布时间','error'); return; }
        const btn=document.getElementById('ai-pub-btn'); btnLoading(btn,true);
        const res=await post('/api/admin/ai/publish',{
          model_key:modelKey,
          title:document.getElementById('ai-title-out').value.trim(),
          content:document.getElementById('ai-content-out').value,
          publish_type:pubType, publish_at:pubAt,
        });
        btnLoading(btn,false);
        toast(res.msg,res.code===0?'success':'error');
        if(res.code===0){
          bootstrap.Dialog.getInstance(modal).hide();
          if(cb) cb();
        }
      };
      bootstrap.Dialog.getOrCreateInstance(modal).show();
    }
    return {isEnabled, inject, open};
  })();
  /* Cloudflare Rocket Loader 等异步加载器可能把脚本推迟到 DOM ready 之后执行，
     此时再监听 DOMContentLoaded 永远不会触发，后台会卡在全局 loading，故按 readyState 分流 */
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initApp);
  } else {
    initApp();
  }
})();
