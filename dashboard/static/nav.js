/** Shared top nav — Main | Fan | Conversation */
(function(){
  const path=(location.pathname.replace(/\/$/,"")||"/").split("?")[0];
  const k=new URLSearchParams(location.search).get("k");
  const q=k?"?k="+encodeURIComponent(k):"";
  const tabs=[
    {href:"/",label:"Main",match:p=>p==="/"},
    {href:"/lights",label:"Lights",match:p=>p==="/lights"},
    {href:"/watch",label:"Watch",match:p=>p==="/watch"},
    {href:"/fan",label:"Fan",match:p=>p==="/fan"},
    {href:"/conversation",label:"Conversation",match:p=>p==="/conversation"||p==="/chat"},
  ];
  const nav=document.createElement("nav");
  nav.className="peachy-nav";
  nav.setAttribute("aria-label","Peachy sections");
  const brand=document.createElement("a");
  brand.className="brand";
  brand.href="/"+q;
  brand.textContent="Peachy";
  const row=document.createElement("div");
  row.className="tabs";
  for(const t of tabs){
    const a=document.createElement("a");
    a.href=t.href+q;
    a.textContent=t.label;
    if(t.match(path)) a.classList.add("active");
    row.appendChild(a);
  }
  nav.append(brand,row);
  const host=document.getElementById("peachyNav")||document.body;
  if(host.id==="peachyNav") host.replaceWith(nav);
  else document.body.insertBefore(nav,host.firstChild);
})();
