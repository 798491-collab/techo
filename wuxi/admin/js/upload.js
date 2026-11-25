/* 统一上传组件：缩略图预览列表 + 拖拽上传 + 素材库选择 + 正方形裁剪 + 大图预览
   所有涉及 文件/图片/附件/头像 的表单统一使用本组件。
   API：
     UploadUI.mount(el, {value, multiple, accept, crop, onChange(values)})
     UploadUI.pickLibrary({multiple, accept}) -> Promise<urls[]>
     UploadUI.crop(url) -> Promise<uploadedUrl>
     UploadUI.preview(url) */
window.UploadUI = (function(){
  const C = window.CMS;
  const {api, toast, esc} = C;
  const token = () => localStorage.getItem('cms_token') || '';

  const isImg = (u) => /\.(png|jpe?g|gif|webp|bmp|svg)(\?|$)/i.test(u||'') || /^data:image/.test(u||'');
  const fileIcon = (u) => /\.(pdf)(\?|$)/i.test(u||'') ? 'bi-file-earmark-pdf' :
    /\.(xls|xlsx|csv)(\?|$)/i.test(u||'') ? 'bi-file-earmark-excel' :
    /\.(doc|docx)(\?|$)/i.test(u||'') ? 'bi-file-earmark-word' :
    /\.(zip|rar|7z)(\?|$)/i.test(u||'') ? 'bi-file-earmark-zip' :
    /\.(mp4|webm)(\?|$)/i.test(u||'') ? 'bi-file-earmark-play' : 'bi-file-earmark';

  function parseValues(v){
    if(!v) return [];
    if(Array.isArray(v)) return v.filter(Boolean);
    const s = String(v).trim();
    if(!s) return [];
    if(s.startsWith('[')){ try{ const a=JSON.parse(s); return Array.isArray(a)?a.filter(Boolean):[s]; }catch(e){ return [s]; } }
    return [s];
  }

  /* 全局上传计数：任一组件上传中即视为「上传处理中」 */
  let uploadCount=0;
  /* ---------------- 上传单个文件（XHR 支持进度回调） ---------------- */
  function uploadFile(file, onProgress){
    return new Promise((resolve, reject)=>{
      const fd = new FormData(); fd.append('file', file);
      const xhr = new XMLHttpRequest();
      xhr.open('POST', '/api/admin/upload');
      xhr.setRequestHeader('Authorization', 'Bearer '+token());
      xhr.upload.onprogress = (e)=>{ if(e.lengthComputable && onProgress) onProgress(e.loaded/e.total); };
      xhr.onload = ()=>{
        let json={}; try{ json=JSON.parse(xhr.responseText); }catch(e){}
        if(json.code===0 && json.data && json.data.url) resolve(json.data.url);
        else reject(new Error(json.msg || '上传失败'));
      };
      xhr.onerror = ()=>reject(new Error('上传失败'));
      xhr.send(fd);
    });
  }

  /* ---------------- 弹窗基础设施 ---------------- */
  function ensureModal(id, inner, cls){
    let el = document.getElementById(id);
    if(!el){
      el = document.createElement('dialog');
      el.id = id; el.className = 'dialog ' + (cls||'');
      el.setAttribute('data-bs-backdrop','static');
      el.innerHTML = inner;
      document.body.appendChild(el);
    } else {
      el.innerHTML = inner;
    }
    return el;
  }

  /* ---------------- 大图预览（PDF 内嵌预览） ---------------- */
  function preview(url){
    const isPdf=/\.(pdf)(\?|$)/i.test(url||'');
    const body=isPdf
      ? `<iframe src="${esc(url)}" title="PDF 预览"></iframe>`
      : isImg(url)?`<img src="${esc(url)}" alt="预览">`
      : `<div class="up-file-view"><i class="bi ${fileIcon(url)}"></i><p>${esc(url.split('/').pop())}</p></div>`;
    const el = ensureModal('up-preview-modal', `
      <div class="up-preview-content">
        <div class="dialog-header"><h5 class="dialog-title">${isPdf?'PDF 预览':'预览'}</h5>
          <button type="button" class="btn-close" data-bs-dismiss="dialog" aria-label="关闭"></button></div>
        <div class="dialog-body up-preview-body">${body}</div>
      </div>`, 'up-preview-modal-c');
    bootstrap.Dialog.getOrCreateInstance(el).show();
  }

  /* ---------------- 素材库选择 ---------------- */
  let libState = {page:1, type:'image', total:0, selected:[], multiple:false, resolve:null, accept:'image'};
  function pickLibrary(opts){
    opts = opts||{};
    return new Promise(resolve=>{
      libState = {page:1, type: opts.accept==='file'?'file':'image', total:0, selected:[], multiple:!!opts.multiple, resolve, accept:opts.accept||'image'};
      const el = ensureModal('up-lib-modal', `
        <div class="">
          <div class="dialog-header"><h5 class="dialog-title">素材库</h5>
            <button type="button" class="btn-close" data-bs-dismiss="dialog" aria-label="关闭"></button></div>
          <div class="dialog-body">
            <div class="up-lib-toolbar">
              <select class="form-control form-control-sm" id="up-lib-type" style="width:130px">
                <option value="image">图片</option><option value="file">文件</option>
              </select>
              <button type="button" class="btn btn-sm btn-solid theme-primary" id="up-lib-upload"><i class="bi bi-cloud-arrow-up"></i> 上传文件</button>
              <input type="file" id="up-lib-file" ${libState.multiple?'multiple':''} accept="${opts.accept==='file'?'':'image/*'}" hidden>
              <span class="fg-secondary small ms-auto" id="up-lib-count"></span>
            </div>
            <div class="up-lib-grid" id="up-lib-grid"><div class="up-lib-loading"><img class="gl-spinner" src="./static/svg/loading-2.svg?v=${window.STATIC_VER||"1"}" alt=""></div></div>
            <div class="up-lib-pager" id="up-lib-pager"></div>
          </div>
          <div class="dialog-footer">
            <button type="button" class="btn btn-subtle theme-secondary" data-bs-dismiss="dialog">取 消</button>
            <button type="button" class="btn btn-solid theme-primary" id="up-lib-ok">确 定</button>
          </div>
        </div>`, 'up-lib-modal-c');
      el.querySelector('#up-lib-type').value = libState.type;
      el.querySelector('#up-lib-type').onchange = (e)=>{ libState.type=e.target.value; libState.page=1; loadLib(); };
      el.querySelector('#up-lib-upload').onclick = ()=>el.querySelector('#up-lib-file').click();
      el.querySelector('#up-lib-file').onchange = async (e)=>{
        const files=[...e.target.files]; if(!files.length) return;
        toast(`正在上传 ${files.length} 个文件…`,'info');
        let ok=0;
        for(const f of files){ try{ await uploadFile(f); ok++; }catch(err){ toast(f.name+'：'+err.message,'error'); } }
        if(ok) toast(`已上传 ${ok} 个文件`);
        e.target.value=''; libState.page=1; loadLib();
      };
      el.querySelector('#up-lib-ok').onclick = ()=>{
        const sel=[...libState.selected];
        if(!sel.length){ toast('请先选择素材','error'); return; }
        if(!libState.multiple && sel.length>1){ toast('只能选择一个文件','error'); return; }
        bootstrap.Dialog.getOrCreateInstance(el).hide();
        libState.resolve && libState.resolve(sel);
      };
      el.addEventListener('hidden.bs.dialog', ()=>{ if(libState.resolve){ libState.resolve(null); libState.resolve=null; } }, {once:true});
      bootstrap.Dialog.getOrCreateInstance(el).show();
      loadLib();
    });
  }

  async function loadLib(){
    const grid=document.getElementById('up-lib-grid'), pager=document.getElementById('up-lib-pager');
    if(!grid) return;
    const size=24;
    const r=await api(`/api/admin/list/media?page=${libState.page}&size=${size}&file_type=${libState.type}`);
    const d=r.data||{}; const list=d.list||[];
    libState.total=d.total||0;
    const cnt=document.getElementById('up-lib-count');
    if(cnt) cnt.textContent=`共 ${libState.total} 个素材` + (libState.selected.length?`，已选 ${libState.selected.length} 个`:'');
    if(!list.length){ grid.innerHTML='<div class="up-lib-empty"><i class="bi bi-inbox"></i>素材库为空，点击「上传文件」添加</div>'; pager.innerHTML=''; return; }
    grid.innerHTML=list.map(m=>{
      const url=m.path||m.storage_path||'';
      const sel=libState.selected.includes(url);
      return `<div class="up-lib-cell ${sel?'sel':''}" data-url="${esc(url)}" title="${esc(m.filename||'')}">
        ${isImg(url)?`<img src="${esc(url)}" loading="lazy" alt="">`:`<div class="up-lib-file"><i class="bi ${fileIcon(url)}"></i><small>${esc((m.filename||'').slice(0,14))}</small></div>`}
        <span class="up-lib-check"><i class="bi bi-check-lg"></i></span>
      </div>`;
    }).join('');
    grid.querySelectorAll('.up-lib-cell').forEach(cell=>{
      cell.onclick=()=>{
        const url=cell.dataset.url;
        if(libState.multiple){
          const i=libState.selected.indexOf(url);
          if(i>=0) libState.selected.splice(i,1); else libState.selected.push(url);
          cell.classList.toggle('sel');
        } else {
          libState.selected=[url];
          grid.querySelectorAll('.up-lib-cell').forEach(c=>c.classList.toggle('sel',c===cell));
        }
        const cnt=document.getElementById('up-lib-count');
        if(cnt) cnt.textContent=`共 ${libState.total} 个素材` + (libState.selected.length?`，已选 ${libState.selected.length} 个`:'');
      };
    });
    const pages=Math.max(1, Math.ceil(libState.total/size));
    pager.innerHTML=`<button class="btn btn-sm btn-subtle theme-secondary" id="up-lib-prev" ${libState.page<=1?'disabled':''}><i class="bi bi-chevron-left"></i></button>
      <span class="fg-secondary small">${libState.page} / ${pages}</span>
      <button class="btn btn-sm btn-subtle theme-secondary" id="up-lib-next" ${libState.page>=pages?'disabled':''}><i class="bi bi-chevron-right"></i></button>`;
    const prev=document.getElementById('up-lib-prev'), next=document.getElementById('up-lib-next');
    if(prev) prev.onclick=()=>{ libState.page--; loadLib(); };
    if(next) next.onclick=()=>{ libState.page++; loadLib(); };
  }

  /* ---------------- 正方形裁剪 ---------------- */
  const STAGE=320, OUT=400;
  function crop(url){
    return new Promise((resolve,reject)=>{
      const img=new Image();
      img.crossOrigin='anonymous';
      img.onload=()=>{
        const el=ensureModal('up-crop-modal', `
          <div class="">
            <div class="dialog-header"><h5 class="dialog-title">裁剪图片</h5>
              <button type="button" class="btn-close" data-bs-dismiss="dialog" aria-label="关闭"></button></div>
            <div class="dialog-body">
              <p class="fg-secondary small mb-2">拖动调整位置，滚轮或滑块缩放，裁剪区域为正方形</p>
              <div class="crop-stage" id="crop-stage"><img id="crop-img" src="${esc(url)}" alt="" draggable="false"></div>
              <div class="crop-zoom"><i class="bi bi-zoom-out"></i><input type="range" id="crop-range" min="0" max="100" value="0"><i class="bi bi-zoom-in"></i></div>
            </div>
            <div class="dialog-footer">
              <button type="button" class="btn btn-subtle theme-secondary" id="crop-cancel">取 消</button>
              <button type="button" class="btn btn-solid theme-primary" id="crop-ok">确认裁剪</button>
            </div>
          </div>`, 'up-crop-modal-c');
        const stage=el.querySelector('#crop-stage'), cimg=el.querySelector('#crop-img'), range=el.querySelector('#crop-range');
        let scale=1, x=0, y=0;   // x/y 为图片中心相对舞台中心的偏移
        const natW=img.naturalWidth, natH=img.naturalHeight;
        const minScale=Math.max(STAGE/natW, STAGE/natH);
        scale=minScale;
        const clamp=()=>{
          const half=Math.max(0,(natW*scale-STAGE)/2);
          x=Math.min(half,Math.max(-half,x));
          const halfY=Math.max(0,(natH*scale-STAGE)/2);
          y=Math.min(halfY,Math.max(-halfY,y));
        };
        const render=()=>{ clamp(); cimg.style.width=(natW*scale)+'px'; cimg.style.height=(natH*scale)+'px';
          cimg.style.left=(STAGE/2-natW*scale/2+x)+'px'; cimg.style.top=(STAGE/2-natH*scale/2+y)+'px'; };
        render();
        const setZoom=(p)=>{ scale=minScale*(1+p*2); render(); };   // 0~100 → 1x~3x minScale
        range.oninput=(e)=>setZoom(+e.target.value/100);
        stage.onwheel=(e)=>{ e.preventDefault();
          const d=e.deltaY<0?0.08:-0.08;
          let p=Math.round(Math.min(100,Math.max(0,(scale/minScale-1)/2*100 + d*100)));
          range.value=p; setZoom(p/100); };
        let drag=null;
        cimg.onmousedown=(e)=>{ e.preventDefault(); drag={sx:e.clientX, sy:e.clientY, ox:x, oy:y}; };
        window.addEventListener('mousemove', mv); window.addEventListener('mouseup', up);
        function mv(e){ if(!drag) return; x=drag.ox+(e.clientX-drag.sx); y=drag.oy+(e.clientY-drag.sy); render(); }
        function up(){ drag=null; }
        el.addEventListener('hidden.bs.dialog', ()=>{ window.removeEventListener('mousemove',mv); window.removeEventListener('mouseup',up); }, {once:true});
        el.querySelector('#crop-cancel').onclick=()=>{ bootstrap.Dialog.getOrCreateInstance(el).hide(); resolve(null); };
        el.querySelector('#crop-ok').onclick=()=>{
          clamp();
          const cv=document.createElement('canvas'); cv.width=OUT; cv.height=OUT;
          const ctx=cv.getContext('2d');
          const sx=(STAGE/2-x-natW*scale/2)/scale, sy=(STAGE/2-y-natH*scale/2)/scale, sw=STAGE/scale;
          ctx.fillStyle='#fff'; ctx.fillRect(0,0,OUT,OUT);
          try{ ctx.drawImage(img, sx, sy, sw, sw, 0, 0, OUT, OUT); }catch(e){ toast('裁剪失败：图片跨域','error'); return; }
          cv.toBlob(async (blob)=>{
            if(!blob){ toast('裁剪失败','error'); return; }
            try{
              const f=new File([blob],'crop_'+Date.now()+'.png',{type:'image/png'});
              const u=await uploadFile(f);
              bootstrap.Dialog.getOrCreateInstance(el).hide();
              resolve(u);
            }catch(err){ toast(err.message||'上传失败','error'); }
          }, 'image/png');
        };
        bootstrap.Dialog.getOrCreateInstance(el).show();
      };
      img.onerror=()=>{ toast('图片加载失败','error'); reject(new Error('加载失败')); };
      img.src=url;
    });
  }

  /* ---------------- 挂载上传控件（大上传区：右上角素材库入口 + 居中图标/标题/提示 + 下方文件列表）
       参数：{value, multiple, accept:'image'|'file', crop, title, hint, ratio, libraryText, onChange}
       title / hint 不传时按 accept、multiple、label 智能生成；全部可覆盖。 ---------------- */
  function mount(el, opts){
    opts=opts||{};
    const multiple=!!opts.multiple;
    const accept=opts.accept||'image';
    const isFile=accept==='file';
    const label=opts.label||'';
    // 默认标题 / 提示（可被 opts.title / opts.hint 覆盖）
    const defTitle=multiple
      ? (isFile?'点击或拖拽上传文件':'点击或拖拽上传图片')
      : (label?`点击或拖拽上传${label}`:'点击或拖拽上传'+(isFile?'文件':'图片'));
    const typeHint=isFile?'支持任意格式文件':(opts.types||'支持 JPG / PNG');
    const ratioHint=opts.ratio?`推荐比例 ${opts.ratio} · `:'';
    const defHint=`${ratioHint}单张最大 ${opts.maxSize||'5MB'} · ${typeHint}`;
    const title=opts.title||defTitle;
    const hint=opts.hint||defHint;
    const libText=opts.libraryText||'从素材库选择';
    const icon=opts.icon||(isFile?'bi-cloud-arrow-up':'bi-image');
    let values=parseValues(opts.value);
    if(!multiple) values=values.slice(0,1);
    el.classList.add('upload-ui');
    /* 保留 uploadHtml 预置的隐藏 input（承载字段值，inner覆盖后会丢失导致保存缺字段） */
    const prevHidden=el.querySelector('input[type=hidden]');
    if(opts.drag===false){
      /* 需求：可关闭拖拽上传（默认开启）——关闭后仅保留上传按钮，无拖拽区、无素材库入口 */
      el.classList.add('upload-btnmode');
      el.innerHTML=`<div class="up-btn-box" title="${esc(title||'点击上传')}">
          <i class="bi bi-plus-lg"></i><span>上传</span>
        </div>
        <div class="up-list" id="${el.id||''}-list"></div>
        <input type="file" class="up-file" ${multiple?'multiple':''} ${isFile?'':'accept="image/*"'} hidden>`;
    } else {
      el.innerHTML=`<div class="up-dropzone" title="${esc(title)}">
        <button type="button" class="up-lib-btn"><i class="bi bi-collection"></i> ${esc(libText)}</button>
        <div class="up-dz-body">
          <div class="up-dz-icon"><i class="bi ${icon}"></i></div>
          <div class="up-dz-title">${esc(title)}</div>
          <div class="up-dz-hint">${esc(hint)}</div>
        </div>
      </div>
      <div class="up-list" id="${el.id||''}-list"></div>
      <input type="file" class="up-file" ${multiple?'multiple':''} ${isFile?'':'accept="image/*"'} hidden>`;
    }
    if(prevHidden) el.appendChild(prevHidden);
    const zone=el.querySelector('.up-dropzone, .up-btn-box'), list=el.querySelector('.up-list'), fileInput=el.querySelector('.up-file');

    const emit=()=>{ opts.onChange && opts.onChange(multiple?[...values]:(values[0]||'')); };

    function thumbHtml(u){
      const inner=isImg(u)?`<img src="${esc(u)}" alt="">`:`<div class="up-thumb-file"><i class="bi ${fileIcon(u)}"></i><span>${esc(u.split('/').pop())}</span></div>`;
      return `<div class="up-thumb" data-url="${esc(u)}" title="${esc(u.split('/').pop())}">${inner}
        <div class="up-mask">
          <button type="button" class="up-act" data-act="view" title="预览"><i class="bi bi-eye"></i></button>
          <button type="button" class="up-act up-del" data-act="del" title="删除"><i class="bi bi-trash3"></i></button>
        </div></div>`;
    }
    function render(){
      list.innerHTML=values.map(thumbHtml).join('');
      list.querySelectorAll('.up-thumb').forEach(t=>{
        t.querySelector('[data-act=view]').onclick=(e)=>{ e.stopPropagation(); preview(t.dataset.url); };
        t.querySelector('[data-act=del]').onclick=(e)=>{ e.stopPropagation();
          values=values.filter(v=>v!==t.dataset.url); render(); emit(); };
      });
    }
    /* 需求（2026-11-24）：上传进度显示在 dropzone 内底部进度条（随进度填充），上传中锁定组件 */
    let zoneUploading=false;
    const setZoneProgress=(p)=>{
      const pct=Math.round(Math.max(0,Math.min(1,p))*100);
      zone.classList.add('uploading');
      let bar=zone.querySelector('.up-progress');
      if(!bar){ bar=document.createElement('div'); bar.className='up-progress'; bar.innerHTML='<i></i>'; zone.appendChild(bar); }
      const fill=bar.querySelector('i'); if(fill) fill.style.width=pct+'%';
      const hint=zone.querySelector('.up-dz-hint');
      if(hint){ if(hint.dataset.orig===undefined) hint.dataset.orig=hint.textContent; hint.textContent=`正在上传 ${pct}%`; }
    };
    const clearZoneProgress=()=>{
      zone.classList.remove('uploading');
      const bar=zone.querySelector('.up-progress'); if(bar) bar.remove();
      const hint=zone.querySelector('.up-dz-hint');
      if(hint && hint.dataset.orig!==undefined){ hint.textContent=hint.dataset.orig; delete hint.dataset.orig; }
    };
    async function handleFiles(files){
      /* 上传中不允许再次触发，成功或失败（结束）后才能继续 */
      if(zoneUploading){ toast('正在上传中，请稍候…','warning'); return; }
      const imgs=[...files].filter(f=>accept!=='file' ? /^image\//.test(f.type) : true);
      if(!imgs.length){ toast('请选择'+(accept==='file'?'文件':'图片文件'),'error'); return; }
      zoneUploading=true; uploadCount++;
      let done=0;
      try{
        for(const f of imgs){
          try{
            setZoneProgress(done/imgs.length);
            let url=await uploadFile(f,(p)=>setZoneProgress((done+p)/imgs.length));
            if(opts.crop && !multiple && /^image\//.test(f.type)){
              setZoneProgress((done+1)/imgs.length);
              const cropped=await crop(url);
              if(cropped) url=cropped;
            }
            if(multiple) values.push(url); else values=[url];
          }catch(err){ toast(f.name+'：'+err.message,'error'); }
          done++;
        }
      }finally{
        zoneUploading=false; uploadCount=Math.max(0,uploadCount-1);
        clearZoneProgress();
        render(); emit();
      }
    }
    const guardUpload=()=>{ if(zoneUploading){ toast('正在上传中，请稍候…','warning'); return true; } return false; };
    zone.onclick=()=>{ if(guardUpload()) return; fileInput.click(); };
    fileInput.onchange=()=>{ if(guardUpload()){ fileInput.value=''; return; } if(fileInput.files.length) handleFiles(fileInput.files); fileInput.value=''; };
    /* 按钮模式（drag:false）不绑定拖拽事件与素材库入口 */
    if(!el.classList.contains('upload-btnmode')){
      ['dragover','dragenter'].forEach(ev=>zone.addEventListener(ev,(e)=>{ e.preventDefault(); zone.classList.add('dragover'); }));
      ['dragleave','drop'].forEach(ev=>zone.addEventListener(ev,(e)=>{ e.preventDefault(); zone.classList.remove('dragover'); }));
      zone.addEventListener('drop',(e)=>{ if(guardUpload()) return; if(e.dataTransfer.files.length) handleFiles(e.dataTransfer.files); });

      el.querySelector('.up-lib-btn').onclick=async (e)=>{
        e.stopPropagation();  // 阻止冒泡到 zone，避免同时打开文件选择框
        if(guardUpload()) return;
        const picked=await pickLibrary({multiple, accept});
        if(!picked || !picked.length) return;
        let pickedList=[...picked];
        if(opts.crop && !multiple && isImg(pickedList[0])){
          const cropped=await crop(pickedList[0]);
          if(cropped) pickedList=[cropped];
        }
        values = multiple ? [...values, ...pickedList.filter(u=>!values.includes(u))] : pickedList.slice(0,1);
        render(); emit();
      };
    }
    render();
    return { get(){ return multiple?[...values]:(values[0]||''); }, set(v){ values=parseValues(v); if(!multiple)values=values.slice(0,1); render(); } };
  }

  return {mount, pickLibrary, crop, preview, uploadFile, isUploading:()=>uploadCount>0};
})();
