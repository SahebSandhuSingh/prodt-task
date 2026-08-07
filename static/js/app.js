/* ─────────────────────────────────────────────
   AuraStays Frontend — app.js
   Vanilla JS client for the Travel Booking API.
   Uses only existing backend endpoints:
     POST /search/hotels
     POST /bookings
     GET  /bookings/{workflow_id}
     GET  /bookings/{booking_id}/history
     POST /bookings/{workflow_id}/cancel
     GET  /search-requests/{request_id}
   ───────────────────────────────────────────── */

// ── State ──────────────────────────────────────
let searchResults = [];
let selectedOffer = null;
let activeWorkflowId = null;
let pollTimer = null;

// Placeholder hotel images (Unsplash, royalty-free, no attribution required for hotlinking)
const PHOTOS = {
  'ATL-PAR-01':  'https://images.unsplash.com/photo-1582719478250-c89cae4dc85b?auto=format&fit=crop&w=800&q=80',
  'NOV-PAR-101': 'https://images.unsplash.com/photo-1566073771259-6a8506099945?auto=format&fit=crop&w=800&q=80',
  'ATL-LON-01':  'https://images.unsplash.com/photo-1513635269975-59663e0ac1ad?auto=format&fit=crop&w=800&q=80',
  'NOV-LON-202': 'https://images.unsplash.com/photo-1542314831-068cd1dbfeeb?auto=format&fit=crop&w=800&q=80',
  'NOV-LON-203': 'https://images.unsplash.com/photo-1560448204-e02f11c3d0e2?auto=format&fit=crop&w=800&q=80',
  'ATL-NYC-02':  'https://images.unsplash.com/photo-1571896349842-33c89424de2d?auto=format&fit=crop&w=800&q=80',
  'ATL-NYC-03':  'https://images.unsplash.com/photo-1568605117036-5fe5e7bab0b7?auto=format&fit=crop&w=800&q=80',
  'NOV-NYC-201': 'https://images.unsplash.com/photo-1517840901100-8179e982acb7?auto=format&fit=crop&w=800&q=80',
  'NOV-NYC-204': 'https://images.unsplash.com/photo-1522708323590-d24dbb6b0267?auto=format&fit=crop&w=800&q=80',
  'ATL-TYO-03':  'https://images.unsplash.com/photo-1540541338287-41700207dee6?auto=format&fit=crop&w=800&q=80',
  'ATL-TYO-04':  'https://images.unsplash.com/photo-1503899036084-c55cdd92da26?auto=format&fit=crop&w=800&q=80',
  'ATL-TYO-05':  'https://images.unsplash.com/photo-1493976040374-85c8e12f0c0e?auto=format&fit=crop&w=800&q=80',
  'NOV-TYO-201': 'https://images.unsplash.com/photo-1535827841776-24afc1e255ac?auto=format&fit=crop&w=800&q=80',
  'NOV-TYO-202': 'https://images.unsplash.com/photo-1578683010236-d716f9a3f461?auto=format&fit=crop&w=800&q=80',
  'ATL-SYD-01':  'https://images.unsplash.com/photo-1506973035872-a4ec16b8e8d9?auto=format&fit=crop&w=800&q=80',
  'NOV-SYD-303': 'https://images.unsplash.com/photo-1520250497591-112f2f40a3f4?auto=format&fit=crop&w=800&q=80',
  'ATL-ROM-01':  'https://images.unsplash.com/photo-1552832230-c0197dd311b5?auto=format&fit=crop&w=800&q=80',
  'ATL-ROM-02':  'https://images.unsplash.com/photo-1515542622106-78bda8ba0e5b?auto=format&fit=crop&w=800&q=80',
  'NOV-ROM-101': 'https://images.unsplash.com/photo-1529154036614-a60975f5c760?auto=format&fit=crop&w=800&q=80',
  'NOV-ROM-102': 'https://images.unsplash.com/photo-1531572753322-ad063cecc140?auto=format&fit=crop&w=800&q=80',
  '_default':    'https://images.unsplash.com/photo-1566073771259-6a8506099945?auto=format&fit=crop&w=800&q=80',
};

const SUPPLIER_NAMES = { atlas: 'Atlas Hotels', nova: 'Nova Stays' };
const TERMINAL_STATES = ['CONFIRMED', 'FAILED', 'CANCELLED', 'PRICE_CHANGED', 'REQUIRES_MANUAL_REVIEW'];


// ── Init ───────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  executeSearch('Paris', '2026-09-01', '2026-09-05', 2, 1);
});


// ── View Navigation ────────────────────────────
function showView(name) {
  ['view-search', 'view-trips', 'view-admin'].forEach(id => {
    document.getElementById(id).style.display = 'none';
  });
  document.getElementById('hero-section').style.display = name === 'search' ? '' : 'none';
  document.getElementById('search-bar-wrap').style.display = name === 'search' ? '' : 'none';

  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));

  if (name === 'search') {
    document.getElementById('view-search').style.display = '';
    document.getElementById('nav-search').classList.add('active');
  } else if (name === 'trips') {
    document.getElementById('view-trips').style.display = '';
    document.getElementById('nav-trips').classList.add('active');
    renderMyBookings();
  } else if (name === 'admin') {
    document.getElementById('view-admin').style.display = '';
    document.getElementById('nav-admin').classList.add('active');
  }
}


// ── Search ─────────────────────────────────────
function handleSearchSubmit(e) {
  e.preventDefault();
  const dest = document.getElementById('search-dest').value;
  const ci = document.getElementById('search-checkin').value;
  const co = document.getElementById('search-checkout').value;
  const guests = +document.getElementById('search-guests').value;
  const rooms = +document.getElementById('search-rooms').value;
  executeSearch(dest, ci, co, guests, rooms);
}

async function executeSearch(destination, check_in, check_out, guests, rooms) {
  const grid = document.getElementById('property-grid');
  const heading = document.getElementById('results-heading');
  const banner = document.getElementById('partial-failure-banner');
  banner.style.display = 'none';

  heading.textContent = 'Searching...';
  grid.innerHTML = '<div style="grid-column:1/-1" class="empty"><h3>Fetching live rates...</h3><p>Comparing prices across suppliers...</p></div>';

  try {
    const res = await fetch('/search/hotels', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ destination, check_in, check_out, guests, rooms }),
    });
    if (!res.ok) throw new Error(`Search failed (${res.status})`);

    const data = await res.json();
    searchResults = data.results || [];

    // Partial failure banner
    if (data.suppliers_failed && data.suppliers_failed.length > 0) {
      const working = data.suppliers_queried
        .filter(s => !data.suppliers_failed.includes(s))
        .map(s => SUPPLIER_NAMES[s] || s).join(' and ');
      const failed = data.suppliers_failed
        .map(s => SUPPLIER_NAMES[s] || s).join(', ');
      document.getElementById('partial-failure-msg').textContent =
        `Showing results from ${working} \u2014 ${failed} is temporarily unavailable.`;
      banner.style.display = 'flex';
    }

    heading.textContent = `${searchResults.length} ${searchResults.length === 1 ? 'property' : 'properties'} found in ${destination}`;
    renderCards(searchResults, check_in, check_out);
  } catch (err) {
    grid.innerHTML = `<div style="grid-column:1/-1" class="empty"><h3>Search Error</h3><p>${esc(err.message)}</p></div>`;
    heading.textContent = 'Search failed';
  }
}

function renderCards(results, checkIn, checkOut) {
  const grid = document.getElementById('property-grid');
  if (!results.length) {
    grid.innerHTML = '<div style="grid-column:1/-1" class="empty"><h3>No stays available</h3><p>Try a different destination or date range.</p></div>';
    return;
  }

  const nights = daysBetween(checkIn, checkOut);

  grid.innerHTML = results.map((r, i) => {
    const photo = PHOTOS[r.property_id] || PHOTOS._default;
    const supplier = SUPPLIER_NAMES[r.supplier_id] || r.supplier_id;
    const perNight = nights > 0 ? (r.total_price / nights).toFixed(0) : r.total_price.toFixed(0);
    const score = (4.9 - i * 0.15).toFixed(1);
    const reviews = 120 + i * 37;
    const isRefundable = r.cancellation_policy.toLowerCase().includes('free') || r.cancellation_policy.toLowerCase().includes('flexible');

    return `
      <div class="card">
        <div class="card-img" style="background-image:url('${photo}')">
          <div class="card-img-overlay">
            <span class="tag-supplier">via ${supplier}</span>
            <span class="tag-rating">${score} (${reviews})</span>
          </div>
        </div>
        <div class="card-content">
          <div>
            <div class="card-name">${esc(r.property_name)}</div>
            <div class="card-location">${esc(r.location)}</div>
            <span class="card-room">${esc(r.room_type)}</span>
            <div class="card-cancel ${isRefundable ? '' : 'non-refundable'}">${esc(r.cancellation_policy)}</div>
          </div>
          <hr class="card-divider">
          <div class="card-bottom">
            <div class="price-block">
              <div class="price-per-night">${r.currency} ${perNight} / night</div>
              <div class="price-total">${r.currency} ${r.total_price.toFixed(2)}</div>
              <div class="price-note">${nights} night${nights !== 1 ? 's' : ''} total, incl. taxes</div>
            </div>
            <button class="btn-book" onclick="openModal(${i}, '${checkIn}', '${checkOut}')">Book Now</button>
          </div>
        </div>
      </div>`;
  }).join('');
}


// ── Sorting ────────────────────────────────────
function handleSortChange() {
  const v = document.getElementById('sort-select').value;
  const ci = document.getElementById('search-checkin').value;
  const co = document.getElementById('search-checkout').value;
  if (v === 'price-asc') searchResults.sort((a, b) => a.total_price - b.total_price);
  else if (v === 'price-desc') searchResults.sort((a, b) => b.total_price - a.total_price);
  else searchResults.sort((a, b) => (b.rank_score || 0) - (a.rank_score || 0));
  renderCards(searchResults, ci, co);
}


// ── Modal / Checkout ───────────────────────────
function openModal(idx, checkIn, checkOut) {
  const r = searchResults[idx];
  if (!r) return;
  const nights = daysBetween(checkIn, checkOut);
  selectedOffer = { ...r, checkIn, checkOut, nights };

  document.getElementById('modal-property-name').textContent = r.property_name;
  document.getElementById('modal-sub').textContent = r.room_type + ' — ' + r.location;
  document.getElementById('modal-supplier').textContent = SUPPLIER_NAMES[r.supplier_id] || r.supplier_id;
  document.getElementById('modal-price').textContent = `${r.currency} ${r.total_price.toFixed(2)}`;

  const ciDate = new Date(checkIn + 'T00:00:00');
  const coDate = new Date(checkOut + 'T00:00:00');
  const fmt = d => d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  document.getElementById('modal-dates').textContent = `${fmt(ciDate)} – ${fmt(coDate)} (${nights} night${nights !== 1 ? 's' : ''})`;

  // Reset to form view
  document.getElementById('checkout-form').style.display = '';
  document.getElementById('polling-section').style.display = 'none';
  document.getElementById('checkout-modal').classList.add('open');
}

function closeCheckoutModal() {
  document.getElementById('checkout-modal').classList.remove('open');
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}


// ── Confirm Booking ────────────────────────────
async function handleConfirmBooking(e) {
  e.preventDefault();
  const firstName = document.getElementById('guest-first-name').value.trim();
  const lastName = document.getElementById('guest-last-name').value.trim();
  const guestName = `${firstName} ${lastName}`;
  const key = 'b-' + Math.random().toString(36).substring(2, 10);

  const o = selectedOffer;

  // Switch to polling view
  document.getElementById('checkout-form').style.display = 'none';
  document.getElementById('polling-section').style.display = '';
  resetStepper();

  try {
    const res = await fetch('/bookings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        offer_id: `OFFER-${o.supplier_id}-${o.property_id}`,
        supplier_id: o.supplier_id,
        property_id: o.property_id,
        check_in_date: o.checkIn,
        check_out_date: o.checkOut,
        quoted_price: o.total_price,
        currency: o.currency,
        guest_name: guestName,
        idempotency_key: key,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Booking failed');

    activeWorkflowId = data.workflow_id;
    document.getElementById('polling-wf-id').textContent = data.workflow_id;

    // Persist to localStorage
    saveBooking({
      workflow_id: data.workflow_id,
      booking_id: null,
      idempotency_key: key,
      property_name: o.property_name,
      room_type: o.room_type,
      location: o.location,
      total_price: o.total_price,
      currency: o.currency,
      guest_name: guestName,
      supplier_id: o.supplier_id,
      status: 'PROCESSING',
      created_at: new Date().toISOString(),
    });

    startPolling(data.workflow_id);
  } catch (err) {
    alert(err.message);
    closeCheckoutModal();
  }
}


// ── Polling ────────────────────────────────────
function startPolling(wfId) {
  if (pollTimer) clearInterval(pollTimer);
  poll(wfId);
  pollTimer = setInterval(() => poll(wfId), 1500);
}

async function poll(wfId) {
  try {
    const res = await fetch(`/bookings/${wfId}`);
    if (!res.ok) return;
    const b = await res.json();

    updateStepper(b);
    updateBadge(b.status);

    // Update localStorage
    saveBooking({
      workflow_id: wfId,
      booking_id: b.booking_id,
      supplier_reservation_id: b.supplier_reservation_id,
      status: b.status,
      current_step: b.current_step,
    });

    // Fetch history using booking_id (matches DB column BK-xxx)
    const historyId = b.booking_id || wfId;
    fetchHistory(historyId);

    if (TERMINAL_STATES.includes(b.status)) {
      clearInterval(pollTimer);
      pollTimer = null;
      document.getElementById('btn-cancel-booking').style.display = 'none';
      document.getElementById('btn-done').style.display = '';
    }
  } catch (e) {
    console.error('Poll error:', e);
  }
}

function resetStepper() {
  for (let i = 1; i <= 4; i++) {
    const el = document.getElementById(`step-${i}`);
    el.classList.remove('active', 'done');
  }
  document.getElementById('step-1').classList.add('active');
  document.getElementById('btn-cancel-booking').style.display = '';
  document.getElementById('btn-done').style.display = 'none';
}

function updateStepper(b) {
  let idx = 1;
  if (b.status === 'CONFIRMED') idx = 5;
  else if (b.current_step === 'POLLING_CONFIRMATION' || b.current_step === 'PERSISTING_RECORD') idx = 3;
  else if (b.current_step === 'RESERVING_SUPPLIER') idx = 2;

  for (let i = 1; i <= 4; i++) {
    const el = document.getElementById(`step-${i}`);
    el.classList.remove('active', 'done');
    if (i < idx) el.classList.add('done');
    else if (i === idx && idx <= 4) el.classList.add('active');
  }
}

function updateBadge(status) {
  const badge = document.getElementById('polling-badge');
  badge.textContent = status;
  badge.className = 'badge badge-' + status.toLowerCase().replace(/_/g, '-');
}

async function fetchHistory(wfId) {
  try {
    const res = await fetch(`/bookings/${wfId}/history`);
    if (!res.ok) return;
    const history = await res.json();
    if (!history || !history.length) return;

    document.getElementById('polling-timeline').innerHTML = history.map(h => `
      <div class="tl-item">
        <div class="tl-time">${new Date(h.changed_at).toLocaleTimeString()}</div>
        <div class="tl-status"><span class="badge badge-${h.new_status.toLowerCase().replace(/_/g, '-')}">${h.new_status}</span></div>
        <div class="tl-reason">${esc(h.reason)}</div>
      </div>
    `).join('');
  } catch (e) {
    console.error('History error:', e);
  }
}


// ── Cancel ─────────────────────────────────────
async function handleCancelBooking() {
  if (!activeWorkflowId) return;
  try {
    const res = await fetch(`/bookings/${activeWorkflowId}/cancel`, { method: 'POST' });
    const data = await res.json();
    // The polling loop will pick up the status change
  } catch (e) {
    alert('Cancel failed: ' + e.message);
  }
}


// ── LocalStorage ───────────────────────────────
function getBookings() {
  try { return JSON.parse(localStorage.getItem('aurastays_bookings') || '[]'); }
  catch { return []; }
}

function saveBooking(b) {
  const list = getBookings();
  const idx = list.findIndex(x => x.workflow_id === b.workflow_id);
  if (idx >= 0) list[idx] = { ...list[idx], ...b };
  else list.unshift(b);
  localStorage.setItem('aurastays_bookings', JSON.stringify(list));
}


// ── My Bookings View ───────────────────────────
async function renderMyBookings() {
  const container = document.getElementById('trip-result-container');
  const bookings = getBookings();

  if (!bookings.length) {
    container.innerHTML = '<div class="empty"><h3>No bookings yet</h3><p>Search for a hotel and make a reservation to see it here.</p></div>';
    return;
  }

  container.innerHTML = '<div style="opacity:.5;font-size:13px;">Loading booking details...</div>';

  let html = '';
  for (const b of bookings) {
    // Fetch latest status
    let status = b.status;
    let supplierRef = b.supplier_reservation_id || '';
    try {
      const res = await fetch(`/bookings/${b.workflow_id}`);
      if (res.ok) {
        const live = await res.json();
        status = live.status;
        supplierRef = live.supplier_reservation_id || supplierRef;
        saveBooking({ workflow_id: b.workflow_id, status, supplier_reservation_id: supplierRef, booking_id: live.booking_id });
      }
    } catch (e) { /* use cached */ }

    // Fetch history
    let historyHtml = '<div style="font-size:12px;color:var(--text-tertiary);">No status transitions recorded yet.</div>';
    try {
      const lookupId = b.booking_id || b.workflow_id;
      const hRes = await fetch(`/bookings/${lookupId}/history`);
      if (hRes.ok) {
        const history = await hRes.json();
        if (history && history.length) {
          historyHtml = history.map(h => `
            <div class="tl-item">
              <div class="tl-time">${new Date(h.changed_at).toLocaleTimeString()}</div>
              <div class="tl-status"><span class="badge badge-${h.new_status.toLowerCase().replace(/_/g, '-')}">${h.new_status}</span></div>
              <div class="tl-reason">${esc(h.reason)}</div>
            </div>
          `).join('');
        }
      }
    } catch (e) { /* use fallback */ }

    const badgeClass = 'badge-' + status.toLowerCase().replace(/_/g, '-');

    html += `
      <div class="booking-card">
        <div class="booking-header">
          <div>
            <h3>${esc(b.property_name || 'Hotel Reservation')}</h3>
            <div class="booking-meta">Ref: <strong class="font-mono">${esc(b.booking_id || b.workflow_id)}</strong></div>
            ${supplierRef ? `<div class="booking-meta">Supplier Ref: <strong class="font-mono" style="color:var(--teal);">${esc(supplierRef)}</strong></div>` : ''}
          </div>
          <div style="text-align:right;">
            <span class="badge ${badgeClass}">${status}</span>
            <div class="booking-price">${b.currency || 'EUR'} ${(b.total_price || 0).toFixed(2)}</div>
          </div>
        </div>
        <div class="booking-timeline-section">
          <h4>Status History</h4>
          <div class="timeline">${historyHtml}</div>
        </div>
      </div>`;
  }

  container.innerHTML = html;
}


// ── Manual Booking Lookup ──────────────────────
async function lookupTripDetails() {
  const q = document.getElementById('trip-search-input').value.trim();
  if (!q) { renderMyBookings(); return; }

  const container = document.getElementById('trip-result-container');
  container.innerHTML = '<div class="empty"><h3>Looking up...</h3></div>';

  try {
    const res = await fetch(`/bookings/${q}`);
    if (!res.ok) throw new Error('Booking not found');
    const b = await res.json();

    const hRes = await fetch(`/bookings/${q}/history`);
    const history = hRes.ok ? await hRes.json() : [];

    const badgeClass = 'badge-' + b.status.toLowerCase().replace(/_/g, '-');
    const historyHtml = history.length
      ? history.map(h => `
        <div class="tl-item">
          <div class="tl-time">${new Date(h.changed_at).toLocaleString()}</div>
          <div class="tl-status"><span class="badge badge-${h.new_status.toLowerCase().replace(/_/g, '-')}">${h.new_status}</span></div>
          <div class="tl-reason">${esc(h.reason)}</div>
        </div>`).join('')
      : '<div style="font-size:12px;color:var(--text-tertiary);">No history available.</div>';

    container.innerHTML = `
      <div class="booking-card">
        <div class="booking-header">
          <div>
            <h3>Booking ${esc(b.booking_id || q)}</h3>
            ${b.supplier_reservation_id ? `<div class="booking-meta">Supplier Ref: <strong class="font-mono" style="color:var(--teal);">${esc(b.supplier_reservation_id)}</strong></div>` : ''}
          </div>
          <span class="badge ${badgeClass}">${b.status}</span>
        </div>
        <div class="booking-timeline-section">
          <h4>Status History</h4>
          <div class="timeline">${historyHtml}</div>
        </div>
      </div>`;
  } catch (e) {
    container.innerHTML = `<div class="empty"><h3>Not Found</h3><p>${esc(e.message)}</p></div>`;
  }
}


// ── Audit ──────────────────────────────────────
async function lookupAuditRecord() {
  const id = document.getElementById('admin-audit-input').value.trim();
  if (!id) return;

  const out = document.getElementById('admin-audit-output');
  out.innerHTML = '<div style="font-size:13px;color:var(--text-tertiary);">Querying...</div>';

  try {
    const res = await fetch(`/search-requests/${id}`);
    if (!res.ok) throw new Error('Search request not found');
    const data = await res.json();
    out.innerHTML = `<pre>${esc(JSON.stringify(data, null, 2))}</pre>`;
  } catch (e) {
    out.innerHTML = `<div style="color:var(--red);font-weight:600;">${esc(e.message)}</div>`;
  }
}


// ── Helpers ────────────────────────────────────
function esc(s) {
  if (!s) return '';
  const d = document.createElement('div');
  d.textContent = String(s);
  return d.innerHTML;
}

function daysBetween(a, b) {
  const d1 = new Date(a + 'T00:00:00');
  const d2 = new Date(b + 'T00:00:00');
  return Math.max(1, Math.round((d2 - d1) / 86400000));
}
