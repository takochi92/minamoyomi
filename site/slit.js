/* Display-only v5 simulation. Reads one frozen race JSON; no client-side model. */
(() => {
  const colors = ['','#eef3f5','#b4c5d2','#ed6b62','#69a0ff','#f4d651','#67d393'];
  const sources = {prior_day_actual_course_local:'本番ST目安',legacy_prior_day:'従来の本番ST目安',
    course_average_blend:'コース平均との代替計算',meeting_average_blend:'今節平均との代替計算',
    local_average_blend:'当地平均との代替計算',program_average_blend:'出走表平均との代替計算',exhibition_only:'展示STをそのまま使用'};
  const reduced = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  for (const box of document.querySelectorAll('.slit-animation')) {
    if (box.dataset.initialized) continue;
    box.dataset.initialized = '1';
    const canvas = box.querySelector('canvas'), ctx = canvas.getContext('2d');
    const play = box.querySelector('button'), status = box.querySelector('.slit-status');
    const zoom = box.querySelector('.slit-zoom');
    const viewNote = box.querySelector('.slit-view-note');
    const chips = box.querySelector('.slit-chips');
    if(!ctx){status.textContent='このブラウザは動画描画に対応していません。静止スリット図をご確認ください。';continue;}
    let data = null, raf = 0, visible = false, autoPlayed = false, fingerprint = '', loading = false, zoomed = false;
    const images = {};
    for (let f = 1; f <= 6; f++) {
      const img = new Image();
      img.onload = () => { if (data && !raf) draw(data.lead_time, true); };
      img.src = `${box.dataset.boatsRoot}slit-boat-${f}.svg`;
      images[f] = img;
    }
    const position = (b,t) => {
      const u = t-b.st;
      return u < 0 ? b.v0*u : u <= b.t_acc ? b.v0*u+.5*b.acceleration*u*u : data.acc_distance+b.v_top*(u-b.t_acc);
    };
    function draw(time, final = false) {
      if (!data || !ctx) return;
      const W=1280,H=720,START=310,END=1100,mobile=canvas.clientWidth<500;
      const spread=Math.max(...data.boats.map(b=>Math.abs(b.gap)));
      const range=zoomed?Math.max(6,spread+3):data.distance,scale=(END-START)/range;
      ctx.clearRect(0,0,W,H);
      const gradient=ctx.createLinearGradient(0,0,W,H);
      gradient.addColorStop(0,'#0b2634'); gradient.addColorStop(.6,'#12394a'); gradient.addColorStop(1,'#091d2a');
      ctx.fillStyle=gradient;ctx.fillRect(0,0,W,H);
      ctx.font=`bold ${mobile?38:25}px sans-serif`;ctx.fillStyle='#e6f2f5';ctx.fillText(zoomed?'到達差の拡大図（計算上）':'展示タイム換算の隊形予想',24,38);
      ctx.font='20px sans-serif';ctx.fillStyle='#a8c7d2';
      ctx.fillText(zoomed?`横方向を約${(data.distance/range).toFixed(1)}倍に拡大 ／ 差の数値は同じ`:`大時計基準 ${time.toFixed(2)}秒 ／ 実時間を圧縮`,24,68);
      const ticks=zoomed?Array.from({length:4},(_,i)=>-range*i/3):[0,50,100,150];
      for(const m of ticks){
        const x=zoomed?END+m*scale:START+m*scale;
        ctx.beginPath();ctx.setLineDash(m===150?[12,8]:[]);ctx.moveTo(x,92);ctx.lineTo(x,594);
        ctx.strokeStyle=m===0?'#f5ce72':m===150?'#ff7770':'#64838c';ctx.lineWidth=m===0?3:1.5;ctx.stroke();
        ctx.setLineDash([]);ctx.fillStyle=m===0?'#f5ce72':'#c4d9e0';ctx.font=`${mobile?34:20}px sans-serif`;ctx.fillText(zoomed?(m===0?'先頭':`${Math.abs(m).toFixed(1)}m後ろ`):`${m}m`,x-20,622);
      }
      ctx.fillStyle='#f16458';ctx.beginPath();ctx.moveTo(END-9,98);ctx.lineTo(END+9,98);ctx.lineTo(END,78);ctx.closePath();ctx.fill();
      for(const [i,b] of data.boats.entries()){
        const y=130+i*80,x=zoomed?END+b.gap*scale:START+position(b,time)*scale;
        if(i%2===0){ctx.fillStyle='rgba(225,248,255,.025)';ctx.fillRect(0,y-32,W,78);}
        ctx.fillStyle=colors[b.frame];ctx.font=`bold ${mobile?36:21}px sans-serif`;ctx.fillText(mobile?`${b.course}C / ${b.frame}号艇`:`${b.course}コース  ${b.frame}号艇`,20,y-8);
        if(!mobile){ctx.fillStyle='#dfedf2';ctx.font='19px sans-serif';ctx.fillText(b.name,20,y+20);}
        if(images[b.frame].complete && images[b.frame].naturalWidth){ctx.drawImage(images[b.frame],x-165,y-33,180,70);}
        if(final){
          ctx.fillStyle='#fff0b0';ctx.font=`bold ${mobile?32:22}px sans-serif`;ctx.textAlign='right';
          ctx.fillText(Math.abs(b.gap)<.00001?'先頭':`${Math.abs(b.gap).toFixed(1)}m後ろ`,W-16,y+8);ctx.textAlign='left';
        }
      }
      ctx.fillStyle='#a8c7d2';ctx.font=`${mobile?32:19}px sans-serif`;
      ctx.fillText(mobile?'直線換算・艇体は拡大表示':'直線換算・艇体は拡大表示。実測の到達差や攻防を再現した映像ではありません。',24,665);
      if(!mobile)ctx.fillText(`目安ST＋行き足＋伸び ／ ${data.version}`,24,696);
    }
    function notes() {
      const spread=Math.max(...data.boats.map(b=>Math.abs(b.gap)));
      const ns=[`計算上の最大差は${spread.toFixed(1)}m。「到達差を拡大」で僅差を確認できます。`];
      if(data.rough) ns.push('荒れ水面：誤差表示を1.5倍にしています。');
      if(data.overlap) ns.push('上位は誤差範囲で入れ替わり得ます。');
      if(data.uncertainty_missing) ns.push('ばらつき不明の艇は誤差未算定です。');
      if(data.weather_incomplete) ns.push('気象の一部が不明です。');
      if(data.fukuoka) ns.push('福岡は展示の計測位置が他場と異なります。係数は共通の目安です。');
      if(!data.lap_used) ns.push('一周なし：チルト・コースによる代替計算。');
      if(!data.straight_used) ns.push('直線なし：展示タイムで速度換算。');
      if(data.boats.some(b=>b.st_source==='exhibition_only' && b.st<0)) ns.push('展示Fをそのまま使った艇があります。本番のF予告ではありません。');
      status.textContent=ns.join(' ') || '過去のばらつきは予測誤差の保証ではありません。';
    }
    function renderChips(){
      chips.replaceChildren();
      for(const b of data.boats){
        const div=document.createElement('div');div.className='slit-chip';div.style.borderTopColor=colors[b.frame];
        const title=document.createElement('b');title.textContent=`${b.frame} ${b.name} ／ ${b.course}コース`;
        const values=document.createElement('span');values.textContent=`展示 ${b.exhibit.toFixed(2)}・一周 ${b.lap?.toFixed(2)??'—'}・ST ${b.st.toFixed(2)}`;
        const gap=document.createElement('strong');gap.className='slit-gap';gap.textContent=Math.abs(b.gap)<.00001?'先頭（計算上）':`先頭から${Math.abs(b.gap).toFixed(1)}m後ろ`;
        const extra=document.createElement('small');extra.textContent=`${sources[b.st_source]||b.st_source} ／ ${b.error_m==null?'誤差未算定':`ばらつき換算 ±${b.error_m.toFixed(1)}m`}`;
        div.append(title,gap,values,extra);chips.append(div);
      }
    }
    function stop(){if(raf)cancelAnimationFrame(raf);raf=0;}
    function updateViewNote(){
      if(!viewNote||!data)return;
      const range=Math.max(6,Math.max(...data.boats.map(b=>Math.abs(b.gap)))+3);
      viewNote.textContent=zoomed?`到達時の横方向を約${(data.distance/range).toFixed(1)}倍に拡大中。距離の数値・予想は変えていません。`:'全体表示は0〜150m。拡大表示は位置の見やすさだけを変えます。';
    }
    function start(){
      if(!data||!visible||document.hidden)return;stop();
      zoomed=false;if(zoom){zoom.setAttribute('aria-pressed','false');zoom.textContent='到達差を拡大';}
      updateViewNote();
      if(reduced()){draw(data.lead_time,true);return;}
      const begin=performance.now(),move=data.move_seconds*1000,total=(data.move_seconds+data.hold_seconds)*1000;
      function frame(now){
        const elapsed=now-begin,p=Math.min(1,elapsed/move);
        draw(data.lead_time*p,p===1);
        if(elapsed<total&&visible&&!document.hidden)raf=requestAnimationFrame(frame);else{raf=0;play.textContent='もう一度再生';}
      }
      raf=requestAnimationFrame(frame);
    }
    async function load(){
      if(loading)return;loading=true;
      try{
        const response=await fetch(`${box.dataset.source}?t=${Math.floor(Date.now()/60000)}`);
        if(!response.ok)throw new Error('unavailable');
        const race=await response.json(),d=race.start_slit;
        if(!d||d.status!=='ready'){
          stop();data=null;play.disabled=true;if(zoom)zoom.disabled=true;chips.replaceChildren();ctx?.clearRect(0,0,1280,720);
          status.textContent=Date.now()>=Date.parse(box.dataset.deadline)?'このレースには締切前の動画記録がありません。':(d?.reason||'展示データと締切前の記録を待っています。');return;
        }
        const key=`${d.fingerprint}:${d.input_fingerprint}`;
        if(key!==fingerprint){
          stop();data=d;fingerprint=key;renderChips();notes();updateViewNote();draw(d.lead_time,true);play.disabled=false;if(zoom)zoom.disabled=false;
          if(visible&&!autoPlayed&&!reduced()){autoPlayed=true;start();}
        }
      }catch{status.textContent='読み込めませんでした。再読み込みで確認できます。';}
      finally{loading=false;}
    }
    play.addEventListener('click',start);
    zoom?.addEventListener('click',()=>{if(!data)return;stop();zoomed=!zoomed;zoom.setAttribute('aria-pressed',String(zoomed));zoom.textContent=zoomed?'全体に戻す':'到達差を拡大';updateViewNote();draw(data.lead_time,true);});
    const observer=new IntersectionObserver(entries=>{
      visible=entries[0].isIntersecting;
      if(visible){load();if(data&&!autoPlayed&&!reduced()){autoPlayed=true;start();}}
      else stop();
    },{threshold:.15});
    observer.observe(box);
    if(window.ResizeObserver)new ResizeObserver(()=>{if(data&&!raf)draw(data.lead_time,true);}).observe(canvas);
    const timer=setInterval(()=>{
      if(Date.now()>=Date.parse(box.dataset.deadline)){clearInterval(timer);if(visible)load();return;}
      if(visible&&!document.hidden)load();
    },60000);
    document.addEventListener('visibilitychange',()=>{if(document.hidden)stop();});
  }
})();
