/* Navigation for long public reference pages; no storage, network or tracking. */
(() => {
  const policy=document.querySelector('main.policy');
  if(policy){
    const headings=[...policy.querySelectorAll('h2')];
    if(headings.length>3){
      const contents=document.createElement('nav');contents.className='page-contents';contents.setAttribute('aria-label','On this page');
      const title=document.createElement('strong');title.textContent='On this page';title.setAttribute('data-i18n','');contents.append(title);
      const list=document.createElement('ol');
      headings.forEach((heading,index)=>{if(!heading.id)heading.id='policy-section-'+(index+1);const item=document.createElement('li');const link=document.createElement('a');link.href='#'+heading.id;link.textContent=heading.textContent;item.append(link);list.append(item);});
      contents.append(list);const first=policy.querySelector('h2');first.before(contents);
    }
  }
  for(const menu of document.querySelectorAll('.public-mobile-menu')){
    menu.addEventListener('keydown',event=>{if(event.key==='Escape'){menu.open=false;menu.querySelector('summary').focus();}});
    menu.querySelectorAll('a').forEach(link=>link.addEventListener('click',()=>menu.open=false));
    document.addEventListener('click',event=>{if(menu.open&&!menu.contains(event.target))menu.open=false;});
  }
})();
