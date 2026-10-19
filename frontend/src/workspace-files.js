// A virtual file picker: only server-listed workspace IDs can be attached.
export function createWorkspaceFiles({loadFiles}) {
  const host = document.createElement('div');
  host.className = 'attachment-control';
  host.innerHTML = `<button type="button" class="attach-plus" aria-label="添加文件" aria-haspopup="menu" aria-expanded="false" title="添加文件"><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M12 3v18M3 12h18"/></svg></button><div class="attach-menu" role="menu" hidden><button type="button" role="menuitem"><span aria-hidden="true">＋</span> Add files</button></div>`;
  document.querySelector('.composer-input').prepend(host);
  const chips = document.createElement('div');
  chips.className = 'attachment-chips';
  document.querySelector('.composer-input').before(chips);
  const dialog = document.createElement('dialog');
  dialog.className = 'workspace-picker';
  dialog.setAttribute('aria-labelledby', 'workspacePickerTitle');
  dialog.innerHTML = `<div class="finder-shell"><aside class="finder-sidebar"><div class="finder-lights" aria-hidden="true"><i></i><i></i><i></i></div><small>个人收藏</small><button type="button" class="finder-home active">▣ <span>Workspace</span></button><p>演示文件空间</p><small class="finder-note">仅可添加此空间中的文件</small></aside><section class="finder-main"><header class="finder-toolbar"><button type="button" class="finder-back" aria-label="返回上一级">‹</button><h2 id="workspacePickerTitle">Workspace</h2><input type="search" placeholder="搜索文件" aria-label="搜索 workspace 文件"></header><div class="finder-columns"></div><div class="finder-path">Workspace</div><footer class="finder-footer"><span role="status" class="finder-status"></span><button type="button" class="finder-cancel">取消</button><button type="button" class="finder-add" disabled>添加文件</button></footer></section></div>`;
  document.body.append(dialog);
  const plus = host.querySelector('.attach-plus'), menu = host.querySelector('.attach-menu');
  const columns = dialog.querySelector('.finder-columns'), search = dialog.querySelector('input');
  const status = dialog.querySelector('.finder-status'), add = dialog.querySelector('.finder-add');
  let files = [], attachments = [], picked = new Set(), path = [], focused = null, busy = false, enabled = false;
  const samePath = (a,b) => a.length === b.length && a.every((x,i)=>x===b[i]);
  const size = n => n < 1024 ? `${n} B` : `${(n/1024).toFixed(1)} KB`;
  function closeMenu() {menu.hidden=true; plus.setAttribute('aria-expanded','false');}
  function renderChips() {
    chips.replaceChildren();
    chips.hidden = !attachments.length;
    for (const file of attachments) {
      const chip = document.createElement('span'); chip.className='attachment-chip';
      const label=document.createElement('span'); label.textContent=`▤ ${file.name}`;
      const remove=document.createElement('button'); remove.type='button'; remove.textContent='×'; remove.disabled=busy;
      remove.setAttribute('aria-label',`移除 ${file.name}`);
      remove.onclick=()=>{attachments=attachments.filter(f=>f.id!==file.id);renderChips();};
      chip.append(label,remove);chips.append(chip);
    }
  }
  function render() {
    columns.replaceChildren();
    const query=search.value.trim().toLocaleLowerCase();
    const depth=query?0:path.length;
    for(let level=0;level<=depth;level++) {
      const prefix=path.slice(0,level), column=document.createElement('div');column.className='finder-column';
      const matching=query?files.filter(f=>`${f.name} ${f.folder.join('/')}`.toLocaleLowerCase().includes(query)):files.filter(f=>prefix.every((p,i)=>f.folder[i]===p));
      const folders=query?[]:[...new Set(matching.filter(f=>f.folder.length>level).map(f=>f.folder[level]))];
      for(const folder of folders) {
        const row=document.createElement('button');row.type='button';row.className='finder-row folder';
        row.classList.toggle('selected',path[level]===folder);
        const icon=document.createElement('span');icon.className='finder-folder-icon';icon.textContent='📁';
        const title=document.createElement('span');title.textContent=folder;
        const arrow=document.createElement('span');arrow.textContent='›';
        row.append(icon,title,arrow);row.onclick=()=>{path=[...prefix,folder];focused=null;render();};column.append(row);
      }
      for(const file of matching.filter(f=>query||samePath(f.folder,prefix))) {
        const row=document.createElement('label');row.className='finder-row file';row.classList.toggle('selected',picked.has(file.id));
        const check=document.createElement('input');check.type='checkbox';check.checked=picked.has(file.id);check.setAttribute('aria-label',file.name);
        const icon=document.createElement('span');icon.className=`finder-file-icon ${file.kind.toLowerCase()}`;icon.textContent=file.kind;
        const title=document.createElement('span');title.textContent=file.name;title.title=file.name;
        check.onchange=()=>{if(check.checked&&picked.size>=10){check.checked=false;status.textContent='每次最多选择 10 个文件';return;} if(check.checked)picked.add(file.id);else picked.delete(file.id);focused=file;render();const target=[...columns.querySelectorAll('input')].find(i=>i.getAttribute('aria-label')===file.name);target?.focus();};
        row.append(check,icon,title);column.append(row);
      }
      if(!column.children.length){const empty=document.createElement('p');empty.className='finder-empty';empty.textContent=query?'没有匹配的文件':'此文件夹为空';column.append(empty);}
      columns.append(column);
    }
    if(focused) {
      const preview=document.createElement('div');preview.className='finder-preview';
      const icon=document.createElement('div');icon.className='finder-preview-icon';icon.textContent=focused.kind;
      const title=document.createElement('strong');title.textContent=focused.name;
      const info=document.createElement('p');info.textContent=`${focused.kind} 文档 · ${size(focused.size)}`;
      const hint=document.createElement('p');hint.textContent=focused.kind==='PDF'?'添加后由工具提取文字':'添加后由工具读取正文';
      preview.append(icon,title,info,hint);columns.append(preview);
    }
    dialog.querySelector('.finder-path').textContent=['Workspace',...path,focused?.name].filter(Boolean).join('  ›  ');
    dialog.querySelector('.finder-back').disabled=!path.length;
    status.textContent=`${files.length} 个文件 · 已选择 ${picked.size} 个`;
    add.disabled=!picked.size;add.textContent=picked.size?`添加 ${picked.size} 个文件`:'添加文件';
  }
  async function open() {
    closeMenu();path=[];focused=null;picked=new Set(attachments.map(f=>f.id));search.value='';columns.replaceChildren();status.textContent='正在加载文件…';add.disabled=true;
    dialog.showModal();
    try { const result=await loadFiles();files=result.files; if(dialog.open)render(); }
    catch(error){status.textContent=`加载失败：${error.message}`;}
  }
  plus.onclick=()=>{menu.hidden=!menu.hidden;plus.setAttribute('aria-expanded',String(!menu.hidden));if(!menu.hidden)menu.querySelector('button').focus();};
  menu.querySelector('button').onclick=open;
  document.addEventListener('click',e=>{if(!host.contains(e.target))closeMenu();});
  host.addEventListener('keydown',e=>{if(e.key==='Escape'){closeMenu();plus.focus();}});
  dialog.querySelector('.finder-cancel').onclick=()=>dialog.close();
  dialog.addEventListener('close',()=>plus.focus());
  dialog.addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();dialog.close();}});
  dialog.querySelector('.finder-home').onclick=()=>{path=[];focused=null;search.value='';render();};
  dialog.querySelector('.finder-back').onclick=()=>{path.pop();focused=null;render();};
  search.oninput=()=>{focused=null;render();};
  add.onclick=()=>{attachments=files.filter(f=>picked.has(f.id));renderChips();dialog.close();};
  renderChips();
  return {
    get files(){return attachments.slice();},
    clear(){attachments=[];closeMenu();if(dialog.open)dialog.close();renderChips();},
    setBusy(value){busy=value;plus.disabled=busy||!enabled;if(busy)closeMenu();renderChips();},
    setEnabled(value){enabled=value;host.hidden=!value;chips.hidden=!value||!attachments.length;plus.disabled=busy||!enabled;},
  };
}
