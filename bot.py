import os
import logging
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
import gspread
from google.oauth2.service_account import Credentials
from dateutil.relativedelta import relativedelta
import json
import re
import unicodedata
import time
import threading
import signal
from decimal import Decimal, InvalidOperation
from uuid import uuid4
from functools import wraps
from telegram.ext import ApplicationHandlerStop, PicklePersistence

# Configuración de logging para ver errores en consola
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
registro_errores = logging.getLogger(__name__)

# Estados para la máquina de conversación
PASO_CATEGORIA, PASO_PLATA, PASO_DETALLE, PASO_RESUMEN_MES, PASO_RESUMEN_CATEGORIA = range(5)

# Permisos de Google
PERMISOS_API = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

# Zona horaria
ZONA_HORARIA = ZoneInfo("America/Argentina/Buenos_Aires")
MAX_TEXTO_MENSAJE_TELEGRAM = 4096


MENU = ReplyKeyboardMarkup([
    ["💰 Nuevo Gasto", "📊 Resumen"], ["📈 Proyección", "❓ Ayuda"]
], resize_keyboard=True)
CONTROLES = ReplyKeyboardMarkup([["⬅️ Volver", "❌ Cancelar"]], resize_keyboard=True)
CATEGORIAS = ReplyKeyboardMarkup([
    ["Comida", "Salud", "Camioneta"], ["Casa", "Trabajo", "Otros"], ["❌ Cancelar"]
], resize_keyboard=True)


def parsear_monto(texto):
    """Pesos: punto para miles, coma para centavos; admite 1500.50 también."""
    texto = str(texto).strip()
    if re.fullmatch(r"[1-9][0-9]{0,2}(?:\.[0-9]{3})+(?:,[0-9]{1,2})?", texto):
        texto = texto.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"[0-9]+(?:[,.][0-9]{1,2})?", texto):
        texto = texto.replace(",", ".")
    else:
        raise ValueError("Importe inválido")
    try:
        monto = Decimal(texto)
        if not monto.is_finite() or monto <= 0 or monto > Decimal("999999999999.99"):
            raise ValueError("Importe fuera de rango")
        return float(monto)
    except InvalidOperation as exc:
        raise ValueError("Importe inválido") from exc


def autorizado(funcion):
    @wraps(funcion)
    async def ejecutar(update, context, *args, **kwargs):
        if not update.effective_user or str(update.effective_user.id) not in bot_app.gente_permitida:
            if update.effective_message:
                await update.effective_message.reply_text("❌ Acceso denegado.")
            return ConversationHandler.END
        return await funcion(update, context, *args, **kwargs)
    return ejecutar


async def verificar_acceso(update, context):
    if not update.effective_user or str(update.effective_user.id) not in bot_app.gente_permitida:
        if update.effective_message:
            await update.effective_message.reply_text("❌ Acceso denegado.")
        raise ApplicationHandlerStop


def normalizar_texto(texto):
    """
    Normaliza texto para comparar categorías sin problemas de mayúsculas,
    acentos o espacios de más.
    """
    texto = str(texto or "").strip().lower()
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return texto


def dividir_texto_en_bloques(texto, limite=MAX_TEXTO_MENSAJE_TELEGRAM):
    """Conserva el contenido y limita unidades UTF-16, incluso sin espacios."""
    if limite < 2:
        raise ValueError("El límite debe ser al menos 2")
    bloques, actual, unidades = [], [], 0
    for caracter in texto:
        cantidad = 2 if ord(caracter) > 0xFFFF else 1
        if unidades + cantidad > limite:
            bloques.append("".join(actual))
            actual, unidades = [], 0
        actual.append(caracter)
        unidades += cantidad
    if actual:
        bloques.append("".join(actual))
    return bloques


class BotDeGastos:
    def __init__(self):
        self.credenciales = None
        self.cliente_api = None
        self.planillita = None
        self.gente_permitida = {x.strip() for x in os.getenv('USUARIOS_AUTORIZADOS', '').split(',') if x.strip()}
        self._hojas = {}
        self._lock = threading.RLock()
        self._derivadas_lock = threading.Lock()
        self._cache = None
        self._cache_hasta = 0
        self._version = 0
        self._version_actualizada = -1
        self._inciertos = set()
        self._guardados = set()
        self._llamadas = 0
        self._tamano_derivadas = {}

    def _hoja(self, nombre):
        if nombre not in self._hojas:
            self._hojas[nombre] = self.planillita.worksheet(nombre)
            self._llamadas += 1
        return self._hojas[nombre]

    def _leer_gastos(self, forzar=False):
        with self._lock:
            if forzar or self._cache is None or time.monotonic() >= self._cache_hasta:
                self._cache = self._hoja('Gastos').get_all_records()
                self._llamadas += 1
                self._cache_hasta = time.monotonic() + 15
            return self._cache

    def _actualizar_derivada(self, nombre, datos):
        # Una sola escritura sustituye el rango gestionado, sin clear() previo.
        hoja = self._hoja(nombre)
        if nombre not in self._tamano_derivadas:
            self._tamano_derivadas[nombre] = len(hoja.get_all_values())
            self._llamadas += 1
        anterior = self._tamano_derivadas[nombre]
        valores = datos + [[''] * len(datos[0]) for _ in range(max(0, anterior - len(datos)))]
        hoja.update(range_name='A1', values=valores, value_input_option='RAW')
        self._llamadas += 1
        self._tamano_derivadas[nombre] = len(datos)

    def _refrescar_derivadas_sync(self):
        with self._derivadas_lock:
            with self._lock:
                datos = self._leer_gastos(forzar=True)
                version = self._version
            # Las escrituras derivadas no retienen el bloqueo del guardado.
            self._refrescar_resumen(datos)
            self._refrescar_proyeccion(datos)
            self._version_actualizada = version

    async def mantener_derivadas(self):
        while True:
            await asyncio.sleep(2)
            if self._version_actualizada != self._version:
                try:
                    await asyncio.to_thread(self._refrescar_derivadas_sync)
                except Exception:
                    registro_errores.exception("No se actualizaron los agregados; se reintentará")
                    await asyncio.sleep(10)

    def _conectar_google_sync(self):
        """Función bloqueante que conecta con Google Sheets."""
        try:
            creds_en_texto = os.getenv('GOOGLE_CREDENTIALS_JSON')

            if creds_en_texto:
                creds_diccionario = json.loads(creds_en_texto)
                self.credenciales = Credentials.from_service_account_info(
                    creds_diccionario,
                    scopes=PERMISOS_API
                )
            else:
                self.credenciales = Credentials.from_service_account_file(
                    'credentials.json',
                    scopes=PERMISOS_API
                )

            self.cliente_api = gspread.authorize(self.credenciales)

            id_planilla = os.getenv('SPREADSHEET_ID')
            if id_planilla:
                self.planillita = self.cliente_api.open_by_key(id_planilla)
            else:
                self.planillita = self.cliente_api.open('Gastos Hormiga')

            self._armar_hojas_si_no_existen()
            hoja = self._hoja('Gastos')
            encabezado = hoja.row_values(1)
            esperado = ['Fecha', 'Usuario', 'Categoría', 'Descripción', 'Monto',
                        'Cuotas', 'Cuota Actual', 'Monto Cuota', 'Mes Impacto']
            if encabezado[:9] != esperado or (len(encabezado) > 9 and encabezado[9] != 'ID'):
                raise ValueError("Columnas de Gastos incompatibles; no se modificaron registros")
            if len(encabezado) == 9:
                if hoja.col_count < 10:
                    hoja.add_cols(10 - hoja.col_count)
                elif any(hoja.col_values(10)):
                    raise ValueError('La columna J contiene datos sin encabezado; no se modificó')
                hoja.update(range_name='J1', values=[['ID']], value_input_option='RAW')
            return True

        except Exception as e:
            registro_errores.error(f"Se rompió la conexión a Google: {e}")
            return False

    async def iniciar_conexion(self):
        return await asyncio.to_thread(self._conectar_google_sync)

    def _armar_hojas_si_no_existen(self):
        """Revisa las pestañas necesarias."""
        nombres_hojas_actuales = [pestaña.title for pestaña in self.planillita.worksheets()]

        if 'Gastos' not in nombres_hojas_actuales:
            hoja_gastos = self.planillita.add_worksheet(title='Gastos', rows=1000, cols=10)
            hoja_gastos.append_row([
                'Fecha',
                'Usuario',
                'Categoría',
                'Descripción',
                'Monto',
                'Cuotas',
                'Cuota Actual',
                'Monto Cuota',
                'Mes Impacto',
                'ID'
            ])

        if 'Resumen Mensual' not in nombres_hojas_actuales:
            hoja_resumen = self.planillita.add_worksheet(title='Resumen Mensual', rows=100, cols=6)
            hoja_resumen.append_row([
                'Mes',
                'Total Gastos',
                'Contado',
                'Cuotas',
                'Categorías',
                'Detalle'
            ])

        if 'Proyección' not in nombres_hojas_actuales:
            hoja_futuro = self.planillita.add_worksheet(title='Proyección', rows=100, cols=5)
            hoja_futuro.append_row([
                'Mes',
                'Cuotas Pendientes',
                'Monto Estimado',
                'Nuevos Gastos',
                'Total Proyectado'
            ])

    def _anotar_gasto_sync(self, nombre_user, categoria_gasto, detalle, plata, gasto_id=None):
        inicio = time.monotonic()
        llamadas = self._llamadas
        gasto_id = gasto_id or str(uuid4())
        try:
            if not categoria_gasto.strip() or not detalle.strip():
                raise ValueError("Categoría y detalle obligatorios")
            plata = parsear_monto(str(plata))
            with self._lock:
                if gasto_id in self._guardados:
                    return True
                hoja = self._hoja('Gastos')
                if gasto_id in self._inciertos:
                    # Un timeout puede ocurrir después de guardar: consultar antes de repetir.
                    registros = self._leer_gastos(forzar=True)
                    if any(str(g.get('ID', '')) == gasto_id for g in registros):
                        self._guardados.add(gasto_id)
                        self._inciertos.discard(gasto_id)
                        self._version += 1
                        return True
                ahora = datetime.now(ZONA_HORARIA)
                fila = [ahora.strftime('%Y-%m-%d %H:%M:%S'), nombre_user,
                        categoria_gasto, detalle, plata, 1, 1, plata,
                        ahora.strftime('%Y-%m'), gasto_id]
                self._inciertos.add(gasto_id)
                self._llamadas += 1
                hoja.append_row(fila, value_input_option='RAW', table_range='A:J')
                self._guardados.add(gasto_id)
                self._inciertos.discard(gasto_id)
                self._cache = None
                self._version += 1
                return True
        except Exception:
            registro_errores.exception("Fallo al guardar el gasto")
            return False
        finally:
            registro_errores.info("Guardado: %.3fs, %d llamadas Sheets",
                                 time.monotonic() - inicio, self._llamadas - llamadas)

    async def anotar_gasto_async(self, nombre_user, categoria_gasto, detalle, plata, gasto_id=None):
        return await asyncio.to_thread(self._anotar_gasto_sync, nombre_user,
                                       categoria_gasto, detalle, plata, gasto_id)

    def _refrescar_resumen(self, todos_los_gastos=None):
        """Recalcula el resumen mensual de la hoja Resumen Mensual."""
        try:
            todos_los_gastos = self._leer_gastos() if todos_los_gastos is None else todos_los_gastos
            datos_por_mes = {}

            for item in todos_los_gastos:
                mes = str(item.get('Mes Impacto', '')).strip()
                if not mes:
                    continue

                if mes not in datos_por_mes:
                    datos_por_mes[mes] = {
                        'total': 0,
                        'contado': 0,
                        'cuotas': 0,
                        'categorias': {}
                    }

                plata = float(item.get('Monto Cuota') or 0)
                datos_por_mes[mes]['total'] += plata

                if int(item.get('Cuotas') or 1) == 1:
                    datos_por_mes[mes]['contado'] += plata
                else:
                    datos_por_mes[mes]['cuotas'] += plata

                rubro = item.get('Categoría', 'Sin Categoría')
                if rubro not in datos_por_mes[mes]['categorias']:
                    datos_por_mes[mes]['categorias'][rubro] = 0

                datos_por_mes[mes]['categorias'][rubro] += plata

            nuevos_datos = [[
                'Mes',
                'Total Gastos',
                'Contado',
                'Cuotas',
                'Categorías Top',
                'Detalle'
            ]]

            for mes in sorted(datos_por_mes.keys(), reverse=True):
                info = datos_por_mes[mes]
                top_3_rubros = sorted(
                    info['categorias'].items(),
                    key=lambda x: x[1],
                    reverse=True
                )[:3]

                texto_top_rubros = ', '.join([
                    f"{r}: ${p:.2f}" for r, p in top_3_rubros
                ])

                nuevos_datos.append([
                    mes,
                    round(info['total'], 2),
                    round(info['contado'], 2),
                    round(info['cuotas'], 2),
                    texto_top_rubros,
                    f"{len(info['categorias'])} categorías"
                ])

            self._actualizar_derivada('Resumen Mensual', nuevos_datos)

        except Exception as e:
            registro_errores.error(f"Fallo actualizando el resumen: {e}")
            raise

    def _refrescar_proyeccion(self, todos_los_gastos=None):
        """
        Mantengo la proyección para no romper el bot.
        Como ahora todos los gastos son en 1 cuota, las cuotas pendientes van a tender a 0.
        """
        try:
            todos_los_gastos = self._leer_gastos() if todos_los_gastos is None else todos_los_gastos
            futuro = {}
            ahora = datetime.now(ZONA_HORARIA)

            for i in range(12):
                mes_futuro = (ahora + relativedelta(months=i)).strftime('%Y-%m')
                futuro[mes_futuro] = {
                    'cuotas_pendientes': 0,
                    'monto_cuotas': 0
                }

            for item in todos_los_gastos:
                mes = str(item.get('Mes Impacto', '')).strip()

                if mes in futuro:
                    plata = float(item.get('Monto Cuota') or 0)
                    cuotas = int(item.get('Cuotas') or 1)

                    if cuotas > 1:
                        futuro[mes]['cuotas_pendientes'] += 1
                        futuro[mes]['monto_cuotas'] += plata

            gastos_pasados = []

            for i in range(1, 4):
                mes_anterior = (ahora - relativedelta(months=i)).strftime('%Y-%m')
                gastos_filtrados = [
                    g for g in todos_los_gastos
                    if g.get('Mes Impacto') == mes_anterior
                    and int(g.get('Cuota Actual') or 1) == 1
                ]

                suma_mes = sum([
                    float(g.get('Monto Cuota') or 0)
                    for g in gastos_filtrados
                ])

                gastos_pasados.append(suma_mes)

            promedio_efectivo = sum(gastos_pasados) / len(gastos_pasados) if gastos_pasados else 0

            nuevos_datos = [[
                'Mes',
                'Cuotas Pendientes',
                'Monto Cuotas',
                'Promedio Nuevos',
                'Total Proyectado'
            ]]

            for mes in sorted(futuro.keys()):
                info = futuro[mes]
                estimado_final = info['monto_cuotas'] + promedio_efectivo

                nuevos_datos.append([
                    mes,
                    info['cuotas_pendientes'],
                    round(info['monto_cuotas'], 2),
                    round(promedio_efectivo, 2),
                    round(estimado_final, 2)
                ])

            self._actualizar_derivada('Proyección', nuevos_datos)

        except Exception as e:
            registro_errores.error(f"Fallo calculando el futuro: {e}")
            raise

    @staticmethod
    def _mes_valido(texto):
        return bool(re.fullmatch(r"[0-9]{4}-(?:0[1-9]|1[0-2])", texto)) and int(texto[:4]) > 0

    def _normalizar_mes_para_resumen(self, mes_solicitado, todos_los_gastos):
        """
        Acepta:
        - este
        - anterior
        - pasado
        - YYYY-MM
        - MM/YYYY
        - todos / todas (devuelve 'ALL')
        - rango en formato YYYY-MM:YYYY-MM (devuelve ('RANGE', desde, hasta))
        """
        ahora = datetime.now(ZONA_HORARIA)
        texto = normalizar_texto(mes_solicitado)

        # Soporte para "todos" los registros
        if texto in ("", "todos", "todas", "todo", "todos los meses", "all"):
            return 'ALL'

        if texto in ("este", "este mes", "mes actual"):
            return ahora.strftime('%Y-%m')

        if texto in ("anterior", "pasado", "mes pasado", "mes anterior"):
            return (ahora - relativedelta(months=1)).strftime('%Y-%m')

        # Rango simple YYYY-MM:YYYY-MM o YYYY-MM..YYYY-MM
        rango_coinc = re.match(r'^(\d{4}-\d{2})\s*[:.]{1,2}\s*(\d{4}-\d{2})$', texto)
        if rango_coinc:
            inicio = rango_coinc.group(1)
            fin = rango_coinc.group(2)
            # Validar que inicio <= fin
            if self._mes_valido(inicio) and self._mes_valido(fin) and inicio <= fin:
                return ('RANGE', inicio, fin)
            else:
                return None

        if self._mes_valido(texto):
            return texto

        coincidencia = re.match(r'^(\d{1,2})/(\d{4})$', texto)
        if coincidencia:
            mes = int(coincidencia.group(1))
            anio = int(coincidencia.group(2))

            if 1 <= mes <= 12 and anio > 0:
                return f"{anio}-{mes:02d}"

        # Soporte para frases del tipo "desde 2026-01 hasta 2026-03"
        desde_hasta = re.match(r'^desde\s+(\d{4}-\d{2})\s+hasta\s+(\d{4}-\d{2})$', texto)
        if desde_hasta:
            inicio = desde_hasta.group(1)
            fin = desde_hasta.group(2)
            if self._mes_valido(inicio) and self._mes_valido(fin) and inicio <= fin:
                return ('RANGE', inicio, fin)

        return None

    def _sacar_resumen_filtrado_sync(self, mes_solicitado=None, categoria_solicitada=None):
        """Devuelve resumen por mes y, opcionalmente, por categoría."""
        try:
            todos_los_gastos = self._leer_gastos()

            mes = self._normalizar_mes_para_resumen(mes_solicitado, todos_los_gastos)

            if not mes:
                return {
                    'ok': False,
                    'error': 'MES_INVALIDO',
                    'mensaje': 'Mes inválido. Usá formato YYYY-MM, por ejemplo 2026-05, o "todos", o un rango YYYY-MM:YYYY-MM.'
                }

            categoria_raw = str(categoria_solicitada or "todas").strip()
            categoria_normalizada = normalizar_texto(categoria_raw)

            filtrar_categoria = categoria_normalizada not in (
                "",
                "todas",
                "todos",
                "todo",
                "sin filtro",
                "general"
            )

            # Soporte para mes == 'ALL' o ranges
            if mes == 'ALL':
                gastos_del_mes = todos_los_gastos
            elif isinstance(mes, tuple) and mes[0] == 'RANGE':
                inicio = mes[1]
                fin = mes[2]
                gastos_del_mes = [
                    g for g in todos_los_gastos
                    if inicio <= str(g.get('Mes Impacto', '')).strip() <= fin
                ]
            else:
                gastos_del_mes = [
                    g for g in todos_los_gastos
                    if str(g.get('Mes Impacto', '')).strip() == mes
                ]

            if filtrar_categoria:
                gastos_filtrados = [
                    g for g in gastos_del_mes
                    if normalizar_texto(g.get('Categoría', '')) == categoria_normalizada
                ]
            else:
                gastos_filtrados = gastos_del_mes

            total = sum([
                float(g.get('Monto Cuota') or 0)
                for g in gastos_filtrados
            ])

            categorias = {}
            detalles = []

            for g in gastos_filtrados:
                rubro = str(g.get('Categoría', 'Sin Categoría')).strip() or 'Sin Categoría'
                plata = float(g.get('Monto Cuota') or 0)

                if rubro not in categorias:
                    categorias[rubro] = 0

                categorias[rubro] += plata

                detalles.append({
                    'fecha': str(g.get('Fecha', '')),
                    'categoria': rubro,
                    'descripcion': str(g.get('Descripción', '')).strip(),
                    'monto': plata
                })

            detalles.reverse()
            detalles.sort(key=lambda x: x['fecha'], reverse=True)

            categorias_disponibles = sorted({
                str(g.get('Categoría', '')).strip()
                for g in gastos_del_mes
                if str(g.get('Categoría', '')).strip()
            })

            # Preparamos la forma en que mostramos el mes al usuario
            if mes == 'ALL':
                mes_display = 'Todos'
            elif isinstance(mes, tuple) and mes[0] == 'RANGE':
                mes_display = f"{mes[1]}..{mes[2]}"
            else:
                mes_display = mes

            return {
                'ok': True,
                'mes': mes_display,
                'categoria': categoria_raw if filtrar_categoria else 'Todas',
                'total': total,
                'cantidad': len(gastos_filtrados),
                'categorias': categorias,
                'detalles': detalles,
                'categorias_disponibles': categorias_disponibles
            }

        except Exception as e:
            registro_errores.error(f"Error sacando resumen filtrado: {e}")
            return {
                'ok': False,
                'error': 'ERROR_GENERAL',
                'mensaje': 'Error leyendo la planilla.'
            }

    async def sacar_resumen_async(self, mes_solicitado=None, categoria_solicitada=None):
        return await asyncio.to_thread(
            self._sacar_resumen_filtrado_sync,
            mes_solicitado,
            categoria_solicitada
        )

    def _sacar_futuro_sync(self):
        try:
            self._refrescar_derivadas_sync()
            return self._hoja('Proyección').get_all_records()
        except Exception as e:
            registro_errores.error(f"Error leyendo la proyección: {e}")
            return None

    async def sacar_futuro_async(self):
        return await asyncio.to_thread(self._sacar_futuro_sync)


# Instancio el bot en memoria
bot_app = BotDeGastos()


# === FUNCIONES DE TELEGRAM ===

@autorizado
async def arrancar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('guardado_incierto'):
        await update.message.reply_text("Conservé un gasto pendiente. Tocá 🔄 Reintentar para verificarlo.",
                                        reply_markup=ReplyKeyboardMarkup([["🔄 Reintentar", "❌ Cancelar"]], resize_keyboard=True))
        return PASO_DETALLE
    await update.message.reply_text(
        f"Hola {update.effective_user.first_name} 👋\n"
        "Anotá un gasto con categoría, monto y detalle.\n\n"
        "Carga rápida: comida 1400 desayuno\n"
        "También podés tocar 💰 Nuevo Gasto.\n"
        "El formato anterior, 5000 Nafta, sigue disponible como Sin clasificar.",
        reply_markup=MENU)
    return ConversationHandler.END


@autorizado
async def tirar_ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 Ayuda\n\n"
        "Carga rápida: categoría monto detalle\n"
        "Ejemplo: camioneta 35000 nafta\n"
        "Formato anterior: 35000 Nafta (Sin clasificar).\n\n"
        "Carga guiada: 💰 Nuevo Gasto. Solo categoría, monto y detalle.\n"
        "Montos: 1500, 1.500, 1.500,50 o 1500.50.\n"
        "Usá ⬅️ Volver para corregir o /cancelar para salir.\n"
        "Si falla el guardado, tocá 🔄 Reintentar.\n\n"
        "Resumen: /resumen este camioneta\n"
        "/resumen anterior comida\n"
        "/resumen todos camioneta\n"
        "/resumen 2026-01:2026-03 camioneta --all\n"
        "Proyección: /proyeccion")


def armar_mensaje_resumen(info, mostrar_todos=False):
    if not info.get('ok'):
        return f"❌ {info.get('mensaje', 'No pude calcular el resumen.')}"

    texto_categorias = ""

    if info['categorias']:
        texto_categorias = "\n".join([
            f"  • {rubro}: ${plata:.2f}"
            for rubro, plata in sorted(
                info['categorias'].items(),
                key=lambda x: x[1],
                reverse=True
            )
        ])
    else:
        texto_categorias = "  Sin movimientos."

    detalles = info.get('detalles', [])

    if mostrar_todos:
        detalles_a_mostrar = detalles
    else:
        detalles_a_mostrar = detalles[:15]

    if detalles_a_mostrar:
        texto_detalles = "\n".join([
            f"  • {d['fecha']} | {d['descripcion']} | ${d['monto']:.2f}"
            for d in detalles_a_mostrar
        ])
    else:
        texto_detalles = "  Sin gastos para ese filtro."

    aviso_limite = ""
    if len(detalles) > 15 and not mostrar_todos:
        aviso_limite = f"\n\nÚltimos 15 de {len(detalles)} movimientos.\nEscribí /resumen {info.get('mes','') } {info.get('categoria','')} --all para verlos todos."

    return (
        f"📊 Resumen de {info['mes']}\n"
        f"🏷 Categoría: {info['categoria']}\n\n"
        f"💰 Total: ${info['total']:.2f}\n"
        f"📝 Movimientos: {info['cantidad']}\n\n"
        f"Por categoría:\n"
        f"{texto_categorias}\n\n"
        f"Últimos movimientos:\n"
        f"{texto_detalles}"
        f"{aviso_limite}"
    )


def _parse_categoria_y_flag(texto_categoria_raw):
    """Devuelve (categoria, mostrar_todos) parseando flags simples en la cadena."""
    if not texto_categoria_raw:
        return texto_categoria_raw, False

    texto = texto_categoria_raw.strip()
    mostrar_todos = False

    # soportar bandera --all
    if texto.endswith('--all') or texto.endswith('--all '):
        mostrar_todos = True
        texto = texto.replace('--all', '').strip()

    # soportar frases en español
    if re.search(r'\bmostrar todo\b', texto.lower()) or re.search(r'\bver todo\b', texto.lower()):
        mostrar_todos = True
        texto = re.sub(r'\bmostrar todo\b', '', texto, flags=re.IGNORECASE).strip()
        texto = re.sub(r'\bver todo\b', '', texto, flags=re.IGNORECASE).strip()

    return texto, mostrar_todos


@autorizado
async def mostrar_resumen_filtrado(update: Update, context: ContextTypes.DEFAULT_TYPE, mes, categoria, mostrar_todos=False):
    await update.message.reply_text("📊 Calculando resumen...")

    info = await bot_app.sacar_resumen_async(
        mes_solicitado=mes,
        categoria_solicitada=categoria
    )

    mensaje = armar_mensaje_resumen(info, mostrar_todos=mostrar_todos)
    bloques = dividir_texto_en_bloques(mensaje, limite=4000)

    for indice, bloque in enumerate(bloques):
        texto_a_enviar = bloque

        if indice > 0:
            texto_a_enviar = f"🔄 Continuación {indice + 1}/{len(bloques)}\n\n{bloque}"

        await update.message.reply_text(texto_a_enviar, reply_markup=MENU)


@autorizado
async def arrancar_resumen_guiado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Permite:
    /resumen 2026-05 camioneta
    /resumen este camioneta
    /resumen anterior comida
    /resumen todos camioneta
    /resumen 2026-01:2026-03 camioneta
    /resumen 2026-05 camioneta --all
    """
    if context.user_data.get('guardado_incierto'):
        await update.message.reply_text("Hay un guardado pendiente. Reintentá o /cancelar antes de cambiar de operación.")
        return PASO_DETALLE
    args = getattr(context, "args", None) or []

    if args:
        # detectar flag --all al final
        mostrar_todos = False
        if '--all' in args:
            mostrar_todos = True
            args = [a for a in args if a != '--all']

        mes = args[0]
        categoria = " ".join(args[1:]) if len(args) > 1 else "todas"
        categoria, flag_categoria = _parse_categoria_y_flag(categoria)
        mostrar_todos = mostrar_todos or flag_categoria

        await mostrar_resumen_filtrado(update, context, mes, categoria, mostrar_todos=mostrar_todos)
        return ConversationHandler.END

    await update.message.reply_text(
        "📅 ¿De qué mes?\n\n"
        "Opciones:\n"
        "• `este`\n"
        "• `anterior`\n"
        "• `2026-05`\n"
        "• `todos` (todas las fechas)\n"
        "• `2026-01:2026-03` (rango)\n\n"
        "Escribí una opción:",
        reply_markup=CONTROLES, parse_mode=None
    )

    return PASO_RESUMEN_MES


@autorizado
async def agarrar_mes_resumen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mes = update.message.text.strip()
    if bot_app._normalizar_mes_para_resumen(mes, []) is None:
        await update.message.reply_text('❌ Mes inválido. Usá este, anterior, todos o YYYY-MM.')
        return PASO_RESUMEN_MES
    context.user_data['resumen_mes'] = mes

    await update.message.reply_text(
        "🏷 ¿De qué categoría?\n\n"
        "Ejemplos:\n"
        "• `camioneta`\n"
        "• `comida`\n"
        "• `salud`\n"
        "• `todas`\n\n"
        "Si querés ver todos los movimientos, escribí, por ejemplo:\n"
        "`camioneta mostrar todo`\n\n"
        "Escribí la categoría:",
        reply_markup=CONTROLES, parse_mode=None
    )

    return PASO_RESUMEN_CATEGORIA


@autorizado
async def agarrar_categoria_resumen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mes = context.user_data.get('resumen_mes', 'este')
    categoria_raw = update.message.text.strip()

    categoria, mostrar_todos = _parse_categoria_y_flag(categoria_raw)

    await mostrar_resumen_filtrado(update, context, mes, categoria, mostrar_todos=mostrar_todos)

    context.user_data.clear()
    return ConversationHandler.END


@autorizado
async def mostrar_futuro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📈 Leyendo proyección...")

    filas = await bot_app.sacar_futuro_async()

    if filas:
        mensaje = "📈 Proyección estimada\n\n"

        for i, fila in enumerate(filas[:6]):
            mes_texto = f"{fila['Mes']} (Este mes)\n" if i == 0 else f"{fila['Mes']}\n"
            mensaje += mes_texto
            mensaje += (
                f"  💳 Tarjeta: ${float(fila.get('Monto Cuotas', 0) or 0):.2f}\n"
                f"  ➕ Estimado extras: ${float(fila.get('Promedio Nuevos', 0) or 0):.2f}\n"
                f"  📊 Vas a necesitar: ${float(fila.get('Total Proyectado', 0) or 0):.2f}\n\n"
            )

        await update.message.reply_text(mensaje, parse_mode=None)

    else:
        await update.message.reply_text("❌ No pude leer la pestaña de Proyección.")


# === MÁQUINA DE ESTADOS PARA CARGA GUIADA ===

@autorizado
async def arrancar_gasto_guiado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('guardado_incierto'):
        await update.message.reply_text("Hay un guardado pendiente. Reintentá o cancelá antes de iniciar otro.")
        return PASO_DETALLE
    for clave in ('categoria_elegida', 'plata_gastada', 'detalle_compra', 'gasto_id', 'guardado_incierto'):
        context.user_data.pop(clave, None)
    context.user_data['gasto_id'] = str(uuid4())
    await update.message.reply_text("🏷 Elegí o escribí la categoría:", reply_markup=CATEGORIAS)
    return PASO_CATEGORIA


@autorizado
async def agarrar_categoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    categoria = update.message.text.strip()
    if not categoria or len(categoria) > 100:
        await update.message.reply_text("❌ Escribí una categoría de 1 a 100 caracteres.")
        return PASO_CATEGORIA
    context.user_data['categoria_elegida'] = categoria.title()
    await update.message.reply_text("💵 ¿Cuánto gastaste? Ejemplo: 1.500,50", reply_markup=CONTROLES)
    return PASO_PLATA


@autorizado
async def agarrar_plata(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data['plata_gastada'] = parsear_monto(update.message.text)
    except ValueError:
        await update.message.reply_text("❌ Ingresá un monto mayor que cero. Ejemplos: 1500 o 1.500,50.")
        return PASO_PLATA
    await update.message.reply_text("📝 Escribí el detalle:", reply_markup=CONTROLES)
    return PASO_DETALLE


@autorizado
async def agarrar_detalle_y_guardar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text != '🔄 Reintentar':
        detalle = update.message.text.strip()
        if not detalle or len(detalle) > 2000:
            await update.message.reply_text("❌ Escribí un detalle de 1 a 2000 caracteres.")
            return PASO_DETALLE
        context.user_data['detalle_compra'] = detalle
    return await guardar_borrador(update, context)


@autorizado
async def guardar_borrador(update, context):
    datos = context.user_data
    if not all(k in datos for k in ('categoria_elegida', 'plata_gastada', 'detalle_compra')):
        await update.message.reply_text("Faltan datos. Tocá 💰 Nuevo Gasto para completar la carga.", reply_markup=MENU)
        return ConversationHandler.END
    datos.setdefault('gasto_id', str(uuid4()))
    if datos.get('guardado_incierto'):
        bot_app._inciertos.add(datos['gasto_id'])
    datos['guardado_incierto'] = True
    # Persistir antes de escribir: un reinicio conserva el borrador y obliga a verificar el ID.
    if context.application.persistence:
        context.application.mark_data_for_update_persistence(user_ids=[update.effective_user.id])
        await context.application.update_persistence()
        await context.application.persistence.flush()
    usuario = update.effective_user
    ok = await bot_app.anotar_gasto_async(
        usuario.username or usuario.first_name, datos['categoria_elegida'],
        datos['detalle_compra'], datos['plata_gastada'], datos['gasto_id'])
    if not ok:
        await update.message.reply_text(
            "❌ Google Sheets no confirmó el guardado. Conservé los datos.\n"
            "Tocá 🔄 Reintentar para verificarlo antes de volver a guardar.",
            reply_markup=ReplyKeyboardMarkup([["🔄 Reintentar", "❌ Cancelar"]], resize_keyboard=True))
        return PASO_DETALLE
    mensaje = f"✅ Anotado: ${datos['plata_gastada']:.2f}\n{datos['categoria_elegida']} | {datos['detalle_compra']}"
    # Limpiar antes de responder: una falla de Telegram no debe permitir otra escritura.
    for clave in ('categoria_elegida', 'plata_gastada', 'detalle_compra', 'gasto_id', 'guardado_incierto'):
        datos.pop(clave, None)
    for bloque in dividir_texto_en_bloques(mensaje, limite=4000):
        await update.message.reply_text(bloque, reply_markup=MENU)
    return ConversationHandler.END


@autorizado
async def tirar_todo_al_tacho(update: Update, context: ContextTypes.DEFAULT_TYPE):
    incierto = context.user_data.get('guardado_incierto', False)
    context.user_data.clear()
    mensaje = "Operación cancelada."
    if incierto:
        mensaje += " El último guardado no fue confirmado; revisá el resumen antes de cargarlo otra vez."
    await update.message.reply_text(mensaje, reply_markup=MENU)
    return ConversationHandler.END


@autorizado
async def volver(update, context):
    datos = context.user_data
    if datos.get('guardado_incierto'):
        await update.message.reply_text("Reintentá el guardado pendiente antes de modificarlo.")
        return PASO_DETALLE
    if 'detalle_compra' in datos or 'plata_gastada' in datos:
        datos.pop('detalle_compra', None)
        datos.pop('plata_gastada', None)
        await update.message.reply_text("💵 Corregí el monto:", reply_markup=CONTROLES)
        return PASO_PLATA
    if 'categoria_elegida' in datos:
        datos.pop('categoria_elegida', None)
        await update.message.reply_text("🏷 Corregí la categoría:", reply_markup=CATEGORIAS)
        return PASO_CATEGORIA
    if 'resumen_mes' in datos:
        datos.pop('resumen_mes', None)
        return await arrancar_resumen_guiado(update, context)
    return await tirar_todo_al_tacho(update, context)


def navegar(funcion):
    @wraps(funcion)
    @autorizado
    async def ejecutar(update, context):
        texto = update.message.text
        if texto == '❌ Cancelar':
            return await tirar_todo_al_tacho(update, context)
        if texto == '⬅️ Volver':
            return await volver(update, context)
        if texto == '🔄 Reintentar':
            return await guardar_borrador(update, context)
        if texto == '💰 Nuevo Gasto':
            return await arrancar_gasto_guiado(update, context)
        if texto in ('📊 Resumen', '📈 Proyección', '❓ Ayuda'):
            # Mostrar información sin abandonar la carga en curso.
            if texto == '❓ Ayuda':
                await tirar_ayuda(update, context)
            elif texto == '📈 Proyección':
                await mostrar_futuro(update, context)
            else:
                await mostrar_resumen_filtrado(update, context, 'este', 'todas')
            await update.message.reply_text("Podés continuar la operación anterior o /cancelar.", reply_markup=CONTROLES)
            return None
        if context.user_data.get('guardado_incierto'):
            await update.message.reply_text("Tocá 🔄 Reintentar o /cancelar; conservé los datos originales.")
            return PASO_DETALLE
        return await funcion(update, context)
    return ejecutar


@autorizado
async def leer_mensaje_al_toque(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()
    if texto == '💰 Nuevo Gasto':
        return await arrancar_gasto_guiado(update, context)
    if texto == '📊 Resumen':
        return await arrancar_resumen_guiado(update, context)
    if texto == '📈 Proyección':
        return await mostrar_futuro(update, context)
    if texto == '❓ Ayuda':
        return await tirar_ayuda(update, context)
    if texto == '🔄 Reintentar':
        return await guardar_borrador(update, context)
    if texto == '❌ Cancelar':
        return await tirar_todo_al_tacho(update, context)
    if context.user_data.get('guardado_incierto'):
        await update.message.reply_text("Hay un guardado pendiente. Tocá 🔄 Reintentar o /cancelar.")
        return PASO_DETALLE
    try:
        # El primer token numérico separa categoría y detalle; admite categorías compuestas.
        con_categoria = re.fullmatch(r'([^|]+?)\s+([0-9][0-9.,]*)\s+(.+)', texto, flags=re.DOTALL)
        primer_token = texto.split(maxsplit=1)[0] if texto else ''
        if re.fullmatch(r'[0-9][0-9.,]*', primer_token):
            monto, detalle = texto.split(maxsplit=1)
            categoria = 'Sin clasificar'
        elif con_categoria:
            categoria, monto, detalle = [parte.strip() for parte in con_categoria.groups()]
        elif '|' in texto:
            # Compatibilidad con gastos escritos en el formato anterior.
            partes = texto.split('|', 2)
            if len(partes) != 3:
                raise ValueError("Faltan campos")
            categoria, monto, detalle = [parte.strip() for parte in partes]
        else:
            raise ValueError("Usá categoría, monto y detalle")
        if not categoria or len(categoria) > 100 or not detalle or len(detalle) > 2000:
            raise ValueError("Categoría o detalle inválidos")
        plata = parsear_monto(monto)
    except ValueError:
        await update.message.reply_text("Usá: comida 1400 desayuno\nO tocá 💰 Nuevo Gasto.", reply_markup=MENU)
        return ConversationHandler.END
    context.user_data.update(categoria_elegida=categoria, plata_gastada=plata,
                             detalle_compra=detalle, gasto_id=f"tg-{update.effective_chat.id}-{update.message.message_id}")
    return await guardar_borrador(update, context)


async def principal_async():
    conectado = await bot_app.iniciar_conexion()

    if not conectado:
        registro_errores.error("No conectó a Sheets. Revisá el JSON o las variables de entorno.")
        return

    estado = os.getenv('BOT_STATE_PATH', str(os.path.join(os.path.dirname(__file__), '.estado-bot.pickle')))
    persistence = PicklePersistence(filepath=estado, update_interval=1)
    app = Application.builder().token(os.getenv('TELEGRAM_BOT_TOKEN')).concurrent_updates(False).persistence(persistence).build()

    charla_guiada = ConversationHandler(
        name="gastos", persistent=True,
        entry_points=[
            MessageHandler(filters.Regex('^💰 Nuevo Gasto$'), arrancar_gasto_guiado),
            MessageHandler(filters.Regex('^📊 Resumen$'), arrancar_resumen_guiado),
            CommandHandler("resumen", arrancar_resumen_guiado),
            CommandHandler("start", arrancar),
            CommandHandler("cancelar", tirar_todo_al_tacho),
            MessageHandler(filters.TEXT & ~filters.COMMAND, leer_mensaje_al_toque),
        ],
        states={
            PASO_CATEGORIA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, navegar(agarrar_categoria))
            ],
            PASO_PLATA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, navegar(agarrar_plata))
            ],
            PASO_DETALLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, navegar(agarrar_detalle_y_guardar))
            ],
            PASO_RESUMEN_MES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, navegar(agarrar_mes_resumen))
            ],
            PASO_RESUMEN_CATEGORIA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, navegar(agarrar_categoria_resumen))
            ],
        },
        fallbacks=[
            CommandHandler('cancelar', tirar_todo_al_tacho),
            CommandHandler('start', arrancar),
            CommandHandler('ayuda', tirar_ayuda),
            CommandHandler('proyeccion', mostrar_futuro),
            CommandHandler('resumen', arrancar_resumen_guiado),
        ],
    )

    app.add_handler(MessageHandler(filters.ALL, verificar_acceso), group=-1)
    app.add_handler(charla_guiada)
    app.add_handler(CommandHandler("ayuda", tirar_ayuda))
    app.add_handler(CommandHandler("proyeccion", mostrar_futuro))

    registro_errores.info("Bot levantado. Escuchando...")

    trabajador = None
    await app.initialize()
    try:
        await app.start()
        trabajador = asyncio.create_task(bot_app.mantener_derivadas())
        await app.updater.start_polling(allowed_updates=["message"])
        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for senal in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(senal, stop_event.set)
        await stop_event.wait()
    finally:
        if app.updater.running:
            await app.updater.stop()
        if app.running:
            await app.stop()
        if trabajador:
            trabajador.cancel()
            try:
                await trabajador
            except asyncio.CancelledError:
                pass
        await app.shutdown()


if __name__ == '__main__':
    asyncio.run(principal_async())
