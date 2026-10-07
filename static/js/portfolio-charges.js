(() => {
  const labels = {brokerage:"Brokerage",exchange:"Exchange charges",clearing:"Clearing charges",sebi:"SEBI charges",gst:"GST",stt:"STT",stamp_duty:"Stamp duty",dp:"DP charges",other:"Other / unitemized",recorded_fee:"Recorded fee"};
  const fmt = value => `₹${Number(value || 0).toLocaleString("en-IN",{minimumFractionDigits:2,maximumFractionDigits:2})}`;
  const el = (tag,text,className) => {const node=document.createElement(tag);if(text!=null)node.textContent=text;if(className)node.className=className;return node;};
  const sum = values => Object.values(values || {}).reduce((n,v)=>n+Number(v),0);
  let tip;
  function description(trade) {
    const lines=[`Buy charges: ${fmt(sum(trade.buy_charges))}`,`Sell charges: ${fmt(sum(trade.sell_charges))}`];
    for(const [side,items] of [["Buy",trade.buy_charges],["Sell",trade.sell_charges]])for(const [key,value] of Object.entries(items||{}))lines.push(`${side} · ${labels[key]||key}: ${fmt(value)}`);
    if(!trade.charges_complete)lines.push("Incomplete charge history; these are recorded amounts only.");
    if(!("dp" in (trade.sell_charges||{})))lines.push("DP charges have not been itemized for this sale.");
    if(trade.charge_sources?.some(s=>s.estimated))lines.push("Includes estimated allocations from document totals.");
    return lines.join("\n");
  }
  function hideTip(){if(tip)tip.hidden=true;}
  function showTip(anchor,trade){
    if(!tip){tip=el("div",null,"charge-tooltip");tip.id="charge-tooltip";tip.setAttribute("role","tooltip");document.body.append(tip);}
    tip.textContent=description(trade);tip.hidden=false;
    const rect=anchor.getBoundingClientRect(), width=Math.min(320,window.innerWidth-24);
    tip.style.width=`${width}px`;tip.style.left=`${Math.max(12,Math.min(rect.left,window.innerWidth-width-12))}px`;
    tip.style.top=`${Math.max(12,rect.top-tip.offsetHeight-8)}px`;
  }
  function link(trade){
    const a=el("a",trade.charges_complete||Number(trade.total_charges)>0?fmt(trade.total_charges):"Not imported","charge-link");
    a.href="#charge-details";a.setAttribute("aria-label",`Charge breakdown for ${trade.symbol||"trade"}`);a.setAttribute("aria-describedby","charge-tooltip");
    a.onmouseenter=a.onfocus=()=>showTip(a,trade);a.onmouseleave=a.onblur=hideTip;
    a.onclick=event=>{event.preventDefault();hideTip();details(trade);};return a;
  }
  function modal(title){
    const dialog=document.getElementById("app-modal"),host=document.getElementById("modal-content");
    host.replaceChildren();dialog.classList.add("charge-modal");const heading=el("h2",title);heading.id="modal-title";host.append(heading);
    const close=()=>{hideTip();dialog.classList.remove("charge-modal");dialog.close();};
    return {dialog,host,close};
  }
  function details(trade){
    const {dialog,host,close}=modal(`Charges · ${trade.symbol||"Closed trade"}`);
    host.append(el("p",`Buy ${trade.buy_date} · Sell ${trade.sell_date} · ${trade.units} units` ,"muted"));
    const table=el("table"),head=el("thead"),body=el("tbody");head.append(Screener.row(["Charge","Buy side","Sell side","Combined"]));
    const keys=new Set([...Object.keys(trade.buy_charges||{}),...Object.keys(trade.sell_charges||{})]);
    for(const key of keys){const buy=Number(trade.buy_charges?.[key]||0),sell=Number(trade.sell_charges?.[key]||0);body.append(Screener.row([labels[key]||key,fmt(buy),fmt(sell),fmt(buy+sell)]));}
    body.append(Screener.row(["Total",fmt(sum(trade.buy_charges)),fmt(sum(trade.sell_charges)),fmt(trade.total_charges)]));table.append(head,body);host.append(table);
    host.append(el("p","Buy charges are allocated to sold units using FIFO. The remaining buy charges stay with open units. DP charges appear only after a matching statement or itemized note. STT and unitemized fees are not deducted in the tax estimate.","muted"));
    if(!trade.charges_complete)host.append(el("p","Some charge history is missing. Import contract notes and the DP statement to complete the breakdown.","notice"));
    if(trade.charge_sources?.length){host.append(el("h3","Source documents"));const sources=new Map(trade.charge_sources.map(s=>[s.filename,s]));for(const source of sources.values())host.append(el("p",`${source.filename}${source.estimated?" · Includes estimated allocation":""}`,"subtle"));}
    if(trade.charge_lots?.length){const lots=el("details");lots.append(el("summary","FIFO lot allocations"));for(const lot of trade.charge_lots)lots.append(el("p",`${lot.buy_date} → ${lot.sell_date} · ${lot.units} units · ${fmt(lot.total_charges)} charges`,"subtle"));host.append(lots);}
    const done=el("button","Close","secondary");done.onclick=close;host.append(done);dialog.showModal();
  }
  function importForm(kind="contract"){
    const account=document.getElementById("account").value;if(!account)return;
    const {dialog,host,close}=modal(`Import ${kind==="statement"?"DP statements":"contract notes"} · ${account}`);
    host.append(el("p","Upload up to 50 PDF, CSV or XLSX files together. Review matched trades and allocations before updating charges. Original trade history is preserved.","muted"));
    const form=el("form"),fileWrap=el("label",null,"field"),files=el("input");files.type="file";files.multiple=true;files.accept=".pdf,.csv,.xlsx";files.required=true;fileWrap.append(el("span","Choose documents"),files);
    const passwordWrap=el("label",null,"field"),password=el("input");password.type="password";password.autocomplete="off";passwordWrap.append(el("span","PDF password, if required"),password);
    const note=el("p","The password is used only to unlock this batch and is not saved. Upload files with different passwords in separate batches.","subtle");
    const template=el("a","Download charge CSV template ↗");template.href="/api/portfolio/accounts/charges/template.csv";template.className="subtle";
    const error=el("p",null,"error"),submit=el("button","Preview matches");submit.type="submit";const cancel=el("button","Cancel","secondary");cancel.type="button";cancel.onclick=close;
    form.append(fileWrap,passwordWrap,note,template,error,submit,cancel);host.append(form);dialog.showModal();
    form.onsubmit=async event=>{event.preventDefault();submit.disabled=true;error.textContent="";const data=new FormData();for(const file of files.files)data.append("files",file);data.append("password",password.value);data.append("kind",kind);
      try{const response=await fetch(`/api/portfolio/accounts/${encodeURIComponent(account)}/charges/preview`,{method:"POST",body:data});const result=await response.json();if(!response.ok)throw Error(result.error||"Could not preview documents");review(result,kind);}
      catch(failure){error.textContent=failure.message;}finally{password.value="";submit.disabled=false;}
    };
  }
  function review(preview,kind){
    const {dialog,host,close}=modal(`Review charges · ${preview.account_id}`);
    host.append(el("p",`${preview.matched_rows} matched rows · ${preview.outside_rows} outside the portfolio · ${preview.documents.length} files`,"muted"));
    host.append(el("p","Contract-note breakdowns replace previously recorded trading fees. DP statement amounts update the DP component separately. Outside trades are ignored. Estimated allocations are marked; repeated or overlapping imports do not add charges twice.","notice"));
    const documents=el("details");documents.append(el("summary","Document extraction results"));
    for(const document of preview.documents){documents.append(el("strong",`${document.filename} · ${document.row_count} rows`));for(const warning of document.warnings)documents.append(el("p",warning,"subtle"));}host.append(documents);
    const targetMap=new Map(preview.targets.map(t=>[t.version,t])),table=el("table"),head=el("thead"),body=el("tbody"),controls=[];
    head.append(Screener.row(["Apply","Source / date","Stock / side","Units","Charges","Match","Status"]));
    for(const row of preview.rows){
      const check=el("input");check.type="checkbox";check.checked=row.status==="MATCHED";check.disabled=["OUTSIDE","INVALID"].includes(row.status);check.setAttribute("aria-label",`Apply ${row.symbol||row.isin||"DP"} charges from ${row.filename}`);
      const select=el("select");select.setAttribute("aria-label","Choose matching transaction");select.append(new Option(row.status==="MATCHED"?"Matched automatically":"Choose transaction…",""));
      for(const version of row.candidate_versions){const t=targetMap.get(version);if(t)select.append(new Option(`${t.symbol} · ${t.date} · ${t.side.toLowerCase()} ${t.units} · ${fmt(t.price)}`,String(version)));}
      select.disabled=check.disabled||row.status==="MATCHED";
      select.onchange=()=>{check.checked=!!select.value;};
      const source=el("span",row.filename);source.append(el("small",row.date,"stock-name"));
      const fees=el("span",fmt(sum(row.components)));fees.title=Object.entries(row.components).map(([k,v])=>`${labels[k]||k}: ${fmt(v)}`).join("\n");if(row.estimated)fees.append(el("small","Estimated allocation","stock-name"));
      const status=el("span",row.status==="MATCHED"?"Matched":row.status==="AMBIGUOUS"?"Needs mapping":row.status==="OUTSIDE"?"Ignored":"Invalid");status.title=row.reason;
      body.append(Screener.row([check,source,`${row.symbol||row.isin||"Unidentified stock"} · ${row.side.toLowerCase()}`,row.units||"—",fees,select,status]));controls.push({row,check,select});
    }
    if(!preview.rows.length){const row=Screener.row(["No importable rows. Expand document extraction results for details."]);row.firstChild.colSpan=7;body.append(row);}table.append(head,body);const wrap=el("div",null,"table-wrap charge-review-table");wrap.append(table);host.append(wrap);
    const status=el("p",null,"error"),summary=el("p",null,"muted"),apply=el("button","Apply selected charges"),back=el("button","Choose files again","secondary"),cancel=el("button","Cancel","secondary");
    const update=()=>{const selected=controls.filter(c=>c.check.checked);summary.textContent=`${selected.length} selected · ${fmt(selected.reduce((total,c)=>total+sum(c.row.components),0))} source charges. Existing fees will be reconciled, not added again.`;apply.disabled=!selected.length;};
    controls.forEach(c=>{c.check.addEventListener("change",update);c.select.addEventListener("change",update);});back.onclick=()=>importForm(kind);cancel.onclick=close;
    apply.onclick=async()=>{apply.disabled=true;status.textContent="";const selected=controls.filter(c=>c.check.checked);const mappings=Object.fromEntries(selected.filter(c=>c.select.value).map(c=>[c.row.row_id,Number(c.select.value)]));
      try{const result=await Screener.api(`/api/portfolio/accounts/${encodeURIComponent(preview.account_id)}/charges/apply`,{method:"POST",body:JSON.stringify({preview_id:preview.preview_id,expected_version:preview.expected_version,selected_row_ids:selected.map(c=>c.row.row_id),mappings})});close();Screener.status(result.duplicate?"Charges already recorded; nothing added.":`Updated ${result.updated_trades} transactions · net charge adjustment ${fmt(result.additional_charges)}.`);window.dispatchEvent(new CustomEvent("portfolio-charges-updated",{detail:{account_id:preview.account_id}}));}
      catch(failure){status.textContent=failure.message;update();}
    };host.append(summary,status,apply,back,cancel);update();if(!dialog.open)dialog.showModal();
  }
  window.PortfolioCharges={link,details,importForm};
  document.addEventListener("DOMContentLoaded",()=>{
    document.getElementById("import-contract-notes")?.addEventListener("click",()=>importForm("contract"));
    document.getElementById("import-dp-statement")?.addEventListener("click",()=>importForm("statement"));
  });
  window.addEventListener("scroll",hideTip,true);
})();
