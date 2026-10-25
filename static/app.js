let prospects = [], selected = null;
const $ = id => document.getElementById(id);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function sourceLink(value) {try {const u=new URL(value);if(u.protocol==='https:')return `<a href="${esc(u.href)}" target="_blank" rel="noopener noreferrer">View source listing ↗</a>`;}catch{}return '';}
const notice = text => {$('notice').textContent = text; if ($('detailNotice')) $('detailNotice').textContent = text;};
async function api(path, data) {
  const r = await fetch('/api/' + path, data === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  const result = await r.json(); if (!r.ok) throw Error(result.error || 'Request failed'); return result;
}
async function run(button, action) {button.disabled = true; try {await action();} catch(e) {notice(e.message);} finally {button.disabled = false;}}
async function refresh() {prospects = await api('prospects'); render();}
function render() {
  const counts = [prospects.length, prospects.filter(p=>p.status==='Reviewed').length, prospects.filter(p=>p.status==='Contacted').length, prospects.filter(p=>p.status==='Replied'||p.status==='Won').length];
  $('stats').innerHTML = ['Prospects saved','Ready for outreach','Contacted','Replies & wins'].map((s,i)=>`<div class="stat"><strong>${counts[i]}</strong><span>${s}</span></div>`).join('');
  const q = $('filter').value.toLowerCase();
  const rows = prospects.filter(p=>[p.name,p.region,p.category,p.status].join(' ').toLowerCase().includes(q));
  $('count').textContent = `${rows.length} prospects · Australia & United Kingdom`;
  $('prospects').innerHTML = rows.length ? rows.map(p=>`<article class="prospect"><div><h3>${esc(p.name)}</h3><p>${esc(p.region)} · ${esc(p.category||'Uncategorized')} · ${esc(p.source)}</p><p>${esc(p.website||'Website not added')}</p><span class="pill">${esc(p.do_not_contact?'Do not contact':p.status)}</span></div><button class="secondary" data-open="${p.id}">Review →</button></article>`).join('') : '<div class="empty"><strong>A fresh start for your pipeline</strong>Search for businesses or add your first prospect.<br>No sample leads or invented contact details.</div>';
  document.querySelectorAll('[data-open]').forEach(b=>b.onclick=()=>openDetail(Number(b.dataset.open)));
}
const field = (label,name,value,type='text') => `<label>${label}<input name="${name}" type="${type}" value="${esc(value)}"></label>`;
function openDetail(id) {
  selected = prospects.find(p=>p.id===id); const p = selected;
  $('detail').innerHTML = `<p id="detailNotice" role="status" aria-live="polite"></p><h2>${esc(p.name)}</h2><p>${esc(p.source)} · ${esc(p.region)}</p>${sourceLink(p.source_url)}<form id="edit">
    ${field('Business name','name',p.name)}${field('Website','website',p.website,'url')}${field('Recipient email — verify before sending','email',p.email,'email')}
    ${field('LinkedIn profile URL','linkedin',p.linkedin,'url')}${field('Instagram profile URL','instagram',p.instagram,'url')}
    <label>Status<select name="status">${['New','Reviewed','Contacted','Replied','Won','Closed'].map(s=>`<option ${p.status===s?'selected':''}>${s}</option>`).join('')}</select></label>
    <label class="check"><input type="checkbox" name="do_not_contact" ${p.do_not_contact?'checked':''}>Do not contact / opted out</label>
    <label>Notes<textarea name="notes">${esc(p.notes)}</textarea></label><button>Save prospect</button></form>
    <div class="actions"><button id="analyze" class="secondary">Check homepage</button><button id="draft" class="secondary">Generate draft</button><button id="history" class="secondary">Activity</button></div>
    <div class="audit">${JSON.parse(p.findings).length?JSON.parse(p.findings).map(esc).join('<br>'):'No recorded findings. Run a homepage check to collect observations.'}<p class="muted">Basic HTML checks only. Verify observations manually; these checks do not measure rankings, speed or the rendered mobile experience.</p></div>
    <form id="message">${field('Email subject','subject',p.subject)}<label>Personalized message<textarea name="message">${esc(p.message)}</textarea></label><button>Save message</button></form>
    <div class="actions"><button id="copy" class="secondary">Copy message</button><button id="social" class="secondary">Open social profile</button><button id="send">Send via Gmail</button></div><p class="muted">Gmail requires configuration, a verified recipient and Reviewed status. One send attempt per prospect; no automatic retries. LinkedIn and Instagram sending is manual.</p><div id="activity"></div>`;
  if (!$('editor').open) $('editor').showModal();
  $('edit').onsubmit = e => {e.preventDefault();run(e.submitter,async()=>{const d=Object.fromEntries(new FormData(e.target));d.do_not_contact=e.target.elements.do_not_contact.checked;await api(`prospects/${id}/update`,d);await refresh();notice('Prospect saved.');});};
  $('message').onsubmit = e=>{e.preventDefault();run(e.submitter,async()=>{await api(`prospects/${id}/update`,Object.fromEntries(new FormData(e.target)));await refresh();notice('Message saved.');});};
  $('analyze').onclick = e=>run(e.target,async()=>{await api(`prospects/${id}/analyze`,{});await refresh();openDetail(id);notice('Homepage checked. Review observations before outreach.');});
  $('draft').onclick = e=>run(e.target,async()=>{if((p.message||$('message').elements.message.value)&&!confirm('Replace the existing message with a new draft?'))return;await api(`prospects/${id}/draft`,{});await refresh();openDetail(id);notice('Draft prepared. Edit it before sending.');});
  $('copy').onclick = e=>run(e.target,async()=>{await navigator.clipboard.writeText($('message').elements.message.value);notice('Message copied.');});
  $('social').onclick=()=>{const url=$('edit').elements.linkedin.value||$('edit').elements.instagram.value;try {const u=new URL(url);if(u.protocol!=='https:'||!['linkedin.com','www.linkedin.com','instagram.com','www.instagram.com'].includes(u.hostname))throw Error();window.open(u.href,'_blank','noopener,noreferrer');}catch{notice('Add a valid HTTPS LinkedIn or Instagram profile URL first.');}};
  $('send').onclick = e=>run(e.target,async()=>{const current=prospects.find(x=>x.id===id);if(!confirm(`Send the saved email to ${current.email||'(no email set)'}? Save edits first.`))return;await api(`prospects/${id}/send`,{confirm:true});await refresh();openDetail(id);notice('Gmail accepted the message. This does not confirm delivery or a reply.');});
  $('history').onclick=e=>run(e.target,async()=>{const rows=await api(`activity/${id}`);$('activity').innerHTML='<h3>Activity</h3>'+rows.map(r=>`<p>${esc(r.created_at)} UTC · ${esc(r.kind)}</p><pre>${esc(r.detail)}</pre>`).join('');});
}
$('manual').onsubmit=e=>{e.preventDefault();run(e.submitter,async()=>{const r=await api('prospects',Object.fromEntries(new FormData(e.target)));await refresh();e.target.reset();notice(r.added?'Prospect added.':'This website is already in your pipeline.');});};
$('search').onsubmit=e=>{e.preventDefault();run(e.submitter,async()=>{notice('Searching business listings…');const d=Object.fromEntries(new FormData(e.target));const {results}=await api('search',d);$('results').innerHTML='<h3>Search results · select to save</h3>'+results.map((p,i)=>`<article class="prospect result"><div><h3>${esc(p.name)}</h3><p>${esc(p.website||'Website not supplied by provider')}</p><p>${esc(p.source)} · ${esc(p.region)}</p>${sourceLink(p.source_url)}</div><button data-add="${i}">Save lead</button></article>`).join('');document.querySelectorAll('[data-add]').forEach(b=>b.onclick=()=>run(b,async()=>{const r=await api('prospects',results[Number(b.dataset.add)]);await refresh();b.textContent=r.added?'Saved':'Already saved';}));notice(`${results.length} listings found. Google/Yelp results are listings, not verified buying intent. Respect provider storage and attribution terms.`);});};
$('csv').onchange=e=>run(e.target,async()=>{const file=e.target.files[0];if(!file)return;const r=await api('import',{csv:await file.text()});await refresh();notice(`${r.added} prospects imported.`);e.target.value='';});
$('filter').oninput=render;
$('export').onclick=()=>{const keys=['name','website','email','region','category','status','notes','do_not_contact'];const safe=v=>{let s=String(v??'');if(/^[=+@\-\t\r]/.test(s))s="'"+s;return '"'+s.replaceAll('"','""')+'"';};const blob=new Blob([[keys,...prospects.map(p=>keys.map(k=>p[k]))].map(r=>r.map(safe).join(',')).join('\r\n')],{type:'text/csv'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='prospects.csv';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);};
(async()=>{try {await refresh();const c=await api('config');$('providers').innerHTML=Object.entries({Google:c.google,Yelp:c.yelp,Gmail:c.gmail}).map(([k,v])=>`${k}: ${v?'configured (not yet verified)':'credentials needed'}`).join('<br>');}catch(e){notice(e.message);}})();
