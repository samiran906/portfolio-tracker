const currencyFormatter=new Intl.NumberFormat("en-IN",{style:"currency",currency:"INR",minimumFractionDigits:2,maximumFractionDigits:2});
const numberFormatter=new Intl.NumberFormat("en-IN",{minimumFractionDigits:0,maximumFractionDigits:4});
const priceFormatter=new Intl.NumberFormat("en-IN",{minimumFractionDigits:2,maximumFractionDigits:2});

async function loadDashboard(){
    const errorMessage=document.getElementById("error-message");
    try{
        setStatus("Loading","");
        const response=await fetch("/api/dashboard",{headers:{"Accept":"application/json"},cache:"no-store"});
        if(!response.ok) throw new Error(`API returned HTTP ${response.status}`);
        const data=await response.json();
        if(data.error) throw new Error(data.error);
        renderPortfolio(data.portfolio);
        renderAccounts(data.accounts||[]);
        renderClassifications(data.classifications||[]);
        renderGroups(data.portfolio_groups||[]);
        renderHoldings(data.securities||[]);
        setStatus("Updated","success");
        errorMessage.classList.add("hidden");
    }catch(error){
        console.error("Failed to load dashboard:",error);
        setStatus("Unavailable","error");
        errorMessage.textContent="Unable to load portfolio data. Please check the Portfolio Tracker service.";
        errorMessage.classList.remove("hidden");
    }
}
function renderPortfolio(p){
    if(!p) throw new Error("Portfolio summary is unavailable");
    document.getElementById("valuation-date").textContent=formatDate(p.valuation_date);
    document.getElementById("portfolio-value").textContent=formatCurrency(p.total_portfolio_value);
    document.getElementById("cost-value").textContent=formatCurrency(p.total_cost_value);
    document.getElementById("securities-value").textContent=formatCurrency(p.total_securities_value);
    document.getElementById("cash-value").textContent=formatCurrency(p.total_cash);
    const pnl=document.getElementById("pnl-value"); pnl.textContent=formatCurrency(p.total_unrealized_pnl); setValueClass(pnl,p.total_unrealized_pnl);
    const pct=document.getElementById("pnl-percent"); pct.textContent=`${formatPercent(p.unrealized_pnl_percent)} unrealized return`; setValueClass(pct,p.unrealized_pnl_percent);
    document.getElementById("xirr-value").textContent=formatPercent(p.portfolio_xirr_percent);
}
function renderAccounts(rows){
    const b=document.getElementById("accounts-body");
    b.innerHTML=rows.length?rows.map(a=>`<tr><td>${escapeHtml(a.account_name)}</td><td>${formatCurrency(a.total_account_value)}</td><td>${formatCurrency(a.total_securities_value)}</td><td>${formatCurrency(a.total_cash)}</td><td class="${valueClass(a.total_unrealized_pnl)}">${formatCurrency(a.total_unrealized_pnl)}</td><td class="${valueClass(a.unrealized_pnl_percent)}">${formatPercent(a.unrealized_pnl_percent)}</td><td>${formatPercent(a.account_xirr_percent)}</td></tr>`).join(""):emptyRow(7,"No account data available");
}
function renderClassifications(rows){
    const b=document.getElementById("classifications-body");
    b.innerHTML=rows.length?rows.map(a=>`<tr><td>${escapeHtml(a.classification_name)}</td><td>${formatCurrency(a.total_securities_value)}</td><td class="${valueClass(a.total_unrealized_pnl)}">${formatCurrency(a.total_unrealized_pnl)}</td><td class="${valueClass(a.unrealized_pnl_percent)}">${formatPercent(a.unrealized_pnl_percent)}</td><td>${formatPercent(a.classification_xirr_percent)}</td></tr>`).join(""):emptyRow(5,"No classification data available");
}
function renderGroups(rows){
    const b=document.getElementById("groups-body");
    b.innerHTML=rows.length?rows.map(a=>`<tr><td>${escapeHtml(a.portfolio_group_name)}</td><td>${formatCurrency(a.total_securities_value)}</td><td class="${valueClass(a.total_unrealized_pnl)}">${formatCurrency(a.total_unrealized_pnl)}</td><td class="${valueClass(a.unrealized_pnl_percent)}">${formatPercent(a.unrealized_pnl_percent)}</td><td>${formatPercent(a.portfolio_group_xirr_percent)}</td></tr>`).join(""):emptyRow(5,"No portfolio groups available");
}
function renderHoldings(rows){
    document.getElementById("holdings-count").textContent=`${rows.length} holding${rows.length===1?"":"s"}`;
    const b=document.getElementById("holdings-body");
    b.innerHTML=rows.length?rows.map(a=>`<tr><td>${escapeHtml(a.security_name)}</td><td>${escapeHtml(a.account_name)}</td><td>${formatNumber(a.quantity_held)}</td><td>${formatPrice(a.average_cost)}</td><td>${formatPrice(a.current_price)}</td><td>${formatCurrency(a.current_value)}</td><td class="${valueClass(a.unrealized_pnl)}">${formatCurrency(a.unrealized_pnl)}</td><td class="${valueClass(a.unrealized_pnl_percent)}">${formatPercent(a.unrealized_pnl_percent)}</td><td>${formatPercent(a.security_xirr_percent)}</td></tr>`).join(""):emptyRow(9,"No current holdings available");
}
function formatCurrency(v){const n=Number(v);return Number.isFinite(n)?currencyFormatter.format(n):"—"}
function formatPrice(v){const n=Number(v);return Number.isFinite(n)?`₹${priceFormatter.format(n)}`:"—"}
function formatNumber(v){const n=Number(v);return Number.isFinite(n)?numberFormatter.format(n):"—"}
function formatPercent(v){const n=Number(v);return Number.isFinite(n)?`${n.toFixed(2)}%`:"—"}
function formatDate(v){if(!v)return"—";const d=new Date(`${v}T00:00:00`);return Number.isNaN(d.getTime())?v:d.toLocaleDateString("en-IN",{day:"2-digit",month:"short",year:"numeric"})}
function valueClass(v){const n=Number(v);return Number.isFinite(n)&&n!==0?(n>0?"positive":"negative"):""}
function setValueClass(el,v){el.classList.remove("positive","negative");const c=valueClass(v);if(c)el.classList.add(c)}
function setStatus(text,state){const s=document.getElementById("status");s.classList.remove("success","error");if(state)s.classList.add(state);s.innerHTML=`<span class="status-dot"></span>${escapeHtml(text)}`}
function emptyRow(cols,msg){return`<tr><td colspan="${cols}" class="muted">${escapeHtml(msg)}</td></tr>`}
function escapeHtml(v){return String(v??"").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;").replaceAll("'","&#039;")}
document.addEventListener("DOMContentLoaded",loadDashboard);