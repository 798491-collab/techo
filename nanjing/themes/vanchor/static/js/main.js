/* 化贸蓝主题交互（原生 JS + GSAP） */
(function () {
  'use strict';

  var header = document.getElementById('vcHeader');
  function onScroll() {
    var y = window.scrollY || 0;
    if (header) header.classList.toggle('is-sticky', y > 60);
    var bt = document.getElementById('vcBackTop');
    if (bt) bt.classList.toggle('show', y > 400);
    var fn = document.querySelector('.vc-float-nav');
    if (fn) { var mn = document.querySelector('main'); fn.classList.toggle('show', y > (mn ? mn.offsetTop - 40 : 400)); }
  }
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();

  var burger = document.getElementById('vcBurger');
  var mnav = document.getElementById('vcMobileNav');
  if (burger && mnav) burger.addEventListener('click', function () { mnav.classList.toggle('open'); });

  var backtop = document.getElementById('vcBackTop');
  if (backtop) backtop.addEventListener('click', function () { window.scrollTo({ top: 0, behavior: 'smooth' }); });

  /* 首屏文字入场 */
  var heroTxt = document.querySelector('.vc-hero-txt');
  if (heroTxt && window.gsap && window.ScrollTrigger) {
    gsap.registerPlugin(ScrollTrigger);
    gsap.from(heroTxt.children, { opacity: 0, y: 36, duration: 0.9, stagger: 0.13, ease: 'power2.out',
      scrollTrigger: { trigger: heroTxt, start: 'top 92%', toggleActions: 'play none none reset' } });
  } else if (heroTxt && window.gsap) {
    gsap.from(heroTxt.children, { opacity: 0, y: 36, duration: 0.9, stagger: 0.13, ease: 'power2.out' });
  }

  /* 滚动进场 */
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
})();

/* 首屏 banner 多图轮播（自动播放 + 圆点切换） */
(function(){
  const hero=document.getElementById('vcHero');
  if(!hero) return;
  const slides=[...hero.querySelectorAll('.vc-hero-slide')];
  const dots=[...hero.querySelectorAll('.vc-hero-dots button')];
  if(slides.length<1) return;
  let cur=0,timer=null;
  function show(i){
    cur=(i+slides.length)%slides.length;
    slides.forEach((s,x)=>s.classList.toggle('on',x===cur));
    dots.forEach((d,x)=>d.classList.toggle('on',x===cur));
  }
  function play(){ if(slides.length>1) timer=setInterval(()=>show(cur+1),6000); }
  dots.forEach(d=>d.onclick=()=>{clearInterval(timer);show(+d.dataset.go-1);play();});
  var prev=document.getElementById('vcPrev'), next=document.getElementById('vcNext');
  if(prev) prev.onclick=()=>{clearInterval(timer);show(cur-1);play();};
  if(next) next.onclick=()=>{clearInterval(timer);show(cur+1);play();};
  show(0);play();
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
