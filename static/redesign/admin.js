let token = localStorage.getItem("token") || "";
let selectedUser = null;
let offset = 0;
let limit = 20;
let radarInstance = null;

function authHeaders(h={}) {
  if (token) h["Authorization"] = "Bearer " + token;
  return h;
}
function handleLogout(){
  localStorage.removeItem("token");
  location.href="/redesign";
}
async function checkAdmin(){
  const r = await fetch("/v1/auth/me", {headers: authHeaders()});
  if(!r.ok){ location.href="/redesign"; return; }
  const j = await r.json();
  if(j.user.role!=="admin"){ alert("仅管理员可访问"); location.href="/redesign"; }
}
async function loadUsers(){
  const r = await fetch("/v1/admin/users", {headers: authHeaders()});
  if(!r.ok){ document.getElementById("userTbody").innerHTML=`<tr><td colspan="6">加载失败 ${r.status}</td></tr>`; return; }
  const j = await r.json();
  const tbody = document.getElementById("userTbody");
  tbody.innerHTML = "";
  j.users.forEach(u=>{
    const tr=document.createElement("tr");
    tr.onclick=()=>selectUser(u);
    tr.innerHTML=`<td>${u.nickname||u.username}</td><td>${u.username}</td><td><span class="tag">${u.role}</span></td><td>${u.stats.total_memories}</td><td>${u.stats.total_interactions}</td><td>${u.personality.samples||0}</td>`;
    tbody.appendChild(tr);
  });
}
function selectUser(u){
  selectedUser=u;
  document.querySelectorAll("#userTbody tr").forEach(tr=>tr.classList.remove("active"));
  // highlight
  event.currentTarget.classList.add("active");
  showRadar(u);
  document.getElementById("chatPanel").style.display="block";
  offset=0;
  loadChats();
}
function showRadar(u){
  const panel=document.getElementById("radarPanel");
  panel.style.display="flex";
  document.getElementById("radarTitle").textContent = `${u.nickname} (${u.username}) 人格雷达`;
  const scores=u.personality.scores||{};
  const work=u.personality.work_style||{};
  document.getElementById("radarDesc").textContent = `样本 ${u.personality.samples||0} | ${work.thinking_label||""} · ${work.execution_label||""}`;
  document.getElementById("workStyle").innerHTML = `思维: ${work.thinking_note||""}<br>执行: ${work.execution_note||""}`;
  const ctx=document.getElementById("radarChart").getContext("2d");
  const data=[scores.openness||0.5, scores.conscientiousness||0.5, scores.extraversion||0.5, scores.agreeableness||0.5, scores.neuroticism||0.5];
  if(radarInstance) radarInstance.destroy();
  radarInstance=new Chart(ctx,{
    type:'radar',
    data:{labels:['开放性','尽责性','外向性','宜人性','神经质'], datasets:[{label:'得分', data:data, backgroundColor:'rgba(44,107,93,0.2)', borderColor:'#2c6b5d', pointBackgroundColor:'#2c6b5d'}]},
    options:{scales:{r:{min:0,max:1,ticks:{stepSize:0.2}}}, plugins:{legend:{display:false}}}
  });
}
async function loadChats(){
  if(!selectedUser) return;
  const q=document.getElementById("qInput").value.trim();
  const from=document.getElementById("fromInput").value;
  const to=document.getElementById("toInput").value;
  let url=`/v1/admin/users/${selectedUser.username}/interactions?limit=${limit}&offset=${offset}`;
  if(q) url+=`&q=${encodeURIComponent(q)}`;
  if(from) url+=`&from=${from}`;
  if(to) url+=`&to=${to}`;
  const r=await fetch(url, {headers: authHeaders()});
  const j=await r.json();
  const list=document.getElementById("chatList");
  if(!r.ok){ list.innerHTML=`<p>加载失败 ${j.error||r.status}</p>`; return; }
  document.getElementById("pageInfo").textContent=`共 ${j.total} 条，偏移 ${j.offset}`;
  list.innerHTML="";
  j.interactions.forEach(it=>{
    const div=document.createElement("div");
    div.className="chat-item";
    div.innerHTML=`
      <div class="meta"><span>${it.created_at}</span><span>${it.id}</span></div>
      <div class="msg"><strong>用户:</strong> ${escapeHtml(it.message)}</div>
      <div class="reply"><strong>助手:</strong> ${escapeHtml(it.reply)}</div>
      <div class="actions">
        <button class="btn btn-danger" onclick="deleteChat('${it.id}')">删除</button>
        <button class="btn" onclick="annotateChat('${it.id}')">标注</button>
      </div>`;
    list.appendChild(div);
  });
  if(j.interactions.length===0) list.innerHTML="<p style='color:var(--muted)'>无匹配记录</p>";
}
async function deleteChat(id){
  if(!confirm("确认删除该条聊天？")) return;
  const r=await fetch(`/v1/admin/interactions/${id}`, {method:"DELETE", headers: authHeaders()});
  const j=await r.json();
  if(j.success) { alert("已删除"); loadChats(); } else alert("删除失败 "+(j.error||""));
}
async function annotateChat(id){
  const tag=prompt("标签（如 重要/待跟进）");
  if(tag===null) return;
  const note=prompt("备注");
  if(note===null) return;
  const r=await fetch(`/v1/admin/interactions/${id}/annotate`, {method:"POST", headers: authHeaders({"Content-Type":"application/json"}), body: JSON.stringify({user_id:selectedUser.username, tag, note})});
  const j=await r.json();
  if(j.feedback_id || j.success) alert("已标注"); else alert("标注失败 "+(j.error||""));
}
function escapeHtml(s){ return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;"); }
(function init(){
  token=localStorage.getItem("token")||"";
  if(!token){ location.href="/redesign"; return; }
  checkAdmin();
  loadUsers();
})();
