"""Arma el informe de estrategia de precios y promociones.

Uso:  python3 scripts/analizar.py [--mercado datos/mercado/AAAA-MM-DD.json] [--dias 60]

Combina:
  * datos/reservas.csv (historial propio, sale de scripts/extraer_reservas.py)
  * el último relevamiento de datos/mercado/ (si existe)
  * estrategia/config.json (comisiones, descuentos, piso neto, fechas especiales)

Escribe informes/estrategia-AAAA-MM-DD.md. Si no hay relevamiento de mercado,
recomienda solo con el historial propio y lo dice en el informe.
"""
import argparse
import collections as C
import csv
import datetime as dt
import json
import re
import statistics as st
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DIAS = 'Lu Ma Mi Ju Vi Sa Do'.split()

INSIGNIAS = {
    # Airbnb
    'Favorito entre huéspedes': r'favorito entre hu[eé]spedes|guest favou?rite',
    'Superanfitrión': r'superanfitri[oó]n|superhost',
    'Nuevo': r'^\s*nuevo\s*$|\bnuevo\b(?! en booking)',
    'Precio rebajado (tachado)': r'antes|originalmente|was',
    'Descuento por estadía': r'descuento (semanal|mensual|por estad[ií]a)',
    'Oferta especial / precio bajo': r'oferta especial|precio (m[aá]s )?bajo|gran precio',
    'Cancelación gratuita': r'cancelaci[oó]n gratu?ita|free cancellation',
    # Booking
    'Genius': r'genius',
    'Oferta de último minuto': r'[uú]ltimo minuto',
    'Oferta por tiempo limitado': r'tiempo limitado',
    'Oferta de temporada': r'oferta de (inicio|fin) de a[nñ]o|oferta de verano|oferta de temporada|black friday|cyber',
    'Precio para móviles': r'm[oó]vil',
    'Sin pago por adelantado': r'sin pago por adelantado|no prepayment',
    'Desayuno incluido': r'desayuno incluido',
    'Nuevo en Booking': r'nuevo en booking',
    'Anuncio patrocinado': r'\bpatrocinado\b|\banuncio\b|\bpublicidad\b',
    'Partner preferido': r'partner preferido|preferred',
    'Quedan pocas unidades': r'solo queda|s[oó]lo queda|[uú]ltim[ao]s? disponible',
}


def num(s):
    s = s.replace(' ', ' ').strip()
    if re.search(r',\d{2}$', s):
        s = s.replace('.', '').replace(',', '.')
    else:
        s = s.replace('.', '').replace(',', '')
    try:
        return float(s)
    except ValueError:
        return None


def parsear_tarjeta(r):
    t = r.get('texto', '')
    tl = t.lower()
    montos = [num(m) for m in re.findall(r'(?:US\$|USD|\$)\s?([\d.,]+)', t)]
    montos = [m for m in montos if m and m >= 10]
    precio = original = None
    m = re.search(r'(?:US\$|USD|\$)\s?([\d.,]+)\s*(?:por noche|noche)', t, re.I)
    if m:
        precio = num(m.group(1))
    elif montos:
        precio = montos[-1] / max(1, r['noches'])  # total de la estadía
    if len(montos) >= 2 and montos[0] > montos[-1] * 1.02:
        original = montos[0] / max(1, r['noches'])
        if m is None:
            precio = montos[-1] / max(1, r['noches'])
    rating = resenas = None
    if r['plataforma'] == 'airbnb':
        mr = re.search(r'(\d[,.]\d{1,2})\s*\((\d+)\)', t)
        if mr:
            rating, resenas = num(mr.group(1)), int(mr.group(2))
    else:
        mr = re.search(r'(?:Puntuaci[oó]n|Scored)\s*(\d+[,.]?\d*)', t) or re.search(r'\b(\d[,.]\d|10)\b\s*\n', t)
        if mr:
            rating = num(mr.group(1))
        mc = re.search(r'([\d.]+)\s*(comentarios|opiniones|reviews)', t, re.I)
        if mc:
            resenas = int(mc.group(1).replace('.', ''))
    insignias = [k for k, rx in INSIGNIAS.items() if re.search(rx, tl, re.M)]
    if original and 'Precio rebajado (tachado)' not in insignias:
        insignias.append('Precio rebajado (tachado)')
    return {**r, 'precio_noche': round(precio, 2) if precio else None,
            'precio_original_noche': round(original, 2) if original else None,
            'rating': rating, 'resenas': resenas, 'insignias': insignias}


def cargar_reservas():
    p = RAIZ / 'datos' / 'reservas.csv'
    if not p.exists():
        return []
    filas = []
    for r in csv.DictReader(open(p, encoding='utf-8')):
        r['checkin'] = dt.date.fromisoformat(r['checkin'])
        r['noches'] = int(r['noches'])
        r['usd'] = float(r['usd']) if r['usd'] else None
        filas.append(r)
    return filas


def historial(reservas, hoy):
    noches_ocupadas = set()
    por_canal = C.defaultdict(lambda: [0, 0, 0.0])
    adr_dow = C.defaultdict(list)
    for r in reservas:
        c = por_canal[r['canal']]
        c[0] += 1
        c[1] += r['noches']
        c[2] += r['usd'] or 0
        for i in range(r['noches']):
            d = r['checkin'] + dt.timedelta(i)
            noches_ocupadas.add(d)
            if r['usd']:
                adr_dow[d.weekday()].append(r['usd'] / r['noches'])
    inicio = min(r['checkin'] for r in reservas)
    tot, occ = C.Counter(), C.Counter()
    d = inicio
    while d < hoy:
        tot[d.weekday()] += 1
        occ[d.weekday()] += d in noches_ocupadas
        d += dt.timedelta(1)
    ocup = {k: occ[k] / tot[k] for k in range(7) if tot[k]}
    return {
        'inicio': inicio, 'ocupacion_dow': ocup,
        'ocupacion_media': sum(occ.values()) / max(1, sum(tot.values())),
        'adr_dow': {k: st.mean(v) for k, v in adr_dow.items()},
        'por_canal': por_canal, 'ocupadas': noches_ocupadas,
        'duracion': C.Counter(r['noches'] for r in reservas),
    }


def fecha_especial(cfg, d):
    """Si hay varias que coinciden (p. ej. Carnaval dentro de temporada alta), gana la más corta."""
    coinciden = [f for f in cfg.get('fechas_especiales', [])
                 if dt.date.fromisoformat(f['desde']) <= d <= dt.date.fromisoformat(f['hasta'])]
    if not coinciden:
        return ''
    return min(coinciden, key=lambda f: dt.date.fromisoformat(f['hasta']) - dt.date.fromisoformat(f['desde']))['motivo']


def neto(cfg, plataforma, publicado):
    """Ingreso neto en el peor caso (todos los descuentos activos acumulados)."""
    d = cfg['descuentos_activos']
    if plataforma == 'booking':
        return publicado * (1 - d['booking_genius']) * (1 - d['booking_movil']) * (1 - cfg['comisiones']['booking'])
    return publicado * (1 - d['airbnb_huespedes_excelentes']) * (1 - cfg['comisiones']['airbnb'])


def piso_publicado(cfg, plataforma):
    return cfg['piso_neto_usd_por_noche'] / neto(cfg, plataforma, 1.0)


def informe(cfg, reservas, mercado, dias, hoy):
    L = []
    w = L.append
    w(f'# Estrategia de precios y promociones — {hoy.isoformat()}\n')
    if not mercado:
        w('> **Sin relevamiento de mercado.** Las recomendaciones salen solo del historial propio. '
          'Correr `node scripts/relevar_mercado.js` (con acceso a Airbnb y Booking) para compararlas con la competencia.\n')
    h = historial(reservas, hoy) if reservas else None

    # 1. Historial propio
    if h:
        w('## 1. Lo que dicen tus reservas\n')
        w('| Canal | Reservas | Noches | Tarifa media/noche (antes de comisión) | Neto aprox./noche |')
        w('|---|---|---|---|---|')
        com = {'Airbnb': cfg['comisiones']['airbnb'], 'Booking': cfg['comisiones']['booking']}
        for canal, (k, n, u) in sorted(h['por_canal'].items(), key=lambda x: -x[1][1]):
            adr = u / n if n else 0
            w(f'| {canal} | {k} | {n} | US$ {adr:.0f} | US$ {adr * (1 - com.get(canal, 0)):.0f} |')
        w('\n| Noche | Ocupación desde ' + h['inicio'].strftime('%d/%m') + ' | Tarifa media |')
        w('|---|---|---|')
        for k in range(7):
            w(f"| {DIAS[k]} | {h['ocupacion_dow'].get(k, 0):.0%} | US$ {h['adr_dow'].get(k, 0):.0f} |")
        tot = sum(h['duracion'].values())
        w(f"\nEstadías de 1 noche: {h['duracion'][1]} de {tot} ({h['duracion'][1] / tot:.0%}). "
          f"Ocupación media: {h['ocupacion_media']:.0%}.\n")

    # 2. Mercado
    tarjetas = [parsear_tarjeta(r) for r in (mercado or {}).get('resultados', []) if r.get('texto')]
    ref = {}
    if tarjetas:
        w('## 2. Lo que hace la competencia\n')
        for plat in ('airbnb', 'booking'):
            ts = [t for t in tarjetas if t['plataforma'] == plat]
            if not ts:
                continue
            top = [t for t in ts if t['posicion'] <= 20]
            w(f'### {plat.capitalize()} — primeros 20 resultados de cada búsqueda\n')
            cnt = C.Counter(i for t in top for i in t['insignias'])
            busquedas = len({(t['checkin'], t['noches']) for t in top}) or 1
            w('| Promoción o insignia | Presencia en el top 20 |')
            w('|---|---|')
            for k, v in cnt.most_common():
                w(f'| {k} | {v / len(top):.0%} de las tarjetas |')
            con_desc = [t for t in top if t['precio_original_noche']]
            if con_desc:
                desc = st.median(1 - t['precio_noche'] / t['precio_original_noche'] for t in con_desc)
                w(f'\nDescuento mediano visible (precio tachado): {desc:.0%}.')
            w('')
            w('| Fecha | Noches | Precio/noche p25 · mediana · p75 (top 20) | Mediana top 5 | Tu posición | Tu precio |')
            w('|---|---|---|---|---|---|')
            for (ci, n), grupo in sorted(C.defaultdict(list, {k: [t for t in ts if (t['checkin'], t['noches']) == k] for k in {(t['checkin'], t['noches']) for t in ts}}).items()):
                precios = sorted(t['precio_noche'] for t in grupo if t['posicion'] <= 20 and t['precio_noche'])
                top5 = [t['precio_noche'] for t in grupo if t['posicion'] <= 5 and t['precio_noche']]
                prop = next((t for t in grupo if t['propio']), None)
                if len(precios) >= 4:
                    q = st.quantiles(precios, n=4)
                    ref[(plat, ci, n)] = q[1]
                    rango = f'US$ {q[0]:.0f} · {q[1]:.0f} · {q[2]:.0f}'
                else:
                    rango = 'pocos datos'
                w(f"| {ci} | {n} | {rango} | {'US$ %.0f' % st.median(top5) if top5 else '—'} | "
                  f"{prop['posicion'] if prop else 'no aparece en las páginas revisadas'} | "
                  f"{'US$ %.0f' % prop['precio_noche'] if prop and prop['precio_noche'] else '—'} |")
            w('')
            lideres = C.Counter(t['nombre'] or t['id'] for t in top if t['posicion'] <= 5)
            if lideres:
                w('Los que más veces aparecen entre los 5 primeros: ' + '; '.join(
                    f'{k} ({v}/{busquedas})' for k, v in lideres.most_common(5)) + '.\n')
        prof = [r for r in mercado.get('resultados', []) if r.get('busqueda_profunda')]
        if prof:
            w('### Búsqueda profunda de tu anuncio\n')
            for r in prof:
                pos = r['posicion_propia']
                w(f"- {r['plataforma']} {r['checkin']} ({r['noches']} n.): "
                  + (f'posición {pos} de {r["total_revisados"]} revisados.' if pos else
                     f'no apareció en {r["paginas_revisadas"]} páginas ({r["total_revisados"]} anuncios).'))
            w('')

    # 3. Calendario recomendado
    w(f'## 3. Precios recomendados para los próximos {dias} días\n')
    pb, pa = piso_publicado(cfg, 'booking'), piso_publicado(cfg, 'airbnb')
    w(f"Piso neto configurado: US$ {cfg['piso_neto_usd_por_noche']}/noche. Con los descuentos activos acumulados, "
      f'eso exige publicar al menos **US$ {pb:.0f} en Booking** y **US$ {pa:.0f} en Airbnb**.\n')
    w('| Fecha | Día | Contexto | Booking (publicado) | Airbnb (publicado) | Neto peor caso B / A | Estadía mín. | Nota |')
    w('|---|---|---|---|---|---|---|---|')
    base_hist = st.median([r['usd'] / r['noches'] for r in reservas if r['usd'] and r['canal'] == 'Booking'
                           and (hoy - r['checkin']).days < 120]) if reservas else 85
    occ_media = h['ocupacion_media'] if h else 0.45
    for i in range(dias):
        d = hoy + dt.timedelta(i)
        if h and d in h['ocupadas']:
            continue
        esp = fecha_especial(cfg, d)
        mult = 1.0
        if h:
            mult += max(-0.10, min(0.15, 0.5 * (h['ocupacion_dow'].get(d.weekday(), occ_media) - occ_media)))
        if esp:
            mult += 0.20 if 'alta' not in esp else 0.10
        nota = []
        if i <= 3:
            mult -= 0.08
            nota.append('último momento')
        precios = {}
        for plat in ('booking', 'airbnb'):
            cand = [v for (p, ci, n), v in ref.items() if p == plat
                    and abs((dt.date.fromisoformat(ci) - d).days) <= 7
                    and (dt.date.fromisoformat(ci).weekday() >= 4) == (d.weekday() >= 4)]
            base = st.median(cand) if cand else base_hist
            precio = base * mult
            piso = pb if plat == 'booking' else pa
            if precio < piso:
                precio = piso
                nota.append(f'{plat}: al piso')
            precios[plat] = round(precio)
        min_n = 2 if esp and d.weekday() in (4, 5) or (esp and 'Carnaval' in esp) else 1
        if h and (d + dt.timedelta(1)) in h['ocupadas']:
            min_n = 1
            if (d - dt.timedelta(1)) in h['ocupadas']:
                nota.append('noche suelta entre dos reservas')
        w(f"| {d.strftime('%d/%m')} | {DIAS[d.weekday()]} | {esp or '—'} | US$ {precios['booking']} | US$ {precios['airbnb']} | "
          f"US$ {neto(cfg, 'booking', precios['booking']):.0f} / {neto(cfg, 'airbnb', precios['airbnb']):.0f} | {min_n} | {', '.join(nota)} |")
    w('\n*Booking: el precio publicado lo ve un huésped sin Genius en computadora; con Genius y móvil paga un 19% menos. '
      'Airbnb: con el descuento para huéspedes con excelentes calificaciones paga un 15% menos.*\n')
    return '\n'.join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mercado')
    ap.add_argument('--dias', type=int, default=60)
    ap.add_argument('--hoy')
    a = ap.parse_args()
    cfg = json.loads((RAIZ / 'estrategia' / 'config.json').read_text(encoding='utf-8'))
    hoy = dt.date.fromisoformat(a.hoy) if a.hoy else dt.date.today()
    if a.mercado:
        archivo = Path(a.mercado)
    else:
        cands = sorted(p for p in (RAIZ / 'datos' / 'mercado').glob('*.json') if 'anuncios' not in p.name)
        archivo = cands[-1] if cands else None
    mercado = json.loads(archivo.read_text(encoding='utf-8')) if archivo else None
    texto = informe(cfg, cargar_reservas(), mercado, a.dias, hoy)
    out = RAIZ / 'informes' / f'estrategia-{hoy.isoformat()}.md'
    out.parent.mkdir(exist_ok=True)
    out.write_text(texto, encoding='utf-8')
    print(f'Informe -> {out.relative_to(RAIZ)}' + (f' (mercado: {archivo.name})' if archivo else ' (sin mercado)'))


if __name__ == '__main__':
    main()
