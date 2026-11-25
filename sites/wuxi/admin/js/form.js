/* 动态表单引擎：配置驱动渲染弹窗表单（点空白/ESC 不关闭）
   控件：text/number/textarea/editor(wangEditor)/password/image(统一上传)/gallery(多图)/
        select/switch/icon(弹窗选择)/perm_tree(权限树)/json/visual-fields/hidden
   - 所有文件/图片/附件统一走 UploadUI（拖拽上传 + 素材库选择 + 头像裁剪）
   - 表单用 JustValidate 做前端校验，失败提示具体字段
   - label 无图标，必填显示红色 * */
window.Form = (function(){
  const C = window.CMS;
  const {api, post, esc, btnLoading, toast} = C;
  let current = null;
  let modalInst = null;
  let ICONS = [];
  let editors = [];       // wangEditor 实例，关闭时销毁（含 toolbar）
  let validator = null;   // JustValidate 实例

  async function ensureIcons(){
    if(ICONS.length) return;
    /* V16：全量图标库 —— 直接解析本地 bootstrap-icons.css（2000+ 图标），接口作为兜底 */
    try{
      const res=await fetch('./vendor/bootstrap-icons/bootstrap-icons.css?v='+(window.STATIC_VER||'1'));
      if(res.ok){
        const css=await res.text();
        const names=[...new Set([...css.matchAll(/\.bi-([a-z0-9-]+)::before/g)].map(m=>'bi-'+m[1]))];
        if(names.length>100) ICONS=names.map(n=>({value:n,label:n.replace('bi-','')}));
      }
    }catch(e){}
    if(!ICONS.length){ try{ const r=await api('/api/admin/icon-options'); ICONS=r.data||[]; }catch(e){ ICONS=[]; } }
  }

  function labelHtml(f){
    const req = f.required ? ' <span class="req-star">*</span>' : '';
    return `<label class="form-label" for="fld-${esc(f.key)}">${esc(f.label)}${req}</label>`;
  }

  function selectHtml(f, v){
    const opts=(f.options||[]).map(o=>`<option value="${esc(o.value)}" ${String(v)===String(o.value)?'selected':''}>${esc(o.label)}</option>`).join('');
    return `<select class="form-control" name="${f.key}" id="fld-${esc(f.key)}">${opts}</select>`;
  }

  /* ---------- 统一上传控件（缩略图列表 + 素材库 + 裁剪） ---------- */
  function uploadHtml(f, v){
    const key=esc(f.key);
    const multiple=['gallery','image_multi','file_multi'].includes(f.type);
    return `<div class="upload-slot" id="upslot-${key}">
      <input type="hidden" name="${f.key}" id="fld-${key}" value="${esc(v??'')}">
    </div>`;
  }

  /* ---------- 日期时间：datetime-local 值 <-> 库值（"2026-11-19 10:00:00"） ---------- */
  function dtInput(v){
    const s=String(v||'').trim();
    if(!s) return '';
    return s.replace(' ', 'T').slice(0, 19);
  }
  function dtOut(v){
    let s=String(v||'').trim().replace('T',' ');
    if(s.length===16) s+=':00';
    return s;
  }

  /* ---------- 富文本编辑器（wangEditor） ---------- */
  function editorHtml(f, v){
    return `<div class="wangeditor-wrap">
      <div class="wangeditor-toolbar" id="wetb-${esc(f.key)}"></div>
      <div class="wangeditor-body" id="webody-${esc(f.key)}"></div>
      <textarea name="${f.key}" id="fld-${esc(f.key)}" class="wangeditor-hidden" hidden>${esc(v)}</textarea>
    </div>`;
  }

  /* ---------- 表单模型可视化字段编辑器 ---------- */
  function visualFieldsHtml(f, v){
    let rows=[];
    try{ rows = JSON.parse(v||'[]'); if(!Array.isArray(rows)) rows=[]; }catch(e){ rows=[]; }
    return `<div class="vf-editor" id="vf-${esc(f.key)}" data-field="${esc(f.key)}">
      <div class="vf-head"><span><i class="bi bi-list-check"></i> 表单字段（一行一个）</span><button type="button" class="btn btn-sm btn-soft-primary" id="vf-add-${esc(f.key)}"><i class="bi bi-plus-lg"></i> 添加字段</button></div>
      <div class="vf-rows" id="vf-rows-${esc(f.key)}">${rows.map((r,i)=>vfRow(r,i)).join('')}</div>
      ${rows.length?'':'<div class="vf-empty"><i class="bi bi-input-cursor-text"></i> 暂无字段，点击「添加字段」创建</div>'}
      <input type="hidden" name="${f.key}" id="fld-${esc(f.key)}" value="${esc(v||'[]')}">
    </div>`;
  }
  function vfRow(r,i){
    r=r||{};
    const sel=(key,opts)=>`<select class="form-control form-control-sm vf-${key}">${opts.map(o=>`<option value="${o[0]}" ${String(r[key]??'')===String(o[0])?'selected':''}>${o[1]}</option>`).join('')}</select>`;
    const hasOpts=['select','radio','checkbox'].includes(r.type);
    const optRow=(o)=>`<div class="vf-opt-row">
      <input class="form-control form-control-sm vf-opt-label" placeholder="选项名称" value="${esc(o?.label||'')}">
      <input class="form-control form-control-sm vf-opt-value" placeholder="选项值" value="${esc(o?.value||'')}">
      <button type="button" class="vf-del vf-opt-del" title="删除选项"><i class="bi bi-trash3"></i></button></div>`;
    return `<div class="vf-row" data-idx="${i}" draggable="true" title="鼠标移上去按住可拖动排序">
      <div class="vf-main">
        <input class="form-control form-control-sm vf-label" placeholder="字段名称" value="${esc(r.label||'')}">
        <input class="form-control form-control-sm vf-key" placeholder="字段标识(英文)" value="${esc(r.field||r.key||r.name||'')}">
        ${sel('type',[['text','单行文本'],['textarea','多行文本'],['number','数字'],['switch','布尔值'],['select','下拉选择'],['date','日期'],['radio','单选'],['checkbox','多选']])}
        <input class="form-control form-control-sm vf-default" placeholder="默认值" value="${esc(r.default??'')}">
        <label class="vf-req"><input type="checkbox" class="check vf-required" ${r.required?'checked':''}> 必填</label>
        <button type="button" class="vf-del" title="删除"><i class="bi bi-trash3"></i></button>
      </div>
      <div class="vf-opts" style="display:${hasOpts?'block':'none'}">
        ${(r.options||[]).map(o=>optRow(o)).join('')}
        <button type="button" class="btn btn-sm btn-soft-primary vf-opt-add"><i class="bi bi-plus-lg"></i> 添加选项</button>
      </div>
    </div>`;
  }

  function control(f, val){
    const v = val??'';
    switch(f.type){
      case 'hidden':
        return `<input type="hidden" name="${f.key}" value="${esc(f.value??v)}">`;
      case 'switch': {
        const on = v===1||v==='1'||v===true;
        return `<div class="field-switch">
          <input class="check" type="checkbox" name="${f.key}" id="fld-${esc(f.key)}" data-switch="1" ${on?'checked':''}>
          <label class="form-label" for="fld-${esc(f.key)}"><span class="sw-text">${on?'已启用':'已关闭'}</span></label>
        </div>`;
      }
      case 'icon': {
        const cur = v||'bi-file-earmark';
        return `<div class="icon-pick-field">
          <input type="hidden" name="${f.key}" id="fld-${esc(f.key)}" value="${esc(cur)}">
          <span class="icon-pick-preview"><i class="bi ${esc(cur)}" id="icon-preview-${esc(f.key)}"></i></span>
          <button type="button" class="btn btn-soft-primary btn-sm icon-pick-btn" data-iconfield="${esc(f.key)}"><i class="bi bi-icons"></i> 选择图标</button>
        </div>`;
      }
      case 'perm_tree': {
        return `<div class="perm-tree" id="pt-${esc(f.key)}">
          <div class="perm-tree-loading"><i class="bi bi-arrow-repeat spin"></i> 正在加载权限节点…</div>
          <input type="hidden" name="${f.key}" id="fld-${esc(f.key)}" value="${esc(v||'[]')}">
        </div>`;
      }
      case 'json':
        if(f.key==='fields' && current && (current.resource==='form_model' || current.resource==='content_type')) return visualFieldsHtml(f,v);
        return `<textarea class="form-control code-field" name="${f.key}" id="fld-${esc(f.key)}" rows="4" spellcheck="false">${esc(v)}</textarea>`;
      case 'editor': case 'body': case 'main_content':
        return editorHtml(f, v);
      case 'textarea':
        return `<textarea class="form-control" name="${f.key}" id="fld-${esc(f.key)}" rows="3" ${f.required?'data-required="1"':''}>${esc(v)}</textarea>`;
      case 'number':
        return `<input type="number" class="form-control" name="${f.key}" id="fld-${esc(f.key)}" value="${esc(v===0?0:(v||0))}" ${f.required?'data-required="1"':''}>`;
      case 'url':
        return `<input type="url" class="form-control" name="${f.key}" id="fld-${esc(f.key)}" placeholder="https://" value="${esc(v)}" ${f.required?'data-required="1"':''}>`;
      case 'email':
        return `<input type="email" class="form-control" name="${f.key}" id="fld-${esc(f.key)}" placeholder="name@example.com" value="${esc(v)}" ${f.required?'data-required="1"':''}>`;
      case 'password':
        return `<input type="password" class="form-control" name="${f.key}" id="fld-${esc(f.key)}" placeholder="${current&&current.id?'留空表示不修改':''}" autocomplete="new-password" ${f.required?'data-required="1"':''}>`;
      case 'image': case 'image_single': case 'gallery': case 'image_multi':
      case 'file_single': case 'file_multi':
        return uploadHtml(f, v);
      case 'date':
        return `<input type="date" class="form-control" name="${f.key}" id="fld-${esc(f.key)}" value="${esc(String(v||'').slice(0,10))}" ${f.required?'data-required="1"':''}>`;
      case 'datetime':
        return `<input type="datetime-local" step="1" class="form-control" name="${f.key}" id="fld-${esc(f.key)}" value="${esc(dtInput(v))}" ${f.required?'data-required="1"':''}>`;
      case 'date_range': case 'datetime_range': {
        const parts=String(v||'').split(',');
        const t=f.type==='date_range'?'date':'datetime-local';
        const cv=x=>f.type==='date_range'?String(x||'').slice(0,10):dtInput(x);
        return `<input type="hidden" name="${f.key}" id="fld-${esc(f.key)}" value="${esc(v??'')}">
          <div class="range-field" data-rangetype="${t}">
            <input type="${t}" ${t==='datetime-local'?'step="1"':''} class="form-control" data-range-start value="${esc(cv(parts[0]))}">
            <span class="range-sep">至</span>
            <input type="${t}" ${t==='datetime-local'?'step="1"':''} class="form-control" data-range-end value="${esc(cv(parts[1]))}">
          </div>`;
      }
      case 'tag': {
        /* 标签：输入回车添加，以英文逗号拼接入库 */
        const tags=String(v||'').split(',').map(s=>s.trim()).filter(Boolean);
        return `<div class="tag-editor" id="tage-${esc(f.key)}">
          <input type="hidden" name="${f.key}" id="fld-${esc(f.key)}" value="${esc(v??'')}">
          <div class="tag-chips" data-chips>${tags.map(t=>`<span class="tag-chip">${esc(t)}<i class="bi bi-x-lg" data-tagdel="${esc(t)}" title="删除"></i></span>`).join('')}</div>
          <input type="text" class="form-control tag-input" placeholder="输入标签后回车添加，可连续输入多个" autocomplete="off">
        </div>`;
      }
      case 'color': {
        const c=/^#[0-9a-fA-F]{6}$/.test(String(v)) ? String(v) : '#ffffff';
        return `<div class="color-field">
          <input type="color" name="${f.key}" id="fld-${esc(f.key)}" value="${esc(c)}">
          <code class="color-hex" data-colorhex>${esc(c)}</code>
        </div>`;
      }
      case 'selectpage': {
        /* 弹窗关联选择：值存关联内容 ID（多选英文逗号拼接），显示所选内容标题 */
        return `<div class="selectpage-field" id="sp-${esc(f.key)}" data-rel="${esc(f.rel_model||'')}">
          <input type="hidden" name="${f.key}" id="fld-${esc(f.key)}" value="${esc(v??'')}">
          <div class="input-group sp-group">
            <input type="text" class="form-control sp-display" readonly placeholder="点击「选择」从关联模型中挑选内容">
            <button type="button" class="btn btn-soft-primary" data-sppick title="选择"><i class="bi bi-search"></i> 选择</button>
            <button type="button" class="btn btn-outline theme-secondary" data-spclear title="清空"><i class="bi bi-x-lg"></i></button>
          </div>
        </div>`;
      }
      case 'select': case 'site': case 'category': case 'content_type': case 'region':
        return selectHtml(f, v);
      case 'radio': {
        /* 单选组（key/value 由字段管理配置） */
        const cur=String(v??'');
        const opts=(f.options||[]).map(o=>`<label class="form-label chk-opt"><input type="radio" class="radio chk-input" name="${esc(f.key)}" value="${esc(o.value)}" ${cur===String(o.value)?'checked':''}> ${esc(o.label)}</label>`).join('');
        return `<div class="check-group" id="fld-${esc(f.key)}">${opts||'<span class="fg-secondary small">未配置选项</span>'}</div>`;
      }
      case 'checkbox': {
        /* 多选组：值以英文逗号拼接存储 */
        const cur=String(v??'').split(',').map(s=>s.trim()).filter(Boolean);
        const opts=(f.options||[]).map(o=>`<label class="form-label chk-opt"><input type="checkbox" class="check chk-input" name="${esc(f.key)}" value="${esc(o.value)}" ${cur.includes(String(o.value))?'checked':''}> ${esc(o.label)}</label>`).join('');
        return `<div class="check-group" data-multi="1">${opts||'<span class="fg-secondary small">未配置选项</span>'}</div>`;
      }
      default:
        return `<input class="form-control" name="${f.key}" id="fld-${esc(f.key)}" value="${esc(v)}" ${f.required?'data-required="1"':''}>`;
    }
  }

  function isWide(f){ return ['editor','body','main_content','textarea','json','icon','image','image_single','gallery','image_multi','file_single','file_multi','date_range','datetime_range','selectpage','perm_tree'].includes(f.type); }

  async function open(key, id, callback, opts){
    opts = opts||{};
    // 需求（2026-11-24）：添加/编辑弹窗不使用全局 loading（global-loading 仅针对整个 app）
    const cfg=await api('/api/admin/crud/config?key='+encodeURIComponent(key));
    const data=cfg.data||{};
    const resource=data.model||key;
    const fields=data.form||[];
    const fixed=data.fixed_filter||{};
    if(fields.some(f=>f.type==='icon')) await ensureIcons();
    let item={...fixed};
    // 字段默认值兜底（如内容新增时发布时间=当前时间）
    fields.forEach(f=>{ if(f.value!==undefined && item[f.key]===undefined) item[f.key]=f.value; });
    if(id){ const r=await api(`/api/admin/detail/${resource}/${id}`); item={...item,...(r.data||{})}; }
    // 内容模型扩展字段（extra.*）：从 extra JSON 回填
    let _extra=item.extra;
    if(typeof _extra==='string'){ try{ _extra=JSON.parse(_extra||'{}'); }catch(e){ _extra={}; } }
    if(_extra && typeof _extra==='object'){
      fields.filter(f=>f.key&&String(f.key).startsWith('extra.')).forEach(f=>{
        const n=String(f.key).slice(6);
        /* 编辑回显：值为 undefined 或空串（默认值预填）时，用 extra 中保存的值覆盖 */
        if(item[f.key]===undefined || item[f.key]==='') item[f.key]=_extra[n]??f.value??'';
      });
    }
    current={resource,id,callback,fields,key};

    document.getElementById('dialog-title').textContent=(id?'编辑':'添加')+' '+(opts.title||data.title||resource);
    // 需求：去掉「正在编辑 ID #x 的记录」副标题；弹窗标题不带图标
    const subEl=document.getElementById('dialog-subtitle');
    subEl.textContent=''; subEl.style.display='none';

    // 布局：宽字段独占一行；窄字段两两配对，落单的窄字段铺满整行
    const blocks=[];
    let pairBuf=[];
    const flushPair=()=>{
      if(pairBuf.length===1) blocks.push({singles:[pairBuf[0]], span:12});
      else if(pairBuf.length>=2) blocks.push({singles:pairBuf.slice(0,2), span:6});
      pairBuf=[];
    };
    fields.forEach(f=>{
      if(f.type==='hidden'){ flushPair(); blocks.push({hidden:f}); return; }
      if(f.type==='section'){ flushPair(); blocks.push({section:f}); return; }
      if(isWide(f) || f.full){ flushPair(); blocks.push({single:f, span:12}); }
      else{
        if(pairBuf.length===2) flushPair();
        pairBuf.push(f);
      }
    });
    flushPair();
    const blockHtml=(b)=>{
      if(b.hidden) return control(b.hidden, item[b.hidden.key]);
      if(b.section) return `<div class="col-12 form-section-divider"><span>${esc(b.section.label||'扩展字段')}</span></div>`;
      if(b.single){
        const f=b.single;
        return `<div class="md:col-12">${f.type==='hidden'?'':labelHtml(f)}${control(f,item[f.key])}</div>`;
      }
      const cls=b.span===12?'md:col-12':'md:col-6';
      return b.singles.map(f=>`<div class="${cls}">${f.type==='hidden'?'':labelHtml(f)}${control(f,item[f.key])}</div>`).join('');
    };
    document.getElementById('dialog-body').innerHTML=`<form id="cms-form" class="cms-form" novalidate><div class="row g-3">${blocks.map(blockHtml).join('')}
      ${fields.length?'':'<div class="col-12 form-readonly"><i class="bi bi-lock"></i><b>只读模块</b><span>该模块暂无可编辑字段</span></div>'}</div></form>`;

    // 开关联动
    document.querySelectorAll('#dialog-body [data-switch]').forEach(ch=>{
      const t=ch.closest('.field-switch').querySelector('.sw-text');
      const sync=()=>{ t.textContent=ch.checked?'已启用':'已关闭'; t.classList.toggle('on',ch.checked); };
      ch.addEventListener('change',sync); sync();
    });

    // 图标弹窗选择
    fields.filter(f=>f.type==='icon').forEach(f=>bindIconPick(f, item[f.key]));
    // 权限树可视化选择
    fields.filter(f=>f.type==='perm_tree').forEach(f=>bindPermTree(f));
    // 统一上传组件
    fields.filter(f=>['image','gallery','image_single','image_multi','file_single','file_multi'].includes(f.type)).forEach(f=>{
      const slot=document.getElementById('upslot-'+f.key);
      if(!slot) return;
      UploadUI.mount(slot,{
        value:item[f.key]||'',
        multiple:['gallery','image_multi','file_multi'].includes(f.type),
        accept:f.accept||(['file_single','file_multi'].includes(f.type)?'file':'image'),
        label:f.label||'',
        title:f.title, hint:f.hint, ratio:f.ratio, types:f.types,
        maxSize:f.maxSize, libraryText:f.libraryText, icon:f.icon,
        crop:f.crop||f.key==='avatar',
        onChange:(vals)=>{
          const hidden=document.getElementById('fld-'+f.key);
          if(hidden) hidden.value = ['gallery','image_multi','file_multi'].includes(f.type) ? JSON.stringify(Array.isArray(vals)?vals:[]) : (vals||'');
        }
      });
    });

    // 标签编辑器 / 日期区间 / 弹窗关联选择 / 颜色选择
    fields.filter(f=>f.type==='tag').forEach(f=>bindTagField(f));
    fields.filter(f=>['date_range','datetime_range'].includes(f.type)).forEach(f=>bindRangeField(f));
    fields.filter(f=>f.type==='selectpage').forEach(f=>bindSelectpage(f));
    fields.filter(f=>f.type==='color').forEach(f=>{
      const inp=document.getElementById('fld-'+f.key);
      const hex=document.querySelector('#dialog-body [data-colorhex]');
      if(inp&&hex) inp.oninput=()=>{ hex.textContent=inp.value; };
    });

    // 富文本初始化（等弹窗显示后再初始化，避免宽度计算为 0）
    destroyEditors();
    setTimeout(()=>{ fields.filter(f=>['editor','body','main_content'].includes(f.type)).forEach(f=>initEditor(f)); }, 120);

    // 需求：新增时「所属分类」默认选中最后一个层级（缩进最深）的第一个选项
    if(!id){
      document.querySelectorAll('#dialog-body select[name="category_id"]').forEach(sel=>{
        const opts=[...sel.options].filter(o=>o.value && o.value!=='0');
        if(!opts.length) return;
        const depth=o=>{ const m=(o.textContent||'').match(/^\u3000+/); return m?m[0].length:0; };
        const maxD=Math.max(...opts.map(depth));
        const first=opts.find(o=>depth(o)===maxD);
        if(first) sel.value=first.value;
      });
    }

    // 编辑分类时不能选择自身作为父级
    if(id){
      document.querySelectorAll('#dialog-body select[name="pid"] option').forEach(o=>{ if(o.value===String(id)) o.remove(); });
    }

    // 可视化字段编辑器绑定
    fields.filter(f=>f.type==='json' && f.key==='fields' && (resource==='form_model'||resource==='content_type')).forEach(f=>bindVisualFields(f.key));

    // 校验规则
    setupValidation(fields);

    const saveBtn=document.getElementById('modal-save');
    const cancelBtn=document.getElementById('modal-cancel');
    saveBtn.style.display=data.readonly?'none':'';
    saveBtn.onclick=()=>submit();
    cancelBtn.onclick=()=>close();
    document.getElementById('modal-x').onclick=()=>close();

    modalInst = bootstrap.Dialog.getOrCreateInstance(document.getElementById('modal'));
    const modalEl=document.getElementById('modal');
    modalEl.addEventListener('hidden.bs.dialog',()=>btnLoading(saveBtn,false));
    modalInst.show();
    setTimeout(()=>{const first=document.querySelector('#dialog-body input:not([type=hidden]):not([data-switch]):not(.drop-file), #dialog-body textarea:not(.wangeditor-hidden), #dialog-body select');if(first)first.focus();},350);
  }

  /* ---------- 图标弹窗选择 ---------- */
  function bindIconPick(f, curVal){
    const btn=document.querySelector(`#dialog-body [data-iconfield="${f.key}"]`);
    const hidden=document.getElementById('fld-'+f.key);
    const previewEl=document.getElementById('icon-preview-'+f.key);
    if(!btn||!hidden) return;
    btn.onclick=async ()=>{
      await ensureIcons();
      const opts=ICONS.length?ICONS:[{value:hidden.value||'bi-file-earmark',label:'file-earmark'}];
      const cur=hidden.value||curVal||'bi-file-earmark';
      const el=ensureIconModal(opts, cur, (val)=>{
        hidden.value=val;
        if(previewEl) previewEl.className='bi '+val;
      });
      bootstrap.Dialog.getOrCreateInstance(el).show();
    };
  }
  function ensureIconModal(opts, cur, onPick){
    let el=document.getElementById('icon-modal');
    if(el) el.remove();
    el=document.createElement('dialog');
    el.id='icon-modal'; el.className='dialog dialog-lg dialog-scrollable icon-modal';
    el.innerHTML=`<div class="dialog-header"><h5 class="dialog-title">选择图标 <span class="badge-soft" id="icon-count"></span></h5>
        <button type="button" class="btn-close" data-bs-dismiss="dialog" aria-label="关闭"></button></div>
      <div class="dialog-body">
        <input type="search" class="form-control form-control-sm mb-2" id="icon-search" placeholder="搜索图标，如：home / user / heart / gear" autocomplete="off">
        <div class="icon-grid-modal" id="icon-grid-modal">${opts.map(o=>`<button type="button" class="icon-cell-modal ${o.value===cur?'active':''}" data-icon="${esc(o.value)}" data-bs-title="${esc(o.label||o.value)}"><i class="bi ${esc(o.value)}"></i></button>`).join('')}</div>
        <div class="list-empty" id="icon-empty" style="display:none;padding:24px 0">没有匹配的图标</div>
      </div>`;
    document.body.appendChild(el);
    el.querySelectorAll('.icon-cell-modal').forEach(c=>{
      c.onclick=()=>{ onPick(c.dataset.icon); bootstrap.Dialog.getOrCreateInstance(el).hide(); };
    });
    // 搜索过滤 + 数量提示 + 选中项滚动定位
    const grid=el.querySelector('#icon-grid-modal'), empty=el.querySelector('#icon-empty'),
          search=el.querySelector('#icon-search'), cnt=el.querySelector('#icon-count');
    if(cnt) cnt.textContent=opts.length+' 个图标';
    if(search) search.oninput=()=>{
      const q=search.value.trim().toLowerCase(); let n=0;
      grid.querySelectorAll('.icon-cell-modal').forEach(c=>{
        const hit=!q||c.dataset.icon.includes(q);
        c.style.display=hit?'':'none'; if(hit)n++;
      });
      if(empty) empty.style.display=n?'none':'block';
    };
    const active=grid.querySelector('.icon-cell-modal.active');
    if(active) setTimeout(()=>active.scrollIntoView({block:'center'}),350);
    return el;
  }
  /* 公共：弹出统一图标选择弹窗（后台所有图标选择都走这里） */
  async function pickIcon(cur, onPick){
    await ensureIcons();
    const opts=ICONS.length?ICONS:[{value:cur||'bi-file-earmark',label:cur||'默认'}];
    const el=ensureIconModal(opts, cur||'bi-file-earmark', (val)=>onPick&&onPick(val));
    bootstrap.Dialog.getOrCreateInstance(el).show();
  }

  /* ---------- 权限树可视化选择 ---------- */
  async function bindPermTree(f){
    const box=document.getElementById('pt-'+f.key);
    const hidden=document.getElementById('fld-'+f.key);
    if(!box||!hidden) return;
    let keys=[];
    try{ keys=JSON.parse(hidden.value||'[]'); }catch(e){ keys=[]; }
    const r=await api('/api/admin/perm-tree');
    const tree=r.data||[];
    if(!tree.length){ box.innerHTML='<div class="fg-secondary small">暂无权限节点</div>'; return; }
    const renderNodes=(nodes, depth)=>nodes.map(n=>{
      const checked=keys.includes(n.key);
      const kids=renderNodes(n.children||[], depth+1);
      return `<div class="perm-node" style="padding-left:${depth*24}px">
        <label class="perm-row">
          <input type="checkbox" class="check perm-check" data-key="${esc(n.key)}" ${checked?'checked':''}>
          <i class="bi ${esc(n.icon||'bi-dot')}"></i>
          <span class="perm-name">${esc(n.name)}</span>
          <span class="badge-soft perm-type">${n.type==='menu'?'菜单':n.type==='button'?'按钮':'接口'}</span>
        </label>
        ${kids}
      </div>`;
    }).join('');
    box.innerHTML=renderNodes(tree,0)+`<input type="hidden" name="${f.key}" id="fld-${esc(f.key)}" value="${esc(hidden.value||'[]')}">`;
    const sync=()=>{
      keys=[...box.querySelectorAll('.perm-check:checked')].map(c=>c.dataset.key);
      const h=document.getElementById('fld-'+f.key);
      if(h) h.value=JSON.stringify(keys);
    };
    box.querySelectorAll('.perm-check').forEach(c=>c.addEventListener('change',sync));
  }

  /* ---------- wangEditor 初始化 ---------- */
  function destroyEditors(){
    editors.forEach(e=>{try{e.destroy();}catch(x){}}); editors=[];
  }
  function initEditor(f){
    if(!window.wangEditor || !window.wangEditor.createEditor){ return; }
    const body=document.getElementById('webody-'+f.key);
    const hidden=document.getElementById('fld-'+f.key);
    if(!body || body.dataset.ready) return;
    body.dataset.ready='1';
    const token=localStorage.getItem('cms_token')||'';
    const ed=window.wangEditor.createEditor({
      selector:'#webody-'+f.key,
      html:hidden.value||'',
      /* wangEditor 官方 API：MENU_CONF / onChange 必须放在 config 内，
         放顶层会被静默忽略，导致上传图片时报“没有配置上传地址” */
      config:{
        MENU_CONF:{
          uploadImage:{
            server:'/api/admin/upload',
            fieldName:'file',
            headers:{'Authorization':'Bearer '+token},
            customInsert(res, insertFn){
              if(res && res.code===0 && res.data && res.data.url) insertFn(res.data.url, res.data.filename||'', res.data.url);
              else toast(res?.msg||'图片上传失败','error');
            },
            maxFileSize:10*1024*1024,
            allowedFileTypes:['image/*'],
          },
        },
        onChange(){ hidden.value = ed.getHtml(); },
      },
    });
    const toolbar=window.wangEditor.createToolbar({editor:ed, selector:'#wetb-'+f.key});
    // createEditor 内部已自动挂载编辑区；工具栏需手动 create
    try{ if(typeof toolbar.create==='function') toolbar.create(); }catch(e){}
    // 需求：可输入区域高度占满编辑器到底部（wangEditor 默认内联 300px）
    const tc=body.querySelector('.w-e-text-container');
    if(tc) tc.style.height='100%';
    const sc=body.querySelector('.w-e-scroll');
    if(sc) sc.style.height='100%';
    editors.push(ed,toolbar);
    body._ed=ed;
  }

  /* ---------- 可视化字段编辑器 ---------- */
  function bindVisualFields(key){
    const box=document.getElementById('vf-'+key);
    const rows=document.getElementById('vf-rows-'+key);
    const hidden=document.getElementById('fld-'+key);
    const add=document.getElementById('vf-add-'+key);
    if(!box||!rows) return;
    const OPT_TYPES=['select','radio','checkbox'];
    /* 从 DOM 行读回字段定义（含默认值与选项配置） */
    const readRow=(r)=>{
      const type=r.querySelector('.vf-type').value;
      const options=[...r.querySelectorAll('.vf-opt-row')].map(o=>({
        label:o.querySelector('.vf-opt-label').value.trim(),
        value:o.querySelector('.vf-opt-value').value.trim(),
      })).filter(o=>o.label&&o.value);
      return {
        label:r.querySelector('.vf-label').value.trim(),
        field:r.querySelector('.vf-key').value.trim(),
        type,
        default:r.querySelector('.vf-default').value,
        required:r.querySelector('.vf-required').checked?1:0,
        options:OPT_TYPES.includes(type)?options:[],
      };
    };
    const sync=()=>{
      const arr=[...rows.querySelectorAll('.vf-row')].map(readRow);
      hidden.value=JSON.stringify(arr);
      const empty=box.querySelector('.vf-empty');
      if(arr.length && empty) empty.remove();
    };
    /* 选项配置增删 */
    const bindOpts=(r)=>{
      const wrap=r.querySelector('.vf-opts');
      const addBtn=wrap.querySelector('.vf-opt-add');
      if(addBtn) addBtn.onclick=()=>{
        const div=document.createElement('div');
        div.innerHTML=`<div class="vf-opt-row">
          <input class="form-control form-control-sm vf-opt-label" placeholder="选项名称">
          <input class="form-control form-control-sm vf-opt-value" placeholder="选项值">
          <button type="button" class="vf-del vf-opt-del" title="删除选项"><i class="bi bi-trash3"></i></button></div>`;
        const row=div.firstElementChild;
        wrap.insertBefore(row, addBtn);
        row.querySelector('.vf-opt-del').onclick=()=>{ row.remove(); sync(); };
        row.querySelectorAll('input').forEach(el=>el.addEventListener('input',sync));
        row.querySelector('.vf-opt-label').focus();
        sync();
      };
      wrap.querySelectorAll('.vf-opt-row').forEach(o=>{
        o.querySelector('.vf-opt-del').onclick=()=>{ o.remove(); sync(); };
        o.querySelectorAll('input').forEach(el=>el.addEventListener('input',sync));
      });
    };
    const bindRow=(r)=>{
      r.querySelector('.vf-del').onclick=()=>{r.remove();sync();};
      r.querySelectorAll('input,select').forEach(el=>{
        el.addEventListener('input',sync);
        el.addEventListener('change',sync);
      });
      /* 类型切换：显示/隐藏选项配置 */
      r.querySelector('.vf-type').addEventListener('change',()=>{
        const wrap=r.querySelector('.vf-opts');
        if(wrap) wrap.style.display=OPT_TYPES.includes(r.querySelector('.vf-type').value)?'block':'none';
      });
      bindOpts(r);
      /* 整行拖动排序（鼠标移上去按住拖动） */
      r.addEventListener('dragstart',e=>{
        rows._drag=r; r.classList.add('vf-dragging'); e.dataTransfer.effectAllowed='move';
      });
      r.addEventListener('dragend',()=>{
        r.classList.remove('vf-dragging');
        rows._drag=null;
        /* 按 DOM 顺序重排并同步 */
        const ordered=[...rows.querySelectorAll('.vf-row')];
        ordered.forEach((x,i)=>x.dataset.idx=i);
        sync();
      });
    };
    rows.addEventListener('dragover',e=>{
      if(!rows._drag) return;
      e.preventDefault();
      const target=e.target.closest('.vf-row');
      if(!target||target===rows._drag) return;
      const rect=target.getBoundingClientRect();
      const after=e.clientY > rect.top + rect.height/2;
      if(after) target.after(rows._drag); else target.before(rows._drag);
    });
    rows.addEventListener('drop',e=>e.preventDefault());
    rows.querySelectorAll('.vf-row').forEach(bindRow);
    add.onclick=()=>{
      const div=document.createElement('div');
      div.innerHTML=vfRow({},rows.children.length);
      const row=div.firstElementChild; rows.appendChild(row); bindRow(row); sync();
      row.querySelector('.vf-label').focus();
    };
  }

  /* ---------- 标签编辑器（英文逗号拼接入库） ---------- */
  function bindTagField(f){
    const box=document.getElementById('tage-'+f.key);
    const hidden=document.getElementById('fld-'+f.key);
    if(!box||!hidden) return;
    const chips=box.querySelector('[data-chips]');
    const input=box.querySelector('.tag-input');
    const render=()=>{
      const tags=hidden.value.split(',').map(s=>s.trim()).filter(Boolean);
      chips.innerHTML=tags.map(t=>`<span class="tag-chip">${esc(t)}<i class="bi bi-x-lg" data-tagdel="${esc(t)}" title="删除"></i></span>`).join('');
      chips.querySelectorAll('[data-tagdel]').forEach(x=>x.onclick=()=>{
        const cur=hidden.value.split(',').map(s=>s.trim()).filter(Boolean);
        const i=cur.indexOf(x.dataset.tagdel);
        if(i>-1) cur.splice(i,1);
        hidden.value=cur.join(',');
        render();
      });
    };
    const add=()=>{
      const v=input.value.replace(/,/g,' ').trim();
      if(!v) return;
      const cur=hidden.value.split(',').map(s=>s.trim()).filter(Boolean);
      if(!cur.includes(v)){ cur.push(v); hidden.value=cur.join(','); render(); }
      input.value='';
    };
    input.addEventListener('keydown',e=>{ if(e.key==='Enter'){ e.preventDefault(); add(); } });
    input.addEventListener('blur',add);
    render();
  }

  /* ---------- 日期/日期时间区间（两输入联动隐藏值，英文逗号拼接） ---------- */
  function bindRangeField(f){
    const hidden=document.getElementById('fld-'+f.key);
    if(!hidden) return;
    const wrap=hidden.parentElement.querySelector('.range-field');
    if(!wrap) return;
    const s=wrap.querySelector('[data-range-start]'), e=wrap.querySelector('[data-range-end]');
    const sync=()=>{
      const a=String(s.value||'').replace('T',' '), b=String(e.value||'').replace('T',' ');
      hidden.value=[a,b].filter(Boolean).join(',');
    };
    s.addEventListener('change',sync);
    e.addEventListener('change',sync);
  }

  /* ---------- 弹窗关联选择（selectpage） ---------- */
  function bindSelectpage(f){
    const wrap=document.getElementById('sp-'+f.key);
    if(!wrap) return;
    const hidden=document.getElementById('fld-'+f.key);
    const display=wrap.querySelector('.sp-display');
    const rel=wrap.dataset.rel;
    let titleMap={};
    const idList=()=>hidden.value.split(',').map(s=>s.trim()).filter(Boolean);
    const syncDisplay=()=>{
      const ids=idList();
      display.value=ids.length?ids.map(id=>titleMap[id]||('#'+id)).join('、'):'';
    };
    const loadTitles=async ()=>{
      if(!rel||!idList().length) return;
      try{
        const r=await api(`/api/admin/list/content?model=${encodeURIComponent(rel)}&page=1&size=200`);
        ((r.data&&r.data.list)||[]).forEach(row=>{ titleMap[String(row.id)]=row.title; });
      }catch(e){}
      syncDisplay();
    };
    wrap.querySelector('[data-spclear]').onclick=()=>{ hidden.value=''; syncDisplay(); };
    wrap.querySelector('[data-sppick]').onclick=async ()=>{
      if(!rel){ toast('该字段未配置关联模型，请在内容模型字段管理中设置','error'); return; }
      await loadTitles();
      openSelectpageModal(rel, idList(), (ids)=>{ hidden.value=ids.join(','); syncDisplay(); });
    };
    loadTitles();
  }
  function openSelectpageModal(rel, selected, onOk){
    let el=document.getElementById('sp-modal');
    if(el) el.remove();
    el=document.createElement('dialog');
    el.id='sp-modal'; el.className='dialog dialog-lg dialog-scrollable';
    el.innerHTML=`<div class="dialog-header"><h5 class="dialog-title"><i class="bi bi-link-45deg"></i> 选择关联内容</h5>
        <button type="button" class="btn-close" data-bs-dismiss="dialog" aria-label="关闭"></button></div>
      <div class="dialog-body">
        <input type="search" class="form-control form-control-sm mb-2" id="sp-kw" placeholder="搜索标题关键词，回车或输入自动搜索" autocomplete="off">
        <div id="sp-list" class="sp-list"><div class="fg-secondary p-3"><i class="bi bi-arrow-repeat spin"></i> 正在加载…</div></div>
      </div>
      <div class="dialog-footer">
        <span class="fg-secondary small me-auto" id="sp-count"></span>
        <button type="button" class="btn btn-solid theme-secondary" data-bs-dismiss="dialog">取消</button>
        <button type="button" class="btn btn-solid theme-primary" id="sp-ok"><i class="bi bi-check-lg"></i> 确定</button>
      </div>`;
    document.body.appendChild(el);
    const picked=new Set(selected);
    const listEl=el.querySelector('#sp-list'), kw=el.querySelector('#sp-kw'), cnt=el.querySelector('#sp-count');
    const syncCnt=()=>{ cnt.textContent=`已选 ${picked.size} 项（保存为内容 ID，英文逗号拼接）`; };
    const load=async ()=>{
      const params=new URLSearchParams({model:rel, page:'1', size:'100'});
      const k=kw.value.trim(); if(k) params.set('keyword', k);
      const r=await api('/api/admin/list/content?'+params.toString());
      const rows=(r.data&&r.data.list)||[];
      listEl.innerHTML=rows.length?rows.map(row=>`<label class="sp-row"><input type="checkbox" class="check" value="${row.id}" ${picked.has(String(row.id))?'checked':''}><span class="sp-title">${esc(row.title||('ID '+row.id))}</span><span class="fg-secondary small">ID ${row.id}</span></label>`).join(''):'<div class="list-empty">没有匹配的内容</div>';
      listEl.querySelectorAll('input[type=checkbox]').forEach(cb=>cb.onchange=()=>{
        if(cb.checked) picked.add(cb.value); else picked.delete(cb.value);
        syncCnt();
      });
    };
    kw.addEventListener('input',()=>{ clearTimeout(el._t); el._t=setTimeout(load,300); });
    syncCnt();
    el.querySelector('#sp-ok').onclick=()=>{ onOk([...picked]); bootstrap.Dialog.getOrCreateInstance(el).hide(); };
    bootstrap.Dialog.getOrCreateInstance(el).show();
    load();
  }

  /* ---------- JustValidate 校验 ---------- */
  function setupValidation(fields){
    if(validator){ try{validator.destroy();}catch(e){} validator=null; }
    if(!window.JustValidate) return;
    const rules={};
    fields.forEach(f=>{
      if(!f.required || ['switch','hidden','image','gallery','image_single','image_multi','file_single','file_multi','icon','perm_tree','radio','checkbox','selectpage','date_range','datetime_range'].includes(f.type)) return;
      /* 字段 key 可能含点号（extra.xxx），CSS 选择器需转义 */
      const sel='#fld-'+f.key.replace(/\./g,'\\.');
      rules[sel] = [{ rule:'required', errorMessage:`「${f.label}」不能为空` }];
      if(f.type==='number') rules[sel].push({rule:'number',errorMessage:`「${f.label}」必须是数字`});
    });
    if(!Object.keys(rules).length) return;
    validator = new window.JustValidate('#cms-form',{
      errorFieldCssClass:'is-invalid',
      errorLabelCssClass:'field-error',
      focusInvalidField:false,
      lockForm:false,
    });
    Object.entries(rules).forEach(([sel,rs])=>validator.addField(sel,rs));
  }

  function close(){
    if(validator){ try{validator.destroy();}catch(e){} validator=null; }
    destroyEditors();
    if(modalInst) modalInst.hide();
  }

  function collectBody(){
    const body={};
    document.querySelectorAll('#dialog-body [name]').forEach(el=>{
      if(el.dataset.switch) body[el.name]=el.checked?1:0;
      else if(el.type==='radio'){ if(el.checked) body[el.name]=el.value; }  /* 单选组：只取选中项 */
      else if(el.type==='checkbox' && el.classList.contains('chk-input')){  /* 多选组：逗号拼接 */
        if(el.checked) body[el.name]=(body[el.name]?body[el.name]+',':'')+el.value;
      }
      else if(el.type==='datetime-local'){  /* 日期时间：转库格式（YYYY-MM-DD HH:MM:SS） */
        let dv=String(el.value||'').replace('T',' ');
        if(dv.length===16) dv+=':00';
        body[el.name]=dv;
      }
      else body[el.name]=el.value;
    });
    return body;
  }

  async function submit(){
    if(!current) return;
    /* 需求（2026-11-24）：有文件正在上传时不允许保存 */
    if(window.UploadUI && UploadUI.isUploading && UploadUI.isUploading()){
      toast('上传处理中，请等待上传完成后再保存','warning'); return;
    }
    // 富文本内容同步（onChange 已同步，这里兜底）
    current.fields.filter(f=>['editor','body','main_content'].includes(f.type)).forEach(f=>{
      const bodyEl=document.getElementById('webody-'+f.key);
      const hidden=document.getElementById('fld-'+f.key);
      if(bodyEl && bodyEl._ed && hidden && typeof bodyEl._ed.getHtml==='function') hidden.value=bodyEl._ed.getHtml();
    });
    const body=collectBody();
    if(current.id) body.id=current.id;
    /* admin_pwd_rule_check: 管理员密码按后台配置的正则 + 文案校验 */
    if(current.resource==='admin_user'){
      const pv=String(body.password_hash||'');
      if(pv || !current.id){
        const rule=await C.getPasswordRule();
        if(!C.checkPassword(pv,rule)){ toast(rule.tip,'error'); return; }
      }
    }

    // 必填校验：以自有逻辑为准（可靠），JustValidate 只负责显示字段级错误提示
    const missing=[];
    for(const f of current.fields){
      if(!f.required || ['switch','hidden','gallery','image_multi','file_single','file_multi','icon','selectpage','date_range','datetime_range'].includes(f.type)) continue;
      let val;
      if(f.type==='image' || f.type==='image_single'){
        val=String(body[f.key]??'');
      }else if(f.type==='perm_tree'){
        let arr=[]; try{arr=JSON.parse(body[f.key]||'[]');}catch(e){}
        val=Array.isArray(arr)&&arr.length?'1':'';
      }else{
        val=String(body[f.key]??'');
      }
      // 富文本内容去掉 HTML 标签后判空
      const plain=['editor','body','main_content'].includes(f.type)?val.replace(/<[^>]*>/g,'').replace(/&nbsp;/g,' ').trim():val.trim();
      if(!plain) missing.push(f.label);
    }
    if(missing.length){
      if(window.JustValidate && validator){ try{ await validator.validate(); }catch(e){} }
      scrollToFirstInvalid();
      toast('请完善必填项：'+missing.join('、'),'error');
      return;
    }
    // JustValidate 附加校验（数字格式等）
    if(window.JustValidate && validator){
      try{ const valid=await validator.validate(); if(!valid){ scrollToFirstInvalid(); toast('请检查填写内容','error'); return; } }catch(e){}
    }

    // 需求：分类「访问别名」必须英文字母开头，仅可包含字母/数字/_/-
    if(current.resource==='category'){
      const slug=String(body.slug||'').trim();
      if(!/^[A-Za-z][A-Za-z0-9_-]*$/.test(slug)){
        toast('「访问别名」必须以英文字母开头，仅可包含英文字母、数字、下划线(_)和连字符(-)','error'); return;
      }
    }
    const saveBtn=document.getElementById('modal-save');
    btnLoading(saveBtn,true);
    const r=await post(`/api/admin/save/${current.resource}`,body);
    btnLoading(saveBtn,false);
    if(r.code===0){ toast('保存成功'); close(); if(current.callback) current.callback(); }
    else toast(r.msg||'保存失败','error');
  }
  /* 需求（2026-11-24）：校验失败时自动滚动到第一个失败项（始终是第一个验证失败的字段），带缓动动画 */
  const COL_SEL='.md\\:col-6,.md\\:col-12,.col-12';
  function scrollToFirstInvalid(){
    let bad=document.querySelector('#dialog-body .is-invalid, #dialog-body .field-error');
    if(!bad){
      /* 兜底：按字段顺序找第一个空必填项（getElementById 不需要转义点号） */
      for(const f of (current&&current.fields||[])){
        const elc=document.getElementById('fld-'+(f.key||''));
        if(elc && !String(elc.value||'').trim()){ bad=elc; break; }
      }
    }
    if(!bad) return;
    const wrap=(bad.closest && bad.closest(COL_SEL))||bad;
    /* 找最近的可滚动祖先（弹窗 dialog 本身） */
    let scroller=null, node=wrap.parentElement;
    while(node && node!==document.body){
      const oy=getComputedStyle(node).overflowY;
      if((oy==='auto'||oy==='scroll') && node.scrollHeight>node.clientHeight){ scroller=node; break; }
      node=node.parentElement;
    }
    /* 自定义缓动滚动：easeInOutCubic，620ms，比 scrollIntoView 更可控 */
    const target=Math.max(0, wrap.getBoundingClientRect().top + (scroller?scroller.scrollTop:window.pageYOffset)
      - (scroller?scroller.getBoundingClientRect().top:0) - (scroller?scroller.clientHeight:window.innerHeight)/2 + wrap.getBoundingClientRect().height/2);
    if(scroller){
      const from=scroller.scrollTop, dist=target-from, t0=performance.now(), dur=620;
      const ease=(t)=>t<0.5 ? 4*t*t*t : 1-Math.pow(-2*t+2,3)/2;
      const step=(now)=>{
        const t=Math.min(1,(now-t0)/dur);
        scroller.scrollTop=from+dist*ease(t);
        if(t<1) requestAnimationFrame(step);
        else { try{ ctlFocus(); }catch(e){} }
      };
      requestAnimationFrame(step);
    }else{
      try{ window.scrollTo({top:target,behavior:'smooth'}); }catch(e){ window.scrollTo(0,target); }
      setTimeout(ctlFocus, 400);
    }
    function ctlFocus(){
      const ctl=(bad.classList && bad.classList.contains('is-invalid')?bad:wrap.querySelector('input,select,textarea'))||bad;
      if(ctl && ctl.focus){ try{ ctl.focus({preventScroll:true}); }catch(e){ ctl.focus(); } }
    }
  }

  function missingFields(){
    return [...document.querySelectorAll('#cms-form .field-error, #cms-form .is-invalid')].map(el=>{
      const lbl=el.closest(COL_SEL)?.querySelector('.form-label');
      return lbl?lbl.textContent.replace('*','').trim():'必填项';
    }).filter(Boolean);
  }

  return {open, close, pickIcon};
})();
