/* 首页专属脚本（自 index.html 抽离）：轮播 / 页签等，?v=static_ver 控制缓存 */
/* 首页轮播：自动播放 + 页码切换 + GSAP 进度条 */
(function(){
  const hero=document.getElementById('sgHero');
  if(!hero) return;
  const slides=[...hero.querySelectorAll('.sg-slide')];
  const dots=[...hero.querySelectorAll('.sg-hero-pager button')];
  const bar=document.getElementById('sgHeroBar');
  let cur=0, timer=null;
  function show(i){
    cur=i%slides.length;
    slides.forEach((s,idx)=>s.classList.toggle('on',idx===cur));
    dots.forEach((d,idx)=>d.classList.toggle('on',idx===cur));
    if(window.gsap){ gsap.fromTo(bar,{scaleX:0},{scaleX:1,duration:6,ease:'none'}); }
  }
  function play(){ timer=setInterval(()=>show(cur+1),6000); }
  dots.forEach(d=>d.onclick=()=>{ clearInterval(timer); show(+d.dataset.go-1); play(); });
  const prev=document.getElementById('sgPrev'), next=document.getElementById('sgNext');
  if(prev) prev.onclick=()=>{ clearInterval(timer); show(cur-1<0?slides.length-1:cur-1); play(); };
  if(next) next.onclick=()=>{ clearInterval(timer); show(cur+1); play(); };
  show(0); play();
})();
