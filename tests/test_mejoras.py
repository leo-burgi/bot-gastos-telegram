import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import bot


HEADERS = ['Fecha', 'Usuario', 'Categoría', 'Descripción', 'Monto', 'Cuotas',
           'Cuota Actual', 'Monto Cuota', 'Mes Impacto', 'ID']


class Hoja:
    def __init__(self, registros=None):
        self.registros = deepcopy(registros or [])
        self.lecturas = 0
        self.escrituras = []
        self.falla = None

    def get_all_records(self):
        self.lecturas += 1
        return deepcopy(self.registros)

    def get_all_values(self):
        return [HEADERS] + [list(g.values()) for g in self.registros]

    def append_row(self, fila, **opciones):
        if self.falla == 'antes':
            self.falla = None
            raise TimeoutError('antes de guardar')
        self.registros.append(dict(zip(HEADERS, fila)))
        self.escrituras.append((fila, opciones))
        if self.falla == 'despues':
            self.falla = None
            raise TimeoutError('después de guardar')

    def update(self, **opciones):
        self.escrituras.append(opciones)


@pytest.fixture
def almacen():
    instancia = bot.BotDeGastos()
    instancia._hojas = {nombre: Hoja() for nombre in ['Gastos', 'Resumen Mensual', 'Proyección']}
    return instancia


@pytest.mark.parametrize('texto,esperado', [('1500', 1500), ('1.500', 1500),
    ('1.500,50', 1500.5), ('1500.50', 1500.5), ('1500,50', 1500.5), ('0,01', .01)])
def test_monto_argentino(texto, esperado):
    assert bot.parsear_monto(texto) == esperado


@pytest.mark.parametrize('texto', ['0', '-1', 'NaN', 'inf', '', '1,500', '1.50.0', '1e3', '0.001'])
def test_monto_invalido(texto):
    with pytest.raises(ValueError):
        bot.parsear_monto(texto)


def test_guardado_no_recalcula_y_preserva_historico(almacen):
    historico = dict(zip(HEADERS, ['2024-01-01 10:00:00', 'Ana', 'Salud', 'Histórico', 600, 3, 2, 200, '2024-02', '']))
    almacen._hojas['Gastos'].registros.append(deepcopy(historico))
    assert almacen._anotar_gasto_sync('Ana', 'Comida', 'Almuerzo', 1500, 'nuevo')
    hoja = almacen._hojas['Gastos']
    assert hoja.registros[0] == historico
    assert hoja.lecturas == 0
    assert len(hoja.escrituras) == 1
    assert hoja.escrituras[0][1]['value_input_option'] == 'RAW'
    assert hoja.registros[-1]['Cuotas'] == 1
    assert hoja.registros[-1]['ID'] == 'nuevo'
    assert not almacen._hojas['Resumen Mensual'].escrituras
    assert not almacen._hojas['Proyección'].escrituras


@pytest.mark.parametrize('falla', ['antes', 'despues'])
def test_reintento_sin_duplicados(almacen, falla):
    almacen._hojas['Gastos'].falla = falla
    assert not almacen._anotar_gasto_sync('Ana', 'Casa', 'Luz', 100, 'id-1')
    assert almacen._anotar_gasto_sync('Ana', 'Casa', 'Luz', 100, 'id-1')
    assert almacen._anotar_gasto_sync('Ana', 'Casa', 'Luz', 100, 'id-1')
    assert len(almacen._hojas['Gastos'].registros) == 1


def test_cache_invalidada_al_guardar(almacen):
    almacen._leer_gastos()
    almacen._leer_gastos()
    assert almacen._hojas['Gastos'].lecturas == 1
    almacen._anotar_gasto_sync('Ana', 'Casa', 'Luz', 100, 'id-1')
    assert len(almacen._leer_gastos()) == 1
    assert almacen._hojas['Gastos'].lecturas == 2


def test_derivadas_comparten_lectura_y_no_borran(almacen):
    almacen._anotar_gasto_sync('Ana', 'Casa', 'Luz', 100, 'id-1')
    almacen._refrescar_derivadas_sync()
    assert almacen._hojas['Gastos'].lecturas == 1
    assert len(almacen._hojas['Resumen Mensual'].escrituras) == 1
    assert len(almacen._hojas['Proyección'].escrituras) == 1
    assert almacen._version_actualizada == almacen._version


def test_historico_cuotas_y_orden_por_hora(almacen):
    almacen._hojas['Gastos'].registros = [
        dict(zip(HEADERS, ['2024-01-01 08:00:00', 'Ana', 'Salud', 'Temprano', 600, 3, 1, 200, '2024-01', ''])),
        dict(zip(HEADERS, ['2024-01-01 15:00:00', 'Ana', 'Salud', 'Tarde', 90, 1, 1, 90, '2024-01', '']))]
    info = almacen._sacar_resumen_filtrado_sync('2024-01', 'salud')
    assert info['total'] == 290
    assert info['cantidad'] == 2
    assert info['detalles'][0]['descripcion'] == 'Tarde'
    almacen._refrescar_derivadas_sync()
    fila = almacen._hojas['Resumen Mensual'].escrituras[0]['values'][1]
    assert fila[:4] == ['2024-01', 290, 90, 200]


def test_mes_invalido_y_rangos(almacen):
    assert almacen._normalizar_mes_para_resumen('2026-13', []) is None
    assert almacen._normalizar_mes_para_resumen('2026-01:2026-99', []) is None
    assert almacen._normalizar_mes_para_resumen('2026-01:2026-03', []) == ('RANGE', '2026-01', '2026-03')


def entorno(almacen, monkeypatch, texto, datos=None, usuario=1):
    almacen.gente_permitida = {'1'}
    monkeypatch.setattr(bot, 'bot_app', almacen)
    update = SimpleNamespace(effective_user=SimpleNamespace(id=usuario, username='Ana', first_name='Ana'),
                             effective_chat=SimpleNamespace(id=1))
    update.message = SimpleNamespace(text=texto, message_id=42, reply_text=AsyncMock())
    update.effective_message = update.message
    context = SimpleNamespace(user_data=datos or {}, application=SimpleNamespace(persistence=None))
    return update, context


def test_rapido_categoria_y_legacy(almacen, monkeypatch):
    for texto, categoria in [('Comida | 1.500,50 | **Almuerzo**', 'Comida'), ('1500 Nafta', 'Sin clasificar')]:
        update, context = entorno(almacen, monkeypatch, texto)
        update.message.message_id += len(almacen._hojas['Gastos'].registros)
        assert asyncio.run(bot.leer_mensaje_al_toque(update, context)) == bot.ConversationHandler.END
        assert almacen._hojas['Gastos'].registros[-1]['Categoría'] == categoria
        assert context.user_data == {}
        assert 'parse_mode' not in update.message.reply_text.call_args.kwargs


def test_falla_preserva_datos_y_reintenta(almacen, monkeypatch):
    update, context = entorno(almacen, monkeypatch, 'Casa | 100 | Luz')
    almacen._hojas['Gastos'].falla = 'despues'
    assert asyncio.run(bot.leer_mensaje_al_toque(update, context)) == bot.PASO_DETALLE
    assert context.user_data['detalle_compra'] == 'Luz'
    # Simular reinicio del estado de memoria: el borrador conserva incertidumbre.
    almacen._inciertos.clear()
    update.message.text = '🔄 Reintentar'
    assert asyncio.run(bot.guardar_borrador(update, context)) == bot.ConversationHandler.END
    assert len(almacen._hojas['Gastos'].registros) == 1


@pytest.mark.parametrize('funcion', [bot.arrancar_gasto_guiado, bot.leer_mensaje_al_toque,
    bot.arrancar_resumen_guiado, bot.mostrar_futuro, bot.guardar_borrador])
def test_permisos_en_todas_las_entradas(almacen, monkeypatch, funcion):
    update, context = entorno(almacen, monkeypatch, 'Casa | 100 | Luz', usuario=2)
    assert asyncio.run(funcion(update, context)) == bot.ConversationHandler.END
    assert not almacen._hojas['Gastos'].registros
    assert almacen._hojas['Gastos'].lecturas == 0


def test_campos_vacios_y_volver(almacen, monkeypatch):
    update, context = entorno(almacen, monkeypatch, '   ')
    assert asyncio.run(bot.agarrar_categoria(update, context)) == bot.PASO_CATEGORIA
    context.user_data.update(categoria_elegida='Casa', plata_gastada=100)
    assert asyncio.run(bot.agarrar_detalle_y_guardar(update, context)) == bot.PASO_DETALLE
    assert asyncio.run(bot.volver(update, context)) == bot.PASO_PLATA
    assert context.user_data['categoria_elegida'] == 'Casa'
    assert asyncio.run(bot.volver(update, context)) == bot.PASO_CATEGORIA


def test_menu_no_se_guarda_como_detalle(almacen, monkeypatch):
    update, context = entorno(almacen, monkeypatch, '❓ Ayuda',
                             {'categoria_elegida': 'Casa', 'plata_gastada': 100})
    assert asyncio.run(bot.navegar(bot.agarrar_detalle_y_guardar)(update, context)) is None
    assert 'detalle_compra' not in context.user_data
    assert not almacen._hojas['Gastos'].registros


def test_limite_unicode_palabra_larga():
    texto = '🐜' * 5000 + '\n' + 'x' * 10000
    partes = bot.dividir_texto_en_bloques(texto, 4000)
    assert ''.join(partes) == texto
    assert all(len(p.encode('utf-16-le')) // 2 <= 4000 for p in partes)


def test_fallo_agregados_no_invalida_guardado(almacen, monkeypatch):
    assert almacen._anotar_gasto_sync('Ana', 'Casa', 'Luz', 100, 'id-1')
    def fallar(**kwargs):
        raise TimeoutError('agregado no disponible')
    monkeypatch.setattr(almacen._hojas['Resumen Mensual'], 'update', fallar)
    with pytest.raises(TimeoutError):
        almacen._refrescar_derivadas_sync()
    assert almacen._version_actualizada != almacen._version
    assert len(almacen._hojas['Gastos'].registros) == 1
    assert almacen._anotar_gasto_sync('Ana', 'Casa', 'Luz', 100, 'id-1')
    assert len(almacen._hojas['Gastos'].registros) == 1


def test_cambio_durante_refresco_queda_pendiente(almacen, monkeypatch):
    almacen._anotar_gasto_sync('Ana', 'Casa', 'Luz', 100, 'id-1')
    original = almacen._refrescar_proyeccion
    def con_guardado(datos):
        assert almacen._anotar_gasto_sync('Ana', 'Comida', 'Cena', 200, 'id-2')
        original(datos)
    monkeypatch.setattr(almacen, '_refrescar_proyeccion', con_guardado)
    almacen._refrescar_derivadas_sync()
    assert almacen._version_actualizada < almacen._version
    monkeypatch.setattr(almacen, '_refrescar_proyeccion', original)
    almacen._refrescar_derivadas_sync()
    assert almacen._version_actualizada == almacen._version
    fila = almacen._hojas['Resumen Mensual'].escrituras[-1]['values'][1]
    assert fila[1] == 300


def test_persistencia_recupera_borrador(tmp_path):
    async def ejecutar():
        path = tmp_path / 'estado.pickle'
        persistence = bot.PicklePersistence(filepath=path)
        datos = {'gasto_id': 'id-1', 'guardado_incierto': True,
                 'categoria_elegida': 'Casa', 'plata_gastada': 100, 'detalle_compra': 'Luz'}
        await persistence.update_user_data(1, datos)
        await persistence.update_conversation('gastos', (1, 1), bot.PASO_DETALLE)
        await persistence.flush()
        recuperada = bot.PicklePersistence(filepath=path)
        assert (await recuperada.get_user_data())[1] == datos
        assert (await recuperada.get_conversations('gastos'))[(1, 1)] == bot.PASO_DETALLE
    asyncio.run(ejecutar())


def test_guardado_persiste_antes_de_escribir(almacen, monkeypatch):
    update, context = entorno(almacen, monkeypatch, 'Casa | 100 | Luz')
    eventos = []
    async def persistir():
        eventos.append('persistir')
        assert context.user_data['guardado_incierto']
    async def flush():
        eventos.append('flush')
    context.application = SimpleNamespace(
        persistence=SimpleNamespace(flush=flush), update_persistence=persistir,
        mark_data_for_update_persistence=lambda **kwargs: None)
    original = almacen._hojas['Gastos'].append_row
    def escribir(*args, **kwargs):
        assert eventos == ['persistir', 'flush']
        original(*args, **kwargs)
    monkeypatch.setattr(almacen._hojas['Gastos'], 'append_row', escribir)
    assert asyncio.run(bot.leer_mensaje_al_toque(update, context)) == bot.ConversationHandler.END


def test_guardia_global_interrumpe_antes_de_handlers(almacen, monkeypatch):
    update, context = entorno(almacen, monkeypatch, '/resumen', usuario=2)
    with pytest.raises(bot.ApplicationHandlerStop):
        asyncio.run(bot.verificar_acceso(update, context))


def test_categoria_markdown_y_emoji_no_rompe_confirmacion(almacen, monkeypatch):
    update, context = entorno(almacen, monkeypatch, 'Salud_[x] | 100 | ' + '🐜' * 2000)
    assert asyncio.run(bot.leer_mensaje_al_toque(update, context)) == bot.ConversationHandler.END
    respuestas = update.message.reply_text.call_args_list
    assert len(respuestas) == 2
    assert all(len(c.args[0].encode('utf-16-le')) // 2 <= 4096 for c in respuestas)


def test_aplicacion_persiste_borrador_real(tmp_path, almacen, monkeypatch):
    async def ejecutar():
        persistence = bot.PicklePersistence(filepath=tmp_path / 'estado.pickle')
        app = bot.Application.builder().token('123456:token-de-prueba').persistence(persistence).build()
        update, contexto = entorno(almacen, monkeypatch, 'Casa | 100 | Luz')
        contexto.application = app
        contexto.user_data = app.user_data[1]
        almacen._hojas['Gastos'].falla = 'antes'
        assert await bot.leer_mensaje_al_toque(update, contexto) == bot.PASO_DETALLE
        guardado = await bot.PicklePersistence(filepath=tmp_path / 'estado.pickle').get_user_data()
        assert guardado[1]['guardado_incierto']
        assert guardado[1]['detalle_compra'] == 'Luz'
        assert guardado[1]['gasto_id'] == contexto.user_data['gasto_id']
    asyncio.run(ejecutar())


def test_agrupar_registros_con_historial_grande(almacen):
    historicos = [dict(zip(HEADERS, ['2024-01-01 08:00:00', 'Ana', 'Casa', f'Histórico {i}',
                                   10, 1, 1, 10, '2024-01', ''])) for i in range(10000)]
    almacen._hojas['Gastos'].registros = deepcopy(historicos)
    for i in range(20):
        assert almacen._anotar_gasto_sync('Ana', 'Comida', 'Almuerzo', 100, f'nuevo-{i}')
    assert almacen._hojas['Gastos'].lecturas == 0
    almacen._refrescar_derivadas_sync()
    assert almacen._hojas['Gastos'].lecturas == 1
    assert almacen._hojas['Gastos'].registros[:10000] == historicos
    assert len(almacen._hojas['Resumen Mensual'].escrituras) == 1
    assert len(almacen._hojas['Proyección'].escrituras) == 1
