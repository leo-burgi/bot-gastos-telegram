import importlib


bot = importlib.import_module('bot')


def test_dividir_texto_en_bloques_respeta_limite():
    texto = "\n".join(["A"] * 1000)

    bloques = bot.dividir_texto_en_bloques(texto, limite=100)

    assert bloques
    assert all(len(bloque) <= 100 for bloque in bloques)
    assert "\n".join(bloques) == texto


def test_normalizar_mes_no_reconoce_actual_ni_ultimo():
    resumen = bot.BotDeGastos()

    assert resumen._normalizar_mes_para_resumen('actual', []) is None
    assert resumen._normalizar_mes_para_resumen('ultimo', []) is None
