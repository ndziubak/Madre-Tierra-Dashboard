// Relevamiento de Airbnb y Booking para Uspallata.
//
// Uso:
//   node scripts/relevar_mercado.js                 # búsquedas de las próximas semanas
//   node scripts/relevar_mercado.js --semanas 4     # menos semanas
//   node scripts/relevar_mercado.js --profundo      # además busca la posición propia hasta la pág. 15
//   node scripts/relevar_mercado.js --anuncios      # guarda el texto de los anuncios propios y seguidos
//
// Guarda datos/mercado/AAAA-MM-DD.json con el texto de cada tarjeta de resultado.
// El análisis (precios, descuentos, insignias) lo hace scripts/analizar.py,
// así que si Airbnb o Booking cambian el diseño solo hay que revisar los selectores.
//
// Uso personal y de bajo volumen: pausas de varios segundos entre páginas.
// Necesita que el entorno permita www.airbnb.com.ar y www.booking.com.

const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const RAIZ = path.resolve(__dirname, '..');
const cfg = JSON.parse(fs.readFileSync(path.join(RAIZ, 'estrategia', 'config.json'), 'utf8'));
const B = cfg.busqueda;
const args = process.argv.slice(2);
const opt = (n, d) => { const i = args.indexOf(n); return i >= 0 ? args[i + 1] : d; };
const SEMANAS = Number(opt('--semanas', B.semanas_adelante));

const iso = (d) => d.toISOString().slice(0, 10);
const masDias = (d, n) => { const x = new Date(d); x.setUTCDate(x.getUTCDate() + n); return x; };
const pausa = () => new Promise((r) => setTimeout(r, 1000 * (B.pausa_segundos[0] + Math.random() * (B.pausa_segundos[1] - B.pausa_segundos[0]))));

// Muestras por semana: martes 1 noche (entre semana), sábado 1 noche, viernes→domingo 2 noches.
function fechasMuestra() {
  const hoy = new Date(); hoy.setUTCHours(0, 0, 0, 0);
  const out = [];
  for (let w = 0; w < SEMANAS; w++) {
    const base = masDias(hoy, 7 * w);
    for (const [dow, noches] of [[2, 1], [6, 1], [5, 2]]) {
      if (!B.estadias.includes(noches)) continue;
      const delta = (dow - base.getUTCDay() + 7) % 7;
      const ci = masDias(base, delta);
      if (ci <= hoy) continue;
      out.push({ checkin: iso(ci), checkout: iso(masDias(ci, noches)), noches });
    }
  }
  const vistos = new Set();
  return out.filter((f) => !vistos.has(f.checkin + f.noches) && vistos.add(f.checkin + f.noches));
}

function urlAirbnb(f, pagina) {
  const p = new URLSearchParams({ adults: B.adultos, checkin: f.checkin, checkout: f.checkout, currency: B.moneda, items_offset: 18 * pagina });
  return `${B.airbnb_dominio}/s/${B.airbnb_lugar}/homes?${p}`;
}
function urlBooking(f, pagina) {
  const p = new URLSearchParams({ ss: B.booking_destino, checkin: f.checkin, checkout: f.checkout, group_adults: B.adultos, no_rooms: 1, group_children: 0, selected_currency: B.moneda, lang: 'es', offset: 25 * pagina });
  return `https://www.booking.com/searchresults.es.html?${p}`;
}

async function tarjetasAirbnb(page) {
  await page.waitForSelector('[itemprop="itemListElement"], [data-testid="card-container"]', { timeout: 30000 });
  return page.$$eval('[itemprop="itemListElement"], [data-testid="card-container"]', (els) => {
    const vistos = new Set();
    return els.map((el) => {
      const a = el.querySelector('a[href*="/rooms/"]');
      const url = (el.querySelector('meta[itemprop="url"]') || {}).content || (a && a.href) || '';
      const id = (url.match(/rooms\/(\d+)/) || [])[1] || '';
      return { id, url, nombre: (el.querySelector('meta[itemprop="name"]') || {}).content || '', texto: el.innerText };
    }).filter((t) => t.id && !vistos.has(t.id) && vistos.add(t.id));
  });
}

async function tarjetasBooking(page) {
  await page.keyboard.press('Escape').catch(() => {});
  await page.waitForSelector('[data-testid="property-card"]', { timeout: 30000 });
  return page.$$eval('[data-testid="property-card"]', (els) => els.map((el) => {
    const a = el.querySelector('a[data-testid="title-link"]') || el.querySelector('a[href*="/hotel/"]');
    const url = a ? a.href.split('?')[0] : '';
    return { id: (url.match(/hotel\/\w+\/([^.]+)/) || [])[1] || '', url, nombre: (el.querySelector('[data-testid="title"]') || {}).innerText || '', texto: el.innerText };
  }));
}

function esPropio(plataforma, t) {
  const u = cfg.anuncios_propios[plataforma + '_url'] || '';
  const id = plataforma === 'airbnb' ? (u.match(/rooms\/(\d+)/) || [])[1] : (u.match(/hotel\/\w+\/([^.?]+)/) || [])[1];
  return Boolean(id && t.id === id);
}

async function buscar(page, plataforma, f, maxPaginas, pararSiPropio) {
  const resultados = [];
  for (let p = 0; p < maxPaginas; p++) {
    const url = plataforma === 'airbnb' ? urlAirbnb(f, p) : urlBooking(f, p);
    try {
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
      const ts = plataforma === 'airbnb' ? await tarjetasAirbnb(page) : await tarjetasBooking(page);
      if (!ts.length) break;
      ts.forEach((t, i) => resultados.push({ ...t, plataforma, ...f, pagina: p + 1, posicion: resultados.length + 1, posicion_en_pagina: i + 1, propio: esPropio(plataforma, t) }));
      if (pararSiPropio && resultados.some((r) => r.propio)) break;
    } catch (e) {
      resultados.push({ plataforma, ...f, pagina: p + 1, error: String(e).slice(0, 300), url });
      break;
    }
    await pausa();
  }
  return resultados;
}

async function textoAnuncio(page, url) {
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(6000);
  await page.keyboard.press('Escape').catch(() => {});
  return page.evaluate(() => document.body.innerText);
}

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ locale: 'es-AR', timezoneId: 'America/Argentina/Mendoza', viewport: { width: 1366, height: 900 } });
  const page = await ctx.newPage();
  // El link de Booking puede ser corto (booking.com/Pulse-...): se abre una vez para obtener /hotel/ar/...
  const bu = cfg.anuncios_propios.booking_url || '';
  if (bu.startsWith('http') && !bu.includes('/hotel/')) {
    try {
      await page.goto(bu, { waitUntil: 'domcontentloaded', timeout: 60000 });
      if (page.url().includes('/hotel/')) cfg.anuncios_propios.booking_url = page.url().split('?')[0];
      console.log('Booking propio: ' + cfg.anuncios_propios.booking_url);
    } catch (e) { console.log('No se pudo resolver el link corto de Booking: ' + e); }
    await pausa();
  }
  const salida = { fecha_relevamiento: iso(new Date()), config_busqueda: B, resultados: [], anuncios: [] };

  if (args.includes('--anuncios')) {
    const urls = [
      ['propio_airbnb', cfg.anuncios_propios.airbnb_url], ['propio_booking', cfg.anuncios_propios.booking_url],
      ...cfg.competidores_seguidos.flatMap((c) => [[c.nombre + ' (Airbnb)', c.airbnb_url], [c.nombre + ' (Booking)', c.booking_url]]),
    ].filter(([, u]) => u && u.startsWith('http'));
    for (const [nombre, url] of urls) {
      try { salida.anuncios.push({ nombre, url, texto: await textoAnuncio(page, url) }); } catch (e) { salida.anuncios.push({ nombre, url, error: String(e).slice(0, 300) }); }
      await pausa();
    }
  } else {
    const fechas = fechasMuestra();
    for (const f of fechas) {
      for (const plataforma of ['airbnb', 'booking']) {
        console.log(`${plataforma} ${f.checkin} (${f.noches} noche/s)`);
        salida.resultados.push(...await buscar(page, plataforma, f, B.paginas_por_busqueda, false));
      }
    }
    if (args.includes('--profundo')) {
      // Posición propia en las dos primeras fechas: sigue paginando hasta encontrar el anuncio.
      for (const f of fechas.slice(0, 2)) {
        for (const plataforma of ['airbnb', 'booking']) {
          const r = await buscar(page, plataforma, f, B.paginas_busqueda_profunda, true);
          const propio = r.find((x) => x.propio);
          salida.resultados.push({ plataforma, ...f, busqueda_profunda: true, paginas_revisadas: Math.max(0, ...r.map((x) => x.pagina || 0)), posicion_propia: propio ? propio.posicion : null, total_revisados: r.filter((x) => x.id).length });
        }
      }
    }
  }

  await browser.close();
  const dir = path.join(RAIZ, 'datos', 'mercado');
  fs.mkdirSync(dir, { recursive: true });
  const archivo = path.join(dir, `${salida.fecha_relevamiento}${args.includes('--anuncios') ? '-anuncios' : ''}.json`);
  fs.writeFileSync(archivo, JSON.stringify(salida, null, 1));
  const errores = salida.resultados.filter((r) => r.error).length;
  console.log(`Guardado ${path.relative(RAIZ, archivo)} · ${salida.resultados.length} registros · ${salida.anuncios.length} anuncios · ${errores} errores`);
})();
