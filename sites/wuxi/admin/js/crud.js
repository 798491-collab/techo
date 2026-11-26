/* 通用 CRUD 引擎：配置驱动，所有业务列表复用，零重复代码 */
window.Crud = (function(){
  const C = window.CMS;
  const {api, post, toast, confirm, esc, qs, btnLoading, skeletonTable} = C;
  let state = {}; // {key, resource, page, filters, config}
  const skRows = (n)=>Array.from({length:n},()=>'<div class="sk-row skeleton"></div>').join('');

  /* 列表封面列缩略图：/uploads 下的位图追加 x-oss-process 参数，后端按需处理并缓存 */
  function cellThumb(u){
    if(!u||typeof u!=='string') return u;
    if(u.indexOf('x-oss-process=')!==-1) return u;
    const path=u.split('?')[0];
    if(!/^\/uploads\/.+\.(jpe?g|png|webp|bmp|gif|tiff?)$/i.test(path)) return u;
    return u+(u.indexOf('?')!==-1?'&':'?')+'x-oss-process=image/resize,m_fill,w_120,h_80/quality,q_80/format,webp';
  }

  function formatSize(n){
    n=Number(n)||0; if(n<1024) return n+' B';
    if(n<1048576) return (n/1024).toFixed(1)+' KB';
    if(n<1073741824) return (n/1048576).toFixed(1)+' MB';
    return (n/1073741824).toFixed(2)+' GB';
  }

  /* 素材库视图：card / list（默认卡片，localStorage 记忆） */
  function mediaView(){ return localStorage.getItem('media_view')||'card'; }
  function setMediaView(v){ localStorage.setItem('media_view', v); }
  /* 非图片素材的默认预览图（static/svg，按扩展名映射） */
  function mediaCover(row){
    const url=row.path||row.storage_path||'';
    const isImg=row.file_type==='image';
    if(isImg && url) return `<img src="${esc(url)}" alt="${esc(row.filename||'')}" loading="lazy" onerror="this.style.display='none';this.nextElementSibling.style.display='flex'"><span class="media-cover-fallback" style="display:none"><i class="bi bi-image"></i></span>`;
    // 非图片：按扩展名取 svg 图标
    const ext=String(row.file_ext||row.ext||'').toLowerCase();
    const map={
      pdf:'Pdf.svg', doc:'Word.svg', docx:'Word.svg', xls:'Excel.svg', xlsx:'Excel.svg', csv:'Excel.svg',
      ppt:'PPT.svg', pptx:'PPT.svg', txt:'txt.svg', zip:'yasuobao.svg', rar:'yasuobao.svg', '7z':'yasuobao.svg',
      mp4:'shipin.svg', avi:'shipin.svg', mov:'shipin.svg', mp3:'music.svg', wav:'music.svg',
      exe:'Exe.svg', gif:'Gif.svg', json:'peizhiwenjian.svg', xml:'peizhiwenjian.svg',
    };
    const svg=map[ext]||'File.svg';
    return `<span class="media-cover-fallback"><img src="./static/svg/${svg}?v=${window.STATIC_VER||"1"}" alt="${esc(ext||'file')}" loading="lazy"></span>`;
  }

  async function open(key, title){
    const el = document.getElementById('content');
    el.innerHTML = skeletonTable();
    const cfg = await api('/api/admin/crud/config?key='+encodeURIComponent(key));
    if (!cfg.data || !cfg.data.columns) { toast('该模块配置不存在','error'); return; }
    state = {key, resource:cfg.data.model, page:1, size:cfg.data.size||10, filters:{...(cfg.data.fixed_filter||{})}, config:cfg.data, title:title||cfg.data.title};
    render();
  }

  async function load(silent){
    const {resource, page, size, filters, config} = state;
    const params = {page, size: size || 10, ...filters};
    if(config.recycle) params.recycle=1;
    const tbody = document.getElementById('crud-body');
    if(!silent && tbody) tbody.innerHTML = `<tr><td colspan="${config.columns.length+2}" class="p-3">${skRows(6)}</td></tr>`;
    const res = await api(`/api/admin/list/${resource}?${qs(params)}`);
    if (res.code!==0) { toast(res.msg,'error'); return; }
    renderTable(res.data);
  }

  /* 模块描述（图3：标题下方说明文字） */
  const DESC = {
    'content-article':'管理网站文章，支持分类、封面图、图集与访问别名',
    'content-product':'管理产品内容，支持封面图与图集展示',
    'content-case':'管理客户案例，支持封面图与图集展示',
    'content-banner':'管理首页及各频道 Banner 轮播图，支持封面图与跳转链接',
    'content-category':'站点内容分类树，支持无限级嵌套，按内容模型过滤',
    'content-recycle':'已删除内容暂存于此，可恢复或彻底删除',
    'media':'图片与文件素材统一管理，支持上传、重命名与在线预览',
    'member-list':'注册会员资料管理',
    'member-group':'会员分组配置',
    'member-level':'会员等级与权益配置',
    'member-balance-log':'会员余额变动明细',
    'member-point-log':'会员积分变动明细',
    'order-list':'站点订单记录',
    'order-refund':'订单退款申请与处理记录',
    'form-model':'自定义表单模型定义',
    'form-record':'表单提交数据记录',
    'comment':'内容评论审核与管理',
    'tool-task':'系统定时任务配置',
    'tool-task-log':'定时任务执行日志',
    'tool-backup':'站点数据备份与恢复',
    'tool-seo':'SEO 信息、运行模式与静态化工具配置',
    'dev-openapi':'为第三方系统分配 AppKey / AppSecret 凭证，独立统计调用量，支持启用禁用',
    'auth-admin-user':'后台管理员账号管理',
    'auth-role':'角色与权限分配，左侧菜单按权限生成',
    'auth-permission':'系统权限节点配置',
    'setting-log':'后台操作日志审计',
    'setting-lang':'多语言管理',
    'setting-lang-package':'语言包管理',
    'station-site':'站群站点列表，独立数据独立域名',
    'station-region':'省市区地区库',
    'station-sync':'站点间内容同步记录',
    'dev-content-model':'内容模型定义，驱动内容表单与列表',
  };

  function render(){
    const c = state.config;
    if(state.size==null) state.size = c.size || 10;
    const isMedia = state.resource==='media';
    const filtersHtml = (c.filters||[]).map(f=>{
      if(f.key==='model'&&c.fixed_filter?.model) return '';
      const cur = state.filters[f.key]||'';
      if (f.type==='select') return `<select class="form-control form-control-sm" data-filter="${f.key}" style="width:180px"><option value="">${esc(f.label)}: 全部</option>${(f.options||[]).map(o=>`<option value="${esc(o.value)}" ${String(o.value)===String(cur)?'selected':''}>${esc(o.label)}</option>`).join('')}</select>`;
      return `<input class="form-control form-control-sm" data-filter="${f.key}" placeholder="${esc(f.label)}" value="${esc(cur)}" style="width:170px">`;
    }).join('');
    const isRecycle = !!c.recycle;
    const addBtn = (c.readonly||isRecycle)?'':`<button class="btn btn-sm btn-solid theme-primary" id="btn-add"><i class="bi bi-plus-lg"></i> 添加</button>`;
    const restoreBtn = isRecycle?`<button class="btn btn-sm btn-outline theme-success" id="btn-restore"><i class="bi bi-arrow-counterclockwise"></i> 恢复</button>`:'';
    const desc = DESC[state.key] || (state.key && state.key.startsWith('content-') ? `管理「${state.title||''}」内容模型的内容` : '');
    const view = isMedia ? mediaView() : 'table';
    const viewToggleHtml = isMedia ? `<div class="view-toggle media-view-toggle">
      <button class="vt-btn ${view==='card'?'on':''}" data-mview="card" title="卡片视图"><i class="bi bi-grid-3x3-gap"></i></button>
      <button class="vt-btn ${view==='list'?'on':''}" data-mview="list" title="列表视图"><i class="bi bi-list-ul"></i></button></div>` : '';
    document.getElementById('content').innerHTML = `
      <div class="crud-head"><h4>${esc(state.title)}</h4>${desc?`<p class="desc">${esc(desc)}</p>`:''}${viewToggleHtml}</div>
      <div class="card-box">
        <div class="crud-toolbar">
          <div class="d-flex gap-2 flex-wrap">
            ${addBtn}
            ${restoreBtn}
            <button class="btn btn-sm btn-outline theme-danger" id="btn-del"><i class="bi bi-trash"></i> ${isRecycle?'彻底删除':'批量删除'}</button>
          </div>
          <div class="ct-right ms-auto">
            <button class="icon-btn" id="btn-export" title="导出 CSV"><i class="bi bi-download"></i></button>
            <button class="icon-btn" id="btn-filter-toggle" title="搜索筛选"><i class="bi bi-search"></i></button>
          </div>
        </div>
        <div class="crud-filters" id="crud-filters" style="display:none">
          ${filtersHtml}
          <button class="btn btn-sm btn-solid theme-primary" id="btn-search"><i class="bi bi-search"></i> 搜索</button>
          <button class="btn btn-sm btn-subtle theme-secondary" id="btn-reset"><i class="bi bi-arrow-counterclockwise"></i> 重置</button>
        </div>
        <div class="table-responsive" id="crud-table-wrap"><table class="table table-hover table-sm align-middle">
          <thead><tr><th style="width:38px"><input type="checkbox" id="check-all" class="check"></th>${c.columns.map(col=>`<th>${esc(col.label)}</th>`).join('')}<th style="width:110px">操作</th></tr></thead>
          <tbody id="crud-body"><tr><td colspan="${c.columns.length+2}" class="p-3">${skRows(7)}</td></tr></tbody>
        </table></div>
        <div id="media-grid" class="media-grid" style="display:none"></div>
        <div id="crud-pager"></div>
      </div>`;
    // 素材库视图切换
    document.querySelectorAll('[data-mview]').forEach(b=>b.onclick=()=>{
      setMediaView(b.dataset.mview);
      document.querySelectorAll('[data-mview]').forEach(x=>x.classList.toggle('on',x===b));
      renderTable({list:state.rows||[],total:(state.lastData&&state.lastData.total)||0,size:state.size});
    });
    // 事件绑定：筛选表单默认隐藏，点右侧搜索图标展开；条件在点击「搜索」后生效
    const filterBox=document.getElementById('crud-filters');
    const toggleBtn=document.getElementById('btn-filter-toggle');
    if(toggleBtn) toggleBtn.onclick=()=>{
      const show = filterBox.style.display==='none';
      filterBox.style.display = show?'flex':'none';
      toggleBtn.classList.toggle('on', show);
      if(show){ const first=filterBox.querySelector('input,select'); if(first) first.focus(); }
    };
    document.getElementById('btn-search').onclick=()=>{document.querySelectorAll('[data-filter]').forEach(el=>state.filters[el.dataset.filter]=el.value);state.page=1;load();};
    document.getElementById('btn-reset').onclick=()=>{state.filters={...(c.fixed_filter||{})};state.page=1;document.querySelectorAll('[data-filter]').forEach(el=>el.value='');load();};
    document.getElementById('check-all').onchange=(e)=>document.querySelectorAll('.row-check').forEach(ch=>ch.checked=e.target.checked);
    document.addEventListener('change', updateSelected);
    const add=document.getElementById('btn-add');
    if(add) add.onclick=()=> isMedia ? mediaModal(null,()=>load(true)) : window.Form.open(state.key,null,()=>load());
    // AI 插件启用后，内容列表「添加」旁注入「AI 添加」（按 fixed_filter 区分文章/产品/案例）
    if(window.AiAdd) AiAdd.inject((state.config.fixed_filter&&state.config.fixed_filter.model)||state.resource, add);
    document.getElementById('btn-del').onclick=onDelete;
    const restore=document.getElementById('btn-restore');
    if(restore)restore.onclick=onRestore;
    document.getElementById('btn-export').onclick=onExport;
    const back=document.getElementById('btn-back-list');
    if(back) back.onclick=()=>App.open('content-article');
    load(true);
  }

  /* ---------- 素材库 添加/编辑 弹窗（上传组件 + 文件名，保存自动入库/更新） ---------- */
  async function mediaModal(id, callback){
    let item={};
    if(id){ const r=await api('/api/admin/detail/media/'+id); item=r.data||{}; }
    const modalEl=document.getElementById('modal');
    document.getElementById('dialog-title').textContent=id?'编辑素材':'添加素材';
    document.getElementById('dialog-subtitle').textContent='';
    document.getElementById('dialog-body').innerHTML=`<form id="cms-form" class="cms-form" novalidate><div class="row g-3">
      <div class="md:col-12"><label class="form-label">文件${id?'':' <span class="req-star">*</span>'}</label><div id="media-up-slot"></div></div>
      <div class="md:col-12"><label class="form-label">文件名</label>
        <input class="form-control" id="media-filename" maxlength="200" value="${esc(item.filename||'')}" placeholder="文件名上传完成后自动写入，可修改"></div>
    </div></form>`;
    const saveBtn=document.getElementById('modal-save'), cancelBtn=document.getElementById('modal-cancel');
    saveBtn.style.display=''; saveBtn.className='btn btn-solid theme-primary btn-loading';
    let touched=false;
    const nameInput=document.getElementById('media-filename');
    nameInput.oninput=()=>{ touched=true; };
    const up=window.UploadUI.mount(document.getElementById('media-up-slot'),{
      accept:'file',
      value:item.path||'',
      onChange:(v)=>{ if(v && !touched && nameInput) nameInput.value=String(v).split('/').pop().split('?')[0]; }
    });
    saveBtn.onclick=async ()=>{
      const url=up.get();
      if(!id && !url){ toast('请先上传文件或从素材库选择','error'); return; }
      const body={ filename: nameInput.value.trim(), ...(url?{path:url}:{}) };
      if(id) body.id=id;
      btnLoading(saveBtn,true);
      const r=await post('/api/admin/save/media',body);
      btnLoading(saveBtn,false);
      if(r.code===0){ toast('保存成功'); bootstrap.Dialog.getOrCreateInstance(modalEl).hide(); callback&&callback(); }
      else toast(r.msg||'保存失败','error');
    };
    cancelBtn.onclick=()=>bootstrap.Dialog.getOrCreateInstance(modalEl).hide();
    document.getElementById('modal-x').onclick=()=>bootstrap.Dialog.getOrCreateInstance(modalEl).hide();
    const modalInst=bootstrap.Dialog.getOrCreateInstance(modalEl);
    modalEl.addEventListener('hidden.bs.dialog',()=>btnLoading(saveBtn,false),{once:true});
    modalInst.show();
  }

  function updateSelected(e){
    if(e && e.target && !e.target.classList.contains('row-check') && e.target.id!=='check-all') return;
    const n=selectedIds().length;
    const el=document.getElementById('crud-selected');
    if(el){ el.style.display = n?'inline':'none'; el.textContent = `已选 ${n} 项`; }
  }
  function selectedIds(){return [...document.querySelectorAll('.row-check:checked')].map(x=>+x.value);}

  async function onDelete(){
    const ids=selectedIds();
    if(!ids.length){ await confirm({type:'warning',title:'未选择数据',text:'请先勾选要删除的记录。',okText:'知道了',hideCancel:true}); return; }
    const c=state.config;
    const ok = await confirm({
      type:'danger', title:c.recycle?'彻底删除':'删除确认',
      html:`确定要${c.recycle?'彻底删除':'删除'}选中的 <b style="color:var(--danger)">${ids.length}</b> 条记录吗？${c.recycle?'此操作不可恢复。':''}`,
      okText:c.recycle?'彻底删除':'确认删除',
      onConfirm: async ()=>{
        const r=await post(`/api/admin/delete/${state.resource}`,{ids,hard:!!c.recycle});
        if(r.code===0){toast('删除成功');load(true);return true;}
        toast(r.msg,'error');return false;
      }
    });
  }

  async function onRestore(){
    const ids=selectedIds();
    if(!ids.length){ await confirm({type:'warning',title:'未选择数据',text:'请先勾选要恢复的记录。',okText:'知道了',hideCancel:true}); return; }
    await confirm({
      type:'info', title:'恢复确认', html:`确定恢复选中的 <b>${ids.length}</b> 条记录吗？`, okText:'确认恢复',
      onConfirm: async ()=>{ const r=await post(`/api/admin/restore/${state.resource}`,{ids});
        if(r.code===0){toast('恢复成功');load(true);return true;} toast(r.msg,'error');return false; }
    });
  }

  /* 单行操作：编辑 / 删除 / 恢复 / 永久删除 */
  function findRow(id){ return (state.rows||[]).find(r=>String(r.id)===String(id)); }
  async function rowDelete(id){
    const row=findRow(id)||{id};
    const c=state.config;
    const hard = !!c.recycle;
    const okd = await confirm({
      type:'danger', title:hard?'永久删除':'删除确认',
      html:`确定要${hard?'永久删除':'删除'}「<b>${esc(String(row.title||row.name||row.filename||('#'+row.id)))}</b>」吗？${hard?'此操作不可恢复。':''}`,
      okText:hard?'永久删除':'确认删除',
      onConfirm: async ()=>{
        const r=await post(`/api/admin/delete/${state.resource}`,{ids:[row.id],hard});
        if(r.code===0){toast('删除成功');load(true);return true;}
        toast(r.msg,'error');return false;
      }
    });
    return okd;
  }
  async function rowRestore(id){
    const row=findRow(id)||{id};
    await confirm({
      type:'info', title:'恢复确认',
      html:`确定恢复「<b>${esc(String(row.title||row.name||row.filename||('#'+row.id)))}</b>」吗？恢复后内容将回到原列表。`, okText:'确认恢复',
      onConfirm: async ()=>{
        const r=await post(`/api/admin/restore/${state.resource}`,{ids:[id]});
        if(r.code===0){toast('恢复成功');load(true);return true;}
        toast(r.msg,'error');return false;
      }
    });
  }

  async function onExport(){
    await confirm({
      type:'question', title:'导出数据', text:`将当前模块「${esc(state.title)}」的全部数据导出为 CSV 文件，是否继续？`, okText:'确认导出',
      onConfirm: async ()=>{ await exportCsv(); return true; }
    });
  }

  function renderTable(data){
    const c=state.config, rows=data.list||[];
    state.rows=rows; state.lastData=data;
    // 素材库卡片视图
    if(state.resource==='media' && mediaView()==='card'){
      const wrap=document.getElementById('crud-table-wrap'), grid=document.getElementById('media-grid');
      if(wrap) wrap.style.display='none';
      if(grid){
        grid.style.display='grid';
        grid.innerHTML=rows.length?rows.map(row=>{
          const tlabel={image:'图片',video:'视频',file:'文件'}[row.file_type]||'文件';
          const size=row.size?formatSize(row.size):'—';
          return `<div class="media-card" data-mid="${row.id}">
            <label class="media-card-check"><input type="checkbox" class="row-check check" value="${row.id}"></label>
            <div class="media-card-cover" onclick="UploadUI.preview('${esc(row.path||row.storage_path||'')}')">${mediaCover(row)}</div>
            <div class="media-card-body">
              <div class="media-card-name" title="${esc(row.filename||'')}">${esc(row.filename||'')}</div>
              <div class="media-card-meta"><span class="badge-soft">${tlabel}</span><span>${size}</span></div>
              <div class="media-card-foot"><span title="上传人"><i class="bi bi-person"></i> ${esc(row.uploader||'系统')}</span>
                <span class="media-card-acts">
                  <button class="table-action-btn" title="编辑" onclick="Crud.mediaModal(${row.id},()=>Crud.load(true))"><i class="bi bi-pencil-square"></i></button>
                  <button class="table-action-btn" title="删除" onclick="Crud.rowDelete(${row.id})"><i class="bi bi-trash3"></i></button>
                </span></div>
            </div></div>`;
        }).join(''):'<div class="list-empty" style="grid-column:1/-1"><i class="bi bi-inbox"></i>暂无素材</div>';
      }
      C.renderPager(document.getElementById('crud-pager'), {
        page: state.page, size: data.size||state.size||10, total: data.total||0,
        onGo: (p)=>{ state.page=p; load(); }, onSize: (s)=>{ state.size=s; state.page=1; load(); },
      });
      updateSelected();
      return;
    }
    // 列表视图：恢复表格显示
    const wrap=document.getElementById('crud-table-wrap'), grid=document.getElementById('media-grid');
    if(wrap) wrap.style.display='';
    if(grid) grid.style.display='none';
    const tbody=document.getElementById('crud-body');
    if(!tbody) return;
    if(!rows.length){tbody.innerHTML=`<tr><td colspan="${c.columns.length+2}" class="list-empty"><i class="bi bi-inbox"></i>暂无数据</td></tr>`;}
    else tbody.innerHTML=rows.map((row,idx)=>{
      const name=esc(String(row.title||row.name||row.filename||('#'+row.id)).replace(/<[^>]+>/g,'').slice(0,30));
      const extraActs=(c.row_actions||[]).map(a=>
        `<button class="table-action-btn" title="${esc(a.title||a.key)}" onclick="Crud.rowAction('${esc(a.key)}',${row.id})"><i class="bi ${esc(a.icon||'bi-gear')}"></i></button>`).join('');
      /* 需求：只读模块（操作日志/任务日志等）不显示编辑/删除按钮 */
      const baseActs = c.recycle
        ? `<button class="table-action-btn" title="恢复" onclick="Crud.rowRestore(${row.id})"><i class="bi bi-arrow-counterclockwise"></i></button>
           <button class="table-action-btn" title="永久删除" onclick="Crud.rowDelete(${row.id})"><i class="bi bi-trash3-fill"></i></button>`
        : state.resource==='media'
        ? `<button class="table-action-btn" title="编辑" onclick="Crud.mediaModal(${row.id},()=>Crud.load(true))"><i class="bi bi-pencil-square"></i></button>
           <button class="table-action-btn" title="预览" onclick="UploadUI.preview('${esc(row.path||row.storage_path||'')}')"><i class="bi bi-eye"></i></button>
           <button class="table-action-btn" title="删除" onclick="Crud.rowDelete(${row.id})"><i class="bi bi-trash3"></i></button>`
        : (c.readonly?'':`<button class="table-action-btn" title="编辑" onclick="Form.open('${state.key}',${row.id},()=>Crud.load(true))"><i class="bi bi-pencil-square"></i></button>
           <button class="table-action-btn" title="删除" onclick="Crud.rowDelete(${row.id})"><i class="bi bi-trash3"></i></button>`);
      const actBtns = baseActs + extraActs;
      return `<tr style="animation:page-in .3s ${Math.min(idx*0.02,0.3)}s both">
      <td><input type="checkbox" class="row-check check" value="${row.id}"></td>
      ${c.columns.map(col=>{
        let v=row[col.key];
        if(state.resource==='media' && col.key==='filename'){
          v=`<div class="media-list-file">${mediaCover(row)}<span class="cell-clip" title="${esc(row.filename||'')}">${esc(row.filename||'')}</span></div>`;
        }
        else if(state.resource==='media' && col.key==='file_type'){
          const tl={image:'图片',video:'视频',file:'文件'}[row.file_type]||'文件';
          v=`<span class="badge-soft"><i class="bi bi-${row.file_type==='image'?'image':row.file_type==='video'?'camera-video':'file-earmark'}"></i> ${tl}</span>`;
        }
        else if(state.resource==='media' && col.key==='size') v=formatSize(row.size);
        else if(state.resource==='media' && col.key==='uploader') v=`<i class="bi bi-person fg-secondary"></i> ${esc(row.uploader||'系统')}`;
        else if(col.key==='form_type') v=`<span class="badge-soft"><i class="bi bi-input-cursor-text"></i> ${esc(row.form_type||'—')}</span>`;
        else if(col.key==='model'){
          /* 需求：内容模型列显示模型名称（后端回填 model_name），不显示标识 */
          const mn=row.model_name||row.model||'';
          v=mn?`<span class="badge-soft"><i class="bi bi-diagram-3"></i> ${esc(mn)}</span>`:'<span class="fg-secondary">—</span>';
        }
        else if(col.key==='category_id') v=row.category_name?`<span class="badge-soft">${esc(row.category_name)}</span>`:'<span class="fg-secondary">—</span>';
        else if(col.key==='data'){
          /* 表单提交记录：按表单字段配置可视化渲染（label：value 徽标），不再显示 JSON */
          if(Array.isArray(row.data_view) && row.data_view.length){
            v=row.data_view.map(d=>`<span class="fr-item"><span class="fr-label">${esc(d.label)}</span>${esc(d.value||'—')}</span>`).join('');
          }else{
            let txt=v||'';try{const o=typeof v==='string'?JSON.parse(v):v;txt=Object.entries(o||{}).map(([k,val])=>`${k}: ${val}`).join('；');}catch(e){}
            v=`<span class="cell-clip" title="${esc(String(txt).slice(0,300))}">${esc(String(txt).slice(0,80))||'—'}</span>`;
          }
        }
        else if(col.key==='status'||col.key==='pay_status'){
          v = v==='publish'?'<span class="badge bg-success">已发布</span>':
              v==='draft'?'<span class="badge bg-secondary">草稿</span>':
              v==='hidden'?'<span class="badge bg-secondary">隐藏</span>':
              v==='paid'?'<span class="badge bg-success">已支付</span>':
              v==='unpaid'?'<span class="badge bg-warning">未支付</span>':
              v==='refunded'?'<span class="badge bg-danger">已退款</span>':
              v===1?'<span class="badge-soft">启用</span>':
              v===0?'<span class="badge bg-secondary">停用</span>':esc(v??'');
        }
        else if(['is_read','is_top','is_hot','is_default','is_master','is_comment','is_order','enable_tag','is_nav','is_notify','is_super','inherit_config','need_login'].includes(col.key)) v=v?'<span class="badge-soft"><i class="bi bi-check-circle"></i> 是</span>':'<span class="badge bg-secondary"><i class="bi bi-x-circle"></i> 否</span>';
        else if(['body','content','data','value','fields','description','summary','main_content'].includes(col.key)) v=String(v??'').replace(/<[^>]+>/g,'').slice(0,50);
        else if(col.key==='cover') v=v?`<img src="${esc(cellThumb(v))}" class="cell-cover" alt="封面" loading="lazy">`:'<span class="cell-noimg"><i class="bi bi-image"></i></span>';
        else if(col.key==='app_secret') v=`<code class="oa-key">${esc(String(v||'').slice(0,10))}••••</code>`;
        else if(col.key==='title'||col.key==='name'||col.key==='filename'){
          const t=String(v??'').replace(/<[^>]+>/g,'');
          v=`<span class="cell-clip" style="max-width:220px" title="${esc(t.slice(0,300))}">${esc(t.slice(0,40))||'—'}</span>`;
        }
        else if(col.key==='app_key') v=`<code class="oa-key">${esc(v||'')}</code>`;
        else v=esc(v??'');
        return `<td title="${esc(String(row[col.key]??'').replace(/<[^>]+>/g,'').slice(0,200))}">${v}</td>`;
      }).join('')}
      <td class="text-nowrap"><div class="d-flex gap-1">${actBtns}</div></td>
    </tr>`;}).join('');
    C.renderPager(document.getElementById('crud-pager'), {
      page: state.page, size: data.size||state.size||10, total: data.total||0,
      onGo: (p)=>{ state.page=p; load(); },
      onSize: (s)=>{ state.size=s; state.page=1; load(); },
    });
    updateSelected();
  }

  /* 行内扩展动作（配置驱动：row_actions）：复制密钥 / 重新生成 / 立即执行 / 查看日志等 */
  async function rowAction(action, id){
    const row=findRow(id)||{id};
    const act=(state.config.row_actions||[]).find(a=>a.key===action)||{};
    const run=async()=>{
      if(action==='copy_key'){ App.copyText(row.app_key||''); return true; }
      if(action==='copy_secret'){ App.copyText(row.app_secret||''); return true; }
      if(state.resource==='api_consumer') return App.openapiRowAction(action, row);
      if(state.resource==='admin_task') return App.taskRowAction(action, row);
      if(state.resource==='form_record' && action==='view') return formRecordView(row);
      if(state.resource==='operation_log' && action==='view') return opLogView(row);
      toast('未知操作','error'); return false;
    };
    if(act.confirm){
      await confirm({type:'warning', title:act.title||'确认操作', text:act.confirm, okText:'确认',
        onConfirm:async ()=>run()});
    } else await run();
  }

  /* 表单提交记录：详情弹窗（按表单字段配置可视化展示，不再显示 JSON） */
  function formRecordView(row){
    let el=document.getElementById('fr-modal');
    if(el) el.remove();
    const items=(Array.isArray(row.data_view)&&row.data_view.length)
      ? row.data_view
      : (()=>{ let o={}; try{o=typeof row.data==='string'?JSON.parse(row.data||'{}'):(row.data||{});}catch(e){} return Object.entries(o||{}).map(([k,val])=>({label:k,value:String(val??'')})); })();
    const meta=[
      ['表单名称', row.form_type||'—'],
      ['提交时间', String(row.created_at||'').replace('T',' ')],
      ['提交IP', row.ip||'—'],
      ['会员ID', row.member_id?('#'+row.member_id):'未登录'],
      ['是否已读', row.is_read?'已读':'未读'],
    ];
    el=document.createElement('dialog');
    el.id='fr-modal'; el.className='dialog dialog-lg dialog-scrollable';
    el.innerHTML=`<div class="dialog-header"><h5 class="dialog-title"><i class="bi bi-envelope-paper"></i> 提交记录详情 <span class="badge-soft">ID ${row.id}</span></h5>
        <button type="button" class="btn-close" data-bs-dismiss="dialog" aria-label="关闭"></button></div>
      <div class="dialog-body">
        <div class="fr-meta">${meta.map(([k,v])=>`<span class="fr-meta-item"><span class="fr-meta-label">${esc(k)}</span>${esc(v)}</span>`).join('')}</div>
        <div class="fr-detail">${items.length?items.map(d=>`<div class="fr-detail-row"><div class="fr-detail-label">${esc(d.label)}</div><div class="fr-detail-value">${esc(d.value||'—')}</div></div>`).join(''):'<div class="list-empty">该记录没有提交内容</div>'}</div>
      </div>
      <div class="dialog-footer"><button type="button" class="btn btn-solid theme-secondary" data-bs-dismiss="dialog">关闭</button></div>`;
    document.body.appendChild(el);
    bootstrap.Dialog.getOrCreateInstance(el).show();
    return true;
  }

  /* 操作日志：详情弹窗（操作人 / 模块 / 操作 / 对象 / IP / UA / 请求地址 / 详情） */
  function opLogView(row){
    let el=document.getElementById('ol-modal');
    if(el) el.remove();
    const meta=[
      ['操作人', row.admin_user||'—'],
      ['模块', row.module||'—'],
      ['操作', row.action||'—'],
      ['对象', row.target||'—'],
      ['IP', row.ip||'—'],
      ['时间', String(row.created_at||'').replace('T',' ')],
    ];
    let detail=row.detail||'';
    if(typeof detail==='object') detail=JSON.stringify(detail,null,2);
    el=document.createElement('dialog');
    el.id='ol-modal'; el.className='dialog dialog-lg dialog-scrollable';
    el.innerHTML=`<div class="dialog-header"><h5 class="dialog-title"><i class="bi bi-clock-history"></i> 操作日志详情 <span class="badge-soft">ID ${row.id}</span></h5>
        <button type="button" class="btn-close" data-bs-dismiss="dialog" aria-label="关闭"></button></div>
      <div class="dialog-body">
        <div class="fr-meta">${meta.map(([k,v])=>`<span class="fr-meta-item"><span class="fr-meta-label">${esc(k)}</span>${esc(v)}</span>`).join('')}</div>
        ${row.url?`<div class="fr-detail-row"><div class="fr-detail-label">请求地址</div><div class="fr-detail-value" style="word-break:break-all">${esc(row.url)}</div></div>`:''}
        ${row.user_agent?`<div class="fr-detail-row"><div class="fr-detail-label">User-Agent</div><div class="fr-detail-value" style="word-break:break-all">${esc(row.user_agent)}</div></div>`:''}
        ${detail?`<div class="fr-detail-row"><div class="fr-detail-label">操作详情</div><div class="fr-detail-value" style="white-space:pre-wrap;word-break:break-all">${esc(detail)}</div></div>`:''}
        ${(!row.url&&!row.user_agent&&!detail)?'<div class="list-empty">该记录没有更多详情</div>':''}
      </div>
      <div class="dialog-footer"><button type="button" class="btn btn-solid theme-secondary" data-bs-dismiss="dialog">关闭</button></div>`;
    document.body.appendChild(el);
    bootstrap.Dialog.getOrCreateInstance(el).show();
    return true;
  }

  function go(page){state.page=page;load();}

  async function exportCsv(){
    const params={size:10000,...(state.config.fixed_filter||{})};
    const res=await api(`/api/admin/list/${state.resource}?${qs(params)}`);
    const rows=res.data.list||[];if(!rows.length){toast('无数据','error');return;}
    const cols=state.config.columns.map(c=>c.key);
    const csv='\ufeff'+cols.join(',')+'\n'+rows.map(r=>cols.map(k=>`"${String(r[k]??'').replace(/"/g,'""').replace(/\n/g,' ')}"`).join(',')).join('\n');
    const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));
    a.download=state.resource+'_'+new Date().toISOString().slice(0,10)+'.csv';document.body.appendChild(a);a.click();a.remove();
    setTimeout(()=>URL.revokeObjectURL(a.href),1000);
    toast(`已导出 ${rows.length} 条记录`);
  }

  /* 核心原则（2026-11-24）：谁自带专属骨架，谁主动声明跳过兜底骨架 —— Crud.open 自己渲染表格骨架屏 */
  return {OWN_SKELETON:true, open, load, go, rowDelete, rowRestore, rowAction, mediaModal, get state(){return state;}};
})();
