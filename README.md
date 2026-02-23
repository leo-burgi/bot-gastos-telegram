# 🤖 Gastos Hormiga Bot - Tu Asistente de Gastos Hormiga

Bot de Telegram para registrar gastos hormiga y categorizarlos, ayudando a proyectar gastos personales con integración a Google Sheets.

## 📋 Características
- ✅ Registro rápido de gastos (contado o cuotas)
- ✅ Permite Múltiples usuarios autorizados 
- ✅ Integración automática con Google Sheets "Gastos Hormiga"
- ✅ Resumen mensual detallado por categorías
- ✅ Proyección de gastos futuros (12 meses)
- ✅ Cálculo automático de cuotas pendientes
- ✅ Hosting gratuito 24/7 (Railway)
- ✅ Compatible con iPhone y Android


## 📱 Uso del Bot

### 2 Métodos de Registro

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

[ ] Refactorización Crítica: Eliminar las funciones _refrescar_resumen y _refrescar_proyeccion del código Python y delegar esos cálculos a Tablas Dinámicas nativas de Google Sheets para evitar cuellos de botella en la API.
[ ] Conexión a Looker Studio para visualización de gráficos dinámicos y métricas de consumo.
[ ] Módulo para registro de ingresos (para balance).
---

## 📄 Licencia

Uso libre para fines personales.

---

**¡Listo para usar!** 🎉

Envía un mensaje al bot para empezar a registrar tus gastos.
