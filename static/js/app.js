/* CRM АвтоБрокер — интерфейс */
(function () {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const CSRF = ($('meta[name=csrf]') || {}).content;
  window.CRM = { csrf: CSRF };
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  /* тема */
  const themeBtn = $('#themeBtn');
  if (themeBtn) themeBtn.addEventListener('click', () => {
    const t = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = t;
    try { localStorage.setItem('crm-theme', t); } catch (e) {}
  });

  /* тосты */
  $$('.toast').forEach((t, i) => setTimeout(() => { t.style.transition = '.3s'; t.style.opacity = 0; setTimeout(() => t.remove(), 300); }, 4200 + i * 400));

  /* строки-ссылки */
  document.addEventListener('click', e => {
    const tr = e.target.closest('[data-href]');
    if (!tr || e.target.closest('a, button, input, select, form, label')) return;
    if (e.ctrlKey || e.metaKey) window.open(tr.dataset.href); else location.href = tr.dataset.href;
  });

  /* подтверждение удаления */
  document.addEventListener('submit', e => {
    const msg = e.target.dataset.confirm;
    if (msg && !confirm(msg)) e.preventDefault();
  });

  /* форматирование денег */
  const fmt = v => { const d = String(v).replace(/[^\d]/g, ''); return d ? Number(d).toLocaleString('ru-RU').replace(/ /g, ' ') : ''; };
  $$('input.money').forEach(inp => {
    if (inp.value && inp.value !== '0') inp.value = fmt(inp.value); else if (inp.value === '0') inp.value = '';
    inp.addEventListener('input', () => {
      const pos = inp.value.length - inp.selectionStart;
      inp.value = fmt(inp.value);
      const p = Math.max(0, inp.value.length - pos); inp.setSelectionRange(p, p);
    });
  });
  window.CRM.parseMoney = v => Number(String(v || '').replace(/[^\d]/g, '')) || 0;
  window.CRM.fmt = fmt;

  /* глобальный поиск */
  const gq = $('#gq'), drop = $('#gsDrop');
  if (gq) {
    document.addEventListener('keydown', e => {
      if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K' || e.key === 'л' || e.key === 'Л')) { e.preventDefault(); gq.focus(); gq.select(); }
      if (e.key === 'Escape') { drop.classList.remove('open'); $('#bellDrop')?.classList.remove('open'); }
    });
    let timer, sel = -1;
    gq.addEventListener('input', () => {
      clearTimeout(timer);
      const v = gq.value.trim();
      if (v.length < 2) { drop.classList.remove('open'); return; }
      timer = setTimeout(async () => {
        const r = await fetch(gq.form.action + '?format=json&q=' + encodeURIComponent(v));
        const d = await r.json();
        let h = '';
        if (d.clients.length) h += '<h4>Клиенты</h4>' + d.clients.map(x => `<a href="${x.url}"><div><b>${esc(x.title)}</b><small>${esc(x.sub)}</small></div></a>`).join('');
        if (d.cars.length) h += '<h4>Автомобили</h4>' + d.cars.map(x => `<a href="${x.url}"><div><b>${esc(x.title)}</b><small>${esc(x.sub)}</small></div></a>`).join('');
        if (!h) h = '<p class="muted pad">Ничего не найдено. Enter — расширенный поиск</p>';
        drop.innerHTML = h; drop.classList.add('open'); sel = -1;
      }, 180);
    });
    gq.addEventListener('keydown', e => {
      const items = $$('a', drop);
      if (!items.length || !drop.classList.contains('open')) return;
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        sel = (sel + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
        items.forEach((a, i) => a.classList.toggle('sel', i === sel));
      } else if (e.key === 'Enter' && sel >= 0) { e.preventDefault(); location.href = items[sel].href; }
    });
    document.addEventListener('click', e => { if (!e.target.closest('.gsearch')) drop.classList.remove('open'); });
  }

  /* уведомления */
  const bellBtn = $('#bellBtn');
  if (bellBtn) {
    const icons = { task: '✓', phone: '☎', key: '🔑', chat: '💬' };
    const load = async () => {
      try {
        const items = await (await fetch(bellBtn.dataset.url)).json();
        const n = $('#bellN');
        n.hidden = !items.length; n.textContent = items.length;
        $('#bellList').innerHTML = items.length ? items.map(i =>
          `<a class="n ${i.warn ? 'warn' : ''}" href="${i.url}"><span style="width:22px;text-align:center">${icons[i.icon] || '•'}</span><div><b>${esc(i.title)}</b><small>${esc(i.sub)}</small></div></a>`).join('')
          : '<p class="muted pad">Всё сделано — новых уведомлений нет</p>';
      } catch (e) {}
    };
    load(); setInterval(load, 120000);
    bellBtn.addEventListener('click', e => { e.stopPropagation(); $('#bellDrop').classList.toggle('open'); });
    document.addEventListener('click', e => { if (!e.target.closest('.bell')) $('#bellDrop').classList.remove('open'); });
  }

  /* счётчик непрочитанных в чате */
  const navChat = $('#navChat');
  if (navChat) {
    const em = $('em', navChat);
    const upd = async () => { try { const d = await (await fetch(navChat.dataset.url)).json();
      em.textContent = d.total; em.hidden = !d.total; window.dispatchEvent(new CustomEvent('chat-unread', { detail: d })); } catch (e) {} };
    setInterval(upd, document.getElementById('chatApp') ? 5000 : 20000);
  }

  /* мини-календарь в сайдбаре */
  const mc = $('#miniCal');
  if (mc) {
    const months = ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь'];
    const now = new Date();
    let y = now.getFullYear(), m = now.getMonth();
    const pad = n => String(n).padStart(2, '0');
    const iso = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
    const todayIso = iso(now);
    async function render() {
      $('b', mc).textContent = months[m] + ' ' + y;
      let marks = {};
      try { marks = await (await fetch(`${mc.dataset.url}?y=${y}&m=${m + 1}`)).json(); } catch (e) {}
      const first = new Date(y, m, 1);
      const start = new Date(y, m, 1 - ((first.getDay() + 6) % 7));
      let h = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'].map(w => `<span class="wd">${w}</span>`).join('');
      for (let i = 0; i < 42; i++) {
        const d = new Date(start); d.setDate(start.getDate() + i);
        if (i >= 35 && d.getMonth() !== m) break;
        const k = iso(d);
        const cls = [d.getMonth() !== m ? 'out' : '', k === todayIso ? 'today' : '', (d.getDay() === 0 || d.getDay() === 6) ? 'we' : ''].join(' ');
        h += `<a class="${cls}" href="${mc.dataset.cal}?y=${d.getFullYear()}&m=${d.getMonth() + 1}&d=${k}" title="${marks[k] ? 'Есть события' : ''}">${d.getDate()}${marks[k] ? '<i></i>' : ''}</a>`;
      }
      $('.mc-grid', mc).innerHTML = h;
    }
    $$('[data-step]', mc).forEach(b => b.addEventListener('click', () => {
      m += Number(b.dataset.step);
      if (m < 0) { m = 11; y--; } if (m > 11) { m = 0; y++; }
      render();
    }));
    render();
  }

  /* канбан: перетаскивание сделок */
  const board = $('.kanban[data-api]');
  if (board) {
    let dragged = null;
    $$('.kcard', board).forEach(c => {
      c.addEventListener('dragstart', e => { dragged = c; c.classList.add('drag'); e.dataTransfer.effectAllowed = 'move'; });
      c.addEventListener('dragend', () => { c.classList.remove('drag'); $$('.kcol', board).forEach(x => x.classList.remove('over')); });
    });
    $$('.kcol', board).forEach(col => {
      col.addEventListener('dragover', e => { e.preventDefault(); col.classList.add('over'); });
      col.addEventListener('dragleave', e => { if (!col.contains(e.relatedTarget)) col.classList.remove('over'); });
      col.addEventListener('drop', async e => {
        e.preventDefault(); col.classList.remove('over');
        if (!dragged || dragged.closest('.kcol') === col) return;
        const from = dragged.closest('.kcol');
        $('.kcol-b', col).prepend(dragged);
        const upd = c => { const n = $$('.kcard', c).length; $('.kcol-h em', c).textContent = n;
          const s = $$('.kcard', c).reduce((a, k) => a + Number(k.dataset.budget || 0), 0); $('.kcol-h small', c).textContent = fmt(s) + ' ₽'; };
        upd(col); upd(from);
        const r = await fetch(board.dataset.api.replace('0', dragged.dataset.id), {
          method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF': CSRF },
          body: JSON.stringify({ stage: col.dataset.stage })
        });
        if (!r.ok) { alert('Не удалось изменить этап'); location.reload(); }
      });
    });
  }

  /* галочки задач без перезагрузки */
  $$('form.tick-form').forEach(f => f.addEventListener('submit', async e => {
    e.preventDefault();
    const r = await fetch(f.action, { method: 'POST', headers: { 'X-CSRF': CSRF } });
    if (r.ok) f.closest('.task').classList.toggle('done');
  }));
})();
