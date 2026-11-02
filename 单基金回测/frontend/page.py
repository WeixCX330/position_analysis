"""生成可直接双击打开的HTML；全部数据内嵌，不依赖服务器或CDN。"""
import html
import json
from pathlib import Path


def write_page(result, output_dir):
    payload = json.dumps(result, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")
    page = (TEMPLATE.replace("__DATA__", payload).replace("__CODE__", html.escape(result["product_code"]))
            .replace("__NAME__", html.escape(result.get("product_name") or "")))
    path = Path(output_dir) / "report.html"
    path.write_text(page, encoding="utf-8")
    return path


TEMPLATE = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__CODE__ · 单基金历史回测</title><style>
:root{--ink:#172b3a;--muted:#526474;--line:#dce4ea;--blue:#0072b2;--orange:#b34700;--navy:#175777;--bg:#f5f7f9}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans CJK SC","Microsoft YaHei",sans-serif}
main{max-width:1440px;margin:auto;padding:32px 30px 60px}header{display:flex;gap:25px;justify-content:space-between;align-items:center;padding-bottom:24px;border-bottom:1px solid var(--line)}
h1{font-size:28px;line-height:1.4;margin:7px 0 10px}h2{font-size:18px;margin:0}.eyebrow{font-size:11px;letter-spacing:2px;color:var(--blue);font-weight:700}.muted{color:var(--muted);font-size:12px}a{color:var(--navy);text-underline-offset:3px}
.toolbar,.figure-head{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap}.toolbar{justify-content:flex-start;margin:22px 0}.figure-head{margin-bottom:8px}.actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
select,button{background:white;color:var(--ink);border:1px solid #aab8c3;border-radius:4px;font:inherit;padding:6px 10px}button{cursor:pointer;font-size:12px}button:hover{background:#edf3f7}button:focus-visible,select:focus-visible,summary:focus-visible{outline:3px solid #0072b2;outline-offset:3px}
.cards{display:grid;grid-template-columns:repeat(6,1fr);gap:10px}.card,.panel{background:#fff;border:1px solid var(--line);border-radius:5px;padding:18px}.card small{display:block;color:var(--muted);font-size:11px}.card strong{display:block;font-size:23px;font-weight:650;margin-top:7px;font-variant-numeric:tabular-nums}.card:nth-child(5) strong{font-size:18px}
.panel{margin-top:18px}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}.chart{min-width:0;border-top:1px solid var(--line);padding-top:16px}.chart h3{font-size:14px;margin:0}.chart p{margin:4px 0 0;font-size:12px;color:var(--muted)}
svg.figure{display:block;width:100%;height:auto;background:#fff}.legend{display:flex;gap:16px;flex-wrap:wrap;color:var(--muted);font-size:12px;margin:8px 0}.swatch{display:inline-block;width:22px;height:0;border-top:2px solid;vertical-align:middle;margin-right:6px}.dash{border-top-style:dashed}.dotdash{border-top-style:dotted}
.notice{padding:10px 14px;border-left:3px solid var(--orange);background:#fff5ed;margin:12px 0}.risk-note{border-left:3px solid var(--blue);padding:10px 14px;background:#f0f6fa;margin:12px 0;font-size:13px}
pre{white-space:pre-wrap;word-break:break-word;font:13px/1.8 inherit;margin:15px 0 0}details summary{cursor:pointer;font-weight:600}footer{margin-top:24px;color:var(--muted);font-size:12px}.chart-caption{color:var(--muted);font-size:12px;margin:7px 0}
table{border-collapse:collapse;width:100%;font-size:12px;margin-top:10px;font-variant-numeric:tabular-nums}th,td{border-bottom:1px solid var(--line);padding:7px;text-align:right}th:first-child,td:first-child{text-align:left}th{font-weight:600;background:#f7f9fb}
#metric-table{overflow-x:auto}@media(max-width:1050px){.cards{grid-template-columns:repeat(3,1fr)}}@media(max-width:720px){main{padding:20px 12px}.cards{grid-template-columns:repeat(2,1fr)}.grid{grid-template-columns:1fr}header{display:block}h1{font-size:23px}.panel{padding:12px}.card strong{font-size:20px}}
@media print{body{background:white}main{padding:0;max-width:none}.actions,.toolbar select{display:none}.panel,.chart{break-inside:avoid}.grid{grid-template-columns:repeat(2,minmax(0,1fr))}details pre{display:block}}
</style></head><body><main>
<header><div><div class="eyebrow">SINGLE FUND / HISTORICAL BACKTEST</div><h1>__CODE__ · __NAME__</h1><div id="meta" class="muted"></div></div><div class="muted"><a href="result.json">结果 JSON</a> · <a href="backtest_output.json">精简字段 JSON</a> · <a href="path_metrics.npz">逐路径指标</a> · <a href="daily_returns.csv">历史收益明细</a><br><span id="static-links"></span>固定历史起点 · 日频 GBM · 无未来预测</div></header>
<div class="toolbar"><label for="period">回测区间</label><select id="period"></select><span id="window" class="muted"></span></div>
<div id="status"></div><div id="cards" class="cards"></div>
<section class="panel"><div class="figure-head"><h2 id="path_title">A · 净值路径对照</h2><div class="actions"><label class="muted" for="path-scale">净值纵轴</label><select id="path-scale"><option value="linear">线性</option><option value="log">对数（log10）</option></select><button type="button" id="save-paths">下载 SVG</button></div></div>
<div class="legend"><span><i class="swatch" style="border-color:#b34700"></i>真实序列</span><span><i class="swatch dash" style="border-color:#0072b2"></i>模拟样例（非分位带）</span></div><div id="paths"></div><p id="path-caption" class="chart-caption"></p><div id="training" class="muted"></div></section>
<section class="panel"><div class="figure-head"><h2>B · 终点损失与尾部风险</h2><button type="button" id="save-loss">下载 SVG</button></div><div id="risk-note" class="risk-note"></div><div id="loss-chart"></div><p class="chart-caption">损失 L = −终点累计收益；负值表示盈利，正值表示亏损。VaR 是损失分位，CVaR 是损失不低于 VaR 的路径平均；不取绝对值、不截零。阴影标记 VaR 右侧区域，面积并非直接给出的尾部概率。</p></section>
<section class="panel"><h2>C · 六项模拟指标分布</h2><div class="legend"><span><i class="swatch" style="border-color:#b34700"></i>真实值</span><span><i class="swatch dash" style="border-color:#175777"></i>P05</span><span><i class="swatch" style="border-color:#175777"></i>P50</span><span><i class="swatch dotdash" style="border-color:#175777"></i>P95</span></div>
<p class="chart-caption">沿用全部有效路径的32箱统计；纵轴为每箱路径占比，零为基线。P05 / P50 / P95 是模拟情景分位，不是参数置信区间。各图横轴分别缩放，并纳入真实值；不平滑、不删尾部。</p><div id="distributions" class="grid"></div>
<details style="margin-top:16px"><summary>查看当前档位数值表</summary><div id="metric-table"></div></details></section>
<details class="panel"><summary>分析文字与数据口径</summary><pre id="analysis"></pre></details>
<footer>图形可离线打开和下载，无外部字体、CDN或绘图库依赖。VaR/CVaR 衡量回测区间终点损失，不是最大回撤或最大可能损失。产品回测不能单独解释客户交易盈亏。</footer>
</main><script type="application/json" id="data">__DATA__</script><script>
'use strict';
const data=JSON.parse(document.getElementById('data').textContent);
const names={total_return:'累计收益',annualized_return:'复合年化收益',maximum_drawdown:'最大回撤',annualized_volatility:'年化波动率',sharpe_ratio:'夏普比率',downside_volatility:'年化下行波动率'};
const palette={ink:'#172b3a',muted:'#526474',grid:'#e3e9ee',axis:'#87939f',blue:'#0072b2',navy:'#175777',actual:'#b34700',tail:'#f4d6c3'};
const $=id=>document.getElementById(id);
const valid=v=>typeof v==='number'&&Number.isFinite(v);
const pct=v=>!valid(v)?'不可用':(Math.abs(v*100)>=1e6?(v*100).toExponential(2):(v*100).toFixed(2))+'%';
const signedPct=v=>!valid(v)?'不可用':(v>0?'+':'')+pct(v);
const fmt=(v,k)=>!valid(v)?'不可用':k==='sharpe_ratio'?v.toFixed(2):pct(v);
function short(v,k) {
  const n=k==='sharpe_ratio'?v:v*100, a=Math.abs(n);
  const text=a!==0&&(a>=1e5||a<.001)?n.toExponential(1):Number(n.toPrecision(4)).toString();
  return text+(k==='sharpe_ratio'?'':'%');
}
$('meta').textContent='数据截止 '+data.data_as_of+' ｜ '+data.source.valid_rows.toLocaleString()+' 条净值 ｜ 每档 '+data.config.paths.toLocaleString()+' 条路径';
$('analysis').textContent=data.analysis.text;
if(data.analysis.chart_file) $('static-links').innerHTML='<a href="charts.svg">静态六联图 SVG</a> · <a href="charts.png">PNG</a>（优先一年档）<br>';
for(const [i,p] of data.periods.entries()){
  const opt=document.createElement('option');opt.value=i;
  opt.textContent=p.label+(p.fit?.calibration_mode==='initial_20_nav_out_of_sample'?' · 前20条训练':'')+(p.available?'':' · 仅历史/不可用');
  $('period').append(opt);
}
const initial=data.periods.findIndex(p=>p.date_type==='4');$('period').value=initial>=0?initial:0;
const current=()=>data.periods[Number($('period').value)];
const NS='http://www.w3.org/2000/svg';
function el(name,attrs={},text=null,parent=null){
  const n=document.createElementNS(NS,name);
  for(const [k,v]of Object.entries(attrs))n.setAttribute(k,String(v));
  if(text!==null)n.textContent=text;if(parent)parent.append(n);return n;
}
function svgFor(host,id,title,desc,width=1100,height=360){
  host.replaceChildren();
  const s=el('svg',{xmlns:NS,id,width,height,viewBox:'0 0 '+width+' '+height,class:'figure',role:'img','aria-labelledby':id+'-title '+id+'-desc'});
  el('title',{id:id+'-title'},title,s);el('desc',{id:id+'-desc'},desc,s);
  el('rect',{width,height,fill:'#fff'},null,s);
  s.setAttribute('font-family',"-apple-system,BlinkMacSystemFont,Segoe UI,Noto Sans CJK SC,Microsoft YaHei,sans-serif");
  s.setAttribute('font-size','12');s.setAttribute('fill',palette.ink);
  el('text',{x:75,y:23,'font-size':14,'font-weight':600},title,s);
  el('text',{x:75,y:43,'font-size':11,fill:palette.muted},desc,s);
  host.append(s);return s;
}
function label(s,x,y,text,attrs={}){return el('text',{x,y,fill:palette.muted,'font-size':11,...attrs},text,s);}
function line(s,x1,y1,x2,y2,attrs={}){
  return el('line',{x1,y1,x2,y2,stroke:palette.axis,'stroke-width':.8,...attrs},null,s);
}
function axes(s,b,xTicks,yTicks,xMap,yMap,xf,yf,xTitle,yTitle){
  for(const value of yTicks){
    const y=yMap(value);line(s,b.l,y,b.r,y,{stroke:palette.grid,'stroke-width':.7});
    label(s,b.l-10,y+4,yf(value),{'text-anchor':'end'});
  }
  line(s,b.l,b.t,b.l,b.b);line(s,b.l,b.b,b.r,b.b);
  for(const value of xTicks){
    const x=xMap(value);line(s,x,b.b,x,b.b+4);
    label(s,x,b.b+19,xf(value),{'text-anchor':x<=b.l+3?'start':x>=b.r-3?'end':'middle'});
  }
  label(s,(b.l+b.r)/2,b.b+43,xTitle,{'text-anchor':'middle','font-size':12});
  label(s,17,(b.t+b.b)/2,yTitle,{transform:'rotate(-90 17 '+((b.t+b.b)/2)+')','text-anchor':'middle','font-size':12});
}
const ticks=(lo,hi,n=4)=>Array.from({length:n+1},(_,i)=>lo+(hi-lo)*i/n);
function bounds(lo,hi){
  const pad=(hi-lo)*.035||Math.max(Math.abs(lo)*.02,1e-6);return[lo-pad,hi+pad];
}
function missing(host,id,title,text,width=560,height=300){
  const s=svgFor(host,id,title,'无可用数据；未按零值绘制。',width,height);
  label(s,width/2,height/2,text,{'text-anchor':'middle','font-size':13});
}
function drawPaths(p){
  const host=$('paths'),d=p.chart_data;
  $('path-caption').textContent='';
  if(!d){missing(host,'path-figure','净值路径对照','本档无有效历史区间',1100,360);return;}
  const samples=d.sample_paths||[], all=[d.actual_nav,...samples].flat().filter(valid);
  if(!all.length){missing(host,'path-figure','净值路径对照','没有有限净值',1100,360);return;}
  const log=$('path-scale').value==='log';
  if(log&&all.some(v=>v<=0)){missing(host,'path-figure','净值路径对照','净值含非正值，不能使用对数轴',1100,360);return;}
  const tr=v=>log?Math.log10(v):v;
  let lo=Math.min(...all.map(tr)),hi=Math.max(...all.map(tr));[lo,hi]=bounds(lo,hi);
  const times=d.dates.map(v=>Date.parse(v+'T00:00:00Z'));
  const b={l:85,r:1070,t:65,b:296},x=t=>b.l+(t-times[0])/(times.at(-1)-times[0]||1)*(b.r-b.l);
  const y=v=>b.b-(tr(v)-lo)/(hi-lo)*(b.b-b.t);
  const title=data.product_code+' · '+p.label+' · 净值路径';
  const desc=p.start+' — '+p.end+' | '+samples.length+' 条展示样例；非全部 '+(p.path_count||0)+' 条路径 | '+(log?'log10 对数轴':'线性轴');
  const s=svgFor(host,'path-figure',title,desc);
  const yvals=ticks(lo,hi).map(v=>log?10**v:v);
  axes(s,b,ticks(times[0],times.at(-1)),yvals,x,y,
    v=>new Date(v).toISOString().slice(0,10),
    v=>Math.abs(v)>=1e5||v<.001?v.toExponential(2):Number(v.toPrecision(4)).toString(),
    '观测日期',log?'净值（log10 对数刻度）':'净值（输入口径）');
  function plot(values,actual){
    let command='',started=false;
    values.forEach((v,i)=>{
      if(!valid(v)){started=false;return;}
      command+=(started?' L ':' M ')+x(times[i]).toFixed(2)+' '+y(v).toFixed(2);started=true;
    });
    el('path',{d:command,fill:'none',stroke:actual?palette.actual:palette.blue,
      'stroke-width':actual?2.3:1.1,'stroke-opacity':actual?1:.48,
      'stroke-dasharray':actual?'none':'5 3','stroke-linejoin':'round'},null,s);
  }
  for(const v of samples)plot(v,false);plot(d.actual_nav,true);
  el('circle',{cx:x(times.at(-1)),cy:y(d.actual_nav.at(-1)),r:3.2,fill:palette.actual},null,s);
  $('path-caption').textContent='真实序列为实线，模拟样例为虚线；展示 '+d.dates.length+' 个日期点的连线，指标按完整路径计算。'+
    (log?'对数轴等距离表示相同比例，不表示相同净值差。':'纵轴自动取范围，未强制从零开始。')+' 数据见结果 JSON 的 chart_data；不做平滑或补点。';
}
function histogram(host,id,p,key,loss=false){
  const source=p.simulation?.metric_distributions[key];
  const small=!loss,W=small?560:1100,H=small?320:360;
  if(!source?.available){missing(host,id,loss?'终点损失分布':names[key],'本档指标不可估计',W,H);return;}
  // 损失 L=-R：只将已有收益直方图镜像，沿用全部32箱计数，不重新拟合。
  const edges=loss?[...source.histogram.edges].reverse().map(v=>-v):source.histogram.edges;
  const counts=loss?[...source.histogram.counts].reverse():source.histogram.counts;
  const n=source.sample_count,actual=p.actual?.[key],s=p.simulation;
  const markers=loss?[
    {v:s.var_loss,color:palette.navy,dash:'6 3',name:'VaR'},
    {v:s.cvar_loss,color:palette.actual,dash:'2 3',name:'CVaR'}
  ]:[
    {v:source.percentiles.p05,color:palette.navy,dash:'6 3',name:'P05'},
    {v:source.percentiles.p50,color:palette.navy,dash:'none',name:'P50'},
    {v:source.percentiles.p95,color:palette.navy,dash:'6 3 1 3',name:'P95'},
    {v:actual,color:palette.actual,dash:'none',name:'真实'}
  ];
  let lo=Math.min(edges[0],...markers.filter(m=>valid(m.v)).map(m=>m.v),...(loss?[0]:[]));
  let hi=Math.max(edges.at(-1),...markers.filter(m=>valid(m.v)).map(m=>m.v),...(loss?[0]:[]));[lo,hi]=bounds(lo,hi);
  const b={l:75,r:W-22,t:85,b:H-62},x=v=>b.l+(v-lo)/(hi-lo)*(b.r-b.l);
  const ymax=Math.max(...counts.map(v=>v/n),.001)*1.12,y=v=>b.b-v/ymax*(b.b-b.t);
  const title=data.product_code+' · '+(loss?'终点损失':names[key]);
  const desc=p.label+' | '+p.start+' — '+p.end+' | n='+n.toLocaleString()+' | 32个等宽箱';
  const svg=svgFor(host,id,title,desc,W,H);
  const metricKey=loss?'total_return':key;
  axes(svg,b,ticks(lo,hi,small?3:5),ticks(0,ymax),x,y,
    v=>short(v,metricKey),v=>(v*100).toFixed(ymax<.05?1:0)+'%',
    key==='sharpe_ratio'&&!loss?'夏普比率（无量纲）':loss?'区间终点损失（%）':'指标值（%）','每箱路径占比');
  counts.forEach((count,i)=>{
    const l=x(edges[i]),r=x(edges[i+1]),top=y(count/n);
    el('rect',{x:l,y:top,width:Math.max(.2,r-l),height:b.b-top,
      fill:palette.blue,'fill-opacity':.24,stroke:palette.blue,'stroke-width':.45},null,svg);
    if(loss&&edges[i+1]>s.var_loss){
      const tailLeft=Math.max(edges[i],s.var_loss);
      el('rect',{x:x(tailLeft),y:top,width:x(edges[i+1])-x(tailLeft),height:b.b-top,
        fill:palette.actual,'fill-opacity':.22},null,svg);
    }
  });
  if(lo<=0&&hi>=0)line(svg,x(0),b.t,x(0),b.b,{stroke:palette.axis,'stroke-dasharray':'2 4'});
  markers.forEach(m=>{
    if(!valid(m.v))return;
    line(svg,x(m.v),b.t,x(m.v),b.b,{stroke:m.color,'stroke-width':m.name==='真实'?2:1.4,'stroke-dasharray':m.dash});
    el('title',{},m.name+' '+fmt(m.v,metricKey),svg.lastChild);
  });
  // 图内文字随SVG导出，颜色和线型同时区分，避免仅靠颜色理解标记。
  let lx=b.l;
  const legendValues=loss?markers:markers.map(m=>({...m,name:m.name}));
  legendValues.forEach(m=>{
    line(svg,lx,63,lx+16,63,{stroke:m.color,'stroke-width':1.6,'stroke-dasharray':m.dash});
    label(svg,lx+21,67,m.name+(loss?' '+signedPct(m.v):''),{'font-size':11});
    lx+=loss?230:small?100:140;
  });
  if(!loss&&valid(actual)&&(actual<edges[0]||actual>edges.at(-1))){
    label(svg,b.l,H-5,'真实值超出模拟箱范围；横轴已扩展，未截断尾部。',{'font-size':10});
  }
}
function saveSvg(id,suffix){
  const svg=$(id);if(!svg)return;
  const source='<?xml version="1.0" encoding="UTF-8"?>\n'+new XMLSerializer().serializeToString(svg);
  const url=URL.createObjectURL(new Blob([source],{type:'image/svg+xml;charset=utf-8'}));
  const a=document.createElement('a');a.href=url;
  a.download=data.product_code+'_'+current().date_type+'_'+suffix+'.svg';
  document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function riskExplanation(s){
  if(!s)return '本档没有模拟结果，VaR/CVaR不可用。';
  let text='置信水平 '+pct(s.var_confidence)+'；VaR '+signedPct(s.var_loss)+'，CVaR '+signedPct(s.cvar_loss)+'。';
  if(s.var_loss<0&&s.cvar_loss>0)text+='VaR所在分位仍盈利，但更差尾部的平均结果已亏损，两者异号可以成立。';
  else if(s.var_loss<0)text+='负损失表示盈利：模型尾部均值仍可为盈利，不代表现实没有亏损风险。';
  else text+='正损失表示亏损：CVaR描述损失不低于VaR的路径平均，不是最大可能亏损。';
  return text+' 阴影沿用收益直方图镜像展示；尾部统计直接读取完整路径结果，不从柱形估算。';
}
function table(p){
  const host=$('metric-table');host.replaceChildren();
  const t=document.createElement('table'),head=document.createElement('tr');
  for(const name of ['指标','真实','P05','P25','P50','P75','P95','有效路径']){
    const th=document.createElement('th');th.textContent=name;head.append(th);
  }t.append(head);
  for(const key of Object.keys(names)){
    const d=p.simulation?.metric_distributions[key],row=document.createElement('tr');
    const cells=[names[key],fmt(p.actual?.[key],key),...['p05','p25','p50','p75','p95'].map(q=>fmt(d?.percentiles?.[q],key)),d?.sample_count?.toLocaleString()??'不可用'];
    for(const value of cells){const td=document.createElement('td');td.textContent=value;row.append(td);}t.append(row);
  }host.append(t);
}
function render(){
  const p=current(),s=p.simulation,a=p.actual||{};
  $('window').textContent=p.historical_available?p.start+' — '+p.end+' ｜ '+p.steps+' 个净值间隔':'目标区间 '+p.requested_start+' — '+p.requested_end;
  $('status').replaceChildren();
  for(const text of [...(p.reason?[p.reason]:[]),...(p.notes||[])]){
    const el=document.createElement('div');el.className='notice';el.textContent=text;$('status').append(el);
  }
  const cards=[['真实累计收益',pct(a.total_return)],['真实最大回撤',pct(a.maximum_drawdown)],
    ['模拟累计收益 P50',pct(s?.metric_distributions.total_return.percentiles?.p50)],
    ['模拟终点亏损频率',pct(s?.loss_frequency)],
    ['终点损失 VaR / CVaR ('+((s?.var_confidence??data.config.confidence)*100).toFixed(0)+'%)',signedPct(s?.var_loss)+' / '+signedPct(s?.cvar_loss)],
    ['真实收益模拟百分位',pct(s?.actual_total_return_percentile_rank)]];
  $('cards').replaceChildren();
  for(const[label,value]of cards){
    const d=document.createElement('div');d.className='card';
    const sm=document.createElement('small');sm.textContent=label;
    const st=document.createElement('strong');st.textContent=value;d.append(sm,st);$('cards').append(d);
  }
  $('training').textContent=!p.fit?'本档未生成模型路径。':p.fit.calibration_mode==='initial_20_nav_out_of_sample'
    ?'训练净值 '+p.fit.training_nav_start+' — '+p.fit.training_end+'；前20条净值产生19条日对数收益；以第20条为起点，之后数据不参与估参。'
    :'训练收益 '+p.fit.training_start+' — '+p.fit.training_end+'，共 '+p.fit.training_observations+' 条日对数收益，严格早于回测起点。';
  $('path_title').textContent=data.source.nav_basis==='per_10000_income_reinvestment_index'?'A · 每万份收益复投指数与模拟路径':'A · 累计净值与模拟路径';
  drawPaths(p);$('risk-note').textContent=riskExplanation(s);
  histogram($('loss-chart'),'loss-figure',p,'total_return',true);
  $('distributions').replaceChildren();
  for(const [i,key]of Object.keys(names).entries()){
    const panel=document.createElement('div');panel.className='chart';
    const header=document.createElement('div');header.className='figure-head';
    const title=document.createElement('h3');title.textContent='C'+(i+1)+' · '+names[key];
    const button=document.createElement('button');button.type='button';button.textContent='SVG';
    button.setAttribute('aria-label','下载'+names[key]+'分布图SVG');button.onclick=()=>saveSvg('figure-'+key,key);
    header.append(title,button);
    const host=document.createElement('div'),caption=document.createElement('p');
    const d=s?.metric_distributions[key],q=d?.percentiles;
    caption.textContent=q?'P05 '+fmt(q.p05,key)+' · P50 '+fmt(q.p50,key)+' · P95 '+fmt(q.p95,key)+' ｜ n='+d.sample_count.toLocaleString():'指标不可估计，不以零代替。';
    panel.append(header,host,caption);$('distributions').append(panel);histogram(host,'figure-'+key,p,key);
  }
  table(p);
}
$('period').addEventListener('change',render);
$('path-scale').addEventListener('change',()=>drawPaths(current()));
$('save-paths').addEventListener('click',()=>saveSvg('path-figure','nav_paths'));
$('save-loss').addEventListener('click',()=>saveSvg('loss-figure','terminal_loss'));
render();
</script></body></html>'''
