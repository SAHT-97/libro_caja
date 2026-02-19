"""
════════════════════════════════════════════════════════════════════════════════
  LIBRO DE CAJA PRO PYME — Conforme SII Chile (Art. 14 D N°3 y N°8)
  Desarrollado para cumplir normativa vigente SII
════════════════════════════════════════════════════════════════════════════════
  Instalación:
      pip install streamlit pandas openpyxl

  Ejecución:
      streamlit run libro_caja_app.py
════════════════════════════════════════════════════════════════════════════════
"""

import io
import re
import os
from datetime import datetime

import pandas as pd
import streamlit as st
from openpyxl import Workbook
from openpyxl.styles import (
    Alignment, Border, Font, PatternFill, Side
)
from openpyxl.utils import get_column_letter

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTES
# ─────────────────────────────────────────────────────────────────────────────
TIPO_DOC_NOMBRES = {
    33: "Factura Electrónica",
    34: "Factura No Afecta o Exenta Elec.",
    35: "Boleta Afecta Electrónica",
    38: "Boleta No Afecta o Exenta Elec.",
    39: "Boleta Electrónica",
    41: "Boleta Exenta Electrónica",
    46: "Factura de Compra Electrónica",
    48: "Comprobante de Pago Electrónico",
    52: "Guía de Despacho Electrónica",
    56: "Nota de Débito Electrónica",
    61: "Nota de Crédito Electrónica",
    110: "Factura de Exportación Electrónica",
    111: "Nota de Débito de Exportación Elec.",
    112: "Nota de Crédito de Exportación Elec.",
}

BOLETAS_AFECTAS = [35, 39]
BOLETAS_EXENTAS = [38, 41]
COMPROBANTES_PAGO = [48]
NOTAS_CREDITO = [61, 112]
NOTAS_DEBITO = [56, 111]
FACTURAS_VENTA = [33, 34, 110]

SEPARADORES = [";", ",", "\t", "|"]
ENCODINGS = ["utf-8", "utf-8-sig", "latin-1", "iso-8859-1", "cp1252"]


# ─────────────────────────────────────────────────────────────────────────────
# UTILIDADES DE LECTURA CSV
# ─────────────────────────────────────────────────────────────────────────────
def detectar_separador(contenido: bytes) -> str:
    muestra = contenido[:2000].decode("latin-1", errors="ignore")
    conteos = {sep: muestra.count(sep) for sep in SEPARADORES}
    return max(conteos, key=conteos.get)


def leer_csv(archivo) -> pd.DataFrame:
    """
    Lee un CSV del SII detectando separador y encoding.
    Maneja trailing semicolons que generan los exportadores del SII.
    """
    contenido = archivo.read()
    sep = detectar_separador(contenido)

    for enc in ENCODINGS:
        try:
            texto = contenido.decode(enc)
            lines = texto.splitlines()
            if not lines:
                continue

            n_header = len(lines[0].split(sep))
            n_data = len(lines[1].split(sep)) if len(lines) > 1 else n_header

            if n_data > n_header:
                extras = n_data - n_header
                header_ext = lines[0].strip().split(sep) + [f"_extra_{i}" for i in range(extras)]
                df = pd.read_csv(
                    io.BytesIO(contenido),
                    sep=sep,
                    encoding=enc,
                    dtype=str,
                    names=header_ext,
                    skiprows=1,
                    on_bad_lines="skip",
                )
            else:
                df = pd.read_csv(
                    io.BytesIO(contenido),
                    sep=sep,
                    encoding=enc,
                    dtype=str,
                    on_bad_lines="skip",
                )

            df.columns = df.columns.str.strip()
            df = df[[c for c in df.columns if not str(c).startswith("_extra_")]]
            return df
        except Exception:
            continue

    raise ValueError(f"No se pudo leer el archivo: {getattr(archivo, 'name', 'desconocido')}")


def parsear_fecha(valor: str) -> pd.Timestamp | None:
    if not valor or pd.isna(valor):
        return None
    valor = str(valor).strip()
    # Solo tomar la parte de fecha (dd/mm/aaaa) si viene con hora
    parte_fecha = valor.split(" ")[0]
    for fmt in ["%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y"]:
        try:
            return pd.to_datetime(parte_fecha, format=fmt)
        except Exception:
            pass
    return None


def a_numero(valor) -> float:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return 0.0
    try:
        return float(str(valor).replace(".", "").replace(",", ".").strip())
    except Exception:
        return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# PROCESAMIENTO VENTAS
# ─────────────────────────────────────────────────────────────────────────────
def procesamiento_ventas(archivos_ventas: list, archivos_resumen: list, periodo: str = "") -> pd.DataFrame:
    """
    Procesa archivos CSV de ventas (facturas y resúmenes).
    Retorna DataFrame con columnas del Libro de Caja.
    """
    registros = []

    # ── Facturas de venta ────────────────────────────────────────────────────
    for archivo in archivos_ventas:
        df = leer_csv(archivo)
        col_map = _mapear_columnas_ventas(df)
        if col_map is None:
            st.warning(f"⚠️ No se reconocieron columnas en {archivo.name}. Se omite.")
            continue

        for _, fila in df.iterrows():
            tipo_doc_raw = a_numero(fila.get(col_map.get("tipo_doc", ""), 0))
            tipo_doc = int(tipo_doc_raw) if tipo_doc_raw else 0

            # Solo procesar facturas en este archivo
            if tipo_doc not in FACTURAS_VENTA + NOTAS_CREDITO + NOTAS_DEBITO:
                continue

            fecha = parsear_fecha(fila.get(col_map.get("fecha", ""), ""))
            if fecha is None:
                continue

            folio = str(fila.get(col_map.get("folio", ""), "")).strip()
            rut_cliente = str(fila.get(col_map.get("rut", ""), "")).strip()
            razon = str(fila.get(col_map.get("razon", ""), "")).strip()
            monto_neto = a_numero(fila.get(col_map.get("neto", ""), 0))
            monto_exento = a_numero(fila.get(col_map.get("exento", ""), 0))
            monto_total = a_numero(fila.get(col_map.get("total", ""), 0))

            if monto_total == 0:
                continue

            # Determinar tipo operación y montos según tipo de documento
            if tipo_doc in NOTAS_CREDITO:
                tipo_op = 2  # Egreso (devuelve dinero)
                c8 = abs(monto_total)
                c9 = abs(monto_neto + monto_exento)
                glosa = f"NC Venta — {razon}"
            elif tipo_doc in NOTAS_DEBITO:
                tipo_op = 1  # Ingreso adicional
                c8 = abs(monto_total)
                c9 = abs(monto_neto + monto_exento)
                glosa = f"ND Venta — {razon}"
            else:
                tipo_op = 1
                c8 = abs(monto_total)
                c9 = abs(monto_neto + monto_exento)  # Sin IVA en ProPyme
                glosa = f"Venta — {razon}"

            registros.append({
                "Tipo Operación": tipo_op,
                "N° Documento": folio,
                "Tipo Documento": tipo_doc,
                "RUT Emisor": rut_cliente,
                "Fecha Operación": fecha,
                "Glosa de Operación": glosa,
                "C8": c8,
                "C9": c9,
                "_origen": "venta_factura",
            })

    # ── Resúmenes de ventas (boletas / comprobantes) ──────────────────────────
    for archivo in archivos_resumen:
        df = leer_csv(archivo)
        _procesar_resumen_ventas(df, archivo.name, registros, periodo)

    if not registros:
        return pd.DataFrame()

    return pd.DataFrame(registros)


def _mapear_columnas_ventas(df: pd.DataFrame) -> dict | None:
    """Mapea columnas del CSV de ventas a nombres estándar."""
    cols = {c.lower(): c for c in df.columns}
    mapa = {}

    # Tipo documento
    for k in ["tipo doc", "tipo_doc", "tipodoc", "tipo documento"]:
        if k in cols:
            mapa["tipo_doc"] = cols[k]
            break

    # Folio
    for k in ["folio", "n° folio", "numero folio"]:
        if k in cols:
            mapa["folio"] = cols[k]
            break

    # Fecha
    for k in ["fecha docto", "fecha_docto", "fechadocto", "fecha operación", "fecha"]:
        if k in cols:
            mapa["fecha"] = cols[k]
            break

    # RUT
    for k in ["rut cliente", "rut_cliente", "rutcliente", "rut proveedor", "rut"]:
        if k in cols:
            mapa["rut"] = cols[k]
            break

    # Razón social
    for k in ["razon social", "razón social", "razon_social"]:
        if k in cols:
            mapa["razon"] = cols[k]
            break

    # Montos
    for k in ["monto neto", "monto_neto", "neto"]:
        if k in cols:
            mapa["neto"] = cols[k]
            break

    for k in ["monto exento", "monto_exento", "exento"]:
        if k in cols:
            mapa["exento"] = cols[k]
            break

    for k in ["monto total", "monto_total", "total"]:
        if k in cols:
            mapa["total"] = cols[k]
            break

    if "tipo_doc" not in mapa or "fecha" not in mapa:
        return None
    return mapa


def _fecha_fallback_desde_nombre(nombre_archivo: str, periodo: str) -> pd.Timestamp:
    """
    Intenta extraer año y mes del nombre del archivo.
    Busca patrones como: 2024-11, 202411, nov2024, etc.
    Si no encuentra nada, usa el 31/12 del año del período.
    """
    # Buscar patrón YYYY-MM o YYYYMM en el nombre del archivo
    match = re.search(r"(\d{4})[_\-]?(\d{2})", nombre_archivo)
    if match:
        anio = int(match.group(1))
        mes = int(match.group(2))
        if 2000 <= anio <= 2100 and 1 <= mes <= 12:
            # Último día del mes
            import calendar
            ultimo_dia = calendar.monthrange(anio, mes)[1]
            return pd.Timestamp(f"{anio}-{mes:02d}-{ultimo_dia}")

    # Fallback: último día del año del período ingresado por el usuario
    anio_periodo = str(periodo).strip()
    if anio_periodo.isdigit() and len(anio_periodo) == 4:
        return pd.Timestamp(f"{anio_periodo}-12-31")

    # Último recurso: año actual
    return pd.Timestamp(f"{datetime.now().year}-12-31")


def _procesar_resumen_ventas(df: pd.DataFrame, nombre: str, registros: list, periodo: str = ""):
    """
    Procesa archivo resumen de ventas (boletas y comprobantes por tipo y día).
    Formato esperado: Tipo Documento | Total Documentos | Monto Exento | Monto Neto | Monto IVA | Monto Total
    Si el CSV tiene fecha (detalle diario), agrupa por fecha.
    Si es resumen mensual, extrae una fila por tipo de documento.
    """
    cols = {c.lower().strip(): c for c in df.columns}

    # Detectar si hay columna de fecha (detalle diario)
    col_fecha = None
    for k in ["fecha", "fecha docto", "fecha_docto"]:
        if k in cols:
            col_fecha = cols[k]
            break

    col_tipo = None
    for k in ["tipo documento", "tipo_documento", "tipodocumento"]:
        if k in cols:
            col_tipo = cols[k]
            break

    col_neto = None
    for k in ["monto neto", "monto_neto", "neto"]:
        if k in cols:
            col_neto = cols[k]
            break

    col_exento = None
    for k in ["monto exento", "monto_exento", "exento"]:
        if k in cols:
            col_exento = cols[k]
            break

    col_total = None
    for k in ["monto total", "monto_total", "total"]:
        if k in cols:
            col_total = cols[k]
            break

    # Detectar folio inicio / fin (para resúmenes diarios con rango)
    col_folio_ini = None
    col_folio_fin = None
    for k in ["folio inicial", "folio_inicial", "desde"]:
        if k in cols:
            col_folio_ini = cols[k]
            break
    for k in ["folio final", "folio_final", "hasta"]:
        if k in cols:
            col_folio_fin = cols[k]
            break

    for _, fila in df.iterrows():
        tipo_str = str(fila.get(col_tipo, "") if col_tipo else "").strip()
        if not tipo_str:
            continue

        # Extraer código numérico del tipo documento ej: "Boleta Afecta Electrónica(35)"
        match = re.search(r"\((\d+)\)", tipo_str)
        if not match:
            # Intentar leer directamente si es número
            try:
                codigo = int(tipo_str)
            except Exception:
                continue
        else:
            codigo = int(match.group(1))

        # Ignorar facturas en resúmenes (se procesan aparte)
        if codigo in FACTURAS_VENTA:
            continue

        # Solo boletas y comprobantes de pago
        # Solo boletas y comprobantes de pago (Excluir NC 61 y ND)
        if codigo not in BOLETAS_AFECTAS + BOLETAS_EXENTAS + COMPROBANTES_PAGO:
            continue

        monto_neto = a_numero(fila.get(col_neto, 0) if col_neto else 0)
        monto_exento = a_numero(fila.get(col_exento, 0) if col_exento else 0)
        monto_total = a_numero(fila.get(col_total, 0) if col_total else 0)

        if monto_total == 0:
            continue

        # Fecha
        if col_fecha:
            fecha = parsear_fecha(fila.get(col_fecha, ""))
            if fecha is None:
                # Intentar extraer del nombre del archivo cuando la celda no parsea
                fecha = _fecha_fallback_desde_nombre(nombre, periodo)
        else:
            # Sin columna fecha: extraer del nombre del archivo o usar período
            fecha = _fecha_fallback_desde_nombre(nombre, periodo)

        if fecha is None:
            continue

        # N° Documento
        if col_folio_ini and col_folio_fin:
            f_ini = str(fila.get(col_folio_ini, "")).strip()
            f_fin = str(fila.get(col_folio_fin, "")).strip()
            n_doc = f"{f_ini} al {f_fin}" if f_ini and f_fin else "Z"
        else:
            n_doc = "Z"

        # Como excluimos NC y ND, todo lo restante es venta/ingreso
        tipo_op = 1
        c9 = abs(monto_neto + monto_exento)

        registros.append({
            "Tipo Operación": tipo_op,
            "N° Documento": n_doc,
            "Tipo Documento": codigo,
            "RUT Emisor": "",
            "Fecha Operación": fecha,
            "Glosa de Operación": f"Resumen ventas boletas del día — {TIPO_DOC_NOMBRES.get(codigo, tipo_str)}",
            "C8": abs(monto_total),
            "C9": c9,
            "_origen": "resumen_ventas",
        })


# ─────────────────────────────────────────────────────────────────────────────
# PROCESAMIENTO COMPRAS
# ─────────────────────────────────────────────────────────────────────────────
def procesamiento_compras(archivos_compras: list) -> pd.DataFrame:
    """Procesa archivos CSV de compras. Retorna DataFrame Libro de Caja."""
    registros = []

    for archivo in archivos_compras:
        df = leer_csv(archivo)
        col_map = _mapear_columnas_compras(df)
        if col_map is None:
            st.warning(f"⚠️ No se reconocieron columnas en {archivo.name}. Se omite.")
            continue

        for _, fila in df.iterrows():
            tipo_doc_raw = a_numero(fila.get(col_map.get("tipo_doc", ""), 0))
            tipo_doc = int(tipo_doc_raw) if tipo_doc_raw else 0

            fecha = parsear_fecha(fila.get(col_map.get("fecha", ""), ""))
            if fecha is None:
                continue

            folio = str(fila.get(col_map.get("folio", ""), "")).strip()
            rut_prov = str(fila.get(col_map.get("rut", ""), "")).strip()
            razon = str(fila.get(col_map.get("razon", ""), "")).strip()
            monto_neto = a_numero(fila.get(col_map.get("neto", ""), 0))
            monto_exento = a_numero(fila.get(col_map.get("exento", ""), 0))
            monto_total = a_numero(fila.get(col_map.get("total", ""), 0))

            if monto_total == 0:
                continue

            if tipo_doc in NOTAS_CREDITO:
                # NC de proveedor: reembolso → ingreso, aumenta base imponible
                tipo_op = 1
                c8 = abs(monto_total)
                c9 = abs(monto_neto + monto_exento)
                glosa = f"NC Compra — {razon}"
            elif tipo_doc in NOTAS_DEBITO:
                # ND de proveedor: pago adicional → egreso, disminuye base imponible
                tipo_op = 2
                c8 = abs(monto_total)
                c9 = abs(monto_neto + monto_exento)
                glosa = f"ND Compra — {razon}"
            else:
                tipo_op = 2  # Egreso
                c8 = abs(monto_total)
                c9 = abs(monto_neto + monto_exento)
                glosa = f"Compra — {razon}"

            registros.append({
                "Tipo Operación": tipo_op,
                "N° Documento": folio,
                "Tipo Documento": tipo_doc,
                "RUT Emisor": rut_prov,
                "Fecha Operación": fecha,
                "Glosa de Operación": glosa,
                "C8": c8,
                "C9": c9,
                "_origen": "compra",
            })

    if not registros:
        return pd.DataFrame()
    return pd.DataFrame(registros)


def _mapear_columnas_compras(df: pd.DataFrame) -> dict | None:
    cols = {c.lower().strip(): c for c in df.columns}
    mapa = {}

    for k in ["tipo doc", "tipo_doc", "tipodoc"]:
        if k in cols:
            mapa["tipo_doc"] = cols[k]
            break

    for k in ["folio", "n° folio"]:
        if k in cols:
            mapa["folio"] = cols[k]
            break

    for k in ["fecha docto", "fecha_docto", "fechadocto", "fecha recepcion"]:
        if k in cols:
            mapa["fecha"] = cols[k]
            break
    if "fecha" not in mapa:
        for k in ["fecha"]:
            if k in cols:
                mapa["fecha"] = cols[k]
                break

    for k in ["rut proveedor", "rut_proveedor", "rutproveedor"]:
        if k in cols:
            mapa["rut"] = cols[k]
            break

    for k in ["razon social", "razón social", "razon_social"]:
        if k in cols:
            mapa["razon"] = cols[k]
            break

    for k in ["monto neto", "monto_neto", "neto"]:
        if k in cols:
            mapa["neto"] = cols[k]
            break

    for k in ["monto exento", "monto_exento", "exento"]:
        if k in cols:
            mapa["exento"] = cols[k]
            break

    for k in ["monto total", "monto_total", "total"]:
        if k in cols:
            mapa["total"] = cols[k]
            break

    if "tipo_doc" not in mapa or "fecha" not in mapa:
        return None
    return mapa


# ─────────────────────────────────────────────────────────────────────────────
# GENERACIÓN LIBRO DE CAJA
# ─────────────────────────────────────────────────────────────────────────────
def generar_libro_caja(
    df_ventas: pd.DataFrame,
    df_compras: pd.DataFrame,
    saldo_inicial: float,
    rut_empresa: str,
    nombre_empresa: str,
    periodo: str,
) -> pd.DataFrame:
    """Combina ventas y compras, ordena cronológicamente y agrega correlativo."""
    frames = [f for f in [df_ventas, df_compras] if not f.empty]

    # Fila saldo inicial
    saldo_row = pd.DataFrame([{
        "Tipo Operación": 0,
        "N° Documento": "",
        "Tipo Documento": "",
        "RUT Emisor": rut_empresa,
        "Tipo Documento": "",
        "RUT Emisor": rut_empresa,
        "Fecha Operación": pd.Timestamp(f"{str(periodo).strip()}-01-01") if periodo and str(periodo).strip().isdigit() and len(str(periodo).strip()) == 4 else pd.Timestamp.now().replace(month=1, day=1),
        "Glosa de Operación": "Saldo Inicial",
        "C8": float(saldo_inicial),
        "C9": 0.0,
        "_origen": "saldo_inicial",
    }])

    if frames:
        df_all = pd.concat(frames, ignore_index=True)
        df_all = df_all.sort_values("Fecha Operación", na_position="first")
        df_final = pd.concat([saldo_row, df_all], ignore_index=True)
    else:
        df_final = saldo_row

    df_final = df_final.reset_index(drop=True)
    df_final.insert(0, "N° Correlativo", range(1, len(df_final) + 1))

    return df_final


def calcular_totales(df: pd.DataFrame) -> dict:
    mask_ing = df["Tipo Operación"].isin([0, 1])
    mask_egr = df["Tipo Operación"] == 2

    total_ingresos = df.loc[mask_ing, "C8"].sum()
    total_egresos = df.loc[mask_egr, "C8"].sum()
    saldo_flujo = total_ingresos - total_egresos

    ing_bi = df.loc[mask_ing, "C9"].sum()
    egr_bi = df.loc[mask_egr, "C9"].sum()
    resultado_neto = ing_bi - egr_bi

    return {
        "total_ingresos": total_ingresos,
        "total_egresos": total_egresos,
        "saldo_flujo": saldo_flujo,
        "ing_bi": ing_bi,
        "egr_bi": egr_bi,
        "resultado_neto": resultado_neto,
    }


# ─────────────────────────────────────────────────────────────────────────────
# EXPORTACIÓN EXCEL (formato oficial SII)
# ─────────────────────────────────────────────────────────────────────────────
def exportar_excel(
    df: pd.DataFrame,
    totales: dict,
    rut_empresa: str,
    nombre_empresa: str,
    periodo: str,
) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Libro Caja"

    # ── Colores ────────────────────────────────────────────────────────────
    AZUL_OSCURO = "1F3864"
    AZUL_HEADER = "2E5090"
    AZUL_CLARO = "BDD7EE"
    GRIS_CLARO = "F2F2F2"
    AMARILLO = "FFFF00"
    VERDE = "E2EFDA"
    ROJO = "FCE4D6"
    BLANCO = "FFFFFF"

    borde_fino = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )

    def estilo_celda(ws, fila, col, valor, negrita=False, alineacion="left",
                     fondo=None, fuente_color="000000", borde=True, num_fmt=None):
        cell = ws.cell(row=fila, column=col, value=valor)
        cell.font = Font(name="Arial", bold=negrita, color=fuente_color, size=9)
        cell.alignment = Alignment(horizontal=alineacion, vertical="center", wrap_text=True)
        if fondo:
            cell.fill = PatternFill("solid", start_color=fondo)
        if borde:
            cell.border = borde_fino
        if num_fmt:
            cell.number_format = num_fmt
        return cell

    # ── Título principal ───────────────────────────────────────────────────
    ws.merge_cells("A1:M1")
    titulo = ws["A1"]
    titulo.value = (
        "ANEXO 3. LIBRO DE CAJA CONTRIBUYENTES ACOGIDOS AL RÉGIMEN DEL "
        "ARTÍCULO 14 LETRA D) DEL N°3 Y N°8 LETRA (a) DE LA LEY SOBRE IMPUESTO A LA RENTA"
    )
    titulo.font = Font(name="Arial", bold=True, color=BLANCO, size=10)
    titulo.fill = PatternFill("solid", start_color=AZUL_OSCURO)
    titulo.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 35

    # ── Datos empresa ──────────────────────────────────────────────────────
    ws.merge_cells("A2:B2"); ws["A2"].value = "PERÍODO"
    ws.merge_cells("C2:F2"); ws["C2"].value = periodo
    ws.merge_cells("A3:B3"); ws["A3"].value = "RUT"
    ws.merge_cells("C3:F3"); ws["C3"].value = rut_empresa
    ws.merge_cells("A4:B4"); ws["A4"].value = "NOMBRE / RAZÓN SOCIAL"
    ws.merge_cells("C4:M4"); ws["C4"].value = nombre_empresa

    for row in range(2, 5):
        for col in range(1, 14):
            cell = ws.cell(row=row, column=col)
            cell.font = Font(name="Arial", bold=(col <= 2), size=9)
            cell.fill = PatternFill("solid", start_color=GRIS_CLARO)
            cell.border = borde_fino
            cell.alignment = Alignment(vertical="center")

    ws.row_dimensions[2].height = 18
    ws.row_dimensions[3].height = 18
    ws.row_dimensions[4].height = 18

    # ── Encabezados de sección ─────────────────────────────────────────────
    ws.merge_cells("A5:M5")
    ws["A5"].value = "REGISTRO DE OPERACIONES"
    ws["A5"].font = Font(name="Arial", bold=True, color=BLANCO, size=10)
    ws["A5"].fill = PatternFill("solid", start_color=AZUL_HEADER)
    ws["A5"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[5].height = 20

    # ── Encabezados de columna ─────────────────────────────────────────────
    headers = [
        ("A6", "N° CORRELATIVO\n(C1)"),
        ("B6", "TIPO OPERACIÓN\n(C2)"),
        ("C6", "N° DE DOCUMENTO\n(C3)"),
        ("D6", "TIPO DOCUMENTO\n(C4)"),
        ("E6", "RUT EMISOR\n(C5)"),
        ("F6", "FECHA OPERACIÓN\n(C6)"),
        ("G6", "GLOSA DE OPERACIÓN\n(C7)"),
        ("H6", "MONTO TOTAL\nFLUJO INGRESO O EGRESO\n(C8)"),
        ("I6", "MONTO QUE AFECTA\nLA BASE IMPONIBLE\n(C9)"),
    ]

    for celda, texto in headers:
        cell = ws[celda]
        cell.value = texto
        cell.font = Font(name="Arial", bold=True, color=BLANCO, size=8)
        cell.fill = PatternFill("solid", start_color=AZUL_HEADER)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = borde_fino

    ws.row_dimensions[6].height = 45

    # ── Ancho de columnas ──────────────────────────────────────────────────
    anchos = {"A": 8, "B": 10, "C": 14, "D": 14, "E": 14, "F": 12,
               "G": 40, "H": 16, "I": 16}
    for col, ancho in anchos.items():
        ws.column_dimensions[col].width = ancho

    # ── Datos del libro ────────────────────────────────────────────────────
    fila_inicio = 7
    for idx, row in df.iterrows():
        fila = fila_inicio + idx
        tipo_op = row["Tipo Operación"]
        fondo_fila = GRIS_CLARO if idx % 2 == 0 else BLANCO

        if tipo_op == 0:
            fondo_fila = AZUL_CLARO

        # Fecha
        fecha = row["Fecha Operación"]
        fecha_str = fecha.strftime("%d/%m/%Y") if pd.notna(fecha) else ""

        # Tipo doc — mostrar nombre si existe
        tipo_doc = row["Tipo Documento"]
        try:
            tipo_doc_int = int(float(str(tipo_doc))) if str(tipo_doc).strip() else ""
            tipo_doc_str = str(tipo_doc_int) if tipo_doc_int else ""
        except Exception:
            tipo_doc_str = str(tipo_doc) if tipo_doc else ""

        valores = [
            row["N° Correlativo"],
            tipo_op,
            str(row["N° Documento"]),
            tipo_doc_str,
            str(row["RUT Emisor"]) if row["RUT Emisor"] else "",
            fecha_str,
            str(row["Glosa de Operación"]),
            row["C8"] if row["C8"] != 0 else None,
            row["C9"] if row["C9"] != 0 else None,
        ]

        alineaciones = ["center", "center", "center", "center", "center",
                        "center", "left", "right", "right"]
        formatos = [None, None, None, None, None, None, None,
                    '#,##0', '#,##0']

        for col_idx, (val, aln, fmt) in enumerate(zip(valores, alineaciones, formatos), 1):
            cell = ws.cell(row=fila, column=col_idx, value=val)
            cell.font = Font(name="Arial", size=9,
                             bold=(tipo_op == 0))
            cell.fill = PatternFill("solid", start_color=fondo_fila)
            cell.alignment = Alignment(horizontal=aln, vertical="center", wrap_text=True)
            cell.border = borde_fino
            if fmt:
                cell.number_format = fmt

        ws.row_dimensions[fila].height = 16

    # ── Fila separadora ────────────────────────────────────────────────────
    fila_sep = fila_inicio + len(df)
    ws.merge_cells(f"A{fila_sep}:I{fila_sep}")
    ws[f"A{fila_sep}"].fill = PatternFill("solid", start_color=AZUL_HEADER)

    # ── Totales ────────────────────────────────────────────────────────────
    fila_tot = fila_sep + 1
    totales_data = [
        ("TOTAL FLUJO INGRESOS (C10)", totales["total_ingresos"], VERDE),
        ("TOTAL FLUJO EGRESOS (C11)", totales["total_egresos"], ROJO),
        ("SALDO FLUJO DE CAJA (C12)", totales["saldo_flujo"],
         VERDE if totales["saldo_flujo"] >= 0 else ROJO),
        ("INGRESOS BASE IMPONIBLE (C13)", totales["ing_bi"], VERDE),
        ("EGRESOS BASE IMPONIBLE (C14)", totales["egr_bi"], ROJO),
        ("RESULTADO NETO (C15)", totales["resultado_neto"],
         VERDE if totales["resultado_neto"] >= 0 else ROJO),
    ]

    for i, (label, valor, fondo) in enumerate(totales_data):
        fila = fila_tot + i
        ws.merge_cells(f"A{fila}:G{fila}")
        cell_label = ws[f"A{fila}"]
        cell_label.value = label
        cell_label.font = Font(name="Arial", bold=True, size=9)
        cell_label.fill = PatternFill("solid", start_color=fondo)
        cell_label.alignment = Alignment(horizontal="right", vertical="center")
        cell_label.border = borde_fino

        ws.merge_cells(f"H{fila}:I{fila}")
        cell_val = ws[f"H{fila}"]
        cell_val.value = valor
        cell_val.font = Font(name="Arial", bold=True, size=9)
        cell_val.fill = PatternFill("solid", start_color=fondo)
        cell_val.number_format = '#,##0'
        cell_val.alignment = Alignment(horizontal="right", vertical="center")
        cell_val.border = borde_fino
        ws.row_dimensions[fila].height = 18

    # ── Pie de página ──────────────────────────────────────────────────────
    fila_pie = fila_tot + len(totales_data) + 1
    ws.merge_cells(f"A{fila_pie}:I{fila_pie}")
    ws[f"A{fila_pie}"].value = (
        "Documento generado conforme al Art. 14 D N°3 y N°8(a) LIR — Régimen Pro Pyme — SII Chile"
    )
    ws[f"A{fila_pie}"].font = Font(name="Arial", italic=True, size=8, color="666666")
    ws[f"A{fila_pie}"].alignment = Alignment(horizontal="center")
    ws.row_dimensions[fila_pie].height = 14

    # ── Guardar en memoria ─────────────────────────────────────────────────
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


# ─────────────────────────────────────────────────────────────────────────────
# VALIDACIONES
# ─────────────────────────────────────────────────────────────────────────────
def validar_libro(df: pd.DataFrame) -> list[str]:
    advertencias = []

    # Duplicados
    df_ops = df[df["Tipo Operación"] != 0]
    duplicados = df_ops[df_ops.duplicated(
        subset=["N° Documento", "Tipo Documento", "Tipo Operación"], keep=False
    )]
    if not duplicados.empty:
        folios = duplicados["N° Documento"].unique()[:5]
        advertencias.append(
            f"⚠️ Posibles documentos duplicados detectados: {', '.join(str(f) for f in folios)}"
        )

    # Base imponible > total
    mask_problema = df["C9"] > df["C8"] + 1
    if mask_problema.any():
        advertencias.append(
            "⚠️ Existen registros donde la Base Imponible supera el Monto Total. Verifique los datos."
        )

    # Correlativo sin saltos
    correlativos = df["N° Correlativo"].tolist()
    esperado = list(range(1, len(correlativos) + 1))
    if correlativos != esperado:
        advertencias.append("⚠️ El correlativo tiene saltos o irregularidades.")

    return advertencias


# ─────────────────────────────────────────────────────────────────────────────
# INTERFAZ STREAMLIT
# ─────────────────────────────────────────────────────────────────────────────
def main():
    st.set_page_config(
        page_title="Libro de Caja — Pro Pyme SII",
        page_icon="📒",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # ── CSS personalizado ──────────────────────────────────────────────────
    st.markdown("""
    <style>
        .main { background-color: #f8f9fa; }
        .stButton>button {
            background-color: #1F3864;
            color: white;
            border-radius: 6px;
            font-weight: bold;
        }
        .stButton>button:hover { background-color: #2E5090; }
        .metric-card {
            background: white;
            border-radius: 8px;
            padding: 16px;
            box-shadow: 0 1px 4px rgba(0,0,0,0.1);
            text-align: center;
        }
        .header-sii {
            background: linear-gradient(90deg, #1F3864 0%, #2E5090 100%);
            color: white;
            padding: 20px 30px;
            border-radius: 8px;
            margin-bottom: 20px;
        }
        div[data-testid="stDataFrame"] {font-size: 12px;}
        .warning-box {
            background-color: #fff3cd;
            border-left: 4px solid #ffc107;
            padding: 10px;
            margin: 5px 0;
            border-radius: 4px;
        }
    </style>
    """, unsafe_allow_html=True)

    # ── Header ─────────────────────────────────────────────────────────────
    st.markdown("""
    <div class="header-sii">
        <h2 style="margin:0;">📒 LIBRO DE CAJA — RÉGIMEN PRO PYME</h2>
        <p style="margin:4px 0 0 0; opacity:0.85; font-size:0.9em;">
            Art. 14 Letra D) N°3 y N°8(a) Ley sobre Impuesto a la Renta — SII Chile
        </p>
    </div>
    """, unsafe_allow_html=True)

    # ── Sidebar — Parámetros empresa ───────────────────────────────────────
    with st.sidebar:
        logo_path = os.path.join(os.path.dirname(__file__), "logo.png")
        if os.path.exists(logo_path):
            st.image(logo_path, width=120, use_container_width=False)
        else:
            st.warning("Logo no encontrado")
        st.markdown("---")
        st.subheader("🏢 Datos de la Empresa")

        rut_empresa = st.text_input("RUT Empresa", placeholder="76.123.456-7")
        nombre_empresa = st.text_input("Nombre / Razón Social",
                                       placeholder="EMPRESA EJEMPLO LTDA.")
        periodo = st.text_input("Año Comercial",
                                value=str(datetime.now().year),
                                placeholder="2025",
                                help="Ingrese el año en formato YYYY",
                                max_chars=4)

        st.markdown("---")
        # Saldo inicial eliminado de la barra lateral
        # Se ingresa directamente en la tabla


        st.markdown("---")
        st.subheader("ℹ️ Tipo Operación")
        st.markdown("""
        | Código | Descripción |
        |--------|-------------|
        | **0** | Saldo Inicial |
        | **1** | Flujo Ingreso |
        | **2** | Flujo Egreso |
        """)

    # ── Carga de archivos ──────────────────────────────────────────────────
    st.markdown("## 📂 Carga de Archivos")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("### 🟢 Ventas (Facturas)")
        st.caption("Archivos CSV del registro de ventas (facturas electrónicas)")
        archivos_ventas = st.file_uploader(
            "Cargar CSV de Ventas",
            type=["csv"],
            accept_multiple_files=True,
            key="ventas",
            help="Suba uno o más archivos CSV con el detalle de facturas de venta"
        )

    with col2:
        st.markdown("### 🟡 Resumen Ventas (Boletas)")
        st.caption("CSV con resumen de boletas y comprobantes electrónicos")
        archivos_resumen = st.file_uploader(
            "Cargar CSV Resumen Ventas",
            type=["csv"],
            accept_multiple_files=True,
            key="resumen",
            help="Suba el archivo de resumen de ventas con boletas"
        )

    with col3:
        st.markdown("### 🔴 Compras")
        st.caption("Archivos CSV del registro de compras (un archivo por mes)")
        archivos_compras = st.file_uploader(
            "Cargar CSV de Compras",
            type=["csv"],
            accept_multiple_files=True,
            key="compras",
            help="Suba uno o más archivos CSV con el detalle de compras"
        )

    # ── Botón procesar ─────────────────────────────────────────────────────
    st.markdown("---")
    col_btn1, col_btn2, col_btn3 = st.columns([1, 2, 1])
    with col_btn2:
        boton_generar = st.button("⚙️ GENERAR LIBRO DE CAJA", use_container_width=True)

    # Cuando se presiona el botón, regenerar desde cero y guardar en session_state
    if boton_generar:
        if not archivos_ventas and not archivos_resumen and not archivos_compras:
            st.error("❌ Debe cargar al menos un archivo CSV para procesar.")
        else:
            if not rut_empresa or not nombre_empresa or not periodo:
                st.warning("⚠️ Complete los datos de la empresa en el panel lateral antes de procesar.")

            with st.spinner("Procesando archivos..."):
                df_ventas = pd.DataFrame()
                df_compras = pd.DataFrame()

                if archivos_ventas or archivos_resumen:
                    try:
                        df_ventas = procesamiento_ventas(
                            archivos_ventas or [],
                            archivos_resumen or [],
                            periodo or "",
                        )
                    except Exception as e:
                        st.error(f"❌ Error procesando ventas: {e}")

                if archivos_compras:
                    try:
                        df_compras = procesamiento_compras(archivos_compras)
                    except Exception as e:
                        st.error(f"❌ Error procesando compras: {e}")

                df_libro_nuevo = generar_libro_caja(
                    df_ventas, df_compras,
                    0.0,
                    rut_empresa or "00.000.000-0",
                    nombre_empresa or "SIN NOMBRE",
                    periodo or "SIN PERÍODO",
                )

                advertencias = validar_libro(df_libro_nuevo)

                # Guardar en session_state (fuente de verdad persistente)
                st.session_state["df_libro"] = df_libro_nuevo
                st.session_state["totales"] = calcular_totales(df_libro_nuevo)
                st.session_state["advertencias"] = advertencias
                st.session_state["editor_version"] = 0  # Reiniciar el editor
                st.session_state["rut_empresa"] = rut_empresa
                st.session_state["nombre_empresa"] = nombre_empresa
                st.session_state["periodo"] = periodo

    # ── Mostrar tabla si ya fue generada ──────────────────────────────────
    if "df_libro" not in st.session_state:
        # ── Estado inicial: instrucciones ──────────────────────────────────
        st.info("""
        **Cómo usar esta aplicación:**

        1. **Complete los datos de la empresa** en el panel lateral (RUT, Nombre, Período)
        2. **Ingrese el saldo inicial de caja** (único dato manual requerido)
        3. **Cargue los archivos CSV** del SII:
           - 📁 *Ventas*: Archivo de facturas electrónicas emitidas
           - 📁 *Resumen Ventas*: Archivo con resumen de boletas y comprobantes
           - 📁 *Compras*: Archivo de facturas de compra recibidas
        4. **Haga clic en "Generar Libro de Caja"**
        5. **Descargue el Excel** con el formato oficial SII
        """)

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("""
            **📌 Columnas del Libro de Caja (SII):**
            | Columna | Descripción |
            |---------|-------------|
            | C1 | N° Correlativo |
            | C2 | Tipo Operación (0/1/2) |
            | C3 | N° Documento |
            | C4 | Tipo Documento |
            | C5 | RUT Emisor |
            | C6 | Fecha Operación |
            | C7 | Glosa |
            | C8 | Monto Total Flujo |
            | C9 | Monto Base Imponible |
            """)
        with col2:
            st.markdown("""
            **📌 Tipos de Operación:**
            | Código | Significado |
            |--------|-------------|
            | 0 | Saldo Inicial |
            | 1 | Ingreso de Caja |
            | 2 | Egreso de Caja |

            **📌 Régimen Pro Pyme:**
            - El IVA **no** afecta la base imponible
            - Base imponible = Neto + Exento
            - Régimen Art. 14 D N°3 y N°8(a) LIR
            """)
        return

    # ── Leer desde session_state ───────────────────────────────────────────
    df_libro = st.session_state["df_libro"]
    totales   = st.session_state["totales"]
    advertencias = st.session_state.get("advertencias", [])
    # Usar siempre los valores actuales del sidebar (pueden haber cambiado sin regenerar)
    rut_empresa_ss    = rut_empresa or st.session_state.get("rut_empresa", "00.000.000-0")
    nombre_empresa_ss = nombre_empresa or st.session_state.get("nombre_empresa", "SIN NOMBRE")
    periodo_ss        = periodo or st.session_state.get("periodo", "SIN PERÍODO")
    editor_ver        = st.session_state.get("editor_version", 0)

    # ── Advertencias ───────────────────────────────────────────────────────
    if advertencias:
        st.markdown("### ⚠️ Advertencias de Validación")
        for adv in advertencias:
            st.warning(adv)

    st.markdown("## 📋 Libro de Caja")

    # Preparar df para mostrar (no modifica session_state)
    df_display = df_libro.copy()
    df_display["Fecha Operación"] = df_display["Fecha Operación"].apply(
        lambda x: x.date() if pd.notna(x) else None
    )

    def tipo_doc_label(v):
        try:
            codigo = int(float(str(v))) if str(v).strip() else 0
            nombre = TIPO_DOC_NOMBRES.get(codigo, "")
            return f"({codigo}) {nombre}" if nombre else str(v)
        except Exception:
            return str(v)

    df_display["Tipo Documento"] = df_display["Tipo Documento"].apply(tipo_doc_label)
    df_display["C9"] = df_display["C9"].apply(
        lambda x: f"$ {x:,.0f}".replace(",", ".") if x else ""
    )

    df_show = df_display.rename(columns={
        "N° Correlativo": "C1 N° Correlativo",
        "Tipo Operación": "C2 Tipo Operación",
        "N° Documento": "C3 N° Documento",
        "Tipo Documento": "C4 Tipo Documento",
        "RUT Emisor": "C5 RUT Emisor",
        "Fecha Operación": "C6 Fecha Operación",
        "Glosa de Operación": "C7 Glosa",
        "C8": "C8 Monto Total",
        "C9": "C9 Base Imponible",
    }).drop(columns=["_origen"], errors="ignore")

    def color_fila(row):
        if row["C2 Tipo Operación"] == 0:
            return ["background-color: #BDD7EE"] * len(row)
        elif row["C2 Tipo Operación"] == 1:
            return ["background-color: #E2EFDA"] * len(row)
        elif row["C2 Tipo Operación"] == 2:
            return ["background-color: #FCE4D6"] * len(row)
        return [""] * len(row)

    st.markdown("### ✏️ Editar Libro de Caja")
    st.caption("Edita el saldo inicial (C8) y las fechas (C6). Al confirmar cambios, la tabla se reordenará y el correlativo se recalculará.")

    # Clave dinámica: cuando se incrementa editor_version, el editor se reinicia
    # con los datos ya ordenados de session_state
    edited_df = st.data_editor(
        df_show.style.apply(color_fila, axis=1),
        use_container_width=True,
        height=520,
        disabled=[
            "C1 N° Correlativo", "C2 Tipo Operación", "C3 N° Documento",
            "C4 Tipo Documento", "C5 RUT Emisor",
            "C7 Glosa", "C9 Base Imponible"
        ],
        column_config={
            "C6 Fecha Operación": st.column_config.DateColumn(
                "C6 Fecha Operación",
                help="Haz clic para cambiar la fecha. Luego presiona 'Aplicar cambios'.",
                format="DD/MM/YYYY",
            ),
            "C8 Monto Total": st.column_config.NumberColumn(
                "C8 Monto Total",
                help="Ingrese monto total",
                min_value=0,
                step=1,
                format="$ %d",
            ),
        },
        key=f"editor_tabla_{editor_ver}"
    )

    # Botón para aplicar cambios explícitamente (reordena y recalcula)
    col_ap1, col_ap2, col_ap3 = st.columns([1, 2, 1])
    with col_ap2:
        if st.button("🔄 Aplicar cambios y reordenar", use_container_width=True, key="btn_aplicar"):
            if edited_df is not None and not edited_df.empty:
                try:
                    df_trabajo = df_libro.copy()

                    # 1) Actualizar saldo inicial
                    fila_saldo = edited_df[edited_df["C2 Tipo Operación"] == 0]
                    if not fila_saldo.empty:
                        nuevo_saldo = float(fila_saldo.iloc[0]["C8 Monto Total"] or 0)
                        idx_saldo = df_trabajo[df_trabajo["Tipo Operación"] == 0].index
                        if not idx_saldo.empty:
                            df_trabajo.loc[idx_saldo[0], "C8"] = nuevo_saldo

                    # 2) Propagar fechas editadas
                    for i, row in edited_df.iterrows():
                        nueva_fecha = row.get("C6 Fecha Operación")
                        if nueva_fecha is not None and i < len(df_trabajo):
                            try:
                                df_trabajo.at[i, "Fecha Operación"] = pd.Timestamp(nueva_fecha)
                            except Exception:
                                pass

                    # 3) Reordenar: saldo inicial siempre primero, resto por fecha
                    saldo_rows = df_trabajo[df_trabajo["Tipo Operación"] == 0].copy()
                    otros_rows = df_trabajo[df_trabajo["Tipo Operación"] != 0].sort_values(
                        "Fecha Operación", na_position="first"
                    )
                    df_trabajo = pd.concat([saldo_rows, otros_rows], ignore_index=True)

                    # 4) Recalcular correlativo
                    df_trabajo["N° Correlativo"] = range(1, len(df_trabajo) + 1)

                    # 5) Guardar en session_state y forzar reinicio del editor
                    st.session_state["df_libro"] = df_trabajo
                    st.session_state["totales"] = calcular_totales(df_trabajo)
                    st.session_state["editor_version"] = editor_ver + 1
                    st.rerun()

                except Exception as e:
                    st.error(f"Error al aplicar cambios: {e}")

    # Leyenda
    col_l1, col_l2, col_l3 = st.columns(3)
    col_l1.markdown("🔵 **Saldo Inicial**")
    col_l2.markdown("🟢 **Flujo Ingreso**")
    col_l3.markdown("🔴 **Flujo Egreso**")

    # ── KPIs ──────────────────────────────────────────────────────────────
    st.markdown("## 📊 Resumen del Período")
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    def fmt_clp(v):
        return f"${v:,.0f}".replace(",", ".")

    k1.metric("Total Ingresos (C10)", fmt_clp(totales["total_ingresos"]))
    k2.metric("Total Egresos (C11)", fmt_clp(totales["total_egresos"]))
    k3.metric("Saldo Flujo Caja (C12)", fmt_clp(totales["saldo_flujo"]))
    k4.metric("Ingresos BI (C13)", fmt_clp(totales["ing_bi"]))
    k5.metric("Egresos BI (C14)", fmt_clp(totales["egr_bi"]))
    resultado_delta = "▲ Positivo" if totales["resultado_neto"] >= 0 else "▼ Negativo"
    k6.metric("Resultado Neto (C15)", fmt_clp(totales["resultado_neto"]), delta=resultado_delta)

    # ── Fila de totales ────────────────────────────────────────────────────
    st.markdown("### 📑 Totales y Resultado")
    df_totales = pd.DataFrame([
        {"Concepto": "Total Flujo Ingresos (C10)", "Monto ($)": f"$ {totales['total_ingresos']:,.0f}".replace(",", ".")},
        {"Concepto": "Total Flujo Egresos (C11)", "Monto ($)": f"$ {totales['total_egresos']:,.0f}".replace(",", ".")},
        {"Concepto": "Saldo Flujo de Caja (C12)", "Monto ($)": f"$ {totales['saldo_flujo']:,.0f}".replace(",", ".")},
        {"Concepto": "Ingresos Base Imponible (C13)", "Monto ($)": f"$ {totales['ing_bi']:,.0f}".replace(",", ".")},
        {"Concepto": "Egresos Base Imponible (C14)", "Monto ($)": f"$ {totales['egr_bi']:,.0f}".replace(",", ".")},
        {"Concepto": "Resultado Neto (C15)", "Monto ($)": f"$ {totales['resultado_neto']:,.0f}".replace(",", ".")},
    ])
    st.dataframe(df_totales, use_container_width=True, hide_index=True, height=230)

    # ── Descarga Excel ─────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("## 💾 Exportar")

    excel_bytes = exportar_excel(
        df_libro, totales,
        rut_empresa_ss,
        nombre_empresa_ss,
        periodo_ss,
    )
    nombre_archivo = f"LibroCaja_{rut_empresa_ss.replace('.', '').replace('-', '')}_{periodo_ss}.xlsx"
    st.download_button(
        label="📥 Descargar Libro de Caja Excel",
        data=excel_bytes,
        file_name=nombre_archivo,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

    st.success(f"✅ Libro de Caja con {len(df_libro)} registros. Usa '🔄 Aplicar cambios' para confirmar ediciones.")


if __name__ == "__main__":
    main()

