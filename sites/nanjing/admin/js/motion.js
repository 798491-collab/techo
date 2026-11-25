/* 管理后台 GSAP 动效：登录页入场 + 页面切换进场（内容子元素错落淡入） */
(function () {
  if (!window.gsap) return;

  /* 登录页每次显示时入场（display 由 core.js/app.js 切换） */
  var loginEl = document.getElementById('login-page');
  function playLogin() {
    var page = document.getElementById('login-page');
    if (!page || page.style.display === 'none') return;
    gsap.from('#login-page .login-card', { opacity: 0, x: 46, duration: 0.7, ease: 'power2.out', clearProps: 'all' });
    gsap.from('#login-page .login-hero', { opacity: 0, duration: 0.9, ease: 'power2.out', clearProps: 'all' });
  }
  if (loginEl && 'MutationObserver' in window) {
    new MutationObserver(playLogin).observe(loginEl, { attributes: true, attributeFilter: ['style'] });
    if (loginEl.style.display && loginEl.style.display !== 'none') setTimeout(playLogin, 200);
  }

  /* 页面切换：#content 顶层子元素错落淡入（CRUD 列表/仪表盘/设置页全部覆盖） */
  var content = document.getElementById('content');
  if (content && 'MutationObserver' in window) {
    var pending = null;
    new MutationObserver(function () {
      if (pending) clearTimeout(pending);
      pending = setTimeout(function () {
        var kids = content.children;
        if (!kids.length) return;
        gsap.from(kids, { opacity: 0, y: 22, duration: 0.45, stagger: 0.06, ease: 'power2.out', clearProps: 'all', overwrite: true });
      }, 60);
    }).observe(content, { childList: true });
  }
})();


/* ---------- 提示统一为 Bootstrap Tooltip：title 属性自动迁移（覆盖动态渲染内容） ---------- */
(function () {
  if (!window.bootstrap || !bootstrap.Tooltip) return;
  var SEL = '[title]:not([data-bs-toggle="tooltip"])';

  function convert(root) {
    var nodes = [];
    if (root.nodeType !== 1) return;
    if (root.matches && root.matches(SEL)) nodes.push(root);
    var list = root.querySelectorAll(SEL);
    for (var i = 0; i < list.length; i++) nodes.push(list[i]);
    nodes.forEach(function (el) {
      var t = el.getAttribute('title');
      if (!t) return;
      el.removeAttribute('title');
      el.setAttribute('data-bs-title', t);
      if (!el.hasAttribute('data-bs-toggle')) el.setAttribute('data-bs-toggle', 'tooltip');
      try { bootstrap.Tooltip.getOrCreateInstance(el); } catch (e) { /* ignore */ }
    });
  }

  /* 初始扫描 + 动态内容实时转换（CRUD 表格、弹窗、插件卡片等全部覆盖） */
  convert(document);
  new MutationObserver(function (muts) {
    muts.forEach(function (m) {
      if (m.type === 'childList') {
        m.addedNodes.forEach(function (n) { if (n.nodeType === 1) convert(n); });
        m.removedNodes.forEach(function (n) {
          if (n.nodeType !== 1) return;
          var list = n.querySelectorAll('[data-bs-toggle="tooltip"]');
          for (var i = 0; i < list.length; i++) {
            var inst = bootstrap.Tooltip.getInstance(list[i]);
            if (inst) { try { inst.dispose(); } catch (e) { /* ignore */ } }
          }
        });
      } else if (m.type === 'attributes' && m.attributeName === 'title') {
        if (m.target.hasAttribute('title')) convert(m.target);
      }
    });
  }).observe(document.documentElement, { childList: true, subtree: true, attributes: true, attributeFilter: ['title'] });
})();
