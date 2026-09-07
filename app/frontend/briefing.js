export default function({ data, parentElement, setTriggerValue }) {
const root=parentElement;
const listeners=new AbortController();
const companies=data.company_intelligence?.companies||[],trends=data.trends||[];
let companyIndex=0,reportName='';
const $=id=>root.querySelector('#'+id),esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const stamp=v=>{const d=new Date(v);return isNaN(d)?'시각 정보 없음':new Intl.DateTimeFormat('ko-KR',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(d)};
const main=c=>c.briefs||[],monitor=c=>c.monitoring_items||[],title=b=>b.headline_ko||b.title_ko||'브리핑';
function summary(c){return c.display_summary||''}
function excerpt(s,max=125){s=String(s||'');if(s.length<=max)return s;const cut=s.slice(0,max),last=Math.max(cut.lastIndexOf('. '),cut.lastIndexOf('다.'));return last>max*.45?cut.slice(0,last+2):cut+'…'}
function tags(values){return (values||[]).map(v=>`<span class="tag">${esc(v)}</span>`).join(' ')}
function evidence(articles){return (articles||[]).map(a=>{const url=/^https?:\/\//i.test(a.url||'')?a.url:'';return `<div class="ev">${url?`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(a.title)} ↗</a>`:`<span class="ev-title">${esc(a.title)} <span class="tag">${data.status==='DEMO'?'합성':'원문 링크 없음'}</span></span>`}<small>${esc(a.source)} · ${esc(stamp(a.published_at))}</small></div>`}).join('')}
function evidenceBlock(items){if(!items?.length)return '';return `<div class="evidence"><div class="label">EVIDENCE · 근거 기사 ${items.length}건</div>${evidence(items.slice(0,2))}${items.length>2?`<details><summary>근거 ${items.length-2}건 더 보기</summary>${evidence(items.slice(2))}</details>`:''}</div>`}
function briefHtml(b){return `<article class="panel brief-card"><div class="brief-top"><h3>${esc(title(b))}</h3><span class="tag">${esc(b.corroboration_label)}</span></div><div class="label">상황 요약</div><p class="body-copy">${esc(b.situation_ko)}</p><div class="fields"><div><div class="label">회사 관련성</div><p class="body-copy">${esc(b.company_relevance_ko)}</p></div><div><div class="label">사업 영향</div><p class="body-copy">${esc(b.business_impact_ko)}</p></div></div><div style="margin-top:12px">${tags(b.business_tags)}</div>${b.watch_next?.length?`<div class="watch"><div class="label">WATCH NEXT · 후속 관찰</div><ul>${b.watch_next.map(w=>`<li>${esc(w)}</li>`).join('')}</ul></div>`:''}${evidenceBlock(b.evidence_articles)}</article>`}
function monitorHtml(b){return `<article class="panel monitor"><h3>${esc(title(b))}</h3><p>${esc(b.reason_ko)}</p>${tags(b.business_tags)}<div class="label">${esc(b.corroboration_label)} · 근거 ${(b.evidence_articles||[]).length}건</div>${b.evidence_articles?.length?`<details><summary>근거 기사 보기</summary>${evidence(b.evidence_articles)}</details>`:''}</article>`}
function render(){const c=companies[companyIndex];
 $('company-notice').textContent=data.company_intelligence.reason||'';$('company-notice').hidden=!data.company_intelligence.reason;
 $('trend-list').innerHTML=trends.map((t,i)=>`<div class="trend-row"><div class="trend" data-trend="${i}"><span class="rank">${String(i+1).padStart(2,'0')}</span><span><span class="trend-title">${esc(t.title_ko)}</span><span class="trend-desc">${esc(t.summary_ko)}</span></span></div><button class="trend-evidence" data-evidence="${i}" aria-haspopup="dialog" aria-controls="evidence-dialog" aria-label="${esc(t.title_ko)} 근거 기사 보기"><strong>기사 ${(t.articles||[]).length}건 · 출처 ${Number(t.source_count)||0}개</strong><span>근거 보기 ›</span></button></div>`).join('');
 if(!trends.length)$('trend-list').innerHTML='<div class="empty-trends">표시할 트렌드가 없습니다. 최신 데이터 불러오기로 다시 확인할 수 있습니다.</div>';
 $('company-tabs').innerHTML=companies.map(v=>`<a href="#/company/${encodeURIComponent(v.company_id)}" aria-current="${v===c?'page':'false'}">${esc(v.company_name.replace('한화',''))}</a>`).join('');
 $('detail-notice').textContent=data.company_intelligence.reason||'';$('detail-notice').hidden=!data.company_intelligence.reason;
 if(!companies.length){$('company-grid').innerHTML='<div class="empty">회사별 브리핑 데이터가 없습니다.</div>';return;}
 $('company-report').href='#/discussion/'+encodeURIComponent(c.company_id);
 $('company-grid').innerHTML=companies.map((v,i)=>`<a class="panel company-card" href="#/company/${encodeURIComponent(v.company_id)}" aria-label="${esc(v.company_name)} 주간 브리핑 보기"><div class="company-top"><h3>${esc(v.company_name)}</h3><span class="company-mark" aria-hidden="true">${['L','I','A'][i]||'H'}</span></div><p class="summary clamp" title="${esc(summary(v))}">${esc(summary(v))}</p><div class="company-foot"><span>${v.status==='AVAILABLE'?`Main Brief <b>${main(v).length}</b> · Monitoring <b>${monitor(v).length}</b>`:'분석 결과 미제공'}</span><span class="text-link" aria-hidden="true">브리핑 보기 →</span></div></a>`).join('');
 $('detail-title').textContent=c.company_name+' 주간 브리핑';
 const overview=`<div class="detail-summary"><strong>이번 주 상태 요약<br><span class="eyebrow">WEEKLY OVERVIEW</span></strong><p>${esc(summary(c))}</p></div>`;
 if(c.status!=='AVAILABLE'){$('detail-body').innerHTML=overview+`<div class="empty">이 회사의 분석 미완료는 관련 이슈가 없다는 뜻이 아닙니다. 다른 회사의 정상 결과는 회사 선택에서 확인할 수 있습니다.</div>`;return;}
 $('detail-body').innerHTML=overview+(main(c).length?`<div class="detail-cols"><div><div class="subhead">Main Brief <span>핵심 브리핑 ${main(c).length}건</span></div>${main(c).map(briefHtml).join('')}</div><div><div class="subhead">Monitoring <span>후속 관찰 ${monitor(c).length}건</span></div>${monitor(c).length?monitor(c).map(monitorHtml).join(''):'<div class="empty">별도 Monitoring 항목이 없습니다.</div>'}</div></div>`:monitor(c).length?`<div class="subhead">Monitoring <span>후속 관찰 ${monitor(c).length}건 · 이번 주 Main Brief 없음</span></div><div class="company-grid monitoring-grid">${monitor(c).map(monitorHtml).join('')}</div>`:'<div class="empty"><b>이번 주 별도 브리핑 항목이 없습니다.</b><br>다음 데이터 갱신 시 다시 확인할 수 있습니다.</div>');
}

function chart(days){if(!days.length)return '';const peak=Math.max(1,...days.map(d=>Number(d.count)||0));return `<div role="img" aria-label="${esc(days.map(d=>`${d.label} ${d.count}건`).join(', '))}"><div class="evidence-chart">${days.map(d=>`<span style="height:${(Number(d.count)||0)/peak*100}%" title="${esc(d.label)} · ${Number(d.count)||0}건"></span>`).join('')}</div><div class="chart-label"><span>${esc(days[0].label)}</span><span>일별 기사 수</span><span>${esc(days.at(-1).label)}</span></div></div>`}
function openEvidence(index){
 const t=trends[index],articles=[...(t.articles||[])].sort((a,b)=>(Date.parse(b.published_at)||0)-(Date.parse(a.published_at)||0));
 $('evidence-content').innerHTML=`<div class="eyebrow">EVIDENCE / TREND ${String(index+1).padStart(2,'0')}</div><h2 id="evidence-title">${esc(t.title_ko)}</h2><p class="intro-copy">${esc(t.summary_ko)}</p><div class="evidence-stats"><span class="tag">기사 ${articles.length}건</span><span class="tag">고유 출처 ${Number(t.source_count)||0}개</span></div><div class="trend-why"><div class="label">WHY IT MATTERS</div><p class="intro-copy">${esc(t.why_it_matters_ko)}</p></div><details><summary>Trend Detail · Watch Next와 집계 보기</summary><p class="body-copy">48시간 집중도 ${Math.round(Number(t.recent_48h_share||0)*100)}% · ${esc(t.watch_area_label||'')}</p>${(t.watch_next||[]).map(w=>`<p class="body-copy">· ${esc(w)}</p>`).join('')}${chart(t.daily_counts||[])}</details><div class="label">관련 기사 · 최신순</div><div class="evidence-list">${articles.length?articles.map(a=>{const url=/^https?:\/\//i.test(a.url||'')?a.url:'';return `<article class="ev">${url?`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(a.title)} ↗</a>`:`<span class="ev-title">${esc(a.title)} <span class="tag">${data.status==='DEMO'?'합성 · 원문 없음':'원문 링크 없음'}</span></span>`}<small>${esc(a.source)} · ${esc(stamp(a.published_at))} KST</small>${a.summary?`<p class="evidence-description">${esc(a.summary)}</p>`:''}</article>`}).join(''):'<div class="evidence-empty">저장된 기사 근거가 없습니다.</div>'}</div><p class="evidence-help">기사 제목을 누르면 원문이 새 탭에서 열립니다. 이 목록은 선택한 회사의 브리핑 유무와 관계없이 트렌드 자체의 근거를 보여줍니다.</p>`;
 $('evidence-dialog').showModal();$('evidence-dialog').scrollTop=0;
}
root.addEventListener('click',e=>{const button=e.target.closest('[data-evidence]');if(button)openEvidence(Number(button.dataset.evidence))},{signal:listeners.signal});
$('close-evidence').onclick=()=>$('evidence-dialog').close();


function report(group){const cs=group?companies:[companies[companyIndex]];reportName=group?'주간_논의자료':cs[0].company_name+'_논의자료';const refs=[];for(const c of cs)for(const b of [...main(c),...monitor(c)])for(const a of b.evidence_articles||[])if(/^https?:\/\//i.test(a.url||'')&&!refs.some(r=>r.url===a.url))refs.push(a);
 $('report-sheet').innerHTML=`<div class="report-brand">HANWHA / EXECUTIVE INTELLIGENCE</div><h1>${group?'주간 논의자료':esc(cs[0].company_name)+' 논의자료'}</h1><p class="report-meta">분석 기준 ${esc(stamp(data.generated_at))} KST · 최근 ${data.window_days}일 · 표시 데이터 기준</p>${data.company_intelligence.reason?`<p class="report-meta">분석 안내: ${esc(data.company_intelligence.reason)}</p>`:''}<h2>이번 주 핵심 트렌드</h2>${trends.map((t,i)=>`<div class="report-row"><b>${String(i+1).padStart(2,'0')} ${esc(t.title_ko)}</b><br>${esc(excerpt(t.why_it_matters_ko,110))}</div>`).join('')}<h2>계열사별 해석</h2><div class="${group?'report-companies':''}">${cs.map(c=>`<div class="report-company"><h3>${esc(c.company_name)}</h3><p>${esc(excerpt(summary(c),group?135:280))}</p><p style="margin-top:7px">${c.status==='AVAILABLE'?`Main Brief ${main(c).length}건 · Monitoring ${monitor(c).length}건`:'분석 결과 미제공'}</p></div>`).join('')}</div><h2>검토·확인할 사항</h2>${cs.map(c=>{const b=main(c)[0],m=monitor(c)[0];return `<div class="report-row"><b>${esc(c.company_name)}</b> · ${esc(excerpt(b?.watch_next?.[0]||m?.reason_ko||(c.status==='AVAILABLE'?'등록된 후속 관찰 항목 없음':'분석 미완료로 관찰 항목을 확인할 수 없음'),group?100:220))}</div>`}).join('')}<div class="fine">주요 근거 ${refs.slice(0,3).map((a,i)=>`<a href="${esc(a.url)}" target="_blank" rel="noopener noreferrer">[${i+1}] ${esc(a.source)}</a>`).join(' · ')||'별도 근거 링크 없음'}<br>한 페이지 요약을 위해 일부 문장과 항목을 발췌했습니다. 전체 브리핑과 근거는 서비스 상세 화면에서 확인하세요.<br>공개 근거 기반의 분석 보조 자료이며 투자 추천이나 미래 예측을 제공하지 않습니다.</div>`;
 }
$('print-report').onclick=()=>{const win=window.open('','_blank');if(!win){$('export-status').textContent='팝업이 차단됐습니다. HTML 다운로드 후 인쇄할 수 있습니다.';return;}win.opener=null;win.document.open();win.document.write(reportDocument());win.document.close();win.document.fonts.ready.then(()=>{win.focus();win.print()});};
function reportDocument(){
 const compact=$('compact-export').checked;
 const content=document.createElement('div');
 content.innerHTML=compact?$('report-sheet').innerHTML:'<h1>'+esc(reportName.replaceAll('_',' '))+'</h1>'+$('discussion-body').innerHTML;
 content.querySelectorAll('details').forEach(el=>el.open=true);
 return '<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+esc(reportName)+'</title><style>'+data.report_css+'</style></head><body><main class="report-sheet">'+content.innerHTML+'</main></body></html>';
}
$('download-report').onclick=()=>{const url=URL.createObjectURL(new Blob([reportDocument()],{type:'text/html;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=reportName+($('compact-export').checked?'_한장요약':'')+'.html';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};
$('logo').src=data.logo;$('stamp').innerHTML=`<span class="badge">${esc(data.status)}</span><br>표시 데이터 ${esc(stamp(data.generated_at))} KST${data.refresh?.attempted_at?`<br>최근 시도 ${esc(stamp(data.refresh.attempted_at))} · ${esc(data.refresh_label)}`:''}`;
$('stats').innerHTML=[['분석 기간',data.window_days,'일'],['수집 기사',data.stats.article_count,'건'],['고유 출처',data.stats.source_count,'개'],['핵심 트렌드',trends.length,'건']].map(([l,v,u])=>`<div><small>${l}</small><strong>${Number(v).toLocaleString()}<em>${u}</em></strong></div>`).join('');
const status=$('refresh-status');status.textContent=data.feedback?.message||data.notice||data.refresh_message||'공개 기사를 수집하고 회사별 사업 관점으로 분석합니다.';status.dataset.outcome=data.feedback?.outcome||data.refresh?.outcome||'';
$('refresh-data').disabled=false;$('refresh-data').textContent='최신 데이터 불러오기';
$('refresh-data').onclick=()=>{const button=$('refresh-data');button.disabled=true;button.textContent='수집·분석 중…';status.textContent='기사를 수집하고 트렌드·회사별 브리핑을 분석하고 있습니다. 기존 결과는 계속 확인할 수 있습니다.';setTriggerValue('refresh',Date.now());};
function route(){
 const parts=location.hash.replace(/^#\/?/,'').split('/');
 let id='';try{id=decodeURIComponent(parts[1]||'')}catch{}
 const type=parts[0]||'home',index=companies.findIndex(c=>c.company_id===id);
 const isCompany=type==='company'&&index>=0;
 const isDiscussion=type==='discussion'&&(id==='all'||index>=0);
 if(index>=0)companyIndex=index;
 render();
 $('home-page').hidden=isCompany||isDiscussion;
 $('company-detail').hidden=!isCompany;
 $('discussion-page').hidden=!isDiscussion;
 $('group-report').hidden=isCompany||isDiscussion;
 if(isDiscussion){
  const group=id==='all',cs=group?companies:[companies[companyIndex]];
  report(group);
  $('discussion-title').textContent=group?'주간 논의자료':cs[0].company_name+' 논의자료';
  $('discussion-back').href=group?'#/':'#/company/'+encodeURIComponent(id);
  $('discussion-back').textContent=group?'← 전체 현황':'← 회사 브리핑';
  $('discussion-body').innerHTML=`<p class="report-meta">분석 기준 ${esc(stamp(data.generated_at))} KST · ${esc(data.status)}</p>${data.company_intelligence.reason?`<p class="overview-alert">${esc(data.company_intelligence.reason)}</p>`:''}<h2>확인된 변화</h2>${trends.map(t=>`<article class="panel monitor"><h3>${esc(t.title_ko)}</h3><p>${esc(t.summary_ko)}</p><p>${esc(t.why_it_matters_ko)}</p>${evidenceBlock(t.articles)}</article>`).join('')||'<p>표시할 트렌드가 없습니다.</p>'}<h2>계열사 관련성 · 검토·확인할 사항</h2>${cs.map(c=>`<section class="discussion-company"><h3>${esc(c.company_name)}</h3><p class="body-copy">${esc(summary(c))}</p>${main(c).map(briefHtml).join('')}${monitor(c).map(monitorHtml).join('')}</section>`).join('')||'<p>회사별 브리핑 데이터가 없습니다.</p>'}`;
 }
 const heading=isCompany?$('detail-title'):isDiscussion?$('discussion-title'):$('home-page');
 root.querySelector('.shell').scrollIntoView({block:'start'});
 if(heading.tabIndex===-1)heading.focus({preventScroll:true});
}
window.addEventListener('hashchange',route,{signal:listeners.signal});
route();
return ()=>{listeners.abort();};
}
