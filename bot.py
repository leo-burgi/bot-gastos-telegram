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
    """Divide un texto largo en bloques compatibles con Telegram."""
    if not texto:
        return []

    if len(texto) <= limite:
        return [texto]

    bloques = []
    bloque_actual = ""

    for linea in texto.splitlines():
        if not linea:
            if bloque_actual:
                bloques.append(bloque_actual)
                bloque_actual = ""
            continue

        if not bloque_actual:
            bloque_actual = linea
            continue

        if len(bloque_actual) + 1 + len(linea) <= limite:
            bloque_actual = f"{bloque_actual}\n{linea}"
        else:
            bloques.append(bloque_actual)
            bloque_actual = linea

    if bloque_actual:
        bloques.append(bloque_actual)

    mensajes = []
    for bloque in bloques:
        if len(bloque) <= limite:
            mensajes.append(bloque)
            continue

        partes = []
        parte_actual = ""

        for palabra in bloque.split(" "):
            if not palabra:
                continue

            if not parte_actual:
                parte_actual = palabra
            elif len(parte_actual) + 1 + len(palabra) <= limite:
                parte_actual = f"{parte_actual} {palabra}"
            else:
                partes.append(parte_actual)
                parte_actual = palabra

        if parte_actual:
            partes.append(parte_actual)

        mensajes.extend(partes)

    return mensajes


class BotDeGastos:
    def __init__(self):
        self.credenciales = None
        self.cliente_api = None
        self.planillita = None
        self.gente_permitida = os.getenv('USUARIOS_AUTORIZADOS', '').split(',')

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

    def _anotar_gasto_sync(self, nombre_user, categoria_gasto, detalle, plata):
        """
        Guarda un gasto siempre en 1 cuota.
        Se mantienen las columnas de cuotas para compatibilidad con la planilla existente.
        """
        try:
            pestaña_gastos = self.planillita.worksheet('Gastos')

            ahora = datetime.now(ZONA_HORARIA)
            fecha_texto = ahora.strftime('%Y-%m-%d %H:%M:%S')
            mes_impacto = ahora.strftime('%Y-%m')

            fila = [
                fecha_texto,
                nombre_user,
                categoria_gasto,
                detalle,
                plata,
                1,
                1,
                plata,
                mes_impacto,
                ''
            ]

            pestaña_gastos.append_row(fila)

            self._refrescar_resumen()
            self._refrescar_proyeccion()

            return True

        except Exception as e:
            registro_errores.error(f"Fallo al querer guardar el gasto: {e}")
            return False

    async def anotar_gasto_async(self, nombre_user, categoria_gasto, detalle, plata):
        return await asyncio.to_thread(
            self._anotar_gasto_sync,
            nombre_user,
            categoria_gasto,
            detalle,
            plata
        )

    def _refrescar_resumen(self):
        """Recalcula el resumen mensual de la hoja Resumen Mensual."""
        try:
            pestaña_gastos = self.planillita.worksheet('Gastos')
            pestaña_resumen = self.planillita.worksheet('Resumen Mensual')

            todos_los_gastos = pestaña_gastos.get_all_records()
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

            pestaña_resumen.clear()
            pestaña_resumen.update(range_name='A1', values=nuevos_datos)

        except Exception as e:
            registro_errores.error(f"Fallo actualizando el resumen: {e}")

    def _refrescar_proyeccion(self):
        """
        Mantengo la proyección para no romper el bot.
        Como ahora todos los gastos son en 1 cuota, las cuotas pendientes van a tender a 0.
        """
        try:
            pestaña_gastos = self.planillita.worksheet('Gastos')
            pestaña_futuro = self.planillita.worksheet('Proyección')

            todos_los_gastos = pestaña_gastos.get_all_records()
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

            pestaña_futuro.clear()
            pestaña_futuro.update(range_name='A1', values=nuevos_datos)

        except Exception as e:
            registro_errores.error(f"Fallo calculando el futuro: {e}")

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
            if inicio <= fin:
                return ('RANGE', inicio, fin)
            else:
                return None

        if re.match(r'^\d{4}-\d{2}$', texto):
            return texto

        coincidencia = re.match(r'^(\d{1,2})/(\d{4})$', texto)
        if coincidencia:
            mes = int(coincidencia.group(1))
            anio = int(coincidencia.group(2))

            if 1 <= mes <= 12:
                return f"{anio}-{mes:02d}"

        # Soporte para frases del tipo "desde 2026-01 hasta 2026-03"
        desde_hasta = re.match(r'^desde\s+(\d{4}-\d{2})\s+hasta\s+(\d{4}-\d{2})$', texto)
        if desde_hasta:
            inicio = desde_hasta.group(1)
            fin = desde_hasta.group(2)
            if inicio <= fin:
                return ('RANGE', inicio, fin)

        return None

    def _sacar_resumen_filtrado_sync(self, mes_solicitado=None, categoria_solicitada=None):
        """Devuelve resumen por mes y, opcionalmente, por categoría."""
        try:
            pestaña_gastos = self.planillita.worksheet('Gastos')
            todos_los_gastos = pestaña_gastos.get_all_records()

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
                    'fecha': str(g.get('Fecha', ''))[:10],
                    'categoria': rubro,
                    'descripcion': str(g.get('Descripción', '')).strip(),
                    'monto': plata
                })

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
            return self.planillita.worksheet('Proyección').get_all_records()
        except Exception as e:
            registro_errores.error(f"Error leyendo la proyección: {e}")
            return None

    async def sacar_futuro_async(self):
        return await asyncio.to_thread(self._sacar_futuro_sync)


# Instancio el bot en memoria
bot_app = BotDeGastos()


# === FUNCIONES DE TELEGRAM ===

async def arrancar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    usuario = update.effective_user
    nombre_pantalla = usuario.username or usuario.first_name

    if str(usuario.id) not in bot_app.gente_permitida and len(bot_app.gente_permitida) > 0:
        await update.message.reply_text(f"❌ Acceso denegado. Tu ID es: {usuario.id}")
        return ConversationHandler.END

    botonera = [
        [KeyboardButton("💰 Nuevo Gasto"), KeyboardButton("📊 Resumen")],
        [KeyboardButton("📈 Proyección"), KeyboardButton("❓ Ayuda")]
    ]

    teclado_visual = ReplyKeyboardMarkup(botonera, resize_keyboard=True)

    await update.message.reply_text(
        f"¡Qué onda {nombre_pantalla}! 👋\n\n"
        "Manejo tus gastos al toque.\n\n"
        "Carga rápida:\n"
        "💵 <monto> <descripción>\n\n"
        "Ejemplo:\n"
        "5000 Nafta camioneta\n\n"
        "Para cargar con categoría, tocá:\n"
        "💰 Nuevo Gasto",
        reply_markup=teclado_visual
    )


async def tirar_ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Ayuda*\n\n"
        "*Carga rápida:*\n"
        "`<monto> <descripción>`\n\n"
        "Ejemplo:\n"
        "`35000 Remera`\n\n"
        "*Carga con categoría:*\n"
        "Tocá `💰 Nuevo Gasto` y seguí los pasos.\n\n"
        "*Resumen filtrado:*\n"
        "Tocá `📊 Resumen` o usá:\n"
        "`/resumen 2026-05 camioneta`\n\n"
        "También podés usar:\n"
        "`/resumen este camioneta`\n"
        "`/resumen anterior comida`\n\n"
        "Ahora también podés usar:\n"
        "`/resumen todos camioneta`  (todos los registros de la categoría)\n"
        "`/resumen 2026-01:2026-03 camioneta`  (rango de meses)\n"
        "Si querés ver todos los movimientos cuando hay más de 15, podés añadir `--all` al final:\n"
        "`/resumen 2026-05 camioneta --all`\n\n"
        "Nota: todos los gastos se guardan automáticamente en 1 cuota.",
        parse_mode='Markdown'
    )


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
        aviso_limite = f"\n\n_Mostré los últimos 15 de {len(detalles)} movimientos._\nEscribí `/resumen {info.get('mes','') } {info.get('categoria','')} --all` para verlos todos."

    return (
        f"📊 *Resumen de {info['mes']}*\n"
        f"🏷 Categoría: *{info['categoria']}*\n\n"
        f"💰 Total: *${info['total']:.2f}*\n"
        f"📝 Movimientos: *{info['cantidad']}*\n\n"
        f"*Por categoría:*\n"
        f"{texto_categorias}\n\n"
        f"*Últimos movimientos:*\n"
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


async def mostrar_resumen_filtrado(update: Update, context: ContextTypes.DEFAULT_TYPE, mes, categoria, mostrar_todos=False):
    await update.message.reply_text("📊 Calculando resumen...")

    info = await bot_app.sacar_resumen_async(
        mes_solicitado=mes,
        categoria_solicitada=categoria
    )

    mensaje = armar_mensaje_resumen(info, mostrar_todos=mostrar_todos)
    bloques = dividir_texto_en_bloques(mensaje)

    for indice, bloque in enumerate(bloques):
        texto_a_enviar = bloque

        if indice > 0:
            texto_a_enviar = f"🔄 Continuación {indice + 1}/{len(bloques)}\n\n{bloque}"

        await update.message.reply_text(texto_a_enviar, parse_mode='Markdown')


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
        "📅 ¿Qué mes querés ver?\n\n"
        "Opciones:\n"
        "• `este`\n"
        "• `anterior`\n"
        "• `2026-05`\n"
        "• `todos` (todas las fechas)\n"
        "• `2026-01:2026-03` (rango)\n\n"
        "Escribí una opción:",
        parse_mode='Markdown'
    )

    return PASO_RESUMEN_MES


async def agarrar_mes_resumen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['resumen_mes'] = update.message.text.strip()

    await update.message.reply_text(
        "🏷 ¿Qué categoría querés ver?\n\n"
        "Ejemplos:\n"
        "• `camioneta`\n"
        "• `comida`\n"
        "• `salud`\n"
        "• `todas`\n\n"
        "Si querés ver todos los movimientos cuando hay más de 15, escribí por ejemplo:\n"
        "`camioneta --all` o `camioneta mostrar todo`\n\n"
        "Escribí la categoría:",
        parse_mode='Markdown'
    )

    return PASO_RESUMEN_CATEGORIA


async def agarrar_categoria_resumen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mes = context.user_data.get('resumen_mes', 'este')
    categoria_raw = update.message.text.strip()

    categoria, mostrar_todos = _parse_categoria_y_flag(categoria_raw)

    await mostrar_resumen_filtrado(update, context, mes, categoria, mostrar_todos=mostrar_todos)

    context.user_data.clear()
    return ConversationHandler.END


async def mostrar_futuro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📈 Leyendo proyección...")

    filas = await bot_app.sacar_futuro_async()

    if filas:
        mensaje = "📈 *Lo que se te viene*\n\n"

        for i, fila in enumerate(filas[:6]):
            mes_texto = f"*{fila['Mes']}* (Este mes)\n" if i == 0 else f"*{fila['Mes']}*\n"
            mensaje += mes_texto
            mensaje += (
                f"  💳 Tarjeta: ${float(fila.get('Monto Cuotas', 0) or 0):.2f}\n"
                f"  ➕ Estimado extras: ${float(fila.get('Promedio Nuevos', 0) or 0):.2f}\n"
                f"  📊 Vas a necesitar: ${float(fila.get('Total Proyectado', 0) or 0):.2f}\n\n"
            )

        await update.message.reply_text(mensaje, parse_mode='Markdown')

    else:
        await update.message.reply_text("❌ No pude leer la pestaña de Proyección.")


# === MÁQUINA DE ESTADOS PARA CARGA GUIADA ===

async def arrancar_gasto_guiado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💰 ¿En qué categoría entra este gasto?\n\n"
        "Ejemplos: Comida, Salud, Camioneta, Casa, Trabajo."
    )
    return PASO_CATEGORIA


async def agarrar_categoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['categoria_elegida'] = update.message.text.strip().title()

    await update.message.reply_text("💵 ¿Cuánta plata gastaste? Solo números:")
    return PASO_PLATA


async def agarrar_plata(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        plata = float(update.message.text.strip().replace(',', '.'))
        context.user_data['plata_gastada'] = plata

        await update.message.reply_text("📝 ¿Qué compraste o qué gasto fue?")
        return PASO_DETALLE

    except ValueError:
        await update.message.reply_text("❌ Pasame un número válido. Sin letras.")
        return PASO_PLATA


async def agarrar_detalle_y_guardar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['detalle_compra'] = update.message.text.strip()

    usuario = update.effective_user
    nombre_pantalla = usuario.username or usuario.first_name

    required_keys = (
        "categoria_elegida",
        "detalle_compra",
        "plata_gastada"
    )

    if not all(k in context.user_data for k in required_keys):
        await update.message.reply_text("❌ Me faltan datos del gasto. Volvé a cargarlo desde el inicio.")
        context.user_data.clear()
        return ConversationHandler.END

    todo_ok = await bot_app.anotar_gasto_async(
        nombre_user=nombre_pantalla,
        categoria_gasto=context.user_data["categoria_elegida"],
        detalle=context.user_data["detalle_compra"],
        plata=context.user_data["plata_gastada"]
    )

    if todo_ok:
        plata = context.user_data["plata_gastada"]
        categoria = context.user_data["categoria_elegida"]
        detalle = context.user_data["detalle_compra"]

        mensaje = (
            f"🐜 *Anotado: ${plata:.2f}*\n"
            f"{categoria} | {detalle}\n"
            f"1 cuota"
        )
    else:
        mensaje = "❌ Error guardando en Google Sheets."

    await update.message.reply_text(mensaje, parse_mode="Markdown")

    context.user_data.clear()
    return ConversationHandler.END


async def tirar_todo_al_tacho(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Operación cancelada.")
    return ConversationHandler.END


# === LECTURA DE TEXTO LIBRE ===

async def leer_mensaje_al_toque(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()

    if texto == "💰 Nuevo Gasto":
        return await arrancar_gasto_guiado(update, context)

    if texto == "📊 Resumen":
        return await arrancar_resumen_guiado(update, context)

    if texto == "📈 Proyección":
        return await mostrar_futuro(update, context)

    if texto == "❓ Ayuda":
        return await tirar_ayuda(update, context)

    patron_gasto_rapido = r'^\s*(\d+(?:[.,]\d+)?)\s+(.+?)\s*$'
    coincidencia = re.match(patron_gasto_rapido, texto)

    if coincidencia:
        try:
            plata = float(coincidencia.group(1).replace(',', '.'))
            descripcion = coincidencia.group(2).strip()

            usuario = update.effective_user
            nombre_pantalla = usuario.username or usuario.first_name

            todo_ok = await bot_app.anotar_gasto_async(
                nombre_user=nombre_pantalla,
                categoria_gasto='Sin clasificar',
                detalle=descripcion,
                plata=plata
            )

            if todo_ok:
                await update.message.reply_text(
                    f"✅ *Anotado al toque*\n"
                    f"💵 ${plata:.2f} en {descripcion}\n"
                    f"🏷 Categoría: Sin clasificar\n"
                    f"1 cuota",
                    parse_mode='Markdown'
                )
            else:
                await update.message.reply_text("❌ Error al guardar.")

        except Exception as e:
            registro_errores.error(f"Error procesando mensaje rápido: {e}")
            await update.message.reply_text("❌ Usá: <plata> <qué es>")

    else:
        await update.message.reply_text(
            "No entendí el mensaje.\n\n"
            "Para carga rápida usá:\n"
            "`5000 Nafta camioneta`\n\n"
            "O tocá `💰 Nuevo Gasto`.",
            parse_mode='Markdown'
        )


async def principal_async():
    conectado = await bot_app.iniciar_conexion()

    if not conectado:
        registro_errores.error("No conectó a Sheets. Revisá el JSON o las variables de entorno.")
        return

    app = Application.builder().token(os.getenv('TELEGRAM_BOT_TOKEN')).build()

    charla_guiada = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex('^💰 Nuevo Gasto$'), arrancar_gasto_guiado),
            MessageHandler(filters.Regex('^📊 Resumen$'), arrancar_resumen_guiado),
            CommandHandler("resumen", arrancar_resumen_guiado),
        ],
        states={
            PASO_CATEGORIA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, agarrar_categoria)
            ],
            PASO_PLATA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, agarrar_plata)
            ],
            PASO_DETALLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, agarrar_detalle_y_guardar)
            ],
            PASO_RESUMEN_MES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, agarrar_mes_resumen)
            ],
            PASO_RESUMEN_CATEGORIA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, agarrar_categoria_resumen)
            ],
        },
        fallbacks=[
            CommandHandler('cancelar', tirar_todo_al_tacho)
        ],
    )

    app.add_handler(CommandHandler("start", arrancar))
    app.add_handler(CommandHandler("ayuda", tirar_ayuda))
    app.add_handler(CommandHandler("proyeccion", mostrar_futuro))
    app.add_handler(charla_guiada)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, leer_mensaje_al_toque))

    registro_errores.info("Bot levantado. Escuchando...")

    await app.initialize()
    await app.start()
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)

    stop_event = asyncio.Event()
    await stop_event.wait()


if __name__ == '__main__':
    asyncio.run(principal_async())
