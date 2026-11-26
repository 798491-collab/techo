/* 首页专属脚本（自 index.html 抽离）：轮播 / 页签等，?v=static_ver 控制缓存 */
/* banner 轮播：自动播放 + 圆点切换 */
(function(){
  const hero=document.getElementById('jgHero');
  if(!hero) return;
  const slides=[...hero.querySelectorAll('.jg-hero-slide')];
  const dots=[...hero.querySelectorAll('.jg-hero-dots button')];
  if(slides.length<1) return;
  let cur=0,timer=null;
  function show(i){
    cur=(i+slides.length)%slides.length;
    slides.forEach((s,x)=>s.classList.toggle('on',x===cur));
    dots.forEach((d,x)=>d.classList.toggle('on',x===cur));
  }
  function play(){ if(slides.length>1) timer=setInterval(()=>show(cur+1),6000); }
  dots.forEach(d=>d.onclick=()=>{clearInterval(timer);show(+d.dataset.go-1);play();});
  const prev=document.getElementById('jgPrev'), next=document.getElementById('jgNext');
  if(prev) prev.onclick=()=>{clearInterval(timer);show(cur-1);play();};
  if(next) next.onclick=()=>{clearInterval(timer);show(cur+1);play();};
  show(0);play();
})();
/* 新闻 tab 切换 */
(function(){
  document.querySelectorAll('.jg-tab-btn').forEach(function(btn){
    btn.addEventListener('click',function(){
      document.querySelectorAll('.jg-tab-btn').forEach(function(b){b.classList.remove('on');});
      document.querySelectorAll('.jg-tab-pane').forEach(function(p){p.classList.remove('on');});
      btn.classList.add('on');
      var pane=document.getElementById(btn.dataset.tab);
      if(pane){ pane.classList.add('on'); if(window.gsap) gsap.fromTo(pane,{opacity:0,y:16},{opacity:1,y:0,duration:.5}); }
    });
  });
})();
