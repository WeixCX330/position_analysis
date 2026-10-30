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
:root{--ink:#173c44;--muted:#687c82;--line:#d9e3e4;--accent:#126c67;--warm:#c55d38}
*{box-sizing:border-box}body{margin:0;background:#f2f5f3;color:var(--ink);font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{max-width:1280px;margin:auto;padding:36px 26px 60px}header{display:flex;gap:28px;justify-content:space-between;align-items:center;padding-bottom:24px;border-bottom:1px solid var(--line)}
h1{font-size:30px;line-height:1.3;margin:7px 0 10px}h2{font-size:19px;margin:0 0 12px}.eyebrow{font-size:12px;letter-spacing:2px;color:var(--accent);font-weight:700}.muted{color:var(--muted);font-size:13px}a{color:var(--accent)}
.toolbar{display:flex;align-items:center;gap:16px;flex-wrap:wrap;margin:24px 0}select{background:white;color:var(--ink);border:1px solid #a5babb;border-radius:7px;font:inherit;padding:8px 14px;min-width:170px}
.cards{display:grid;grid-template-columns:repeat(6,1fr);gap:12px}.card,.panel{background:#fff;border:1px solid var(--line);border-radius:10px;padding:18px}.card small{display:block;color:var(--muted);font-size:12px}.card strong{display:block;font-size:23px;font-weight:600;margin-top:7px;font-variant-numeric:tabular-nums}
.card:nth-child(5) strong{font-size:17px}.panel{margin-top:18px}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}.chart{background:white;border:1px solid var(--line);border-radius:10px;padding:16px}.chart h3{font-size:14px;margin:0 0 8px}.chart p{margin:0;font-size:12px;color:var(--muted)}
canvas{display:block;width:100%;height:190px}#paths{height:270px}.legend{display:flex;gap:20px;font-size:12px;color:var(--muted)}.dot{display:inline-block;width:20px;height:3px;vertical-align:middle;margin-right:6px}.notice{padding:12px 16px;border-left:3px solid var(--warm);background:#fcf2e9;margin:14px 0}pre{white-space:pre-wrap;word-break:break-word;font:13px/1.8 inherit;margin:0}details summary{cursor:pointer;font-weight:600}footer{margin-top:25px;color:var(--muted);font-size:12px}
@media(max-width:1000px){.cards{grid-template-columns:repeat(3,1fr)}.grid{grid-template-columns:repeat(2,1fr)}}
@media(max-width:620px){main{padding:22px 14px}.cards{grid-template-columns:repeat(2,1fr)}.grid{grid-template-columns:1fr}header{display:block}h1{font-size:25px}}
</style></head><body><main>
<header><div><div class="eyebrow">SINGLE FUND / HISTORICAL BACKTEST</div><h1>__CODE__ · __NAME__</h1><div id="meta" class="muted"></div></div><div class="muted"><a href="result.json">完整结果 JSON</a> · <a href="path_metrics.npz">逐路径指标</a><br>固定历史起点 · 日频 GBM · 无未来预测</div></header>
<div class="toolbar"><label for="period">时间范围</label><select id="period"></select><span id="window" class="muted"></span></div>
<div id="status"></div><div id="cards" class="cards"></div>
<section class="panel"><h2 id="path_title">累计净值与历史起点模拟路径</h2><div class="legend"><span><i class="dot" style="background:#c55d38"></i>真实序列</span><span><i class="dot" style="background:#94b5cb"></i>10 条模拟样本（非全部路径）</span></div><canvas id="paths"></canvas><div id="training" class="muted"></div></section>
<section class="panel"><h2>模拟指标分布</h2><p class="muted">橙线：真实值；绿线：P5 / P50 / P95。柱形覆盖全部有效路径；统计使用完整日频路径。</p><div id="distributions" class="grid"></div></section>
<details class="panel"><summary>分析文字与数据口径</summary><pre id="analysis"></pre></details>
<footer>VaR/CVaR 使用负的终点累计收益作为损失，可为负；不代表最大可能损失。回测数据与客户交易无关，不能单独解释客户亏损原因。</footer>
</main><script type="application/json" id="data">__DATA__</script><script>
const data=JSON.parse(document.getElementById('data').textContent);
const names={total_return:'累计收益',annualized_return:'复合年化收益',maximum_drawdown:'最大回撤',annualized_volatility:'年化波动率',sharpe_ratio:'夏普比率',downside_volatility:'年化下行波动率'};
const pct=v=>v==null?'不可用':(Math.abs(v*100)>=1e7?(v*100).toExponential(2):(v*100).toFixed(2))+'%';
const fmt=(v,k)=>v==null?'不可用':k==='sharpe_ratio'?v.toFixed(2):pct(v);
const $=id=>document.getElementById(id);
$('meta').textContent=`数据截止 ${data.data_as_of} ｜ ${data.source.valid_rows.toLocaleString()} 条净值 ｜ 每档 ${data.config.paths.toLocaleString()} 条路径`;
$('analysis').textContent=data.analysis.text;
$('path_title').textContent=data.source.nav_basis==='per_10000_income_reinvestment_index'
  ?'每万份收益复投指数与模拟路径':'累计净值与历史起点模拟路径';
for (const [i,p] of data.periods.entries()) {
  const opt=document.createElement('option');
  opt.value=i;
  opt.textContent=p.label+(p.fit?.calibration_mode==='initial_20_nav_out_of_sample'?' · 前20条训练':'')
    +(p.available?'':' · 仅历史/不可用');
  $('period').append(opt);
}
const defaultIndex=data.periods.findIndex(p=>p.date_type==='4');
$('period').value=defaultIndex>=0?defaultIndex:0;

function setup(canvas) {
  const rect=canvas.getBoundingClientRect(), ratio=window.devicePixelRatio||1;
  canvas.width=rect.width*ratio;
  canvas.height=rect.height*ratio;
  const ctx=canvas.getContext('2d');
  ctx.scale(ratio,ratio);
  ctx.font='11px sans-serif';
  return [ctx,rect.width,rect.height];
}

function empty(ctx,w,h,text) {
  ctx.fillStyle='#687c82';
  ctx.fillText(text,20,h/2);
}

function drawPaths(p) {
  const [c,w,h]=setup($('paths')), d=p.chart_data;
  if (!d) { empty(c,w,h,'无有效历史区间'); return; }
  const all=[d.actual_nav,...d.sample_paths].flat();
  let low=Math.min(...all), high=Math.max(...all);
  if (high===low) { low*=.99; high*=1.01; }
  const left=55, right=w-16, top=15, bottom=h-35;
  const x=i=>left+i*(right-left)/(d.dates.length-1);
  const y=v=>bottom-(v-low)/(high-low)*(bottom-top);
  c.fillStyle='#687c82';
  for (let i=0;i<4;i++) {
    const v=low+(high-low)*i/3;
    c.fillText(v.toFixed(3),3,y(v)+4);
    c.strokeStyle='#e6eded';
    c.beginPath(); c.moveTo(left,y(v)); c.lineTo(right,y(v)); c.stroke();
  }
  function line(values,color,width) {
    c.strokeStyle=color; c.lineWidth=width; c.beginPath();
    values.forEach((v,i)=>i?c.lineTo(x(i),y(v)):c.moveTo(x(i),y(v)));
    c.stroke();
  }
  for (const v of d.sample_paths) line(v,'#aac2d3',1);
  line(d.actual_nav,'#c55d38',2.5);
  c.fillText(d.dates[0],left,h-8);
  c.textAlign='right'; c.fillText(d.dates.at(-1),right,h-8);
}

function drawHistogram(canvas,p,key) {
  const [c,w,h]=setup(canvas), d=p.simulation?.metric_distributions[key];
  if (!d?.available) { empty(c,w,h,'本档无可用模拟指标'); return; }
  const {edges,counts}=d.histogram, actual=p.actual[key];
  let lo=edges[0], hi=edges.at(-1);
  if (actual!=null) { lo=Math.min(lo,actual); hi=Math.max(hi,actual); }
  if (lo===hi) hi=lo+1e-6;
  const left=8, right=w-8, top=12, bottom=h-30;
  const x=v=>left+(v-lo)/(hi-lo)*(right-left), max=Math.max(...counts,1);
  c.fillStyle='#698fa8';
  counts.forEach((n,i)=>c.fillRect(x(edges[i]),bottom-n/max*(bottom-top),
    Math.max(1,x(edges[i+1])-x(edges[i])-1),n/max*(bottom-top)));
  function marker(value,color,width) {
    c.strokeStyle=color; c.lineWidth=width;
    c.beginPath(); c.moveTo(x(value),top); c.lineTo(x(value),bottom); c.stroke();
  }
  for (const q of ['p05','p50','p95']) marker(d.percentiles[q],'#267a70',1);
  if (actual!=null) marker(actual,'#c55d38',2);
  c.fillStyle='#687c82'; c.fillText(fmt(lo,key),left,h-9);
  c.textAlign='right'; c.fillText(fmt(hi,key),right,h-9);
}

function render() {
  const p=data.periods[Number($('period').value)], s=p.simulation, a=p.actual||{};
  $('window').textContent=p.historical_available
    ?`${p.start} — ${p.end} ｜ ${p.steps} 个净值间隔`
    :`目标区间 ${p.requested_start} — ${p.requested_end}`;
  $('status').replaceChildren();
  for (const text of [...(p.reason?[p.reason]:[]),...(p.notes||[])]) {
    const el=document.createElement('div');
    el.className='notice'; el.textContent=text; $('status').append(el);
  }
  const metrics=[
    ['真实累计收益',pct(a.total_return)],
    ['真实最大回撤',pct(a.maximum_drawdown)],
    ['模拟累计收益 P50',pct(s?.metric_distributions.total_return.percentiles.p50)],
    ['模拟终点亏损频率',pct(s?.loss_frequency)],
    [`VaR / CVaR (${((s?.var_confidence??data.config.confidence)*100).toFixed(0)}%)`,
      pct(s?.var_loss)+' / '+pct(s?.cvar_loss)],
    ['真实收益模拟百分位',pct(s?.actual_percentile_rank)]
  ];
  $('cards').replaceChildren();
  for (const [label,value] of metrics) {
    const div=document.createElement('div'); div.className='card';
    const small=document.createElement('small'); small.textContent=label;
    const strong=document.createElement('strong'); strong.textContent=value;
    div.append(small,strong); $('cards').append(div);
  }
  $('training').textContent=!p.fit?'本档只展示可用历史，没有模型路径。'
    :p.fit.calibration_mode==='initial_20_nav_out_of_sample'
      ?`前20条净值（${p.fit.training_nav_start} — ${p.fit.training_end}）产生19个日收益用于估参；第20条作为起点，之后的收益不参与估参，首段训练期不计入回测收益。`
      :`仅用 ${p.fit.training_start} 至 ${p.fit.training_end} 的 ${p.fit.training_observations} 个日收益估计；训练数据严格早于起点。`;
  drawPaths(p);
  $('distributions').replaceChildren();
  for (const key of Object.keys(names)) {
    const div=document.createElement('div'); div.className='chart';
    const title=document.createElement('h3'); title.textContent=names[key];
    const cv=document.createElement('canvas'), txt=document.createElement('p');
    const q=s?.metric_distributions[key]?.percentiles;
    txt.textContent=q?`P5 ${fmt(q.p05,key)} · P50 ${fmt(q.p50,key)} · P95 ${fmt(q.p95,key)}`
      :'至少需要足够的日收益与有效波动';
    div.append(title,cv,txt); $('distributions').append(div);
    drawHistogram(cv,p,key);
  }
}
$('period').addEventListener('change',render);
window.addEventListener('resize',render);
render();
</script></body></html>'''
