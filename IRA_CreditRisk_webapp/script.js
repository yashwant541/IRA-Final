/* ================= IRA Credit Risk - JS tab (light, 3-step flow) ================= */
(function () {
  "use strict";
  var RC = { "Very Low":"#2fbf71","Low":"#8ccf4d","Medium":"#e7b53c","High":"#ef8a3c","Very High":"#e0483e","Not Available":"#9aa6bf" };
  var CATS = ["Secured","Unsecured","SME Banking","Wealth Lending"];
  var files = { mi:null, other:null, config:null };
  var DATA = null, RUN_ID = null;
  var overrides = {};        // overrides[product][country] = {override_rating, override_text}
  var curProd = "Secured", curCountry = null;

  function bu(p){ try { return getWebAppBackendUrl(p); } catch(e){ return p; } }
  var $=function(s,r){return (r||document).querySelector(s);};
  var $$=function(s,r){return [].slice.call((r||document).querySelectorAll(s));};
  function esc(v){return v==null?"":String(v).replace(/[&<>]/g,function(c){return{"&":"&amp;","<":"&lt;",">":"&gt;"}[c];});}
  function toast(m){var t=$("#toast");t.textContent=m;t.hidden=false;clearTimeout(t._t);t._t=setTimeout(function(){t.hidden=true;},2600);}

  /* steps */
  function goStep(n){
    [1,2,3].forEach(function(i){ $("#view"+i).hidden = (i!==n); });
    $$(".step").forEach(function(s){
      var si=+s.getAttribute("data-s");
      s.classList.toggle("active", si===n);
      s.classList.toggle("done", si<n);
    });
    window.scrollTo({top:0,behavior:"smooth"});
  }
  $$("[data-goto]").forEach(function(b){ b.addEventListener("click",function(){ goStep(+b.getAttribute("data-goto")); }); });

  /* uploads */
  $$(".drop").forEach(function(drop){
    var key=drop.getAttribute("data-key"), input=$("input",drop);
    drop.addEventListener("click",function(e){ if(e.target!==input) input.click(); });
    input.addEventListener("change",function(){ if(input.files[0]) setFile(key,input.files[0],drop); });
    ["dragenter","dragover"].forEach(function(ev){drop.addEventListener(ev,function(e){e.preventDefault();drop.classList.add("drag");});});
    ["dragleave","drop"].forEach(function(ev){drop.addEventListener(ev,function(e){e.preventDefault();drop.classList.remove("drag");});});
    drop.addEventListener("drop",function(e){var f=e.dataTransfer.files[0]; if(f) setFile(key,f,drop);});
  });
  function setFile(key,file,drop){
    files[key]=file; drop.classList.add("filled");
    $(".drop-status",drop).textContent="\u2713 "+file.name;
    $("#btn-run").disabled=!(files.mi&&files.config);
  }

  /* run */
  $("#btn-run").addEventListener("click", function(){
    if(!files.mi||!files.config){ toast("MI file and countries config are required."); return; }
    var fd=new FormData();
    if(files.mi) fd.append("mi",files.mi);
    if(files.other) fd.append("other",files.other);
    if(files.config) fd.append("config",files.config);
    fd.append("user", $("#f-user").value.trim()||"unknown");
    fd.append("quarter", $("#f-quarter").value);
    fd.append("year", $("#f-year").value.trim()||new Date().getFullYear());
    $("#btn-run").disabled=true; $("#btn-run").textContent="Processing\u2026";
    fetch(bu("/analyze"),{method:"POST",body:fd}).then(function(r){return r.json();}).then(function(res){
      $("#btn-run").disabled=false; $("#btn-run").textContent="Run checks & process";
      if(!res.ok){ toast(res.error||"Failed."); return; }
      DATA=res; RUN_ID=res.run_id; overrides={};
      renderChecks(res); renderResultsInit(res);
      goStep(2);
    }).catch(function(e){ $("#btn-run").disabled=false; $("#btn-run").textContent="Run checks & process"; toast("Request failed: "+e); });
  });

  /* step 2 - checks */
  function renderChecks(res){
    $("#run-badge").textContent = res.meta.user+" \u00b7 "+res.meta.quarter+" "+res.meta.year+" \u00b7 "+res.meta.timestamp;
    var a="<table><thead><tr><th>Table</th><th>Available</th></tr></thead><tbody>";
    res.availability.forEach(function(x){
      a+="<tr><td>"+esc(x.table)+"</td><td class='yn "+(x.available?"y":"n")+"'>"+(x.available?"Y":"N")+"</td></tr>";
    });
    $("#availability").innerHTML=a+"</tbody></table>";
    renderNA("");
  }
  $("#na-search").addEventListener("input",function(){ renderNA(this.value.toLowerCase()); });
  function renderNA(q){
    var rows=DATA.na_details.filter(function(d){ return !q || (d.product+" "+d.country+" "+d.label+" "+d.reason).toLowerCase().indexOf(q)>=0; });
    if(!rows.length){ $("#na-details").innerHTML="<p class='muted pad'>Nothing missing \u2014 all values computed.</p>"; return; }
    var h="<table><thead><tr><th>Product</th><th>Country</th><th>Label</th><th>Why not available</th></tr></thead><tbody>";
    rows.forEach(function(d){ h+="<tr><td>"+esc(d.product)+"</td><td>"+esc(d.country)+"</td><td>"+esc(d.label)+"</td><td class='na'>"+esc(d.reason)+"</td></tr>"; });
    $("#na-details").innerHTML=h+"</tbody></table>";
  }

  /* step 3 - results */
  function renderResultsInit(res){
    var sp=$("#sel-product"); sp.innerHTML="";
    CATS.forEach(function(c){ if((res.countries_by_product[c]||[]).length){ var o=document.createElement("option"); o.value=c;o.textContent=c; sp.appendChild(o);} });
    curProd = sp.value || "Secured";
    fillCountries(); renderResultTable();
    sp.onchange=function(){ curProd=sp.value; fillCountries(); renderResultTable(); };
    $("#sel-country").onchange=function(){ curCountry=$("#sel-country").value; renderResultTable(); loadOverride(); };
    $("#ov-rating").onchange=saveOverrideField;
    $("#ov-text").oninput=saveOverrideField;
  }
  function fillCountries(){
    var sc=$("#sel-country"); sc.innerHTML="";
    (DATA.countries_by_product[curProd]||[]).forEach(function(c){ var o=document.createElement("option"); o.value=c;o.textContent=c; sc.appendChild(o); });
    curCountry=sc.value||null; loadOverride();
  }
  function renderResultTable(){
    var rows=((DATA.results[curProd]||{})[curCountry])||[];
    var ov=(overrides[curProd]||{})[curCountry]||{};
    var h="<table><thead><tr><th>Label</th><th>Value</th><th>Risk Rating</th><th>Risk Number</th></tr></thead><tbody>";
    rows.forEach(function(r){
      var cls=r.calc?"rowfinal":(r.override?"rowoverride":"");
      var rating=r.rating, value=r.value, num=r.number;
      if(r.override){ rating=ov.override_rating||"—"; value=ov.override_text||""; num=""; }
      var rcell = (rating&&RC[rating]) ? "<span class='rate' style='background:"+RC[rating]+"'>"+esc(rating)+"</span>" : esc(rating||"");
      h+="<tr class='"+cls+"'><td>"+esc(r.label)+"</td><td>"+(value==null||value===""?"<span class='na'>—</span>":esc(value))+"</td><td>"+rcell+"</td><td>"+(num==null?"":esc(num))+"</td></tr>";
    });
    $("#result-table").innerHTML=h+"</tbody></table>";
    $("#ov-scope").textContent=curProd+" \u00b7 "+(curCountry||"");
  }
  function loadOverride(){
    var ov=(overrides[curProd]||{})[curCountry]||{};
    $("#ov-rating").value=ov.override_rating||"";
    $("#ov-text").value=ov.override_text||"";
    $("#ov-saved").textContent="";
    renderResultTable();
  }
  function saveOverrideField(){
    overrides[curProd]=overrides[curProd]||{};
    overrides[curProd][curCountry]={ override_rating:$("#ov-rating").value, override_text:$("#ov-text").value.trim() };
    $("#ov-saved").textContent="Captured for "+curProd+" \u00b7 "+curCountry+" (saved on approval).";
    renderResultTable();
  }

  /* finalize actions */
  function logLine(msg,cls){ var d=document.createElement("div"); d.className="line "+(cls||""); d.innerHTML=msg; $("#finalize-log").appendChild(d); }
  $("#btn-save").addEventListener("click",function(){
    post("/save_output",{run_id:RUN_ID}).then(function(r){
      logLine(r.ok?("Output saved to managed folder: <b>"+esc(r.path)+"</b>"):("Save failed: "+esc(r.error)), r.ok?"ok":"err");
      toast(r.ok?"Saved to Dataiku folder":"Save failed"); loadHistory();
    });
  });
  $("#btn-tableau").addEventListener("click",function(){
    logLine("Triggering Tableau scenario\u2026");
    post("/trigger_tableau",{run_id:RUN_ID}).then(function(r){
      logLine(r.ok?("Tableau scenario triggered: <b>"+esc(r.scenario)+"</b>"):("Trigger failed: "+esc(r.error)), r.ok?"ok":"err");
      toast(r.ok?"Tableau upload triggered":"Trigger failed");
    });
  });
  $("#btn-approve").addEventListener("click",function(){
    var payload=[];
    Object.keys(overrides).forEach(function(p){ Object.keys(overrides[p]).forEach(function(c){
      var o=overrides[p][c]; if((o.override_rating&&o.override_rating!=="")||(o.override_text&&o.override_text!=="")){
        payload.push({product:p,country:c,override_rating:o.override_rating,override_text:o.override_text});
      }
    });});
    post("/approve",{run_id:RUN_ID,overrides:payload}).then(function(r){
      logLine(r.ok?("Approved & finalized. Overrides saved: <b>"+r.overrides_saved+"</b> \u2192 "+esc(r.path)):("Approve failed: "+esc(r.error)), r.ok?"ok":"err");
      toast(r.ok?"Approved & finalized":"Approve failed"); loadHistory();
    });
  });
  $("#btn-download").addEventListener("click",function(){
    window.open(bu("/download/"+encodeURIComponent(RUN_ID)),"_blank");
  });

  function post(path,body){
    return fetch(bu(path),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)})
      .then(function(r){return r.json();}).catch(function(e){return {ok:false,error:String(e)};});
  }

  /* history */
  $("#btn-refresh").addEventListener("click", loadHistory);
  function loadHistory(){
    fetch(bu("/history")).then(function(r){return r.json();}).then(function(res){
      var runs=(res&&res.runs)||[];
      if(!runs.length){ $("#history").innerHTML="<p class='muted pad'>No runs yet.</p>"; return; }
      var h="<table><thead><tr><th>When</th><th>User</th><th>Quarter</th><th>Year</th><th>Countries</th><th>Gaps</th><th>Status</th></tr></thead><tbody>";
      runs.forEach(function(m){
        h+="<tr><td>"+esc(m.timestamp)+"</td><td>"+esc(m.user)+"</td><td>"+esc(m.quarter)+"</td><td>"+esc(m.year)+"</td><td>"+esc(m.n_countries)+"</td><td>"+esc(m.na_count)+"</td><td>"+esc(m.status)+"</td></tr>";
      });
      $("#history").innerHTML=h+"</tbody></table>";
    }).catch(function(){});
  }
  loadHistory();
})();
