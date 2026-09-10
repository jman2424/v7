(() => {
  const $ = id => document.getElementById(id);
  const tenant = document.body.dataset.tenant;
  const csrf = document.querySelector('meta[name="csrf-token"]').content;
  let page = 1, value = null, loadedResource = "", dirty = false;
  let productSearch = "", productCategory = "", productPage = 1;
  async function json(url, options = {}) {
    const response = await fetch(url, {credentials: "same-origin", ...options});
    if (!response.ok) throw new Error(response.status === 401 ? "Your session expired. Please sign in again." : response.status === 403 ? "Access denied. Reload and check your account permissions." : "Request failed (" + response.status + "). Check the data and try again.");
    return response.json();
  }
  async function overview() {
    if (!$("platform-panel")) return;
    $("platform-status").textContent = "Loading…";
    try {
      const data = await json("/admin/api/platform?minutes=" + $("period").value + "&page=" + page);
      $("companies").replaceChildren();
      $("company-count").textContent = data.company_count + " companies · page " + page;
      for (const company of data.companies) {
        const row = document.createElement("tr");
        for (const text of [company.name, company.mode, company.kpis?.total ?? "Unavailable", company.kpis?.errors ?? "Unavailable"]) {
          const cell = document.createElement("td"); cell.textContent = text; row.append(cell);
        }
        const cell = document.createElement("td");
        const status = document.createElement("p");
        status.textContent = company.status.replaceAll("_", " ");
        const detail = document.createElement("p"); detail.textContent = company.issues.join("; ");
        const link = document.createElement("a"); link.className = "btn"; link.textContent = "Open business";
        link.href = "/admin/?tenant=" + encodeURIComponent(company.tenant);
        cell.append(status, detail, link); row.append(cell); $("companies").append(row);
      }
      $("companies-prev").disabled = page === 1; $("companies-next").disabled = !data.has_next;
      $("platform-status").textContent = "Updated " + new Date(data.generated_at).toLocaleString();
    } catch (error) { $("platform-status").textContent = error.message; }
  }
  function markDirty() { dirty = true; $("resource-status").textContent = "Unsaved changes"; }
  function labelText(key) { return String(key).replaceAll("_", " ").replaceAll(".", " "); }
  function draw(parent, object, key, path) {
    const current = object[key];
    if (current !== null && typeof current === "object") {
      const group = document.createElement("fieldset"), legend = document.createElement("legend");
      legend.textContent = labelText(key); group.append(legend); parent.append(group);
      const children = key === "hours" && loadedResource === "branches.json"
        ? [...new Set([...Object.keys(current), "mon", "tue", "wed", "thu", "fri", "sat", "sun"])] : Object.keys(current);
      for (const child of children) draw(group, current, child, path.concat(key));
      if (Array.isArray(current)) {
        const add = document.createElement("button"); add.type = "button"; add.className = "btn"; add.textContent = "Add item";
        add.onclick = () => {
          let template = current[0];
          if (template === undefined) {
            template = key === "product_catalog" ? {name: "", items: []} : key === "categories" ? {id: "", name: "", items: []} : key === "items" ? (path.includes("product_catalog") ? {name: "", price_str: "", stock: "", subcategory: ""} : {sku: "", name: "", price: 0, in_stock: true}) : loadedResource === "faq.json" ? {q: "", a: ""} : "";
          }
          const blank = item => Array.isArray(item) ? [] : item && typeof item === "object" ? Object.fromEntries(Object.entries(item).map(([k,v]) => [k, blank(v)])) : typeof item === "number" ? 0 : typeof item === "boolean" ? false : "";
          const defaults = loadedResource === "branches.json" && key === "data"
            ? {id: "", name: "", address: "", postcode: "", lat: null, lon: null, phone: "", hours: {}}
            : loadedResource === "delivery.json" && key === "zones" ? {area: "", fee: 0, min_order: 0, eta_hours: ""}
            : loadedResource === "delivery.json" && key === "areas" ? {postcode_prefix: "", fee: 0, min_order: 0}
            : null;
          current.push(defaults ?? blank(template)); markDirty(); render();
        };
        group.append(add);
      }
      return;
    }
    const label = document.createElement("label"); label.append(document.createTextNode(labelText(key) + " "));
    const input = document.createElement(typeof current === "string" && (current.length > 100 || ["q","a","greeting"].includes(key)) ? "textarea" : "input");
    const coordinate = loadedResource === "branches.json" && ["lat", "lon"].includes(key);
    if (typeof current === "boolean") { input.type = "checkbox"; input.checked = current; }
    else { input.value = current ?? ""; if (typeof current === "number" || coordinate) { input.type = "number"; input.step = "any"; } }
    input.oninput = () => { object[key] = coordinate && input.value === "" ? null : typeof current === "boolean" ? input.checked : typeof current === "number" || coordinate ? Number(input.value) : input.value; markDirty(); };
    label.append(input); parent.append(label);
  }
  function render() {
    $("business-editor").replaceChildren();
    if (loadedResource === "catalog.json" && value && !Array.isArray(value)) renderProducts();
    else draw($("business-editor"), {data: value}, "data", []);
    $("resource-json").value = JSON.stringify(value, null, 2); $("save-resource").disabled = false;
  }
  function renderProducts() {
    const root = $("business-editor");
    const sheet = Array.isArray(value.product_catalog);
    const categories = sheet ? value.product_catalog : value.categories;
    if (!Array.isArray(categories)) { draw(root, {data:value}, "data", []); return; }
    const tools = document.createElement("div"); tools.className = "product-tools";
    const search = document.createElement("input"); search.type = "search"; search.placeholder = "Search products or SKU"; search.setAttribute("aria-label","Search products"); search.value = productSearch;
    const filter = document.createElement("select"); filter.setAttribute("aria-label","Product category");
    const all = document.createElement("option"); all.value = ""; all.textContent = "All categories"; filter.append(all);
    categories.forEach((cat, index) => { const option = document.createElement("option"); option.value = String(index); option.textContent = cat.name; filter.append(option); });
    filter.value = productCategory;
    const add = document.createElement("button"); add.type = "button"; add.className = "btn btn-quiet"; add.textContent = "Add product";
    const addCategory = document.createElement("button"); addCategory.type = "button"; addCategory.className = "btn btn-quiet"; addCategory.textContent = "Add category";
    tools.append(search,filter,add,addCategory); root.append(tools);
    const tableWrap = document.createElement("div"); tableWrap.className = "table-scroll";
    const table = document.createElement("table"), header = document.createElement("thead"), headerRow = document.createElement("tr");
    for (const name of ["Product","Category","Price","Stock","Action"]) { const th = document.createElement("th"); th.textContent = name; headerRow.append(th); }
    header.append(headerRow); const body = document.createElement("tbody"); table.append(header,body); tableWrap.append(table); root.append(tableWrap);
    const pager = document.createElement("div"); pager.className = "pagination";
    const prev = document.createElement("button"), next = document.createElement("button"), count = document.createElement("span");
    for (const button of [prev,next]) { button.type = "button"; button.className = "btn btn-quiet"; }
    prev.textContent = "Previous"; next.textContent = "Next"; pager.append(prev,count,next); root.append(pager);
    const detail = document.createElement("div"); root.append(detail);
    function editItem(item) {
      detail.replaceChildren(); detail.className = "item-editor";
      const title = document.createElement("h3"); title.textContent = item.name || "New product"; detail.append(title);
      draw(detail, {product:item}, "product", []);
      const close = document.createElement("button"); close.type = "button"; close.className = "btn btn-quiet"; close.textContent = "Back to product list";
      close.onclick = () => { detail.replaceChildren(); detail.className = ""; list(); };
      detail.append(close); detail.querySelector("input")?.focus();
    }
    function list() {
      const rows = categories.flatMap((category,index) => (category.items || []).map(item => ({category,index,item})))
        .filter(row => (!productCategory || String(row.index) === productCategory) && (row.item.name + " " + (row.item.sku || "")).toLowerCase().includes(productSearch.toLowerCase()));
      productPage = Math.max(1,Math.min(productPage,Math.ceil(rows.length / 15)));
      body.replaceChildren();
      for (const row of rows.slice((productPage-1)*15,productPage*15)) {
        const tr = document.createElement("tr");
        for (const text of [row.item.name,row.category.name,row.item.price_str ?? row.item.price ?? "Not set",row.item.stock ?? (row.item.in_stock === false ? "Out of stock":"Available")]) { const td=document.createElement("td"); td.textContent=text; tr.append(td); }
        const td=document.createElement("td"), edit=document.createElement("button"); edit.type="button"; edit.className="btn btn-quiet"; edit.textContent="Edit"; edit.onclick=()=>editItem(row.item); td.append(edit); tr.append(td); body.append(tr);
      }
      if (!rows.length) { const tr=document.createElement("tr"), td=document.createElement("td"); td.colSpan=5; td.textContent="No matching products."; tr.append(td); body.append(tr); }
      count.textContent=rows.length+" products · page "+productPage; prev.disabled=productPage===1; next.disabled=productPage*15>=rows.length;
    }
    search.oninput=()=>{productSearch=search.value;productPage=1;list();}; filter.onchange=()=>{productCategory=filter.value;productPage=1;list();};
    prev.onclick=()=>{productPage--;list();}; next.onclick=()=>{productPage++;list();};
    add.onclick=()=> {
      if (!categories.length) { $("resource-status").textContent="Add a category first."; return; }
      if (!productCategory && categories.length > 1) { $("resource-status").textContent="Choose a category before adding a product."; filter.focus(); return; }
      const category=categories[Number(productCategory || 0)];
      const item=sheet ? {name:"",price_str:"",stock:"",subcategory:""} : {sku:"",name:"",price:0,in_stock:true};
      category.items ||= []; category.items.push(item); markDirty(); list(); editItem(item);
    };
    addCategory.onclick=()=> {
      const name=window.prompt("Category name"); if (!name?.trim()) return;
      if (categories.some(category => category.name.toLowerCase()===name.trim().toLowerCase())) { $("resource-status").textContent="That category already exists."; return; }
      categories.push(sheet ? {name:name.trim(),items:[]} : {id:name.toLowerCase().replace(/[^a-z0-9]+/g,"_"),name:name.trim(),items:[]}); markDirty(); render();
    };
    list();
  }
  if (!$("resource")) {
    if ($("companies-prev")) $("companies-prev").onclick = () => { page--; overview(); };
    if ($("companies-next")) $("companies-next").onclick = () => { page++; overview(); };
    $("refresh").addEventListener("click", overview); $("period").addEventListener("change", overview);
    overview(); return;
  }
  $("load-resource").onclick = async () => {
    if (dirty && !window.confirm("Discard your unsaved changes and reload?")) return;
    $("resource-status").textContent = "Loading…"; $("save-resource").disabled = true;
    try {
      const selected = $("resource").value;
      value = await json("/files/raw/" + selected + "?tenant=" + encodeURIComponent(tenant));
      loadedResource = selected; dirty = false; render(); $("resource-status").textContent = "Loaded " + selected;
    } catch (error) { $("resource-status").textContent = error.message; }
  };
  $("business-form").onsubmit = async event => {
    event.preventDefault(); if (!loadedResource) return;
    $("save-resource").disabled = true; $("resource-status").textContent = "Saving…";
    try {
      await json("/files/raw/" + loadedResource + "?tenant=" + encodeURIComponent(tenant), {method: "PUT",
        headers: {"Content-Type": "application/json", "X-CSRF-Token": csrf}, body: JSON.stringify(value)});
      dirty = false; render(); $("resource-status").textContent = "Saved. Your agent will use the updated information. A recovery snapshot was kept.";
      overview();
    } catch (error) { $("resource-status").textContent = error.message; }
    finally { $("save-resource").disabled = false; }
  };
  $("use-json").onclick = () => {
    if (!loadedResource) { $("resource-status").textContent = "Load a resource first."; return; }
    try {
      const parsed = JSON.parse($("resource-json").value);
      if (!parsed || typeof parsed !== "object") throw new Error();
      value = parsed; markDirty(); render();
    } catch { $("resource-status").textContent = "Enter a valid JSON object or list."; }
  };
  if ($("companies-prev")) $("companies-prev").onclick = () => { page--; overview(); };
  if ($("companies-next")) $("companies-next").onclick = () => { page++; overview(); };
  $("refresh")?.addEventListener("click", overview); $("period")?.addEventListener("change", overview);
  window.addEventListener("beforeunload", event => { if (dirty) { event.preventDefault(); event.returnValue = ""; } });
  overview();
  $("resource").addEventListener("change", () => $("load-resource").click());
  $("load-resource").click();
})();
