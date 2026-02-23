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

# Configuración de logging para ver errores en consola
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
registro_errores = logging.getLogger(__name__)

# Estados para la máquina de conversación
PASO_CATEGORIA, PASO_PLATA, PASO_DETALLE, PASO_CUOTAS = range(4)

# Permisos de Google
PERMISOS_API = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']

# PASO 1: FIJAR LA ZONA HORARIA
ZONA_HORARIA = ZoneInfo("America/Argentina/Buenos_Aires")

class BotDeGastos:
    def __init__(self):
        self.credenciales = None
        self.cliente_api = None
        self.planillita = None
        self.gente_permitida = os.getenv('USUARIOS_AUTORIZADOS', '').split(',')
        
    def _conectar_google_sync(self):
        """Función bloqueante (sincrónica) que hace el trabajo sucio de conectar."""
        try:
            creds_en_texto = os.getenv('GOOGLE_CREDENTIALS_JSON')
            if creds_en_texto:
                creds_diccionario = json.loads(creds_en_texto)
                self.credenciales = Credentials.from_service_account_info(creds_diccionario, scopes=PERMISOS_API)
            else:
                self.credenciales = Credentials.from_service_account_file('credentials.json', scopes=PERMISOS_API)
            
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
        """PASO 2: Envuelve la conexión en un hilo separado para no bloquear el bot."""
        return await asyncio.to_thread(self._conectar_google_sync)
    
    def _armar_hojas_si_no_existen(self):
        """Revisa las pestañas. Se ejecuta dentro del hilo secundario."""
        nombres_hojas_actuales = [pestaña.title for pestaña in self.planillita.worksheets()]
        
        if 'Gastos' not in nombres_hojas_actuales:
            hoja_gastos = self.planillita.add_worksheet(title='Gastos', rows=1000, cols=10)
            hoja_gastos.append_row(['Fecha', 'Usuario', 'Categoría', 'Descripción', 'Monto', 
                                  'Cuotas', 'Cuota Actual', 'Monto Cuota', 'Mes Impacto', 'ID'])
        
        if 'Resumen Mensual' not in nombres_hojas_actuales:
            hoja_resumen = self.planillita.add_worksheet(title='Resumen Mensual', rows=100, cols=6)
            hoja_resumen.append_row(['Mes', 'Total Gastos', 'Contado', 'Cuotas', 'Categorías', 'Detalle'])
            
        if 'Proyección' not in nombres_hojas_actuales:
            hoja_futuro = self.planillita.add_worksheet(title='Proyección', rows=100, cols=5)
            hoja_futuro.append_row(['Mes', 'Cuotas Pendientes', 'Monto Estimado', 'Nuevos Gastos', 'Total Proyectado'])

    def _anotar_gasto_sync(self, nombre_user, categoria_gasto, detalle, plata, cant_cuotas):
        """PASO 3: Lógica sincrónica mejorada con inserción en lotes (batching)"""
        try:
            pestaña_gastos = self.planillita.worksheet('Gastos')
            # Usamos nuestra zona horaria para que no haya desfasajes
            ahora = datetime.now(ZONA_HORARIA)
            fecha_texto = ahora.strftime('%Y-%m-%d %H:%M:%S')
            
            filas_a_insertar = []
            
            if cant_cuotas == 1:
                mes_del_tarjetazo = ahora.strftime('%Y-%m')
                fila = [fecha_texto, nombre_user, categoria_gasto, detalle, plata, 1, 1, plata, mes_del_tarjetazo, '']
                filas_a_insertar.append(fila)
            else:
                plata_por_mes = round(plata / cant_cuotas, 2)
                for numero_cuota in range(cant_cuotas):
                    mes_del_tarjetazo = (ahora + relativedelta(months=numero_cuota)).strftime('%Y-%m')
                    id_casero = f"{fecha_texto}_{detalle}"
                    fila = [fecha_texto, nombre_user, categoria_gasto, detalle, plata, 
                           cant_cuotas, numero_cuota+1, plata_por_mes, mes_del_tarjetazo, id_casero]
                    filas_a_insertar.append(fila)
            
            # ¡Magia! Guardamos las 12 cuotas en UNA sola llamada a la API
            pestaña_gastos.append_rows(filas_a_insertar)
            
            # Refrescamos tablas
            self._refrescar_resumen()
            self._refrescar_proyeccion()
            return True
        except Exception as e:
            registro_errores.error(f"Fallo al querer guardar el gasto: {e}")
            return False

    async def anotar_gasto_async(self, nombre_user, categoria_gasto, detalle, plata, cant_cuotas=1):
        """Llama al guardado de Google en un hilo separado"""
        return await asyncio.to_thread(self._anotar_gasto_sync, nombre_user, categoria_gasto, detalle, plata, cant_cuotas)
    
    def _refrescar_resumen(self):
        """Recalcula el resumen. Optimizado para hacer solo 2 llamadas a la API."""
        try:
            pestaña_gastos = self.planillita.worksheet('Gastos')
            pestaña_resumen = self.planillita.worksheet('Resumen Mensual')
            
            todos_los_gastos = pestaña_gastos.get_all_records()
            datos_por_mes = {}
            
            for item in todos_los_gastos:
                mes = str(item.get('Mes Impacto', ''))
                if not mes: continue # Previene errores si hay filas vacías
                
                if mes not in datos_por_mes:
                    datos_por_mes[mes] = {'total': 0, 'contado': 0, 'cuotas': 0, 'categorias': {}}
                
                plata = float(item.get('Monto Cuota') or 0)
                datos_por_mes[mes]['total'] += plata
                
                if item.get('Cuotas') == 1:
                    datos_por_mes[mes]['contado'] += plata
                else:
                    datos_por_mes[mes]['cuotas'] += plata
                
                rubro = item.get('Categoría', 'Sin Categoría')
                if rubro not in datos_por_mes[mes]['categorias']:
                    datos_por_mes[mes]['categorias'][rubro] = 0
                datos_por_mes[mes]['categorias'][rubro] += plata
            
            # Armamos una matriz con los nuevos datos
            nuevos_datos = [['Mes', 'Total Gastos', 'Contado', 'Cuotas', 'Categorías Top', 'Detalle']]
            
            for mes in sorted(datos_por_mes.keys(), reverse=True):
                info = datos_por_mes[mes]
                top_3_rubros = sorted(info['categorias'].items(), key=lambda x: x[1], reverse=True)[:3]
                texto_top_rubros = ', '.join([f"{r}: ${p:.2f}" for r, p in top_3_rubros])
                
                nuevos_datos.append([
                    mes,
                    round(info['total'], 2),
                    round(info['contado'], 2),
                    round(info['cuotas'], 2),
                    texto_top_rubros,
                    f"{len(info['categorias'])} categorías"
                ])
            
            # Borramos y actualizamos de una sola vez
            pestaña_resumen.clear()
            pestaña_resumen.update(range_name='A1', values=nuevos_datos)
            
        except Exception as e:
            registro_errores.error(f"Fallo actualizando el resumen: {e}")
    
    def _refrescar_proyeccion(self):
        """Igual optimización de API que el resumen."""
        try:
            pestaña_gastos = self.planillita.worksheet('Gastos')
            pestaña_futuro = self.planillita.worksheet('Proyección')
            
            todos_los_gastos = pestaña_gastos.get_all_records()
            futuro = {}
            ahora = datetime.now(ZONA_HORARIA)
            
            for i in range(12):
                mes_futuro = (ahora + relativedelta(months=i)).strftime('%Y-%m')
                futuro[mes_futuro] = {'cuotas_pendientes': 0, 'monto_cuotas': 0}
            
            for item in todos_los_gastos:
                mes = str(item.get('Mes Impacto', ''))
                if mes in futuro:
                    plata = float(item.get('Monto Cuota') or 0)
                    if int(item.get('Cuotas', 1)) > 1:
                        futuro[mes]['cuotas_pendientes'] += 1
                        futuro[mes]['monto_cuotas'] += plata
            
            gastos_pasados = []
            for i in range(1, 4):
                mes_anterior = (ahora - relativedelta(months=i)).strftime('%Y-%m')
                gastos_filtrados = [g for g in todos_los_gastos if g.get('Mes Impacto') == mes_anterior and g.get('Cuota Actual') == 1]
                suma_mes = sum([float(g.get('Monto Cuota') or 0) for g in gastos_filtrados])
                gastos_pasados.append(suma_mes)
            
            promedio_efectivo = sum(gastos_pasados) / len(gastos_pasados) if gastos_pasados else 0
            
            nuevos_datos = [['Mes', 'Cuotas Pendientes', 'Monto Cuotas', 'Promedio Nuevos', 'Total Proyectado']]
            
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
    
    def _sacar_resumen_del_mes_sync(self):
        """Saca los números para el mensajito de Telegram"""
        try:
            este_mes = datetime.now(ZONA_HORARIA).strftime('%Y-%m')
            pestaña_gastos = self.planillita.worksheet('Gastos')
            todos_los_gastos = pestaña_gastos.get_all_records()
            
            gastos_ahora = [g for g in todos_los_gastos if g.get('Mes Impacto') == este_mes]
            
            total_plata = sum([float(g.get('Monto Cuota') or 0) for g in gastos_ahora])
            plata_contado = sum([float(g.get('Monto Cuota') or 0) for g in gastos_ahora if g.get('Cuotas') == 1])
            plata_cuotas = total_plata - plata_contado
            
            rubros = {}
            for item in gastos_ahora:
                r = item.get('Categoría', 'General')
                plata = float(item.get('Monto Cuota') or 0)
                if r not in rubros: rubros[r] = 0
                rubros[r] += plata
            
            return {
                'mes': este_mes,
                'total': total_plata,
                'contado': plata_contado,
                'cuotas': plata_cuotas,
                'cantidad': len(gastos_ahora),
                'categorias': rubros
            }
        except Exception as e:
            registro_errores.error(f"Error sacando la data del mes: {e}")
            return None

    async def sacar_resumen_async(self):
        return await asyncio.to_thread(self._sacar_resumen_del_mes_sync)

    def _sacar_futuro_sync(self):
        try:
            return self.planillita.worksheet('Proyección').get_all_records()
        except Exception as e:
            registro_errores.error(f"Error leyendo la proyeccion: {e}")
            return None

    async def sacar_futuro_async(self):
        return await asyncio.to_thread(self._sacar_futuro_sync)

# Instancio el botcito en memoria
bot_app = BotDeGastos()

# === FUNCIONES DE TELEGRAM (HANDLERS) ===

async def arrancar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    usuario = update.effective_user
    nombre_pantalla = usuario.username or usuario.first_name
    
    if str(usuario.id) not in bot_app.gente_permitida and len(bot_app.gente_permitida) > 0:
        await update.message.reply_text(f"❌ Acceso denegado. Tu ID es: {usuario.id}")
        return ConversationHandler.END
    
    botonera = [
        [KeyboardButton("💰 Nuevo Gasto"), KeyboardButton("📊 Resumen Mes")],
        [KeyboardButton("📈 Proyección"), KeyboardButton("❓ Ayuda")]
    ]
    teclado_visual = ReplyKeyboardMarkup(botonera, resize_keyboard=True)
    
    await update.message.reply_text(
        f"¡Qué onda {nombre_pantalla}! 👋\n\n"
        "Manejo tus gastos al toque.\n"
        "Usa los botones o mandame:\n"
        "💵 <monto> <descripción> [cuotas]\n\n"
        "Ejemplo: 5000 Birra",
        reply_markup=teclado_visual
    )

async def tirar_ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Ayudín*\n\n"
        "Carga rápida: 💵 <plata> <qué compraste> [cuotas]\n"
        "Ejemplo: 35000 Remera 3\n\n"
        "Si preferís paso a paso, tocá '💰 Nuevo Gasto'.",
        parse_mode='Markdown'
    )

async def mostrar_resumen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📊 Calculando (no te asustes)...")
    
    # AWAIT importante: Esperamos sin colgar al resto del bot
    info_mes = await bot_app.sacar_resumen_async()
    
    if info_mes:
        texto_rubros = "\n".join([f"  • {rubro}: ${plata:.2f}" 
                                  for rubro, plata in sorted(info_mes['categorias'].items(), 
                                                           key=lambda x: x[1], reverse=True)])
        
        mensaje = (
            f"📊 *Tu mes de {info_mes['mes']}*\n\n"
            f"💰 Total gastado: ${info_mes['total']:.2f}\n"
            f"💵 Taca Taca: ${info_mes['contado']:.2f}\n"
            f"💳 Tarjetazos: ${info_mes['cuotas']:.2f}\n"
            f"📝 Transacciones: {info_mes['cantidad']}\n\n"
            f"*Te la gastaste en:*\n{texto_rubros}"
        )
    else:
        mensaje = "❌ Error leyendo la planilla. Probá en un rato."
    
    await update.message.reply_text(mensaje, parse_mode='Markdown')

async def mostrar_futuro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📈 Leyendo el tarot financiero...")
    
    filas = await bot_app.sacar_futuro_async()
    
    if filas:
        mensaje = "📈 *Lo que se te viene*\n\n"
        for i, fila in enumerate(filas[:6]): 
            mes_texto = f"*{fila['Mes']}* (Este mes)\n" if i == 0 else f"*{fila['Mes']}*\n"
            mensaje += mes_texto
            mensaje += (
                f"  💳 Tarjeta: ${fila.get('Monto Cuotas', 0):.2f}\n"
                f"  ➕ Estimado extras: ${fila.get('Promedio Nuevos', 0):.2f}\n"
                f"  📊 Vas a necesitar: ${fila.get('Total Proyectado', 0):.2f}\n\n"
            )
        await update.message.reply_text(mensaje, parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ No pude leer la pestaña de Proyección.")

# === MÁQUINA DE ESTADOS (GUIADA) ===

async def arrancar_gasto_guiado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("💰 ¿En qué rubro entra esto? (Comida, Salud, etc.):")
    return PASO_CATEGORIA

async def agarrar_categoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['categoria_elegida'] = update.message.text.strip().title()
    await update.message.reply_text("💵 ¿Cuánta plata gastaste? (Solo números):")
    return PASO_PLATA

async def agarrar_plata(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        plata = float(update.message.text.strip().replace(',', '.'))
        context.user_data['plata_gastada'] = plata
        await update.message.reply_text("📝 ¿Qué compraste?:")
        return PASO_DETALLE
    except ValueError:
        await update.message.reply_text("❌ Pasame un número válido. Sin letras.")
        return PASO_PLATA

async def agarrar_detalle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['detalle_compra'] = update.message.text.strip()
    await update.message.reply_text("💳 ¿En cuántas cuotas? (1 para contado):")
    return PASO_CUOTAS

async def agarrar_cuotas_y_guardar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        cuotas = int(update.message.text.strip())
        if cuotas < 1:
            await update.message.reply_text("❌ Minimo 1 cuota.")
            return PASO_CUOTAS
        
        usuario = update.effective_user
        nombre_pantalla = usuario.username or usuario.first_name
        
        # AWAIT: Escribir en Sheets sin bloquear
        todo_ok = await bot_app.anotar_gasto_async(
            nombre_user=nombre_pantalla,
            categoria_gasto=context.user_data['categoria_elegida'],
            detalle=context.user_data['detalle_compra'],
            plata=context.user_data['plata_gastada'],
            cant_cuotas=cuotas
        )
        
        if todo_ok:

            mensaje = f"🐜 *Nuevo Gasto registrado*\n
            {context.user_data['categoria_elegida']}\n {context.user_data['detalle_compra']} - ${context.user_data['plata_gastada']:.2f}"
        else:
            mensaje = "❌ Error guardando en Google Sheets."
        
        await update.message.reply_text(mensaje, parse_mode='Markdown')
        context.user_data.clear()
        return ConversationHandler.END
        
    except ValueError:
        await update.message.reply_text("❌ Pasame un número entero para las cuotas.")
        return PASO_CUOTAS

async def tirar_todo_al_tacho(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Operación cancelada.")
    return ConversationHandler.END

# === LECTURA DE TEXTO LIBRE ===

async def leer_mensaje_al_toque(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()
    
    if texto == "💰 Nuevo Gasto": return await arrancar_gasto_guiado(update, context)
    elif texto == "📊 Resumen Mes": return await mostrar_resumen(update, context)
    elif texto == "📈 Proyección": return await mostrar_futuro(update, context)
    elif texto == "❓ Ayuda": return await tirar_ayuda(update, context)
    
    # PASO 4: Regex robusto. Permite espacios en blanco de sobra al principio y final.
    patron_magico = r'^\s*(\d+(?:[.,]\d+)?)\s+(.+?)(?:\s+(\d+))?\s*$'
    coincidencia = re.match(patron_magico, texto)
    
    if coincidencia:
        try:
            plata = float(coincidencia.group(1).replace(',', '.'))
            descripcion = coincidencia.group(2).strip()
            cuotas = int(coincidencia.group(3)) if coincidencia.group(3) else 1
            
            usuario = update.effective_user
            nombre_pantalla = usuario.username or usuario.first_name
            
            # AWAIT: Escribir sin bloquear
            todo_ok = await bot_app.anotar_gasto_async(
                nombre_user=nombre_pantalla,
                categoria_gasto='Sin clasificar',
                detalle=descripcion,
                plata=plata,
                cant_cuotas=cuotas
            )
            
            if todo_ok:
                await update.message.reply_text(f"✅ *Anotado al toque*\n💵 ${plata:.2f} en {descripcion}", parse_mode='Markdown')
            else:
                await update.message.reply_text("❌ Error al guardar.")
                
        except Exception as e:
            registro_errores.error(f"Error procesando mensaje rápido: {e}")
            await update.message.reply_text("❌ Usá: <plata> <qué es> [cuotas]")


async def principal_async():
    """Arranque del sistema (ahora también asincrónico)"""
    # AWAIT inicial
    conectado = await bot_app.iniciar_conexion()
    if not conectado:
        registro_errores.error("Me rindo, no conectó a Sheets. Fijate el JSON.")
        return
    
    app = Application.builder().token(os.getenv('TELEGRAM_BOT_TOKEN')).build()
    
    charla_guiada = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^💰 Nuevo Gasto$'), arrancar_gasto_guiado)],
        states={
            PASO_CATEGORIA: [MessageHandler(filters.TEXT & ~filters.COMMAND, agarrar_categoria)],
            PASO_PLATA: [MessageHandler(filters.TEXT & ~filters.COMMAND, agarrar_plata)],
            PASO_DETALLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, agarrar_detalle)],
            PASO_CUOTAS: [MessageHandler(filters.TEXT & ~filters.COMMAND, agarrar_cuotas_y_guardar)],
        },
        fallbacks=[CommandHandler('cancelar', tirar_todo_al_tacho)],
    )
    
    app.add_handler(CommandHandler("start", arrancar))
    app.add_handler(CommandHandler("ayuda", tirar_ayuda))
    app.add_handler(CommandHandler("resumen", mostrar_resumen))
    app.add_handler(CommandHandler("proyeccion", mostrar_futuro))
    app.add_handler(charla_guiada)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, leer_mensaje_al_toque))
    
    registro_errores.info("¡Bot levantado y asincrónico! Escuchando...")
    
    # IMPORTANTE: al usar un event loop que nosotros creamos, tenemos que arrancar la app así:
    await app.initialize()
    await app.start()
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    
    # Mantener vivo el programa
    stop_event = asyncio.Event()
    await stop_event.wait()

if __name__ == '__main__':
    # Lanzamos el loop asincrónico base
    asyncio.run(principal_async())
