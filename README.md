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

## 1. Registro rápido

Ingresá categoría, monto y detalle en un mensaje:

```txt
comida 1400 desayuno
camioneta 35000 nafta
casa 1500.50 artículos de limpieza
```

Se acepta punto para miles y coma para centavos (`1.500,50`), o punto decimal
sin separador de miles (`1500.50`). `1.500` representa mil quinientos pesos.
El monto debe ser positivo, finito y tener hasta dos decimales.

Las categorías pueden contener espacios: `comida y bebida 1400 desayuno`.
El primer número indica el monto y todo lo que sigue es el detalle.

El formato anterior con barras verticales también sigue disponible.
El formato `<monto> <descripción>` sigue funcionando y guarda la
categoría `Sin clasificar`.

## 2. Registro guiado

Tocá **💰 Nuevo Gasto**. Solo se solicita **categoría → monto → detalle**.
Podés elegir una categoría sugerida o escribir una propia. Fecha y usuario
se completan automáticamente; los gastos nuevos conservan una cuota en la
planilla para mantener la compatibilidad.

- **⬅️ Volver** permite corregir el paso anterior.
- **❌ Cancelar** o `/cancelar` cancela la operación.
- Si Google no confirma el guardado, se conserva el borrador y aparece
  **🔄 Reintentar**. El mismo ID permite comprobar si la fila ya existe antes
  de repetir la escritura. No vuelvas a ingresar el gasto en otro mensaje
  mientras esté pendiente.
- Los botones de ayuda, resumen y proyección no se guardan como datos del gasto.

### Comandos Disponibles

- `/start` - Iniciar el bot y ver menú
- `/resumen` - Ver resumen del mes actual
- `/proyeccion` - Ver proyección de gastos futuros
- `/ayuda` - Guía de uso completa

### Botones del Menú

- 💰 **Nuevo Gasto** - Registro paso a paso con categorías
- 📊 **Resumen** - Total gastado este mes
- 📈 **Proyección** - Gastos proyectados próximos meses
- ❓ **Ayuda** - Guía rápida

---

## 📊 Estructura de Google Sheets

El bot crea automáticamente 3 hojas:

### 1. Gastos (Registro completo)
| Fecha | Usuario | Categoría | Descripción | Monto | Cuotas | Cuota Actual | Monto Cuota | Mes Impacto | ID |
|-------|---------|-----------|-------------|-------|--------|--------------|-------------|-------------|----|

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

## Compatibilidad, rendimiento y recuperación

Los registros históricos de **Gastos** no se borran ni se migran. Se conservan
las diez columnas existentes y el cálculo por **Monto Cuota**, incluidas las
cuotas antiguas. Si falta el encabezado ID en una planilla de nueve columnas,
se agrega únicamente ese encabezado y, si hace falta, una columna vacía. Si la
estructura no coincide o esa columna contiene datos sin encabezado, el bot
se detiene para evitar escribir en columnas equivocadas.

El guardado normal agrega una fila y confirma sin recalcular las otras hojas.
Una tarea supervisada agrupa los cambios cada dos segundos y actualiza
**Resumen Mensual** y **Proyección** con una sola lectura del historial,
sin borrar las hojas antes de escribir. Los errores se reintentan; un error
en los agregados no convierte un gasto guardado en un fallo de guardado.
La proyección solicitada se recalcula al consultar. Las consultas de gastos
usan una caché de 15 segundos, invalidada tras cada guardado del bot; una
edición manual de la planilla puede tardar ese intervalo en verse.

Los logs registran duración del guardado y cantidad de operaciones Sheets
(sin incluir los datos del gasto). Los resúmenes ordenan por fecha y hora y
los mensajes largos respetan el límite de Telegram, incluso con emojis.
Todas las entradas requieren un ID autorizado. Se combinan los IDs de
`USUARIOS_AUTORIZADOS` con la lista adicional de `usuarios_autorizados.json`,
sin reemplazar los usuarios configurados en el despliegue. El segundo usuario
está registrado en ese archivo. Para revocar un acceso, quitá su ID de ambas
fuentes si aparece en las dos; reiniciá el bot después de cambiar la configuración.
Si ambas listas están vacías, se deniega el acceso.

El estado de conversación y los borradores se guardan en `.estado-bot.pickle`.
Para conservarlos entre despliegues, configurá `BOT_STATE_PATH` en un volumen
persistente y ejecutá **una sola instancia** del bot. El archivo contiene datos
personales: mantenelo privado, fuera del repositorio y de carpetas públicas.
La pérdida de ese archivo no elimina los gastos de Google Sheets, pero sí
puede perder borradores locales. No uses un archivo de estado de origen ajeno.

## Verificación local

```bash
python -m pytest -q
```

Las pruebas usan planillas simuladas: no escriben en Google Sheets ni envían
mensajes de Telegram.
