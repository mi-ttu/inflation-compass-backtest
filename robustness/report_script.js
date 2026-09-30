const R = __RESULTS_JSON__;
const TEXT = __TEXT_JSON__;
const pct = (x, d=1) => x == null || !isFinite(x) ? '—' : (x*100).toFixed(d) + '%';
const num = x => x == null || !isFinite(x) ? '—' : x.toFixed(2);
const cls = x => x < 0 ? ' class="neg"' : '';

document.getElementById('overall').innerHTML = TEXT.overall;
document.getElementById('verdicts').innerHTML = TEXT.verdicts.map((v,i) =>
  `<div class="verdict"><span class="n">${i+1}</span><span class="t">${v.title}</span><span class="chip ${v.status}">${{good:'Holds up',warn:'Mixed',bad:'Concern'}[v.status]}</span><span class="s">${v.summary}</span></div>`).join('');

function section(id, n, title, finding, body, note){
  document.getElementById(id).innerHTML = `<h2><span class="num">${n}</span>${title}</h2><div class="finding">${finding}</div>${body}${note ? `<div class="note">${note}</div>` : ''}`;
}

// ---- test 1
(function(){
  const t = R.test1, sp = t.split;
  const row = (label, o, hl) => `<tr${hl ? ' class="hl"' : ''}><td>${label}</td><td${cls(o.oos.cagr)}>${pct(o.oos.cagr)}</td><td>${num(o.oos.sharpe)}</td><td${cls(o.oos.mdd)}>${pct(o.oos.mdd,0)}</td><td>${pct(o.in.cagr)}</td><td>${num(o.in.sharpe)}</td><td${cls(o.in.mdd)}>${pct(o.in.mdd,0)}</td></tr>`;
  const split = `<div class="table-scroll"><table><thead><tr class="group"><th></th><th colspan="3">1990–2002, before the published backtest</th><th colspan="3">2003–2026, the published backtest's period</th></tr>
    <tr><th></th><th>CAGR</th><th>Sharpe</th><th>Max DD</th><th>CAGR</th><th>Sharpe</th><th>Max DD</th></tr></thead><tbody>
    ${row('Inflation Compass, Hybrid QLD/XLE daily', sp.published, true)}${row('Same, with a costed QLD stand-in before 2006', sp.published_qld_costed)}${row('S&amp;P 500, buy &amp; hold', sp.spy)}${row('QLD (2× Nasdaq-100), buy &amp; hold', sp.qld)}</tbody></table></div>`;
  const sw = t.swaps.map((s,i) => `<tr${i===0?' class="hl"':''}><td>${s.label}</td><td>${pct(s.in.cagr)}</td><td>${num(s.in.sharpe)}</td><td${cls(s.in.mdd)}>${pct(s.in.mdd,0)}</td><td>${pct(s.bh_in.cagr)}</td><td>${num(s.bh_in.sharpe)}</td><td${cls(s.bh_in.mdd)}>${pct(s.bh_in.mdd,0)}</td></tr>`).join('');
  const swaps = `<h3 style="font-size:13px;margin:18px 0 4px">Same signals, different goldilocks holding (2003–2026)</h3>
    <div class="table-scroll"><table><thead><tr class="group"><th></th><th colspan="3">Inflation Compass with that holding</th><th colspan="3">That holding, buy &amp; hold</th></tr>
    <tr><th>Goldilocks holding</th><th>CAGR</th><th>Sharpe</th><th>Max DD</th><th>CAGR</th><th>Sharpe</th><th>Max DD</th></tr></thead><tbody>${sw}</tbody></table></div>`;
  // permutations: 24 bars of full-period Sharpe, published highlighted
  const P = t.permutations.slice().sort((a,b) => b.full.sharpe - a.full.sharpe);
  const W = 900, H = 230, ML = 40, MR = 10, MT = 14, MB = 60;
  const mx = Math.max(...P.map(p => p.full.sharpe)) * 1.1, mn = Math.min(0, ...P.map(p => p.full.sharpe));
  const bw = (W-ML-MR) / P.length;
  const y = v => MT + (1 - (v-mn)/(mx-mn)) * (H-MT-MB);
  const short = h => ({'XLP+IEF':'P+I'})[h] || h;
  const bars = P.map((p,i) => `<rect x="${(ML+i*bw+2).toFixed(1)}" y="${y(Math.max(0,p.full.sharpe)).toFixed(1)}" width="${(bw-4).toFixed(1)}" height="${Math.abs(y(p.full.sharpe)-y(0)).toFixed(1)}" rx="3" fill="${p.published ? 'var(--strat)' : 'var(--lev)'}" fill-opacity="${p.published ? 1 : .55}"><title>Reflation ${p.map[0]}, goldilocks ${p.map[1]}, stagflation ${p.map[2]}, slowdown ${p.map[3]}: Sharpe ${num(p.full.sharpe)}, CAGR ${pct(p.full.cagr)}</title></rect>
      <text x="${(ML+i*bw+bw/2).toFixed(1)}" y="${H-MB+12}" text-anchor="middle" class="axis-small">${short(p.map[0])}</text><text x="${(ML+i*bw+bw/2).toFixed(1)}" y="${H-MB+23}" text-anchor="middle" class="axis-small">${short(p.map[1])}</text><text x="${(ML+i*bw+bw/2).toFixed(1)}" y="${H-MB+34}" text-anchor="middle" class="axis-small">${short(p.map[2])}</text><text x="${(ML+i*bw+bw/2).toFixed(1)}" y="${H-MB+45}" text-anchor="middle" class="axis-small">${short(p.map[3])}</text>`).join('');
  const ticks = [0, .25, .5, .75, 1].filter(v => v <= mx).map(v => `<line class="gridline" x1="${ML}" x2="${W-MR}" y1="${y(v)}" y2="${y(v)}"/><text x="${ML-6}" y="${y(v)+3}" text-anchor="end">${v.toFixed(2)}</text>`).join('');
  const perm = `<h3 style="font-size:13px;margin:18px 0 2px">All 24 ways to assign the four holdings to the four regimes (Sharpe ratio, 1990–2026)</h3>
    <div class="note" style="margin:0 0 6px">Columns list the holding for reflation, goldilocks, stagflation and slowdown, top to bottom (P+I = 50/50 XLP and IEF). Hover a bar for its CAGR.</div>
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Sharpe ratio for every assignment of holdings to regimes"><g class="axis">${ticks}</g>${bars}
    <text class="lbl-muted" x="${ML-30}" y="${H-MB+12}">Refl.</text><text class="lbl-muted" x="${ML-30}" y="${H-MB+23}">Gold.</text><text class="lbl-muted" x="${ML-30}" y="${H-MB+34}">Stag.</text><text class="lbl-muted" x="${ML-30}" y="${H-MB+45}">Slow.</text></svg>`;
  section('t1', 1, 'Out of sample, and does the signal matter?', TEXT.t1, split + swaps + perm, TEXT.t1_note);
})();

// ---- test 2
(function(){
  const t2 = R.test2, pubC = t2.published.full.cagr;
  const labels = {sma:['Growth filter: S&P 500 average (days)', 200], threshold:['Breakeven threshold (%)', 2.0], mom:['Breakeven momentum window (days)', 60], basket:['Sector-basket slope window (days)', 60]};
  const W = 290, H = 130, ML = 40, MR = 8, MT = 10, MB = 22;
  const all = Object.values(t2.sweeps).flat().flatMap(p => [p.full.cagr, p.oos.cagr, p.in.cagr]);
  const lo = Math.min(...all)*0.9, hi = Math.max(...all)*1.05;
  const small = (name, pts) => {
    const [title, pub] = labels[name];
    const n = pts.length, x = i => ML + i*(W-ML-MR)/(n-1), y = v => MT + (1-(v-lo)/(hi-lo))*(H-MT-MB);
    const ticks = [0.15,0.2,0.25,0.3,0.35].filter(t => t >= lo && t <= hi).map(t => `<line class="gridline" x1="${ML}" x2="${W-MR}" y1="${y(t)}" y2="${y(t)}"/><text x="${ML-5}" y="${y(t)+3}" text-anchor="end">${(t*100).toFixed(0)}%</text>`).join('');
    const xl = pts.map((p,i) => `<text x="${x(i)}" y="${H-6}" text-anchor="middle"${p.value === pub ? ' style="fill:var(--text);font-weight:600"' : ''}>${p.value}</text>`).join('');
    const line = (key, color, dash) => `<path d="${pts.map((p,i) => (i?'L':'M') + x(i).toFixed(1) + ',' + y(p[key].cagr).toFixed(1)).join(' ')}" fill="none" stroke="${color}" stroke-width="2"${dash ? ` stroke-dasharray="${dash}"` : ''}/>` +
      pts.map((p,i) => `<circle cx="${x(i)}" cy="${y(p[key].cagr)}" r="${p.value === pub ? 4 : 2.5}" fill="${p.value === pub ? color : 'var(--surface)'}" stroke="${color}" stroke-width="1.8"><title>${p.value}: ${key === 'full' ? '1990–2026' : key === 'oos' ? '1990–2002' : '2003–2026'} CAGR ${pct(p[key].cagr)}, max DD ${pct(p[key].mdd,0)}</title></circle>`).join('');
    return `<div class="small"><h3>${title}</h3><p>Published: ${pub}</p><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${title} sweep"><g class="axis">${ticks}${xl}</g>${line('oos','var(--lev)','4,3')}${line('in','var(--bench)')}${line('full','var(--strat)')}</svg></div>`;
  };
  const legend = `<div class="legend"><span><i style="background:var(--strat)"></i>1990–2026</span><span><i style="background:var(--bench)"></i>2003–2026 (published period)</span><span><i style="background:var(--lev)"></i>1990–2002 (before it)</span></div>`;
  const smalls = `<div class="smalls">${Object.entries(t2.sweeps).map(([k,v]) => small(k,v)).join('')}</div>`;
  const cs = t2.random.map(c => c.full.cagr).sort((a,b) => a-b);
  const bins = 24, mn = Math.min(...cs, pubC), mx = Math.max(...cs, pubC), bw = (mx-mn)/bins || 1;
  const counts = new Array(bins).fill(0); cs.forEach(v => counts[Math.min(bins-1, Math.floor((v-mn)/bw))]++);
  const HW = 900, HH = 170, hl = 40, hr = 10, ht = 16, hb = 26, cmax = Math.max(...counts);
  const hx = v => hl + (v-mn)/(mx-mn)*(HW-hl-hr), hy = c => ht + (1-c/cmax)*(HH-ht-hb);
  const bars = counts.map((c,i) => `<rect x="${(hx(mn+i*bw)+1).toFixed(1)}" y="${hy(c).toFixed(1)}" width="${Math.max(1,(HW-hl-hr)/bins-2).toFixed(1)}" height="${(HH-hb-hy(c)).toFixed(1)}" rx="2" fill="var(--lev)" fill-opacity=".55"><title>${pct(mn+i*bw)} to ${pct(mn+(i+1)*bw)}: ${c} sets</title></rect>`).join('');
  const med = cs[Math.floor(cs.length/2)];
  const xt = [0,1,2,3,4,5,6].map(k => mn + k*(mx-mn)/6).map(v => `<text x="${hx(v)}" y="${HH-8}" text-anchor="middle">${pct(v)}</text>`).join('');
  const pctl = key => { const a = t2.random.map(c => c[key].cagr); return 100 * a.filter(v => v < t2.published[key].cagr).length / a.length; };
  const hist = `<div class="legend"><span><i style="background:var(--lev)"></i>300 nearby parameter sets</span><span><i style="background:var(--strat)"></i>Published</span><span><i style="background:var(--text)"></i>Median</span></div>
    <svg viewBox="0 0 ${HW} ${HH}" role="img" aria-label="CAGR across random parameter sets"><g class="axis">${xt}<line x1="${hl}" x2="${HW-hr}" y1="${HH-hb}" y2="${HH-hb}"/></g>${bars}
    <line x1="${hx(med)}" x2="${hx(med)}" y1="${ht-6}" y2="${HH-hb}" stroke="var(--text)" stroke-width="1.5" stroke-dasharray="3,3"/><text class="lbl-muted" x="${hx(med)-5}" y="${ht+2}" text-anchor="end">median ${pct(med)}</text>
    <line x1="${hx(pubC)}" x2="${hx(pubC)}" y1="${ht-6}" y2="${HH-hb}" stroke="var(--strat)" stroke-width="2.5"/><text class="lbl" x="${hx(pubC)+5}" y="${ht+2}">published ${pct(pubC)}</text></svg>`;
  const body = `<h3 style="font-size:13px;margin:4px 0 6px">One setting at a time (CAGR)</h3>${legend}${smalls}
    <h3 style="font-size:13px;margin:18px 0 2px">All settings nudged at once (1990–2026)</h3>
    <div class="note" style="margin:0 0 6px">300 sets with the growth average 150–250 days, threshold 1.75–2.25%, and both momentum windows 40–80 days. The published settings beat ${pctl('full').toFixed(0)}% of them over 1990–2026, ${pctl('in').toFixed(0)}% over the published 2003–2026 period, but only ${pctl('oos').toFixed(0)}% over 1990–2002.</div>${hist}`;
  section('t2', 2, 'Parameter robustness', TEXT.t2, body, TEXT.t2_note);
})();

// ---- test 3
(function(){
  const t3 = R.test3;
  const rows = t3.frictions.map((f,i) => `<tr${i===0?' class="hl"':''}><td>${f.scenario}</td><td>${pct(f.full.cagr)}</td><td${cls(f.full.mdd)}>${pct(f.full.mdd,0)}</td><td>${num(f.full.sharpe)}</td><td>${pct(f.oos.cagr)}</td><td>${pct(f.in.cagr)}</td></tr>`).join('');
  const it = t3.intraday;
  const dis = it.disagreements.map(d => `${d.date}: ${d.close} → ${d.live}`).join(' · ');
  const body = `<div class="table-scroll"><table><thead><tr class="group"><th></th><th colspan="3">1990–2026</th><th colspan="2">CAGR by period</th></tr><tr><th>Scenario</th><th>CAGR</th><th>Max DD</th><th>Sharpe</th><th>1990–2002</th><th>2003–2026</th></tr></thead><tbody>${rows}</tbody></table></div>
    <div class="note">The strategy changes holdings about ${t3.switches_per_year.toFixed(0)} times a year, and 44% of its holding periods last three days or less.</div>
    <h3 style="font-size:13px;margin:18px 0 4px">Deciding at 2:30 PM Central, with inflation data a day late</h3>
    <div class="stat-row">
      <div class="stat"><div class="k">Same regime as the close signal</div><div class="v">${pct(it.agreement)}</div><div class="d">${it.days} trading days, ${it.from} to ${it.to}</div></div>
      <div class="stat"><div class="k">CAGR, close signal</div><div class="v">${pct(it.close_signal.cagr)}</div><div class="d">max DD ${pct(it.close_signal.mdd,0)}</div></div>
      <div class="stat"><div class="k">CAGR, 2:30 PM signal</div><div class="v">${pct(it.live_signal.cagr)}</div><div class="d">max DD ${pct(it.live_signal.mdd,0)}</div></div>
    </div>
    <div class="note">Days where the 2:30 PM regime differs (close → 2:30 PM): ${dis || 'none'}.</div>`;
  section('t3', 3, 'Execution stress', TEXT.t3, body, TEXT.t3_note);
})();

// ---- test 4
(function(){
  const t4 = R.test4, m = t4['expanding'], m3 = t4['trailing 3 years'];
  const g = m.growth, n = g.dates.length;
  const W = 900, H = 260, ML = 52, MR = 120, MT = 12, MB = 26;
  const all = g.wf.concat(g.pub, m3.growth.wf);
  const lmin = Math.log10(Math.min(...all)*0.9), lmax = Math.log10(Math.max(...all)*1.1);
  const x = i => ML + i/(n-1)*(W-ML-MR), y = v => MT + (1-(Math.log10(v)-lmin)/(lmax-lmin))*(H-MT-MB);
  const ticks = []; for (let e = Math.ceil(lmin); e <= lmax; e++) ticks.push(Math.pow(10,e));
  const grid = ticks.map(t => `<line class="gridline" x1="${ML}" x2="${W-MR}" y1="${y(t)}" y2="${y(t)}"/><text x="${ML-6}" y="${y(t)+3}" text-anchor="end">${t >= 1000 ? (t/1000)+'k' : t}×</text>`).join('');
  const xl = [0,.2,.4,.6,.8,1].map(f => { const i = Math.round(f*(n-1)); return `<text x="${x(i)}" y="${H-8}" text-anchor="${f===0?'start':f===1?'end':'middle'}">${g.dates[i].slice(0,4)}</text>`; }).join('');
  const line = (v, c) => `<path d="${v.map((val,i) => (i?'L':'M') + x(i).toFixed(1) + ',' + y(val).toFixed(1)).join(' ')}" fill="none" stroke="${c}" stroke-width="2"/>`;
  const end = (v, label, c, dy=0) => `<circle cx="${x(n-1)}" cy="${y(v)}" r="3.5" fill="${c}" stroke="var(--surface)" stroke-width="2"/><text class="lbl" x="${x(n-1)+8}" y="${y(v)+4+dy}">${label}</text>`;
  const ends = [[g.pub[n-1], 'Published ' + pct(m.published_same_years.cagr), 'var(--strat)'], [g.wf[n-1], 'All history ' + pct(m.walk_forward.cagr), 'var(--bench)'], [m3.growth.wf[m3.growth.wf.length-1], 'Last 3 yrs ' + pct(m3.walk_forward.cagr), 'var(--lev)']]
    .map(e => ({...e, y: y(e[0])})).sort((a,b) => a.y-b.y);
  for (let i=1; i<ends.length; i++) if (ends[i].y - ends[i-1].y < 14) ends[i].y = ends[i-1].y + 14;
  const endsSvg = ends.map(e => `<circle cx="${x(n-1)}" cy="${y(e[0])}" r="3.5" fill="${e[2]}" stroke="var(--surface)" stroke-width="2"/><text class="lbl" x="${x(n-1)+8}" y="${e.y+4}">${e[1]}</text>`).join('');
  const chart = `<div class="legend"><span><i style="background:var(--strat)"></i>Published settings</span><span><i style="background:var(--bench)"></i>Walk-forward, all history so far</span><span><i style="background:var(--lev)"></i>Walk-forward, last 3 years</span></div>
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Walk-forward versus published growth"><g class="axis">${grid}${xl}</g>${line(m3.growth.wf,'var(--lev)')}${line(g.wf,'var(--bench)')}${line(g.pub,'var(--strat)')}${endsSvg}</svg>`;
  const tbl = (label, o) => `<tr><td>${label}</td><td>${pct(o.walk_forward.cagr)}</td><td${cls(o.walk_forward.mdd)}>${pct(o.walk_forward.mdd,0)}</td><td>${num(o.walk_forward.sharpe)}</td><td>${pct(o.published_same_years.cagr)}</td><td>${pct(o.median_candidate_same_years)}</td></tr>`;
  const body = chart + `<div class="table-scroll" style="margin-top:10px"><table><thead><tr><th>Re-selection uses</th><th>CAGR</th><th>Max DD</th><th>Sharpe</th><th>Published, same years</th><th>Typical candidate</th></tr></thead><tbody>${tbl('All history so far', m)}${tbl('Last 3 years only', m3)}</tbody></table></div>
    <div class="note">Each January from ${m.picks[0].year}, the settings with the best Sharpe ratio so far (published set plus the 300 random sets from test 2) are traded for the year.</div>`;
  section('t4', 4, 'Walk-forward: choosing settings without hindsight', TEXT.t4, body, TEXT.t4_note);
})();

// ---- test 5
(function(){
  const t5 = R.test5;
  const W = 900, H = 300, ML = 52, MR = 12, MT = 12, MB = 34;
  const xs = t5.paths.map(p => p.q), ys = t5.paths.map(p => p.s);
  const xmin = Math.min(...xs)-0.02, xmax = Math.max(...xs)+0.02, ymin = Math.min(0,...ys)-0.03, ymax = Math.max(...ys)+0.03;
  const x = v => ML + (v-xmin)/(xmax-xmin)*(W-ML-MR), y = v => MT + (1-(v-ymin)/(ymax-ymin))*(H-MT-MB);
  const tk = (a,b,k) => Array.from({length:k+1}, (_,i) => a + i*(b-a)/k);
  const grid = tk(ymin,ymax,5).map(v => `<line class="gridline" x1="${ML}" x2="${W-MR}" y1="${y(v)}" y2="${y(v)}"/><text x="${ML-6}" y="${y(v)+3}" text-anchor="end">${pct(v,0)}</text>`).join('') + tk(xmin,xmax,6).map(v => `<text x="${x(v)}" y="${H-18}" text-anchor="middle">${pct(v,0)}</text>`).join('');
  const lo = Math.max(xmin,ymin), hi = Math.min(xmax,ymax);
  const diag = hi > lo ? `<line x1="${x(lo)}" y1="${y(lo)}" x2="${x(hi)}" y2="${y(hi)}" stroke="var(--bench)" stroke-width="1.5" stroke-dasharray="5,4"/><text class="lbl-muted" x="${x(hi)-4}" y="${y(hi)+14}" text-anchor="end">IC = S&amp;P 500</text>` : '';
  const dots = t5.paths.map(p => `<circle cx="${x(p.q).toFixed(1)}" cy="${y(p.s).toFixed(1)}" r="3" fill="var(--strat)" fill-opacity=".55"><title>S&amp;P 500 ${pct(p.q)}, Inflation Compass ${pct(p.s)} (max DD ${pct(p.sm,0)})</title></circle>`).join('');
  const tr = (label, o) => `<tr><td>${label}</td><td${cls(o.cagr[5])}>${pct(o.cagr[5])}</td><td>${pct(o.cagr[50])}</td><td>${pct(o.cagr[95])}</td><td class="neg">${pct(o.mdd[50],0)}</td><td class="neg">${pct(o.mdd[5],0)}</td><td>${num(o.sharpe[50])}</td></tr>`;
  const body = `<div class="stat-row">
      <div class="stat"><div class="k">Beats the S&amp;P 500 (CAGR)</div><div class="v">${pct(t5.p_beats_spy_cagr,0)}</div><div class="d">of ${t5.paths.length} synthetic histories</div></div>
      <div class="stat"><div class="k">…and on Sharpe</div><div class="v">${pct(t5.p_beats_spy_sharpe,0)}</div><div class="d">risk-adjusted</div></div>
      <div class="stat"><div class="k">Beats QLD on Sharpe</div><div class="v">${pct(t5.p_beats_qld_sharpe,0)}</div><div class="d">vs just holding 2× Nasdaq</div></div>
      <div class="stat"><div class="k">Drawdown worse than −40%</div><div class="v">${pct(t5.p_mdd_worse_40,0)}</div><div class="d">of histories</div></div>
    </div>
    <div class="legend"><span><i style="background:var(--strat)"></i>One synthetic history</span><span><i style="background:var(--bench)"></i>Where IC would equal the S&amp;P 500</span></div>
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="IC CAGR versus S&P 500 CAGR across synthetic histories"><g class="axis">${grid}</g>${diag}${dots}
    <text class="lbl-muted" x="${(ML+W-MR)/2}" y="${H-2}" text-anchor="middle">S&amp;P 500 CAGR on that history</text>
    <text class="lbl-muted" transform="translate(12 ${(MT+H-MB)/2}) rotate(-90)" text-anchor="middle">Inflation Compass CAGR</text></svg>
    <div class="table-scroll" style="margin-top:10px"><table><thead><tr><th></th><th>CAGR, bad case (5th pct)</th><th>CAGR, median</th><th>CAGR, good case (95th)</th><th>Max DD, median</th><th>Max DD, bad case</th><th>Sharpe, median</th></tr></thead>
    <tbody>${tr('Inflation Compass', t5.s)}${tr('S&amp;P 500 buy &amp; hold', t5.spy)}${tr('QLD buy &amp; hold', t5.qld)}</tbody></table></div>`;
  section('t5', 5, 'Synthetic histories', TEXT.t5, body, TEXT.t5_note);
})();

document.getElementById('method').innerHTML = TEXT.method;
document.getElementById('footer').textContent = `Data through ${R.as_of}. Engine reproduces the Inflation Compass backtest exactly (${(R.validation.regime_agreement*100).toFixed(1)}% of regimes match; daily returns identical).`;
