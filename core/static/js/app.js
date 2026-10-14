/**
 * VIKMO DealerDesk — Frontend Application Logic
 * Integrates directly with DRF backend endpoints for automotive operations.
 */

const API_BASE = '/api';

// Application State
const state = {
  activeTab: 'dashboard',
  products: [],
  productsCount: 0,
  productsPage: 1,
  productsSearch: '',
  productsCategory: '',
  dealers: [],
  orders: [],
  ordersCount: 0,
  ordersPage: 1,
  ordersStatusFilter: '',
  selectedOrder: null,
  reorderSuggestions: [],
  forecastMap: {},
  assistantSessionId: 'session-' + Math.random().toString(36).substring(2, 9),
  selectedDealerId: 1,
  isSyncing: false,
  isAssistantTyping: false
};

// Utilities & Formatting
function formatMoney(amount) {
  if (amount === null || amount === undefined) return '₹0.00';
  const num = parseFloat(amount);
  return '₹' + num.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = `toast-msg ${type}`;
  toast.innerHTML = `<span>${message}</span>`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(10px)';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// Health Verification & Status Monitoring
let healthCheckTimer = null;
let isHealthChecking = false;

async function checkBackendHealth(userInitiated = false) {
  if (isHealthChecking) return;
  isHealthChecking = true;

  const sideDot = document.getElementById('sidebar-status-dot');
  const sideTitle = document.getElementById('sidebar-status-title');
  const sideDesc = document.getElementById('sidebar-status-desc');
  const topDot = document.getElementById('topbar-health-dot');
  const topText = document.getElementById('backend-health-text');

  if (userInitiated) {
    if (sideDesc) sideDesc.innerText = 'Checking services...';
    if (topText) topText.innerText = 'Verifying...';
    if (sideDot) sideDot.className = 'pulse-dot pulse-neutral';
    if (topDot) topDot.className = 'pulse-dot pulse-neutral';
  }

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 6000);

  try {
    const res = await fetch(`${API_BASE}/health/`, {
      signal: controller.signal,
      headers: { 'Accept': 'application/json' }
    });
    clearTimeout(timeoutId);

    if (res.ok) {
      const data = await res.json().catch(() => ({}));
      if (data.status === 'ok') {
        if (sideDot) sideDot.className = 'pulse-dot';
        if (sideTitle) sideTitle.innerText = 'System status';
        if (sideDesc) sideDesc.innerText = 'API & Database connected';
        if (topDot) topDot.className = 'pulse-dot';
        if (topText) topText.innerText = 'System operational';
        if (userInitiated) showToast('System status: Healthy (API & DB online)', 'success');
      } else {
        if (sideDot) sideDot.className = 'pulse-dot pulse-amber';
        if (sideTitle) sideTitle.innerText = 'Service degraded';
        if (sideDesc) sideDesc.innerText = data.error || 'Database unavailable';
        if (topDot) topDot.className = 'pulse-dot pulse-amber';
        if (topText) topText.innerText = 'Degraded';
        if (userInitiated) showToast('Service degraded: Database unavailable', 'warning');
      }
    } else if (res.status === 503) {
      if (sideDot) sideDot.className = 'pulse-dot pulse-amber';
      if (sideTitle) sideTitle.innerText = 'Database offline';
      if (sideDesc) sideDesc.innerText = 'PostgreSQL unreachable';
      if (topDot) topDot.className = 'pulse-dot pulse-amber';
      if (topText) topText.innerText = 'Database offline';
      if (userInitiated) showToast('Database unreachable (HTTP 503)', 'error');
    } else {
      if (sideDot) sideDot.className = 'pulse-dot pulse-amber';
      if (sideTitle) sideTitle.innerText = 'Service degraded';
      if (sideDesc) sideDesc.innerText = `HTTP ${res.status}`;
      if (topDot) topDot.className = 'pulse-dot pulse-amber';
      if (topText) topText.innerText = `HTTP ${res.status}`;
      if (userInitiated) showToast(`Unexpected status: HTTP ${res.status}`, 'warning');
    }
  } catch (err) {
    clearTimeout(timeoutId);
    const isTimeout = err.name === 'AbortError';
    if (sideDot) sideDot.className = 'pulse-dot pulse-red';
    if (sideTitle) sideTitle.innerText = 'System offline';
    if (sideDesc) sideDesc.innerText = isTimeout ? 'Connection timed out' : 'API server unreachable';
    if (topDot) topDot.className = 'pulse-dot pulse-red';
    if (topText) topText.innerText = isTimeout ? 'Timeout' : 'API offline';
    if (userInitiated) showToast(isTimeout ? 'Health check timed out' : 'Backend server unreachable', 'error');
  } finally {
    isHealthChecking = false;
  }
}

function refreshActiveWorkspace() {
  switchTab(state.activeTab);
  checkBackendHealth(true);
}

// Tab Switching & Routing
function switchTab(tabName) {
  state.activeTab = tabName;
  document.querySelectorAll('.nav-item').forEach(el => {
    el.classList.toggle('active', el.dataset.tab === tabName);
  });
  document.querySelectorAll('.tab-pane').forEach(el => {
    el.classList.toggle('active', el.id === `tab-${tabName}`);
  });
  
  const titles = {
    dashboard: 'Operational Overview',
    products: 'Products & Inventory',
    orders: 'Dealer Orders Management',
    sync: 'Supplier Feed Synchronisation',
    assistant: 'Dealer Operations Assistant',
    forecast: 'Demand Forecasting & Reorder Engine'
  };
  const titleEl = document.getElementById('topbar-page-title');
  if (titleEl) titleEl.innerText = titles[tabName] || 'Overview';

  // Load screen data
  if (tabName === 'dashboard') loadDashboard();
  if (tabName === 'products') loadProducts(state.productsPage);
  if (tabName === 'orders') loadOrders(state.ordersPage);
  if (tabName === 'forecast') loadForecast();
}

// SCREEN 1: OPERATIONAL OVERVIEW
async function loadDashboard() {
  try {
    // 1. Fetch products count
    const prodRes = await fetch(`${API_BASE}/products/?page_size=1`);
    if (prodRes.ok) {
      const data = await prodRes.json();
      document.getElementById('stat-total-products').innerText = data.count || 0;
    }

    // 2. Fetch dealers count
    const dealerRes = await fetch(`${API_BASE}/dealers/?page_size=100`);
    if (dealerRes.ok) {
      const data = await dealerRes.json();
      state.dealers = data.results || [];
      document.getElementById('stat-total-dealers').innerText = data.count || 0;
      populateDealerSelectors();
    }

    // 3. Fetch orders
    const orderRes = await fetch(`${API_BASE}/orders/?page_size=5`);
    if (orderRes.ok) {
      const data = await orderRes.json();
      document.getElementById('stat-total-orders').innerText = data.count || 0;
      renderRecentOrders(data.results || []);
    }

    // 4. Fetch reorder suggestions for alerts
    const reorderRes = await fetch(`${API_BASE}/reorder-suggestions/`);
    if (reorderRes.ok) {
      const data = await reorderRes.json();
      const needsReorder = (data.results || []).filter(r => r.reorder_qty > 0);
      document.getElementById('stat-reorder-alerts').innerText = needsReorder.length;
      renderReorderAlerts(needsReorder.slice(0, 5));
    }
  } catch (err) {
    console.error('Error loading dashboard stats:', err);
  }
}

function renderRecentOrders(orders) {
  const container = document.getElementById('dashboard-recent-orders');
  if (!container) return;
  if (!orders.length) {
    container.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--text-dim); padding: 24px;">No recent orders recorded.</td></tr>`;
    return;
  }
  container.innerHTML = orders.map(o => `
    <tr>
      <td><span class="sku-tag">${o.order_number}</span></td>
      <td>Dealer #${o.dealer_id}</td>
      <td><span class="status-pill ${o.status.toLowerCase()}">${o.status}</span></td>
      <td class="cell-right price-val">${formatMoney(o.grand_total)}</td>
      <td style="text-align: center;">
        <button class="btn btn-secondary btn-sm" onclick="inspectOrder('${o.order_number}')">View</button>
      </td>
    </tr>
  `).join('');
}

function renderReorderAlerts(alerts) {
  const container = document.getElementById('dashboard-reorder-alerts');
  if (!container) return;
  if (!alerts.length) {
    container.innerHTML = `<div style="color: #16a34a; font-size: 13px; padding: 12px; background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: var(--radius-xs);">All forecast SKUs currently have sufficient safety stock.</div>`;
    return;
  }
  container.innerHTML = alerts.map(a => `
    <div style="display: flex; justify-content: space-between; align-items: center; padding: 10px 0; border-bottom: 1px solid var(--border-default);">
      <div>
        <span class="sku-tag">${a.sku}</span>
        <div style="font-size: 11px; color: var(--text-dim); margin-top: 3px;">Stock: <strong>${a.current_stock}</strong> / Reorder Point: <strong>${a.reorder_point}</strong></div>
      </div>
      <div style="text-align: right;">
        <span style="font-size: 12px; font-weight: 700; color: #b45309;">+${a.reorder_qty} units</span>
        <div><button class="btn btn-secondary btn-sm" style="padding: 2px 8px; margin-top: 3px; font-size: 11px;" onclick="quickOrderFromSuggestion('${a.sku}', ${a.reorder_qty})">+ Draft</button></div>
      </div>
    </div>
  `).join('');
}

// SCREEN 2: PRODUCTS & INVENTORY
async function loadProducts(page = 1) {
  state.productsPage = page;
  const tbody = document.getElementById('products-table-body');
  if (tbody) tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; padding: 30px; color: var(--text-dim);">Loading catalogue records...</td></tr>`;

  let url = `${API_BASE}/products/?page=${page}&page_size=15`;
  if (state.productsSearch) url += `&search=${encodeURIComponent(state.productsSearch)}`;
  if (state.productsCategory) url += `&category=${encodeURIComponent(state.productsCategory)}`;

  try {
    const res = await fetch(url);
    const data = await res.json();
    state.products = data.results || [];
    state.productsCount = data.count || 0;
    renderProductsTable();
    renderProductsPagination(data);
  } catch (err) {
    if (tbody) tbody.innerHTML = `<tr><td colspan="7" style="color: #dc2626; text-align: center; padding: 20px;">Failed to load products: ${err.message}</td></tr>`;
  }
}

function renderProductsTable() {
  const tbody = document.getElementById('products-table-body');
  if (!tbody) return;
  if (!state.products.length) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-dim); padding: 30px;">No products match the search query.</td></tr>`;
    return;
  }
  tbody.innerHTML = state.products.map(p => {
    let stockClass = 'in-stock';
    if (p.stock === 0) stockClass = 'out-stock';
    else if (p.stock < 15) stockClass = 'low-stock';

    return `
      <tr>
        <td><span class="sku-tag">${p.sku}</span></td>
        <td>
          <div style="font-weight: 600; color: var(--text-main);">${escapeHtml(p.name)}</div>
          <div style="font-size: 11px; color: var(--text-dim);">${escapeHtml(p.vehicle_fitment || 'Universal Compatibility')}</div>
        </td>
        <td><span style="font-size: 12px; color: var(--text-muted);">${escapeHtml(p.category)}</span></td>
        <td><span style="font-size: 12px; color: #64748b;">${escapeHtml(p.brand)}</span></td>
        <td class="cell-right price-val">${formatMoney(p.price)}</td>
        <td><span class="stock-tag ${stockClass}">${p.stock} units</span></td>
        <td style="text-align: right;">
          <div style="display: inline-flex; gap: 6px;">
            <button class="btn btn-secondary btn-sm" onclick="openStockModal('${p.sku}', ${p.stock})">Set Stock</button>
            <button class="btn btn-secondary btn-sm" onclick="viewProductDetail('${p.sku}')">Spec</button>
          </div>
        </td>
      </tr>
    `;
  }).join('');
}

function renderProductsPagination(data) {
  const infoEl = document.getElementById('products-page-info');
  const prevBtn = document.getElementById('products-prev-btn');
  const nextBtn = document.getElementById('products-next-btn');
  if (!infoEl) return;

  const totalPages = Math.ceil((data.count || 0) / 15) || 1;
  infoEl.innerText = `Showing page ${state.productsPage} of ${totalPages} (${data.count} items)`;
  if (prevBtn) prevBtn.disabled = !data.previous;
  if (nextBtn) nextBtn.disabled = !data.next;
}

function openStockModal(sku, currentStock) {
  document.getElementById('stock-modal-sku').value = sku;
  document.getElementById('stock-modal-qty').value = currentStock;
  document.getElementById('stock-modal-reason').value = 'Warehouse inventory verification';
  document.getElementById('modal-stock').classList.add('active');
}

async function saveInventoryUpdate() {
  const sku = document.getElementById('stock-modal-sku').value;
  const quantity = parseInt(document.getElementById('stock-modal-qty').value, 10);
  const reason = document.getElementById('stock-modal-reason').value;

  if (isNaN(quantity) || quantity < 0) {
    showToast('Quantity must be a non-negative integer', 'error');
    return;
  }

  try {
    const res = await fetch(`${API_BASE}/inventory/${sku}/`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ quantity, reason })
    });
    const body = await res.json();
    if (res.ok) {
      showToast(`Stock updated for ${sku} to ${quantity} units`, 'success');
      closeModal('modal-stock');
      loadProducts(state.productsPage);
    } else {
      showToast(body.error?.message || 'Inventory update failed', 'error');
    }
  } catch (err) {
    showToast(`Network error: ${err.message}`, 'error');
  }
}

// SCREEN 3: ORDERS ENGINE
async function loadOrders(page = 1) {
  state.ordersPage = page;
  const tbody = document.getElementById('orders-table-body');
  if (tbody) tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; padding: 30px; color: var(--text-dim);">Loading order registers...</td></tr>`;

  let url = `${API_BASE}/orders/?page=${page}&page_size=15`;
  if (state.ordersStatusFilter) url += `&status=${encodeURIComponent(state.ordersStatusFilter)}`;

  try {
    const res = await fetch(url);
    const data = await res.json();
    state.orders = data.results || [];
    state.ordersCount = data.count || 0;
    renderOrdersTable();
    renderOrdersPagination(data);
  } catch (err) {
    if (tbody) tbody.innerHTML = `<tr><td colspan="7" style="color: #dc2626; text-align: center; padding: 20px;">Failed to load orders: ${err.message}</td></tr>`;
  }
}

function renderOrdersTable() {
  const tbody = document.getElementById('orders-table-body');
  if (!tbody) return;
  if (!state.orders.length) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-dim); padding: 30px;">No orders found.</td></tr>`;
    return;
  }
  tbody.innerHTML = state.orders.map(o => `
    <tr>
      <td><span class="sku-tag">${o.order_number}</span></td>
      <td>Dealer #${o.dealer_id}</td>
      <td><span class="status-pill ${o.status.toLowerCase()}">${o.status}</span></td>
      <td style="text-align: center;">${(o.items || []).length} lines</td>
      <td class="cell-right price-val">${formatMoney(o.grand_total)}</td>
      <td style="font-size: 12px; color: var(--text-dim);">${formatDateTime(o.created_at)}</td>
      <td style="text-align: right;">
        <button class="btn btn-secondary btn-sm" onclick="inspectOrder('${o.order_number}')">Manage</button>
      </td>
    </tr>
  `).join('');
}

function renderOrdersPagination(data) {
  const infoEl = document.getElementById('orders-page-info');
  const prevBtn = document.getElementById('orders-prev-btn');
  const nextBtn = document.getElementById('orders-next-btn');
  if (!infoEl) return;

  const totalPages = Math.ceil((data.count || 0) / 15) || 1;
  infoEl.innerText = `Showing page ${state.ordersPage} of ${totalPages} (${data.count} orders)`;
  if (prevBtn) prevBtn.disabled = !data.previous;
  if (nextBtn) nextBtn.disabled = !data.next;
}

async function inspectOrder(orderNumber) {
  try {
    const res = await fetch(`${API_BASE}/orders/${orderNumber}/`);
    const data = await res.json();
    if (!res.ok) {
      showToast(data.error?.message || 'Could not load order details', 'error');
      return;
    }
    state.selectedOrder = data;
    renderOrderDetailModal(data);
    document.getElementById('modal-order-detail').classList.add('active');
  } catch (err) {
    showToast(`Network error: ${err.message}`, 'error');
  }
}

function renderOrderDetailModal(order) {
  document.getElementById('order-detail-num').innerText = order.order_number;
  document.getElementById('order-detail-status').innerHTML = `<span class="status-pill ${order.status.toLowerCase()}">${order.status}</span>`;
  document.getElementById('order-detail-dealer').innerText = `Dealer ID: ${order.dealer_id}`;
  document.getElementById('order-detail-subtotal').innerText = formatMoney(order.subtotal);
  document.getElementById('order-detail-tax').innerText = formatMoney(order.tax_total);
  document.getElementById('order-detail-grand').innerText = formatMoney(order.grand_total);

  const linesTbody = document.getElementById('order-detail-lines');
  linesTbody.innerHTML = (order.items || []).map(it => `
    <tr>
      <td><span class="sku-tag">${it.sku}</span></td>
      <td>${escapeHtml(it.name)}</td>
      <td style="text-align: center;">${it.quantity}</td>
      <td class="cell-right price-val">${formatMoney(it.unit_price)}</td>
      <td class="cell-right price-val">${formatMoney(it.line_tax)}</td>
      <td class="cell-right price-val" style="font-weight: 700;">${formatMoney(it.line_total)}</td>
    </tr>
  `).join('');

  // Setup Actions based on status state machine
  const actionsDiv = document.getElementById('order-detail-actions');
  let buttons = '';
  if (order.status === 'DRAFT') {
    buttons = `
      <button class="btn btn-primary" onclick="executeOrderAction('${order.order_number}', 'confirm')">Confirm Order</button>
      <button class="btn btn-danger" onclick="executeOrderAction('${order.order_number}', 'cancel')">Cancel Order</button>
    `;
  } else if (order.status === 'CONFIRMED') {
    buttons = `
      <button class="btn btn-primary" onclick="executeOrderAction('${order.order_number}', 'dispatch')">Dispatch Order</button>
      <button class="btn btn-danger" onclick="executeOrderAction('${order.order_number}', 'cancel')">Cancel Order (Restore Stock)</button>
    `;
  } else if (order.status === 'DISPATCHED') {
    buttons = `
      <button class="btn btn-primary" onclick="executeOrderAction('${order.order_number}', 'deliver')">Mark Delivered</button>
    `;
  } else {
    buttons = `<span style="font-size: 12px; color: var(--text-dim); align-self: center;">Terminal status: ${order.status}</span>`;
  }
  actionsDiv.innerHTML = buttons;
}

async function executeOrderAction(orderNumber, action) {
  try {
    const res = await fetch(`${API_BASE}/orders/${orderNumber}/${action}/`, { method: 'POST' });
    const data = await res.json();
    if (res.ok) {
      showToast(`Order ${orderNumber} is now ${data.status}`, 'success');
      inspectOrder(orderNumber);
      loadOrders(state.ordersPage);
    } else {
      let msg = data.error?.message || `Action failed with status ${res.status}`;
      if (data.error?.code === 'INSUFFICIENT_STOCK' && data.error.details) {
        msg += ': ' + data.error.details.map(d => `${d.sku} (Need ${d.requested}, Stock ${d.available})`).join(', ');
      }
      showToast(msg, 'error');
    }
  } catch (err) {
    showToast(`Network error: ${err.message}`, 'error');
  }
}

// Order Creation Modal
let draftItems = [];
function openCreateOrderModal() {
  draftItems = [{ sku: '', quantity: 1 }];
  renderDraftItemsInputs();
  document.getElementById('modal-create-order').classList.add('active');
}

function renderDraftItemsInputs() {
  const container = document.getElementById('create-order-items-container');
  container.innerHTML = draftItems.map((it, idx) => `
    <div style="display: flex; gap: 8px; margin-bottom: 8px; align-items: center;">
      <div style="flex: 2;">
        <input type="text" class="form-control" placeholder="SKU (e.g. BRK-1044)" value="${it.sku}" onchange="draftItems[${idx}].sku = this.value.trim().toUpperCase()">
      </div>
      <div style="flex: 1;">
        <input type="number" class="form-control" min="1" value="${it.quantity}" onchange="draftItems[${idx}].quantity = parseInt(this.value, 10)">
      </div>
      <div>
        <button type="button" class="btn btn-secondary btn-sm" onclick="removeDraftItem(${idx})" ${draftItems.length === 1 ? 'disabled' : ''}>✕</button>
      </div>
    </div>
  `).join('');
}

function addDraftItemRow() {
  draftItems.push({ sku: '', quantity: 1 });
  renderDraftItemsInputs();
}

function removeDraftItem(idx) {
  if (draftItems.length > 1) {
    draftItems.splice(idx, 1);
    renderDraftItemsInputs();
  }
}

async function submitCreateOrder() {
  const dealerId = parseInt(document.getElementById('create-order-dealer-select').value, 10);
  const items = draftItems.filter(it => it.sku && it.quantity > 0);
  if (!items.length) {
    showToast('Please specify at least one valid item and quantity', 'error');
    return;
  }

  try {
    const res = await fetch(`${API_BASE}/orders/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dealer_id: dealerId, items })
    });
    const data = await res.json();
    if (res.ok) {
      showToast(`Draft Order ${data.order_number} created successfully!`, 'success');
      closeModal('modal-create-order');
      loadOrders(1);
      inspectOrder(data.order_number);
    } else {
      showToast(data.error?.message || 'Order creation failed', 'error');
    }
  } catch (err) {
    showToast(`Network error: ${err.message}`, 'error');
  }
}

// SCREEN 4: SUPPLIER SYNC
async function triggerSupplierSync() {
  if (state.isSyncing) return;
  state.isSyncing = true;
  const syncBtn = document.getElementById('sync-trigger-btn');
  const statusEl = document.getElementById('sync-status-msg');
  const progressBox = document.getElementById('sync-progress-box');
  
  if (syncBtn) {
    syncBtn.disabled = true;
    syncBtn.innerHTML = `Ingesting Feed...`;
  }
  if (statusEl) statusEl.innerHTML = `<span class="pulse-dot"></span> Ingesting supplier catalog with cursor pagination...`;
  if (progressBox) progressBox.style.display = 'block';

  try {
    const res = await fetch(`${API_BASE}/sync/supplier/`, { method: 'POST' });
    const data = await res.json();
    if (res.ok) {
      showToast('Supplier synchronization completed successfully!', 'success');
      renderSyncResults(data);
      loadDashboard();
    } else {
      showToast(data.error?.message || 'Supplier sync failed', 'error');
      if (statusEl) statusEl.innerText = `Sync failed: ${data.error?.message || res.statusText}`;
    }
  } catch (err) {
    showToast(`Sync request failed: ${err.message}`, 'error');
    if (statusEl) statusEl.innerText = `Network error: ${err.message}`;
  } finally {
    state.isSyncing = false;
    if (syncBtn) {
      syncBtn.disabled = false;
      syncBtn.innerText = `Trigger Catalogue Sync`;
    }
  }
}

function renderSyncResults(data) {
  document.getElementById('sync-result-created').innerText = data.created || 0;
  document.getElementById('sync-result-updated').innerText = data.updated || 0;
  document.getElementById('sync-result-unchanged').innerText = data.unchanged || 0;
  document.getElementById('sync-result-rejected-count').innerText = (data.rejected || []).length;
  document.getElementById('sync-result-pages').innerText = data.pages_fetched || 0;
  document.getElementById('sync-result-requests').innerText = data.requests_made || 0;

  const rejectedTbody = document.getElementById('sync-rejected-table-body');
  if (rejectedTbody) {
    if (!data.rejected || !data.rejected.length) {
      rejectedTbody.innerHTML = `<tr><td colspan="2" style="text-align: center; color: var(--text-dim); padding: 16px;">Zero rejected items. All supplier records ingested cleanly.</td></tr>`;
    } else {
      rejectedTbody.innerHTML = data.rejected.map(r => `
        <tr>
          <td><span class="sku-tag">${r.supplier_sku || 'N/A'}</span></td>
          <td style="color: #dc2626; font-size: 12px;">${escapeHtml(r.reason)}</td>
        </tr>
      `).join('');
    }
  }
  document.getElementById('sync-results-card').style.display = 'block';
}

// SCREEN 5: DEALER ASSISTANT (GenAI)
function useQuickPrompt(promptText) {
  const input = document.getElementById('assistant-chat-input');
  if (input) {
    input.value = promptText;
    sendAssistantMessage();
  }
}

async function sendAssistantMessage() {
  if (state.isAssistantTyping) return;
  const input = document.getElementById('assistant-chat-input');
  const message = input.value.trim();
  if (!message) return;

  let dealerId = null;
  const dealerSelect = document.getElementById('assistant-dealer-select');
  if (dealerSelect && dealerSelect.value) {
    dealerId = parseInt(dealerSelect.value, 10);
  }
  if (!dealerId && state.dealers.length) {
    dealerId = state.dealers[0].id;
  }
  input.value = '';
  appendChatMessage('user', message);

  // Show thinking indicator
  state.isAssistantTyping = true;
  const thinkingId = appendChatThinking();

  try {
    const payload = {
      session_id: state.assistantSessionId,
      message: message
    };
    if (dealerId) payload.dealer_id = dealerId;

    const res = await fetch(`${API_BASE}/assistant/chat/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    removeChatElement(thinkingId);
    state.isAssistantTyping = false;

    if (res.ok) {
      appendChatMessage('assistant', data.reply, data.tool_calls, data.cited_skus, data.actions);
    } else {
      appendChatMessage('assistant', `Error: ${data.error?.message || 'Failed to communicate with AI provider.'}`);
    }
  } catch (err) {
    removeChatElement(thinkingId);
    state.isAssistantTyping = false;
    appendChatMessage('assistant', `Network Error: ${err.message}`);
  }
}

function appendChatMessage(role, text, toolCalls = [], citedSkus = [], actions = []) {
  const container = document.getElementById('chat-history');
  if (!container) return;

  const msgDiv = document.createElement('div');
  msgDiv.className = `chat-message ${role}`;

  let toolsHtml = '';
  if (toolCalls && toolCalls.length) {
    toolsHtml = toolCalls.map(tc => `
      <div class="tool-badge">
        <span>Tool Executed: <strong>${tc.name}</strong></span>
      </div>
    `).join('');
  }

  let citedHtml = '';
  if (citedSkus && citedSkus.length) {
    citedHtml = `
      <div class="sku-pills">
        <span style="font-size: 11px; color: var(--text-dim); align-self: center;">Referenced:</span>
        ${citedSkus.map(s => `<button class="sku-btn" onclick="viewProductDetail('${s}')">${s}</button>`).join('')}
      </div>
    `;
  }

  let actionsHtml = '';
  if (actions && actions.length) {
    actionsHtml = actions.map(act => `
      <div class="action-alert">
        <span>Draft Order Created: <strong>${act.order_number}</strong></span>
        <button class="btn btn-secondary btn-sm" onclick="inspectOrder('${act.order_number}')">View Order</button>
      </div>
    `).join('');
  }

  // Format basic markdown bolding & newlines
  const formattedText = escapeHtml(text)
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
    .replace(/\n/g, '<br>');

  msgDiv.innerHTML = `
    <div class="chat-bubble">${formattedText}</div>
    ${toolsHtml}
    ${actionsHtml}
    ${citedHtml}
  `;

  container.appendChild(msgDiv);
  container.scrollTop = container.scrollHeight;
}

function appendChatThinking() {
  const container = document.getElementById('chat-history');
  const id = 'thinking-' + Date.now();
  const div = document.createElement('div');
  div.id = id;
  div.className = 'chat-message assistant';
  div.innerHTML = `
    <div class="chat-bubble" style="display: flex; align-items: center; gap: 8px;">
      <span class="pulse-dot"></span>
      <span style="font-size: 12px; color: var(--text-dim);">Researching catalogue records and live stock balances...</span>
    </div>
  `;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
  return id;
}

function removeChatElement(id) {
  const el = document.getElementById(id);
  if (el) el.remove();
}

function clearAssistantChat() {
  state.assistantSessionId = 'session-' + Math.random().toString(36).substring(2, 9);
  const container = document.getElementById('chat-history');
  if (container) {
    container.innerHTML = `
      <div class="chat-message assistant">
        <div class="chat-bubble">
          Welcome to the DealerDesk Operations Assistant. I can search vehicle parts and compatibility, check live inventory balances across SKUs, or generate draft dealer purchase orders directly into the database.
        </div>
      </div>
    `;
  }
  showToast('Chat session reset', 'info');
}

// SCREEN 6: DEMAND FORECASTING & REORDER ENGINE
async function loadForecast() {
  try {
    const res = await fetch(`${API_BASE}/reorder-suggestions/`);
    const data = await res.json();
    state.reorderSuggestions = data.results || [];
    renderReorderSuggestionsTable();
    populateForecastSkuDropdown();
    if (state.reorderSuggestions.length) {
      loadSkuForecastChart(state.reorderSuggestions[0].sku);
    }
  } catch (err) {
    console.error('Error loading reorder suggestions:', err);
  }
}

function renderReorderSuggestionsTable() {
  const tbody = document.getElementById('reorder-table-body');
  if (!tbody) return;
  tbody.innerHTML = state.reorderSuggestions.map(r => {
    const needOrder = r.reorder_qty > 0;
    return `
      <tr>
        <td><span class="sku-tag" style="cursor: pointer;" onclick="loadSkuForecastChart('${r.sku}')">${r.sku}</span></td>
        <td class="stock-tag ${r.current_stock > 0 ? 'in-stock' : 'out-stock'}">${r.current_stock}</td>
        <td>${r.lead_time_weeks} wks</td>
        <td>${r.lead_time_demand}</td>
        <td>${r.safety_stock}</td>
        <td>${r.reorder_point}</td>
        <td>
          <span style="font-weight: 700; color: ${needOrder ? '#b45309' : 'var(--text-dim)'};">
            ${r.reorder_qty}
          </span>
        </td>
        <td style="text-align: right;">
          <button class="btn ${needOrder ? 'btn-primary' : 'btn-secondary'} btn-sm" onclick="quickOrderFromSuggestion('${r.sku}', ${r.reorder_qty || 5})">
            Draft Order
          </button>
        </td>
      </tr>
    `;
  }).join('');
}

function populateForecastSkuDropdown() {
  const select = document.getElementById('forecast-sku-select');
  if (!select || select.children.length > 0) return;
  select.innerHTML = state.reorderSuggestions.map(r => `
    <option value="${r.sku}">${r.sku}</option>
  `).join('');
  select.addEventListener('change', (e) => loadSkuForecastChart(e.target.value));
}

async function loadSkuForecastChart(sku) {
  try {
    const res = await fetch(`${API_BASE}/forecast/${sku}/`);
    const data = await res.json();
    if (res.ok) {
      renderSvgForecastChart(sku, data.forecast || []);
    }
  } catch (err) {
    console.error('Failed to load forecast for chart:', err);
  }
}

function renderSvgForecastChart(sku, forecastPoints) {
  const container = document.getElementById('forecast-chart-box');
  const title = document.getElementById('forecast-chart-sku-title');
  if (title) title.innerText = `Demand Curve: ${sku}`;
  if (!container || !forecastPoints.length) return;

  const width = 560;
  const height = 210;
  const padding = 40;

  const maxVal = Math.max(...forecastPoints.map(p => p.forecast_units), 10) * 1.25;
  const points = forecastPoints.map((p, i) => {
    const x = padding + (i / (forecastPoints.length - 1)) * (width - 2 * padding);
    const y = height - padding - (p.forecast_units / maxVal) * (height - 2 * padding);
    return { x, y, ...p };
  });

  const pathD = points.reduce((acc, p, i) => i === 0 ? `M ${p.x} ${p.y}` : `${acc} L ${p.x} ${p.y}`, '');
  const areaD = `${pathD} L ${points[points.length - 1].x} ${height - padding} L ${points[0].x} ${height - padding} Z`;

  container.innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" style="width: 100%; height: 100%; overflow: visible;">
      <!-- Horizontal Grid Lines -->
      <line x1="${padding}" y1="${height - padding}" x2="${width - padding}" y2="${height - padding}" stroke="#cbd5e1" stroke-width="1"/>
      <line x1="${padding}" y1="${height / 2}" x2="${width - padding}" y2="${height / 2}" stroke="#f1f5f9" stroke-width="1" stroke-dasharray="3,3"/>
      <line x1="${padding}" y1="${padding}" x2="${width - padding}" y2="${padding}" stroke="#f1f5f9" stroke-width="1" stroke-dasharray="3,3"/>
      
      <!-- Faint Area Fill -->
      <path d="${areaD}" fill="#eff6ff" opacity="0.8"/>
      
      <!-- Solid Line -->
      <path d="${pathD}" fill="none" stroke="#2563eb" stroke-width="2" stroke-linecap="round"/>
      
      <!-- Data Points & Labels -->
      ${points.map(p => `
        <circle cx="${p.x}" cy="${p.y}" r="4" fill="#ffffff" stroke="#2563eb" stroke-width="2"/>
        <text x="${p.x}" y="${p.y - 8}" fill="#0f172a" font-size="11" font-weight="600" font-family="monospace" text-anchor="middle">${p.forecast_units}</text>
        <text x="${p.x}" y="${height - padding + 16}" fill="#64748b" font-size="10" font-family="monospace" text-anchor="middle">${p.week_start.substring(5)}</text>
      `).join('')}
    </svg>
  `;
}

async function quickOrderFromSuggestion(sku, qty) {
  if (!state.dealers.length) {
    try {
      const dRes = await fetch(`${API_BASE}/dealers/?page_size=20`);
      if (dRes.ok) {
        const dData = await dRes.json();
        state.dealers = dData.results || [];
      }
    } catch {}
  }
  const dealerId = state.dealers[0]?.id;
  if (!dealerId) {
    showToast('No dealer profile available for draft order creation.', 'error');
    return;
  }
  const quantity = Math.max(1, qty || 5);
  try {
    const res = await fetch(`${API_BASE}/orders/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        dealer_id: dealerId,
        items: [{ sku, quantity }]
      })
    });
    const data = await res.json();
    if (res.ok) {
      showToast(`Draft Order ${data.order_number} created for ${quantity} × ${sku}!`, 'success');
      switchTab('orders');
      inspectOrder(data.order_number);
    } else {
      showToast(data.error?.message || 'Failed to create reorder draft', 'error');
    }
  } catch (err) {
    showToast(`Network error: ${err.message}`, 'error');
  }
}

// Product Details Modal
async function viewProductDetail(sku) {
  try {
    const res = await fetch(`${API_BASE}/products/${sku}/`);
    const p = await res.json();
    if (!res.ok) {
      showToast(p.error?.message || 'Product not found', 'error');
      return;
    }
    document.getElementById('product-detail-sku').innerText = p.sku;
    document.getElementById('product-detail-name').innerText = p.name;
    document.getElementById('product-detail-cat').innerText = p.category;
    document.getElementById('product-detail-brand').innerText = p.brand;
    document.getElementById('product-detail-fit').innerText = p.vehicle_fitment || 'Universal Compatibility';
    document.getElementById('product-detail-price').innerText = formatMoney(p.price);
    document.getElementById('product-detail-stock').innerText = `${p.stock} units in warehouse`;
    document.getElementById('product-detail-desc').innerText = p.description || 'No detailed supplier catalogue description provided.';
    document.getElementById('modal-product-detail').classList.add('active');
  } catch (err) {
    showToast(`Network error: ${err.message}`, 'error');
  }
}

function populateDealerSelectors() {
  const options = state.dealers.map(d => `<option value="${d.id}">${escapeHtml(d.name)} (${d.dealer_code})</option>`).join('');
  const assistantSelect = document.getElementById('assistant-dealer-select');
  const createOrderSelect = document.getElementById('create-order-dealer-select');
  if (assistantSelect) {
    assistantSelect.innerHTML = options;
    if (state.dealers.length) assistantSelect.value = state.dealers[0].id;
  }
  if (createOrderSelect) {
    createOrderSelect.innerHTML = options;
    if (state.dealers.length) createOrderSelect.value = state.dealers[0].id;
  }
  if (state.dealers.length) {
    state.selectedDealerId = state.dealers[0].id;
  }
}

function closeModal(modalId) {
  const modal = document.getElementById(modalId);
  if (modal) modal.classList.remove('active');
}

function escapeHtml(str) {
  if (!str) return '';
  return str.toString()
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function formatDateTime(isoStr) {
  if (!isoStr) return 'N/A';
  try {
    const d = new Date(isoStr);
    return d.toLocaleDateString('en-IN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  } catch {
    return isoStr;
  }
}

// Global Function Exports for Inline Event Handlers
window.switchTab = switchTab;
window.refreshActiveWorkspace = refreshActiveWorkspace;
window.useQuickPrompt = useQuickPrompt;
window.loadProducts = loadProducts;
window.loadOrders = loadOrders;
window.openStockModal = openStockModal;
window.saveInventoryUpdate = saveInventoryUpdate;
window.viewProductDetail = viewProductDetail;
window.inspectOrder = inspectOrder;
window.executeOrderAction = executeOrderAction;
window.openCreateOrderModal = openCreateOrderModal;
window.submitCreateOrder = submitCreateOrder;
window.addDraftItemRow = addDraftItemRow;
window.removeDraftItem = removeDraftItem;
window.triggerSupplierSync = triggerSupplierSync;
window.sendAssistantMessage = sendAssistantMessage;
window.clearAssistantChat = clearAssistantChat;
window.quickOrderFromSuggestion = quickOrderFromSuggestion;
window.closeModal = closeModal;
window.loadSkuForecastChart = loadSkuForecastChart;
window.checkBackendHealth = checkBackendHealth;

// Initial Setup
window.addEventListener('DOMContentLoaded', () => {
  // Check backend health and initiate periodic polling
  checkBackendHealth(false);
  if (healthCheckTimer) clearInterval(healthCheckTimer);
  healthCheckTimer = setInterval(() => checkBackendHealth(false), 30000);

  window.addEventListener('beforeunload', () => {
    if (healthCheckTimer) {
      clearInterval(healthCheckTimer);
      healthCheckTimer = null;
    }
  });

  // Navigation event listeners
  document.querySelectorAll('.nav-item').forEach(el => {
    el.addEventListener('click', (e) => {
      const tab = el.dataset.tab;
      if (tab) {
        e.preventDefault();
        switchTab(tab);
      }
    });
  });

  // Search input listeners
  const searchInput = document.getElementById('products-search-input');
  if (searchInput) {
    let debounceTimer;
    searchInput.addEventListener('input', (e) => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        state.productsSearch = e.target.value.trim();
        loadProducts(1);
      }, 300);
    });
  }

  // Category filter
  const categorySelect = document.getElementById('products-category-select');
  if (categorySelect) {
    categorySelect.addEventListener('change', (e) => {
      state.productsCategory = e.target.value;
      loadProducts(1);
    });
  }

  // Orders status filter
  const orderStatusSelect = document.getElementById('orders-status-select');
  if (orderStatusSelect) {
    orderStatusSelect.addEventListener('change', (e) => {
      state.ordersStatusFilter = e.target.value;
      loadOrders(1);
    });
  }

  // Assistant Enter key
  const assistantInput = document.getElementById('assistant-chat-input');
  if (assistantInput) {
    assistantInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') sendAssistantMessage();
    });
  }

  // Modal Backdrop Close
  document.querySelectorAll('.modal-overlay').forEach(overlay => {
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) overlay.classList.remove('active');
    });
  });

  // Load Initial Dashboard
  switchTab('dashboard');
});
