/* 智造橙主题交互（原生 JS + GSAP） */
(function () {
  'use strict';

  /* 头部吸顶收缩 */
  var header = document.getElementById('sgHeader');
  var topbar = document.querySelector('.sg-topbar');
  function onScroll() {
    var y = window.scrollY || 0;
    if (header) header.classList.toggle('is-sticky', y > 60);
    if (topbar) topbar.classList.toggle('hide', y > 120);
    var bt = document.getElementById('sgBackTop');
    if (bt) bt.classList.toggle('show', y > 400);
    var fn = document.querySelector('.sg-float-nav');
    if (fn) { var mn = document.querySelector('main'); fn.classList.toggle('show', y > (mn ? mn.offsetTop - 40 : 400)); }
  }
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();

  /* 移动端菜单 */
  var burger = document.getElementById('sgBurger');
  var mnav = document.getElementById('sgMobileNav');
  if (burger && mnav) {
    burger.addEventListener('click', function () { mnav.classList.toggle('open'); });
  }

  /* 返回顶部 */
  var backtop = document.getElementById('sgBackTop');
  if (backtop) backtop.addEventListener('click', function () {
    window.scrollTo({ top: 0, behavior: 'smooth' });
  });

  /* 顶部入场：顶栏（非吸顶）离开视口再进入时重播；头部为吸顶元素（始终可见，
     不存在「离开再进入」），保留加载入场。运行时动画，GSAP 缺失或系统
     开启「减弱动态效果」时元素不受任何影响，绝不空白。 */
  var reducedMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var topbarEl = document.querySelector('.sg-topbar, .zt-topbar');
  if (topbarEl && window.gsap && window.ScrollTrigger && !reducedMotion) {
    try {
      gsap.registerPlugin(ScrollTrigger);
      gsap.from(topbarEl, {
        opacity: 0, y: -24, duration: 0.8, ease: 'power2.out',
        scrollTrigger: { trigger: topbarEl, start: 'top 96%', toggleActions: 'play none none reset' }
      });
    } catch (e) { /* 动画异常不影响显示 */ }
  }
  var pageHeader = document.querySelector('header');
  if (pageHeader && window.gsap && !reducedMotion) {
    try {
      gsap.from(pageHeader, { opacity: 0, y: -24, duration: 0.8, ease: 'power2.out' });
    } catch (e) { /* 动画异常不影响显示 */ }
  }

  /* 滚动进场（GSAP，重复播放）：内容默认可见，只把首屏外的元素隐藏后交给
     ScrollTrigger 淡入上浮；滚出视口再回来时动画重播（play none none reset）。
     GSAP 未加载不隐藏任何元素；触发器创建失败时兜底恢复显示，绝不空白。 */
  var reveals = document.querySelectorAll('[data-reveal]');
  if (window.gsap && window.ScrollTrigger) {
    gsap.registerPlugin(ScrollTrigger);
    var vh = window.innerHeight || document.documentElement.clientHeight;
    var hiddenCount = 0;
    try {
      reveals.forEach(function (el) {
        if (el.getBoundingClientRect().top > vh * 0.92) {
          gsap.set(el, { opacity: 0, y: 36 });
          hiddenCount++;
          gsap.to(el, {
            opacity: 1, y: 0, duration: 0.9, ease: 'power2.out',
            scrollTrigger: { trigger: el, start: 'top 90%', toggleActions: 'play none none reset' }
          });
        }
      });
    } catch (e) {
      reveals.forEach(function (el) { gsap.set(el, { clearProps: 'all' }); });
      hiddenCount = 0;
    }
    if (hiddenCount) {
      setTimeout(function () {
        if (!ScrollTrigger.getAll().length) {
          reveals.forEach(function (el) { gsap.set(el, { clearProps: 'all' }); });
        }
      }, 1500);
    }
  }

  /* 数字滚动统计（重复播放：离开视口归零，再进入时重新滚动） */
  function parseNum(v) {
    var m = String(v).match(/[\d.]+/);
    return m ? parseFloat(m[0]) : 0;
  }
  var counters = document.querySelectorAll('[data-counter]');
  if (counters.length && ('IntersectionObserver' in window)) {
    var cio = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        var nums = en.target.querySelectorAll('[data-num]');
        if (en.isIntersecting) {
          nums.forEach(function (el) {
            var target = parseNum(el.dataset.num);
            if (!target) return;
            var unit = String(el.dataset.num).replace(/^[\d.]+/, '');
            if (window.gsap) {
              if (el._numTween) el._numTween.kill();
              var obj = { n: 0 };
              el._numTween = gsap.to(obj, { n: target, duration: 1.6, ease: 'power1.out',
                onUpdate: function () { el.textContent = Math.round(obj.n) + unit; } });
            } else {
              el.textContent = target + unit;
            }
          });
        } else if (window.gsap) {
          nums.forEach(function (el) {
            if (el._numTween) { el._numTween.kill(); el._numTween = null; }
            el.textContent = '0' + String(el.dataset.num).replace(/^[\d.]+/, '');
          });
        }
      });
    }, { threshold: 0.4 });
    counters.forEach(function (el) { cio.observe(el); });
  }
})();


/* ---------- 提示统一为 tooltip（data-bs-toggle="tooltip" / data-bs-title），不使用原生 title ---------- */
(function () {
  var tip = null;
  var SEL = '[data-bs-toggle="tooltip"],[data-bs-title]';
  function show(el) {
    var t = el.getAttribute('data-bs-title') || el.getAttribute('title');
    if (!t) return;
    hide();
    tip = document.createElement('div');
    tip.className = 'bs-tip';
    var inner = document.createElement('div');
    inner.className = 'bs-tip-inner';
    inner.textContent = t;
    tip.appendChild(inner);
    document.body.appendChild(tip);
    var r = el.getBoundingClientRect();
    var left = r.left + r.width / 2 - tip.offsetWidth / 2;
    var top = r.top - tip.offsetHeight - 8;
    if (top < 8) { top = r.bottom + 8; tip.classList.add('bs-tip-bottom'); }
    left = Math.max(8, Math.min(left, window.innerWidth - tip.offsetWidth - 8));
    tip.style.left = left + 'px';
    tip.style.top = top + 'px';
    tip.classList.add('bs-tip-show');
  }
  function hide() { if (tip) { tip.remove(); tip = null; } }
  document.addEventListener('mouseover', function (e) {
    var el = e.target.closest ? e.target.closest(SEL) : null;
    if (el && !(e.relatedTarget && el.contains(e.relatedTarget))) show(el);
  }, true);
  document.addEventListener('mouseout', function (e) {
    var el = e.target.closest ? e.target.closest(SEL) : null;
    if (el && !(e.relatedTarget && (el.contains(e.relatedTarget) || (tip && tip.contains(e.relatedTarget))))) hide();
  }, true);
  window.addEventListener('scroll', hide, true);
  window.addEventListener('blur', hide);
})();
