# 🤖 Gastos Hormiga Bot - Asistente Personal de Gastos

Bot de Telegram para registrar gastos personales de forma rápida, categorizarlos y consultar resúmenes por mes y categoría usando Google Sheets como base de datos.

El bot está pensado para registrar gastos simples, cotidianos y personales. Todos los gastos se guardan automáticamente en 1 cuota.

---

## 📋 Características

- ✅ Registro rápido de gastos desde Telegram
- ✅ Registro guiado con categoría personalizada
- ✅ Todos los gastos se guardan automáticamente en 1 cuota
- ✅ Usuarios autorizados mediante variable de entorno
- ✅ Integración automática con Google Sheets
- ✅ Resumen filtrable por mes
- ✅ Resumen filtrable por categoría
- ✅ Consulta de gastos por categoría, por ejemplo: camioneta, comida, salud, hogar
- ✅ Proyección de gastos futuros
- ✅ Hosting 24/7 en Railway
- ✅ Compatible con iPhone y Android

---

## 📱 Uso del Bot

El bot tiene dos formas principales de registrar gastos.

---

## 1. Registro Rápido

Sirve para anotar un gasto al instante.

Formato:

```txt
<monto> <descripción>
```
500 Almuerzo
3000 Zapatillas 
12000 Notebook 
```
Formato: <monto> <descripción> 
```
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


## 📄 Licencia

Uso libre para fines personales.

---

**¡Listo para usar!** 🎉

Envía un mensaje al bot para empezar a registrar tus gastos.
