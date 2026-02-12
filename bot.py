import os
import logging
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
import gspread
from google.oauth2.service_account import Credentials
from dateutil.relativedelta import relativedelta
import json
import re

# Configuración de logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Estados de la conversación
CATEGORIA, MONTO, DESCRIPCION, CUOTAS = range(4)

# Configuración de Google Sheets
SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']

class GastosBot:
    def __init__(self):
        self.creds = None
        self.client = None
        self.sheet = None
        self.usuarios_autorizados = os.getenv('USUARIOS_AUTORIZADOS', '').split(',')
        
    def inicializar_google_sheets(self):
        """Inicializa la conexión con Google Sheets"""
        try:
            # Lee las credenciales del archivo JSON
            creds_json = os.getenv('GOOGLE_CREDENTIALS_JSON')
            if creds_json:
                creds_dict = json.loads(creds_json)
                self.creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
            else:
                self.creds = Credentials.from_service_account_file('credentials.json', scopes=SCOPES)
            
            self.client = gspread.authorize(self.creds)
            
            # Abre o crea la hoja de cálculo
            spreadsheet_id = os.getenv('SPREADSHEET_ID')
            if spreadsheet_id:
                self.sheet = self.client.open_by_key(spreadsheet_id)
            else:
                self.sheet = self.client.open('Gastos Hormiga')
            
            # Verifica o crea las hojas necesarias
            self._verificar_hojas()
            
            logger.info("Google Sheets inicializado correctamente")
            return True
        except Exception as e:
            logger.error(f"Error al inicializar Google Sheets: {e}")
            return False
    
    def _verificar_hojas(self):
        """Verifica que existan las hojas necesarias y las crea si no existen"""
        hojas_necesarias = ['Gastos', 'Resumen Mensual', 'Proyección']
        hojas_existentes = [ws.title for ws in self.sheet.worksheets()]
        
        # Crear hoja de Gastos
        if 'Gastos' not in hojas_existentes:
            gastos_ws = self.sheet.add_worksheet(title='Gastos', rows=1000, cols=10)
            gastos_ws.append_row(['Fecha', 'Usuario', 'Categoría', 'Descripción', 'Monto', 
                                 'Cuotas', 'Cuota Actual', 'Monto Cuota', 'Mes Impacto', 'ID'])
        
        # Crear hoja de Resumen Mensual
        if 'Resumen Mensual' not in hojas_existentes:
            resumen_ws = self.sheet.add_worksheet(title='Resumen Mensual', rows=100, cols=6)
            resumen_ws.append_row(['Mes', 'Total Gastos', 'Contado', 'Cuotas', 'Categorías', 'Detalle'])
        
        # Crear hoja de Proyección
        if 'Proyección' not in hojas_existentes:
            proyeccion_ws = self.sheet.add_worksheet(title='Proyección', rows=100, cols=5)
            proyeccion_ws.append_row(['Mes', 'Cuotas Pendientes', 'Monto Estimado', 'Nuevos Gastos', 'Total Proyectado'])

    def registrar_gasto(self, usuario, categoria, descripcion, monto, cuotas=1):
        """Registra un gasto en Google Sheets"""
        try:
            gastos_ws = self.sheet.worksheet('Gastos')
            fecha = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            if cuotas == 1:
                # Gasto al contado
                mes_impacto = datetime.now().strftime('%Y-%m')
                row = [fecha, usuario, categoria, descripcion, monto, 1, 1, monto, mes_impacto, '']
                gastos_ws.append_row(row)
            else:
                # Gasto en cuotas
                monto_cuota = round(monto / cuotas, 2)
                fecha_base = datetime.now()
                
                for i in range(cuotas):
                    mes_impacto = (fecha_base + relativedelta(months=i)).strftime('%Y-%m')
                    row = [fecha, usuario, categoria, descripcion, monto, 
                           cuotas, i+1, monto_cuota, mes_impacto, f"{fecha}_{descripcion}"]
                    gastos_ws.append_row(row)
            
            self._actualizar_resumen()
            self._actualizar_proyeccion()
            
            return True
        except Exception as e:
            logger.error(f"Error al registrar gasto: {e}")
            return False
    
    def _actualizar_resumen(self):
        """Actualiza el resumen mensual"""
        try:
            gastos_ws = self.sheet.worksheet('Gastos')
            resumen_ws = self.sheet.worksheet('Resumen Mensual')
            
            # Obtener todos los gastos
            gastos = gastos_ws.get_all_records()
            
            # Agrupar por mes
            resumen_meses = {}
            for gasto in gastos:
                mes = gasto['Mes Impacto']
                if mes not in resumen_meses:
                    resumen_meses[mes] = {
                        'total': 0,
                        'contado': 0,
                        'cuotas': 0,
                        'categorias': {}
                    }
                
                monto_cuota = float(gasto['Monto Cuota']) if gasto['Monto Cuota'] else 0
                resumen_meses[mes]['total'] += monto_cuota
                
                if gasto['Cuotas'] == 1:
                    resumen_meses[mes]['contado'] += monto_cuota
                else:
                    resumen_meses[mes]['cuotas'] += monto_cuota
                
                cat = gasto['Categoría']
                if cat not in resumen_meses[mes]['categorias']:
                    resumen_meses[mes]['categorias'][cat] = 0
                resumen_meses[mes]['categorias'][cat] += monto_cuota
            
            # Limpiar y actualizar resumen
            resumen_ws.clear()
            resumen_ws.append_row(['Mes', 'Total Gastos', 'Contado', 'Cuotas', 'Categorías Top', 'Detalle'])
            
            for mes in sorted(resumen_meses.keys(), reverse=True):
                datos = resumen_meses[mes]
                categorias_top = sorted(datos['categorias'].items(), key=lambda x: x[1], reverse=True)[:3]
                cats_str = ', '.join([f"{cat}: ${monto:.2f}" for cat, monto in categorias_top])
                
                resumen_ws.append_row([
                    mes,
                    round(datos['total'], 2),
                    round(datos['contado'], 2),
                    round(datos['cuotas'], 2),
                    cats_str,
                    f"{len(datos['categorias'])} categorías"
                ])
            
        except Exception as e:
            logger.error(f"Error al actualizar resumen: {e}")
    
    def _actualizar_proyeccion(self):
        """Actualiza la proyección de gastos futuros"""
        try:
            gastos_ws = self.sheet.worksheet('Gastos')
            proyeccion_ws = self.sheet.worksheet('Proyección')
            
            # Obtener todos los gastos
            gastos = gastos_ws.get_all_records()
            
            # Proyectar próximos 12 meses
            proyeccion = {}
            fecha_actual = datetime.now()
            
            for i in range(12):
                mes = (fecha_actual + relativedelta(months=i)).strftime('%Y-%m')
                proyeccion[mes] = {
                    'cuotas_pendientes': 0,
                    'monto_cuotas': 0,
                    'items': []
                }
            
            # Calcular cuotas pendientes
            for gasto in gastos:
                mes_impacto = gasto['Mes Impacto']
                if mes_impacto in proyeccion:
                    monto_cuota = float(gasto['Monto Cuota']) if gasto['Monto Cuota'] else 0
                    if gasto['Cuotas'] > 1:
                        proyeccion[mes_impacto]['cuotas_pendientes'] += 1
                        proyeccion[mes_impacto]['monto_cuotas'] += monto_cuota
                        proyeccion[mes_impacto]['items'].append(f"{gasto['Descripción']} (cuota {gasto['Cuota Actual']}/{gasto['Cuotas']})")
            
            # Actualizar hoja
            proyeccion_ws.clear()
            proyeccion_ws.append_row(['Mes', 'Cuotas Pendientes', 'Monto Cuotas', 'Promedio Nuevos', 'Total Proyectado'])
            
            # Calcular promedio de gastos nuevos (últimos 3 meses)
            meses_pasados = []
            for i in range(1, 4):
                mes_pasado = (fecha_actual - relativedelta(months=i)).strftime('%Y-%m')
                gastos_mes = [g for g in gastos if g['Mes Impacto'] == mes_pasado and g['Cuota Actual'] == 1]
                total_mes = sum([float(g['Monto Cuota']) for g in gastos_mes if g['Monto Cuota']])
                meses_pasados.append(total_mes)
            
            promedio_nuevos = sum(meses_pasados) / len(meses_pasados) if meses_pasados else 0
            
            for mes in sorted(proyeccion.keys()):
                datos = proyeccion[mes]
                total_proyectado = datos['monto_cuotas'] + promedio_nuevos
                
                proyeccion_ws.append_row([
                    mes,
                    datos['cuotas_pendientes'],
                    round(datos['monto_cuotas'], 2),
                    round(promedio_nuevos, 2),
                    round(total_proyectado, 2)
                ])
            
        except Exception as e:
            logger.error(f"Error al actualizar proyección: {e}")
    
    def obtener_resumen_mes_actual(self):
        """Obtiene el resumen del mes actual"""
        try:
            mes_actual = datetime.now().strftime('%Y-%m')
            gastos_ws = self.sheet.worksheet('Gastos')
            gastos = gastos_ws.get_all_records()
            
            gastos_mes = [g for g in gastos if g['Mes Impacto'] == mes_actual]
            
            total = sum([float(g['Monto Cuota']) for g in gastos_mes if g['Monto Cuota']])
            contado = sum([float(g['Monto Cuota']) for g in gastos_mes if g['Monto Cuota'] and g['Cuotas'] == 1])
            cuotas = total - contado
            
            # Categorías
            categorias = {}
            for gasto in gastos_mes:
                cat = gasto['Categoría']
                monto = float(gasto['Monto Cuota']) if gasto['Monto Cuota'] else 0
                if cat not in categorias:
                    categorias[cat] = 0
                categorias[cat] += monto
            
            return {
                'mes': mes_actual,
                'total': total,
                'contado': contado,
                'cuotas': cuotas,
                'cantidad': len(gastos_mes),
                'categorias': categorias
            }
        except Exception as e:
            logger.error(f"Error al obtener resumen: {e}")
            return None

# Instancia global del bot
gastos_bot = GastosBot()

# Funciones de comandos
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /start"""
    user = update.effective_user
    username = user.username or user.first_name
    
    # Verificar si el usuario está autorizado
    if str(user.id) not in gastos_bot.usuarios_autorizados and len(gastos_bot.usuarios_autorizados) > 0:
        await update.message.reply_text(
            "❌ No tienes autorización para usar este bot.\n"
            f"Tu ID de usuario es: {user.id}\n"
            "Contacta al administrador para obtener acceso."
        )
        return ConversationHandler.END
    
    keyboard = [
        [KeyboardButton("💰 Nuevo Gasto"), KeyboardButton("📊 Resumen Mes")],
        [KeyboardButton("📈 Proyección"), KeyboardButton("❓ Ayuda")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        f"¡Hola {username}! 👋\n\n"
        "Soy tu asistente para registrar gastos hormiga.\n\n"
        "Puedes:\n"
        "• Registrar gastos al contado o en cuotas\n"
        "• Ver el resumen mensual\n"
        "• Consultar la proyección de gastos futuros\n\n"
        "Usa los botones o envía un gasto con formato:\n"
        "💵 <monto> <descripción> [cuotas]\n\n"
        "Ejemplos:\n"
        "• 500 Almuerzo\n"
        "• 12000 Auriculares 6 (6 cuotas)",
        reply_markup=reply_markup
    )

async def ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /ayuda"""
    await update.message.reply_text(
        "📖 *Guía de Uso*\n\n"
        "*Registrar gasto rápido:*\n"
        "💵 <monto> <descripción> [cuotas]\n"
        "Ejemplos:\n"
        "• 500 Almuerzo\n"
        "• 3500 Zapatillas 3\n\n"
        "*Botones disponibles:*\n"
        "• 💰 Nuevo Gasto: Registro guiado paso a paso\n"
        "• 📊 Resumen Mes: Ver gastos del mes actual\n"
        "• 📈 Proyección: Ver gastos proyectados\n\n"
        "*Categorías sugeridas:*\n"
        "Comida, Transporte, Entretenimiento, Salud, "
        "Ropa, Tecnología, Hogar, Otros\n\n"
        "*Comandos:*\n"
        "/start - Iniciar bot\n"
        "/resumen - Resumen del mes\n"
        "/proyeccion - Proyección futura\n"
        "/ayuda - Esta ayuda",
        parse_mode='Markdown'
    )

async def resumen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra el resumen del mes actual"""
    await update.message.reply_text("📊 Generando resumen...")
    
    resumen = gastos_bot.obtener_resumen_mes_actual()
    
    if resumen:
        categorias_texto = "\n".join([f"  • {cat}: ${monto:.2f}" 
                                      for cat, monto in sorted(resumen['categorias'].items(), 
                                                              key=lambda x: x[1], reverse=True)])
        
        mensaje = (
            f"📊 *Resumen de {resumen['mes']}*\n\n"
            f"💰 Total gastado: ${resumen['total']:.2f}\n"
            f"💵 Al contado: ${resumen['contado']:.2f}\n"
            f"💳 En cuotas: ${resumen['cuotas']:.2f}\n"
            f"📝 Cantidad de gastos: {resumen['cantidad']}\n\n"
            f"*Por categoría:*\n{categorias_texto}"
        )
    else:
        mensaje = "❌ No se pudo obtener el resumen. Intenta de nuevo."
    
    await update.message.reply_text(mensaje, parse_mode='Markdown')

async def proyeccion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra la proyección de gastos"""
    await update.message.reply_text("📈 Generando proyección...")
    
    try:
        proyeccion_ws = gastos_bot.sheet.worksheet('Proyección')
        proyeccion_data = proyeccion_ws.get_all_records()
        
        mensaje = "📈 *Proyección de Gastos*\n\n"
        
        for i, row in enumerate(proyeccion_data[:6]):  # Próximos 6 meses
            if i == 0:
                mensaje += f"*{row['Mes']}* (mes actual)\n"
            else:
                mensaje += f"*{row['Mes']}*\n"
            
            mensaje += (
                f"  💳 Cuotas: ${row['Monto Cuotas']:.2f} ({row['Cuotas Pendientes']} cuotas)\n"
                f"  ➕ Nuevos: ${row['Promedio Nuevos']:.2f}\n"
                f"  📊 Total: ${row['Total Proyectado']:.2f}\n\n"
            )
        
        mensaje += "💡 *Promedio Nuevos* se calcula con los últimos 3 meses"
        
    except Exception as e:
        logger.error(f"Error al obtener proyección: {e}")
        mensaje = "❌ No se pudo obtener la proyección. Intenta de nuevo."
    
    await update.message.reply_text(mensaje, parse_mode='Markdown')

async def nuevo_gasto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia el proceso de registro de un nuevo gasto"""
    await update.message.reply_text(
        "💰 *Registrar Nuevo Gasto*\n\n"
        "¿En qué categoría se encuentra este gasto?\n\n"
        "Categorías sugeridas:\n"
        "• Comida\n"
        "• Transporte\n"
        "• Entretenimiento\n"
        "• Salud\n"
        "• Ropa\n"
        "• Tecnología\n"
        "• Hogar\n"
        "• Otros\n\n"
        "Escribe la categoría o /cancelar para abortar:",
        parse_mode='Markdown'
    )
    return CATEGORIA

async def recibir_categoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recibe la categoría del gasto"""
    context.user_data['categoria'] = update.message.text.strip().title()
    await update.message.reply_text(
        f"Categoría: *{context.user_data['categoria']}*\n\n"
        "💵 ¿Cuál es el monto total del gasto?\n"
        "Ejemplo: 1500",
        parse_mode='Markdown'
    )
    return MONTO

async def recibir_monto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recibe el monto del gasto"""
    try:
        monto = float(update.message.text.strip().replace(',', '.'))
        context.user_data['monto'] = monto
        await update.message.reply_text(
            f"Monto: *${monto:.2f}*\n\n"
            "📝 ¿Qué compraste o para qué fue el gasto?\n"
            "Ejemplo: Almuerzo con amigos",
            parse_mode='Markdown'
        )
        return DESCRIPCION
    except ValueError:
        await update.message.reply_text(
            "❌ Monto inválido. Por favor ingresa solo números.\n"
            "Ejemplo: 1500"
        )
        return MONTO

async def recibir_descripcion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recibe la descripción del gasto"""
    context.user_data['descripcion'] = update.message.text.strip()
    await update.message.reply_text(
        f"Descripción: *{context.user_data['descripcion']}*\n\n"
        "💳 ¿En cuántas cuotas?\n"
        "Escribe 1 para contado o el número de cuotas (ej: 3, 6, 12)",
        parse_mode='Markdown'
    )
    return CUOTAS

async def recibir_cuotas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recibe las cuotas y registra el gasto"""
    try:
        cuotas = int(update.message.text.strip())
        
        if cuotas < 1:
            await update.message.reply_text("❌ El número de cuotas debe ser al menos 1.")
            return CUOTAS
        
        user = update.effective_user
        username = user.username or user.first_name
        
        # Registrar el gasto
        exito = gastos_bot.registrar_gasto(
            usuario=username,
            categoria=context.user_data['categoria'],
            descripcion=context.user_data['descripcion'],
            monto=context.user_data['monto'],
            cuotas=cuotas
        )
        
        if exito:
            if cuotas == 1:
                mensaje = (
                    "✅ *Gasto registrado exitosamente*\n\n"
                    f"💰 Categoría: {context.user_data['categoria']}\n"
                    f"💵 Monto: ${context.user_data['monto']:.2f}\n"
                    f"📝 Descripción: {context.user_data['descripcion']}\n"
                    f"💳 Tipo: Contado"
                )
            else:
                monto_cuota = context.user_data['monto'] / cuotas
                mensaje = (
                    "✅ *Gasto registrado exitosamente*\n\n"
                    f"💰 Categoría: {context.user_data['categoria']}\n"
                    f"💵 Monto total: ${context.user_data['monto']:.2f}\n"
                    f"📝 Descripción: {context.user_data['descripcion']}\n"
                    f"💳 Cuotas: {cuotas} x ${monto_cuota:.2f}"
                )
        else:
            mensaje = "❌ Hubo un error al registrar el gasto. Intenta de nuevo."
        
        await update.message.reply_text(mensaje, parse_mode='Markdown')
        
        # Limpiar datos de usuario
        context.user_data.clear()
        
        return ConversationHandler.END
        
    except ValueError:
        await update.message.reply_text(
            "❌ Número de cuotas inválido. Por favor ingresa un número entero.\n"
            "Ejemplo: 1, 3, 6, 12"
        )
        return CUOTAS

async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancela la operación actual"""
    context.user_data.clear()
    await update.message.reply_text(
        "❌ Operación cancelada.\n"
        "Usa /start para volver a comenzar."
    )
    return ConversationHandler.END

async def procesar_mensaje_rapido(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Procesa mensajes con formato rápido: monto descripción [cuotas]"""
    texto = update.message.text.strip()
    
    # Botones del menú
    if texto == "💰 Nuevo Gasto":
        return await nuevo_gasto(update, context)
    elif texto == "📊 Resumen Mes":
        return await resumen(update, context)
    elif texto == "📈 Proyección":
        return await proyeccion(update, context)
    elif texto == "❓ Ayuda":
        return await ayuda(update, context)
    
    # Formato rápido: monto descripción [cuotas]
    # Buscar patrón: número (puede incluir decimales) seguido de texto
    patron = r'^(\d+(?:[.,]\d+)?)\s+(.+?)(?:\s+(\d+))?$'
    match = re.match(patron, texto)
    
    if match:
        try:
            monto = float(match.group(1).replace(',', '.'))
            descripcion = match.group(2).strip()
            cuotas = int(match.group(3)) if match.group(3) else 1
            
            user = update.effective_user
            username = user.username or user.first_name
            
            # Registrar con categoría por defecto
            exito = gastos_bot.registrar_gasto(
                usuario=username,
                categoria='General',
                descripcion=descripcion,
                monto=monto,
                cuotas=cuotas
            )
            
            if exito:
                if cuotas == 1:
                    mensaje = (
                        "✅ *Gasto registrado*\n\n"
                        f"💵 ${monto:.2f}\n"
                        f"📝 {descripcion}\n"
                        f"💳 Contado"
                    )
                else:
                    monto_cuota = monto / cuotas
                    mensaje = (
                        "✅ *Gasto registrado*\n\n"
                        f"💵 ${monto:.2f}\n"
                        f"📝 {descripcion}\n"
                        f"💳 {cuotas} cuotas de ${monto_cuota:.2f}"
                    )
                
                await update.message.reply_text(mensaje, parse_mode='Markdown')
            else:
                await update.message.reply_text("❌ Error al registrar el gasto.")
            
        except Exception as e:
            logger.error(f"Error en mensaje rápido: {e}")
            await update.message.reply_text(
                "❌ Formato incorrecto. Usa:\n"
                "💵 <monto> <descripción> [cuotas]\n\n"
                "Ejemplos:\n"
                "• 500 Almuerzo\n"
                "• 3000 Zapatillas 3"
            )
    else:
        await update.message.reply_text(
            "No entiendo ese mensaje 🤔\n\n"
            "Usa los botones del menú o escribe:\n"
            "💵 <monto> <descripción> [cuotas]\n\n"
            "Ejemplo: 500 Almuerzo"
        )

def main():
    """Función principal"""
    # Inicializar Google Sheets
    if not gastos_bot.inicializar_google_sheets():
        logger.error("No se pudo inicializar Google Sheets. Verifica las credenciales.")
        return
    
    # Crear aplicación
    application = Application.builder().token(os.getenv('TELEGRAM_BOT_TOKEN')).build()
    
    # Manejador de conversación para nuevo gasto
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^💰 Nuevo Gasto$'), nuevo_gasto)],
        states={
            CATEGORIA: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_categoria)],
            MONTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_monto)],
            DESCRIPCION: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_descripcion)],
            CUOTAS: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_cuotas)],
        },
        fallbacks=[CommandHandler('cancelar', cancelar)],
    )
    
    # Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("ayuda", ayuda))
    application.add_handler(CommandHandler("resumen", resumen))
    application.add_handler(CommandHandler("proyeccion", proyeccion))
    application.add_handler(conv_handler)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, procesar_mensaje_rapido))
    
    # Iniciar bot
    logger.info("Bot iniciado...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
