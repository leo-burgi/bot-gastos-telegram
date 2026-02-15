# 🤖 PelaGastos Bot - Tu Asistente de Gastos Hormiga

Bot de Telegram **@Pela_Gastos_bot** para registrar y proyectar gastos personales con integración a Google Sheets.

## 📋 Características

- ✅ Registro rápido de gastos (contado o cuotas)
- ✅ Múltiples usuarios autorizados (tú y tu esposa)
- ✅ Integración automática con Google Sheets "BALANCE2026"
- ✅ Resumen mensual detallado por categorías
- ✅ Proyección de gastos futuros (12 meses)
- ✅ Cálculo automático de cuotas pendientes
- ✅ Hosting gratuito 24/7
- ✅ Compatible con iPhone y Android

## ✅ Ya Configurado

- ✅ Bot de Telegram: **@Pela_Gastos_bot**
- ✅ Cuenta de servicio Google: **pelagastosbot@pelagastosbot.iam.gserviceaccount.com**
- ✅ Google Sheet: **BALANCE2026** (ID: 1t8Pzskd0MVhRtlrHqIUURpP1FBvN7xjhP6S3uUoCYQo)
- ✅ Acceso de editor concedido a la cuenta de servicio
- ✅ Tu User ID: **5484630697**

---

## 🚀 Pasos que Te Faltan (Solo 3)

### PASO 1: Obtener el ID de Telegram de tu Esposa (2 minutos)

1. **Desde el iPhone de tu esposa**, abre Telegram
2. Busca el bot **@userinfobot**
3. Envía `/start`
4. **Copia el ID** que aparece (será un número similar a: 987654321)
5. Guarda ese número, lo necesitarás en el PASO 3

---

### PASO 2: Subir el Código a GitHub (10 minutos)

**Opción A - Desde la Web (Más Fácil):**

1. **Crea cuenta en GitHub** (si no tienes): https://github.com/join

2. **Crea un nuevo repositorio:**
   - Click en el botón "+" arriba a la derecha
   - "New repository"
   - Nombre: `pelagastos-bot`
   - Marca "Private" (para mantenerlo privado)
   - Click "Create repository"

3. **Sube los archivos:**
   - Click en "uploading an existing file"
   - Arrastra TODOS los archivos que te compartí:
     - bot.py
     - requirements.txt
     - Procfile
     - runtime.txt
   - Click "Commit changes"

**Opción B - Desde la Terminal (Si sabes usar Git):**

```bash
# Clonar este proyecto
cd tu_carpeta_proyecto

# Inicializar Git
git init

# Agregar archivos
git add .

# Commit
git commit -m "Initial commit - PelaGastos Bot"

# Conectar con GitHub (reemplaza con tu usuario)
git remote add origin https://github.com/TU_USUARIO/pelagastos-bot.git

# Push
git push -u origin main
```

---

### PASO 3: Configurar Hosting en Railway (15 minutos)

**Railway** ofrece 500 horas gratis al mes (más que suficiente para el bot).

1. **Crea cuenta en Railway:**
   - Ve a: https://railway.app/
   - Click "Start a New Project"
   - Login con GitHub (crea cuenta de GitHub si no tienes)

2. **Sube el código:**
   
   **Opción A - Desde GitHub (Recomendado):**
   - Crea un repositorio en GitHub
   - Sube todos los archivos del bot (bot.py, requirements.txt, Procfile, runtime.txt)
   - En Railway: "New Project" → "Deploy from GitHub repo"
   - Selecciona tu repositorio

   **Opción B - Desde Railway CLI:**
   ```bash
   # Instala Railway CLI
   npm i -g @railway/cli
   
   # Login
   railway login
   
   # Inicializa proyecto
   railway init
   
   # Deploy
   railway up
   ```

3. **Configurar Variables de Entorno en Railway:**
   - En tu proyecto de Railway, ve a "Variables"
   - Click "New Variable" para cada una:

   **Variable 1 - TELEGRAM_BOT_TOKEN:**
   - Name: `TELEGRAM_BOT_TOKEN`
   - Value: (pega aquí el token completo que te dio BotFather)

   **Variable 2 - USUARIOS_AUTORIZADOS:**
   - Name: `USUARIOS_AUTORIZADOS`
   - Value: `5484630697,ID_DE_TU_ESPOSA`
   - ⚠️ IMPORTANTE: Reemplaza `ID_DE_TU_ESPOSA` con el ID que obtuviste en el PASO 1

   **Variable 3 - GOOGLE_CREDENTIALS_JSON:**
   - Name: `GOOGLE_CREDENTIALS_JSON`
   - Value: (abre el archivo JSON que descargaste de Google Cloud, copia TODO el contenido y pégalo aquí en UNA SOLA LÍNEA)
   - Ejemplo de cómo debe verse: `{"type":"service_account","project_id":"pelagastosbot",...}`
   - ⚠️ Debe tener el email: **pelagastosbot@pelagastosbot.iam.gserviceaccount.com**

   **Variable 4 - SPREADSHEET_ID:**
   - Name: `SPREADSHEET_ID`
   - Value: `1t8Pzskd0MVhRtlrHqIUURpP1FBvN7xjhP6S3uUoCYQo`

4. **Deploy:**
   - Railway detectará automáticamente el `Procfile`
   - El bot se desplegará automáticamente
   - Ve a "Deployments" para ver el estado

---

### ALTERNATIVA: Hosting en Render (También Gratuito)

1. **Crea cuenta en Render:**
   - Ve a: https://render.com/
   - Regístrate con GitHub

2. **Nuevo Web Service:**
   - Click "New +" → "Background Worker"
   - Conecta tu repositorio de GitHub
   - Name: "bot-gastos"
   - Environment: Python
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python bot.py`

3. **Variables de Entorno:**
   - En "Environment", agrega las mismas 4 variables de arriba

4. **Deploy:**
   - Click "Create Background Worker"

---

## 📱 Uso del Bot

### Métodos de Registro

**1. Formato Rápido:**
```
500 Almuerzo
3000 Zapatillas 3
12000 Notebook 12
```
Formato: `<monto> <descripción> [cuotas]`

**2. Registro Guiado:**
- Usa el botón "💰 Nuevo Gasto"
- Sigue las instrucciones paso a paso
- Incluye categoría personalizada

### Comandos Disponibles

- `/start` - Iniciar el bot y ver menú
- `/resumen` - Ver resumen del mes actual
- `/proyeccion` - Ver proyección de gastos futuros
- `/ayuda` - Guía de uso completa

### Botones del Menú

- 💰 **Nuevo Gasto** - Registro paso a paso con categorías
- 📊 **Resumen Mes** - Total gastado este mes
- 📈 **Proyección** - Gastos proyectados próximos meses
- ❓ **Ayuda** - Guía rápida

---

## 📊 Estructura de Google Sheets

El bot crea automáticamente 3 hojas:

### 1. Gastos (Registro completo)
| Fecha | Usuario | Categoría | Descripción | Monto | Cuotas | Cuota Actual | Monto Cuota | Mes Impacto |
|-------|---------|-----------|-------------|-------|--------|--------------|-------------|-------------|

### 2. Resumen Mensual
| Mes | Total Gastos | Contado | Cuotas | Categorías Top |
|-----|--------------|---------|--------|----------------|

### 3. Proyección
| Mes | Cuotas Pendientes | Monto Cuotas | Promedio Nuevos | Total Proyectado |
|-----|-------------------|--------------|-----------------|------------------|

---

## 🎨 Categorías Sugeridas

- 🍔 Comida
- 🚗 Transporte
- 🎬 Entretenimiento
- 💊 Salud
- 👕 Ropa
- 💻 Tecnología
- 🏠 Hogar
- 📦 Otros

---

## 🔧 Solución de Problemas

### El bot no responde

1. Verifica que esté corriendo en Railway/Render (ve a "Deployments")
2. Revisa los logs en Railway/Render
3. Confirma que el TOKEN sea correcto

### Error de Google Sheets

1. Verifica que compartiste la hoja con el email de la cuenta de servicio
2. Confirma que las APIs estén habilitadas
3. Revisa que el JSON de credenciales esté completo

### No puedo usar el bot

1. Verifica que tu ID esté en `USUARIOS_AUTORIZADOS`
2. Envía `/start` al bot @userinfobot para confirmar tu ID
3. Actualiza la variable de entorno con el ID correcto

---

## 💡 Consejos de Uso

1. **Registra inmediatamente:** Anota el gasto apenas lo haces para no olvidarte
2. **Sé específico:** Describe bien los gastos para recordarlos después
3. **Revisa el resumen:** Consulta mensualmente para tomar mejores decisiones
4. **Proyección:** Usa la proyección para planificar gastos grandes

---

## 🔐 Seguridad

- ✅ Solo usuarios autorizados pueden usar el bot
- ✅ Credenciales guardadas como variables de entorno
- ✅ No se guardan credenciales en el código
- ✅ Google Sheet privada (solo compartida con la cuenta de servicio)

---

## 📞 Soporte

Si tienes problemas:

1. Revisa los logs en Railway/Render
2. Verifica que todas las variables de entorno estén configuradas
3. Confirma que las APIs de Google estén habilitadas
4. Verifica que la Google Sheet esté compartida correctamente

---

## 🚀 Próximas Mejoras (Opcional)

- [ ] Gráficos automáticos en Google Sheets
- [ ] Alertas de presupuesto
- [ ] Exportar reportes en PDF
- [ ] Recordatorios de registro diario
- [ ] Categorización automática con IA
- [ ] Multi-moneda

---

## 📄 Licencia

Uso libre para fines personales.

---

**¡Listo para usar!** 🎉

Envía un mensaje al bot para empezar a registrar tus gastos.
