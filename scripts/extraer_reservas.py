"""Extrae las reservas del dashboard (index-2.html) a datos/reservas.csv.

Uso:  python3 scripts/extraer_reservas.py [ruta_dashboard.html]

Cada fila es una reserva con check-in, noches, importe en USD (antes de
comisión), canal y comentarios. El agente estratega lo usa para medir
ocupación por día de la semana, tarifa media por mes y por canal.
"""
import csv
import datetime as dt
import html
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
MESES = {'ene': 1, 'feb': 2, 'mar': 3, 'abr': 4, 'may': 5, 'jun': 6,
         'jul': 7, 'ago': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dic': 12}


def texto(bloque, clase):
    m = re.search(r'class="%s">(.*?)</div>' % clase, bloque, re.S)
    if not m:
        return ''
    t = html.unescape(re.sub(r'<[^>]+>', ' ', m.group(1)))
    return re.sub(r'\s+', ' ', t).strip()


def extraer(ruta_html, anio_base=2026):
    s = Path(ruta_html).read_text(encoding='utf-8')
    s = re.sub(r'data:[^)"\']+', '', s)  # quita fuentes e imágenes embebidas
    bloques = re.findall(
        r'<div class="reserva[^"]*">(.*?)<div class="r-pago">(.*?)</div>\s*</div>\s*</div>', s, re.S)
    filas = []
    for b, pago in bloques:
        rango = texto(b, 'r-rango')
        m = re.match(r'\w+ (\d+)(?: (\w+))? → \w+ (\d+) (\w+)(?: (\d{4}))?', rango)
        if not m:
            continue
        d1, m1, _d2, m2, anio = m.groups()
        checkin = dt.date(int(anio or anio_base), MESES[m1 or m2], int(d1))
        noches = int(re.search(r'(\d+) noche', rango).group(1))
        extra = texto(b, 'r-extra')
        mu = re.search(r'US\$ ([\d.]+,\d+)', extra)
        canales = [html.unescape(c) for c in re.findall(r'chip canal">([^<]+)', pago)]
        filas.append({
            'checkin': checkin.isoformat(),
            'dia_llegada': 'Lu Ma Mi Ju Vi Sa Do'.split()[checkin.weekday()],
            'noches': noches,
            'usd': float(mu.group(1).replace('.', '').replace(',', '.')) if mu else '',
            'canal': canales[0] if canales else '',
            'huespedes': rango.split('·')[-1].strip(),
            'nombre': texto(b, 'r-nombre').replace(' Completada', ''),
            'detalle_cobro': extra,
            'comentarios': (texto(b, 'r-coment') + ' ' + texto(b, 'r-cobro')).strip(),
        })
    return filas


def main():
    ruta = sys.argv[1] if len(sys.argv) > 1 else RAIZ / 'index-2.html'
    filas = extraer(ruta)
    salida = RAIZ / 'datos' / 'reservas.csv'
    salida.parent.mkdir(exist_ok=True)
    with open(salida, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0].keys()))
        w.writeheader()
        w.writerows(filas)
    print(f'{len(filas)} reservas -> {salida.relative_to(RAIZ)}')


if __name__ == '__main__':
    main()
