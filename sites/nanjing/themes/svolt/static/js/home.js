/* 首页专属脚本（自 index.html 抽离）：轮播 / 页签等，?v=static_ver 控制缓存 */
/* 首屏轮播：自动播放 + 箭头 + 圆点 */
(function(){
  const hero=document.getElementById('svHero');
  if(!hero) return;
  const slides=[...hero.querySelectorAll('.sv-slide')];
  const dots=[...hero.querySelectorAll('.sv-hero-dots button')];
  let cur=0,timer=null;
  function show(i){
    cur=(i+slides.length)%slides.length;
    slides.forEach((s,x)=>s.classList.toggle('on',x===cur));
    dots.forEach((d,x)=>d.classList.toggle('on',x===cur));
  }
  function play(){ timer=setInterval(()=>show(cur+1),6000); }
  document.getElementById('svPrev').onclick=()=>{clearInterval(timer);show(cur-1);play();};
  document.getElementById('svNext').onclick=()=>{clearInterval(timer);show(cur+1);play();};
  dots.forEach(d=>d.onclick=()=>{clearInterval(timer);show(+d.dataset.go-1);play();});
  show(0);play();
})();
