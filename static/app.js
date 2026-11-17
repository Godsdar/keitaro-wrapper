// Фронт без сборки: fetch к нашему FastAPI и немного DOM.
'use strict';

const $ = (sel, root = document) => root.querySelector(sel);

// ------------------------------------------------------------ общие помощники

async function api(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = res.headers.get('content-type')?.includes('json') ? await res.json() : null;
  if (!res.ok) {
    const detail = data?.detail;
    const text = Array.isArray(detail) ? detail.map((d) => d.msg).join('; ') : detail;
    throw new Error(text || `HTTP ${res.status}`);
  }
  return data;
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
}

let toastTimer;
function toast(message, kind = 'ok') {
  const el = $('#toast');
  el.textContent = message;
  el.className = `toast ${kind}`;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.hidden = true), kind === 'error' ? 8000 : 3500);
}

// Кнопка показывает «занято», пока идёт запрос, и не даёт нажать дважды.
async function busy(button, work) {
  const label = button.textContent;
  button.disabled = true;
  button.textContent = '…';
  try {
    return await work();
  } catch (err) {
    toast(err.message, 'error');
  } finally {
    button.disabled = false;
    button.textContent = label;
  }
}

// ------------------------------------------------------------ размер текста

(function textSize() {
  const root = document.documentElement;
  let size = 20;
  try { size = Number(localStorage.getItem('fontSize')) || 20; } catch {}
  const apply = () => {
    root.style.setProperty('--font', `${size}px`);
    try { localStorage.setItem('fontSize', String(size)); } catch {}
  };
  $('#font-down').onclick = () => { size = Math.max(16, size - 2); apply(); };
  $('#font-up').onclick = () => { size = Math.min(30, size + 2); apply(); };
  apply();
})();

// ------------------------------------------------------------ вкладки

function showTab(name) {
  document.querySelectorAll('.tab').forEach((t) => t.setAttribute('aria-selected', String(t.dataset.tab === name)));
  $('#tab-create').hidden = name !== 'create';
  $('#tab-editor').hidden = name !== 'editor';
  if (name === 'editor') {
    loadCampaignList();
    if (!location.hash.startsWith('#campaign/')) history.replaceState(null, '', '#editor');
  } else {
    history.replaceState(null, '', '#create');
  }
}
document.querySelectorAll('.tab').forEach((t) => (t.onclick = () => showTab(t.dataset.tab)));

// ------------------------------------------------------------ автокомплит офферов

function offerPicker(container, onPick) {
  container.replaceChildren($('#offer-picker-tpl').content.cloneNode(true));
  const input = $('.picker-input', container);
  const list = $('.picker-list', container);
  let items = [];
  let active = -1;
  let timer;
  let selected = null;

  const render = () => {
    list.hidden = false;
    if (!items.length) {
      list.innerHTML = '<li class="muted">Nothing found</li>';
      return;
    }
    list.innerHTML = items
      .map((o, i) => `<li role="option" data-i="${i}" aria-selected="${i === active}"><span class="offer-id">#${o.id}</span> ${escapeHtml(o.name)}</li>`)
      .join('');
  };

  const choose = (offer) => {
    selected = offer;
    input.value = `#${offer.id} ${offer.name}`;
    list.hidden = true;
    onPick?.(offer);
  };

  input.addEventListener('input', () => {
    selected = null;
    onPick?.(null);
    clearTimeout(timer);
    timer = setTimeout(async () => {
      try {
        items = await api('GET', `/api/offers?q=${encodeURIComponent(input.value.replace(/^#/, ''))}`);
        active = -1;
        render();
      } catch (err) {
        toast(err.message, 'error');
      }
    }, 200);
  });
  input.addEventListener('focus', () => input.dispatchEvent(new Event('input')));
  input.addEventListener('keydown', (e) => {
    if (list.hidden || !items.length) return;
    if (e.key === 'ArrowDown') { active = (active + 1) % items.length; render(); e.preventDefault(); }
    if (e.key === 'ArrowUp') { active = (active - 1 + items.length) % items.length; render(); e.preventDefault(); }
    if (e.key === 'Enter' && active >= 0) { choose(items[active]); e.preventDefault(); }
    if (e.key === 'Escape') list.hidden = true;
  });
  list.addEventListener('mousedown', (e) => {
    const li = e.target.closest('li[data-i]');
    if (li) choose(items[Number(li.dataset.i)]);
  });
  input.addEventListener('blur', () => setTimeout(() => (list.hidden = true), 150));

  return {
    get value() { return selected; },
    clear() { selected = null; input.value = ''; },
  };
}

// ------------------------------------------------------------ создаватор

let settings = null;
const createOffer = offerPicker($('#create-offer'));

async function loadSettings() {
  try {
    settings = await api('GET', '/api/settings');
  } catch (err) {
    toast(err.message, 'error');
    return;
  }
  $('#prefix').textContent = settings.prefix;
  const fill = (select, items, selectedId) => {
    select.innerHTML = items
      .map((i) => `<option value="${i.id}" ${i.id === selectedId ? 'selected' : ''}>${escapeHtml(i.name)}</option>`)
      .join('');
  };
  fill($('#domain'), settings.domains, settings.defaults.domain_id);
  fill($('#group'), settings.groups, settings.defaults.group_id);
  fill($('#source'), settings.sources, settings.defaults.traffic_source_id);
}

$('#geo').addEventListener('input', (e) => {
  const codes = e.target.value.toUpperCase().split(/[\s,;]+/).filter(Boolean);
  const bad = codes.filter((c) => !/^[A-Z]{2}$/.test(c));
  const hint = $('#geo-hint');
  hint.classList.toggle('error', bad.length > 0);
  hint.textContent = bad.length
    ? `Not a country code: ${bad.join(', ')}`
    : codes.length ? `Countries: ${[...new Set(codes)].join(', ')}` : 'Two-letter country codes, comma separated';
});

$('#create-form').addEventListener('submit', (e) => {
  e.preventDefault();
  const offer = createOffer.value;
  if (!offer) {
    toast('Pick an offer from the list', 'error');
    return;
  }
  busy($('#create-btn'), async () => {
    const campaign = await api('POST', '/api/campaigns', {
      name: $('#name').value,
      geo: $('#geo').value,
      offer_id: offer.id,
      domain_id: Number($('#domain').value),
      group_id: Number($('#group').value),
      traffic_source_id: Number($('#source').value),
    });
    renderCreated(campaign);
    toast(`Campaign ${campaign.name} created`);
    $('#create-form').reset();
    $('#geo').dispatchEvent(new Event('input'));
    createOffer.clear();
  });
});

function renderCreated(c) {
  const domain = settings?.domains.find((d) => d.id === Number($('#domain').value));
  const link = domain && c.alias ? `${domain.name.replace(/\/$/, '')}/${c.alias}` : null;
  const rows = c.streams
    .map((s) => `<li>${escapeHtml(s.name)} — ${s.offers.length ? s.offers.map((o) => `#${o.offer_id} ${o.share}%`).join(', ') : escapeHtml(s.schema)}</li>`)
    .join('');
  $('#create-result').innerHTML = `
    <div class="card result">
      <h2>Created: ${escapeHtml(c.name)}</h2>
      <dl>
        <dt>Keitaro ID</dt><dd>${c.keitaro_id}</dd>
        <dt>Geo</dt><dd>${escapeHtml(c.geo)}</dd>
        ${link ? `<dt>Campaign URL</dt><dd><a href="${escapeHtml(link)}" target="_blank" rel="noopener">${escapeHtml(link)}</a></dd>` : ''}
        ${settings?.keitaro_url ? `<dt>In Keitaro</dt><dd><a href="${escapeHtml(settings.keitaro_url)}/admin/#!/campaigns/${c.keitaro_id}" target="_blank" rel="noopener">open admin</a></dd>` : ''}
      </dl>
      <ul>${rows}</ul>
      <button class="primary" id="open-created">Open in editor</button>
    </div>`;
  $('#open-created').onclick = () => {
    showTab('editor');
    openCampaign(c.keitaro_id);
  };
}

// ------------------------------------------------------------ редактор

let current = null; // открытая кампания

async function loadCampaignList() {
  const list = $('#campaign-list');
  try {
    const items = await api('GET', `/api/campaigns?all=${$('#show-all').checked}`);
    list.innerHTML = items.length
      ? items
          .map((c) => `<li><button data-id="${c.keitaro_id}" aria-current="${current?.keitaro_id === c.keitaro_id}">
              <span class="offer-id">#${c.keitaro_id}</span> ${escapeHtml(c.name)}</button></li>`)
          .join('')
      : '<li class="empty">No campaigns yet</li>';
  } catch (err) {
    list.innerHTML = '';
    toast(err.message, 'error');
  }
}

$('#show-all').onchange = loadCampaignList;
$('#campaign-list').onclick = (e) => {
  const btn = e.target.closest('button[data-id]');
  if (btn) openCampaign(Number(btn.dataset.id));
};
$('#open-form').onsubmit = (e) => {
  e.preventDefault();
  const id = Number($('#open-id').value);
  if (id) openCampaign(id);
};

async function openCampaign(keitaroId) {
  try {
    current = await api('GET', `/api/campaigns/${keitaroId}`);
    history.replaceState(null, '', `#campaign/${keitaroId}`);
    renderCampaign();
    loadCampaignList();
  } catch (err) {
    toast(err.message, 'error');
  }
}

function renderCampaign() {
  const c = current;
  const box = $('#campaign');
  const fetched = c.fetched_at ? new Date(c.fetched_at).toLocaleString() : 'never';
  box.innerHTML = `
    <div class="campaign-head">
      <h1>${escapeHtml(c.name)}</h1>
      <span class="meta">Keitaro #${c.keitaro_id} · fetched ${escapeHtml(fetched)}</span>
      <button id="fetch-btn">Fetch streams from KT</button>
    </div>
    <div id="streams"></div>`;
  const streams = $('#streams', box);
  c.streams.forEach((s) => streams.append(renderStream(s)));
  $('#fetch-btn').onclick = (e) => fetchStreams(e.target);
}

async function fetchStreams(button) {
  if (current.streams.some((s) => s.dirty) && !confirm('Unpublished changes will be discarded. Fetch anyway?')) return;
  await busy(button, async () => {
    current = await api('POST', `/api/campaigns/${current.keitaro_id}/fetch`);
    renderCampaign();
    toast('Streams fetched from Keitaro');
  });
}

function replaceStream(updated) {
  current.streams = current.streams.map((s) => (s.id === updated.id ? updated : s));
  const old = document.querySelector(`[data-stream="${updated.id}"]`);
  old.replaceWith(renderStream(updated));
}

function renderStream(s) {
  const card = document.createElement('section');
  card.className = `card stream${s.dirty ? ' dirty' : ''}`;
  card.dataset.stream = s.id;

  const head = `
    <div class="stream-head">
      <h2>Stream: ${escapeHtml(s.name || '(no name)')} <span class="offer-id">[${s.keitaro_id}]</span></h2>
      <span class="meta">${escapeHtml(s.type || '')} · ${escapeHtml(s.schema || '')}</span>
      ${s.dirty ? '<span class="badge unpublished">not published</span>' : ''}
      ${s.dirty ? `<button class="push" data-act="push" ${s.problems.length ? 'disabled' : ''}>Push to KT</button>
                   <button data-act="cancel">Cancel</button>` : ''}
    </div>
    ${s.problems.length && s.dirty ? `<p class="problems">${s.problems.map(escapeHtml).join('<br>')}</p>` : ''}`;

  if (!s.can_hold_offers) {
    card.innerHTML = `${head}<p class="meta">Stream without offers — shown as is.</p>`;
    return card;
  }

  const total = s.offers.filter((o) => o.status === 'active').reduce((sum, o) => sum + o.share, 0);
  const rows = s.offers
    .map((o) => {
      const removed = o.status !== 'active';
      const was = o.dirty && o.pub_status === 'active' ? `<span class="was">was ${o.pub_share}%</span>` : o.dirty && !o.pub_status ? '<span class="was">new</span>' : '';
      return `
      <tr class="${removed ? 'removed' : ''} ${o.dirty ? 'changed' : ''}" data-row="${o.id}">
        <td><span class="offer-id">#${o.offer_id}</span> <span class="offer-name">${escapeHtml(o.offer_name)}</span>
          ${removed ? '<span class="badge removed">removed</span>' : ''}</td>
        <td class="num">
          <div class="share">
            ${removed
              ? '0%'
              : `<input type="number" min="0" max="100" step="1" value="${o.share}" aria-label="Share of offer ${o.offer_id}" data-act="share">%
                 <button class="pin ghost" data-act="pin" aria-pressed="${o.pinned}" title="${o.pinned ? 'Unpin share' : 'Pin share'}">📌</button>`}
            ${was}
          </div>
        </td>
        <td>${removed
          ? '<button data-act="bring-back">Bring back</button>'
          : '<button class="danger" data-act="remove">Remove</button>'}</td>
      </tr>`;
    })
    .join('');

  card.innerHTML = `${head}
    <table>
      <thead><tr><th>Offer</th><th>Share</th><th>Actions</th></tr></thead>
      <tbody>${rows || '<tr><td colspan="3" class="meta">No offers yet</td></tr>'}</tbody>
      <tfoot><tr><td></td><td class="total ${total === 100 || !s.offers.some((o) => o.status === 'active') ? '' : 'bad'}">Σ ${total}%</td><td></td></tr></tfoot>
    </table>
    <div class="add-row"><div class="offer-slot"></div><button data-act="add">Add</button></div>`;

  const picker = offerPicker($('.offer-slot', card));
  bindStream(card, s, picker);
  return card;
}

function bindStream(card, s, picker) {
  const base = `/api/streams/${s.id}`;
  const act = (button, method, url, body, message) =>
    busy(button, async () => {
      const updated = await api(method, url, body);
      replaceStream(updated);
      if (message) toast(message);
    });

  card.addEventListener('click', (e) => {
    const button = e.target.closest('button[data-act]');
    if (!button) return;
    const row = button.closest('[data-row]')?.dataset.row;
    switch (button.dataset.act) {
      case 'push': return act(button, 'POST', `${base}/push`, null, 'Pushed to Keitaro');
      case 'cancel': return act(button, 'POST', `${base}/cancel`, null, 'Changes cancelled');
      case 'remove': return act(button, 'POST', `${base}/offers/${row}/remove`);
      case 'bring-back': return act(button, 'POST', `${base}/offers/${row}/bring-back`);
      case 'pin': return act(button, 'PATCH', `${base}/offers/${row}`, { pinned: button.getAttribute('aria-pressed') !== 'true' });
      case 'add': {
        const offer = picker.value;
        if (!offer) return toast('Pick an offer from the list', 'error');
        return act(button, 'POST', `${base}/offers`, { offer_id: offer.id, offer_name: offer.name });
      }
    }
  });

  // Ручная доля: применяем по Enter или при уходе из поля.
  card.addEventListener('change', (e) => {
    if (e.target.dataset.act !== 'share') return;
    const row = e.target.closest('[data-row]').dataset.row;
    const share = Number(e.target.value);
    if (!Number.isInteger(share) || share < 0 || share > 100) {
      toast('Share must be a whole number from 0 to 100', 'error');
      replaceStream(s);
      return;
    }
    act(e.target, 'PATCH', `${base}/offers/${row}`, { share });
  });
}

// ------------------------------------------------------------ старт

loadSettings();

// Адрес хранит вкладку и открытую кампанию: #create, #editor, #campaign/123.
(function restoreFromHash() {
  const match = location.hash.match(/^#campaign\/(\d+)$/);
  if (match) {
    showTab('editor');
    openCampaign(Number(match[1]));
  } else if (location.hash === '#editor') {
    showTab('editor');
  }
})();
