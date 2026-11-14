import re
import logging
from datetime import datetime
from typing import Optional

try:
    import requests
except ImportError:
    requests = None

from refatored.config import (
    OPENWEATHER_KEY,
    OPENWEATHER_CITY,
    OPENWEATHER_TIMEOUT,
    sanitize_for_log,
)

logger = logging.getLogger(__name__)

# ==========================================
# RECONHECIMENTO DE PADRÕES LOCAIS
# ==========================================

RE_TIME = re.compile(
    r'\b(que\s+horas?\s+s[ãa]o|que\s+horas?\s+[eé]|qual\s+a\s+hora|hora\s+certa|horas?\s+s[ãa]o|diga\s+as\s+horas|tem)\b',
    re.IGNORECASE
)

RE_WEATHER = re.compile(
    r'\b(previs[ãa]o\s+do\s+tempo|como\s+est[áa]\s+o\s+tempo|como\s+t[áa]\s+o\s+tempo|temperatura(?:\s+hoje)?|clima(?:\s+hoje)?|vai\s+chover)\b',
    re.IGNORECASE
)

WEATHER_CONDITIONS_PT_BR = {
    200: "Está tendo trovoadas com chuva fraca.",
    201: "Está tendo trovoadas com chuva.",
    202: "Está tendo trovoadas com chuva forte.",
    210: "Está tendo trovoadas fracas.",
    211: "Está tendo trovoadas.",
    212: "Está tendo trovoadas fortes.",
    221: "Está tendo trovoadas irregulares.",
    230: "Está tendo trovoadas com garoa fraca.",
    231: "Está tendo trovoadas com garoa.",
    232: "Está tendo trovoadas com garoa intensa.",
    300: "Está tendo garoa fraca.",
    301: "Está tendo garoa.",
    302: "Está tendo garoa intensa.",
    310: "Está tendo garoa fraca.",
    311: "Está tendo garoa.",
    312: "Está tendo garoa intensa.",
    313: "Está tendo chuva e garoa.",
    314: "Está tendo chuva e garoa intensas.",
    321: "Está tendo pancadas de garoa.",
    500: "Está tendo chuva fraca.",
    501: "Está tendo chuva moderada.",
    502: "Está tendo chuva forte.",
    503: "Está tendo chuva muito forte.",
    504: "Está tendo chuva extremamente forte.",
    511: "Está tendo chuva congelante.",
    520: "Está tendo pancadas de chuva fracas.",
    521: "Está tendo pancadas de chuva.",
    522: "Está tendo pancadas de chuva fortes.",
    531: "Está tendo pancadas irregulares de chuva.",
    600: "Está tendo neve fraca.",
    601: "Está tendo neve.",
    602: "Está tendo neve intensa.",
    611: "Está tendo chuva com neve.",
    612: "Está tendo chuva com neve fraca.",
    613: "Está tendo pancadas de chuva com neve.",
    615: "Está tendo chuva fraca com neve.",
    616: "Está tendo chuva com neve.",
    620: "Está tendo pancadas fracas de neve.",
    621: "Está tendo pancadas de neve.",
    622: "Está tendo pancadas intensas de neve.",
    701: "Está tendo névoa.",
    711: "Está tendo fumaça.",
    721: "Está tendo névoa seca.",
    731: "Está tendo poeira no ar.",
    741: "Está tendo nevoeiro.",
    751: "Está tendo areia no ar.",
    761: "Está tendo poeira no ar.",
    762: "Está tendo cinzas vulcânicas no ar.",
    771: "Está tendo rajadas de vento.",
    781: "Está tendo um tornado.",
    800: "O céu está limpo.",
    801: "O céu tem poucas nuvens.",
    802: "O céu está parcialmente nublado.",
    803: "O céu está muito nublado.",
    804: "O céu está encoberto.",
}


# ==========================================
# FORMATAÇÃO DE HORA EM PORTUGUÊS
# ==========================================

def number_to_words_ptbr(n: int) -> str:
    """Converte números de 0 a 59 em palavras em português."""
    unidades = {
        0: "zero", 1: "um", 2: "dois", 3: "três", 4: "quatro",
        5: "cinco", 6: "seis", 7: "sete", 8: "oito", 9: "nove",
        10: "dez", 11: "onze", 12: "doze", 13: "treze", 14: "quatorze",
        15: "quinze", 16: "dezesseis", 17: "dezessete", 18: "dezoito", 19: "dezenove"
    }
    dezenas = {20: "vinte", 30: "trinta", 40: "quarenta", 50: "cinquenta"}

    if n < 20:
        return unidades.get(n, str(n))
    if n < 60:
        d = (n // 10) * 10
        u = n % 10
        if u == 0:
            return dezenas.get(d, str(d))
        return f"{dezenas.get(d, '')} e {unidades.get(u, '')}"
    return str(n)


def format_time_ptbr(dt: datetime) -> str:
    """Formata a data/hora para fala natural em português."""
    h24 = dt.hour
    m = dt.minute

    # Determinar período do dia
    if 0 <= h24 < 5:
        periodo = "da madrugada"
    elif 5 <= h24 < 12:
        periodo = "da manhã"
    elif 12 <= h24 < 18:
        periodo = "da tarde"
    else:
        periodo = "da noite"

    h12 = h24 % 12
    if h12 == 0:
        h12 = 12

    hora_extenso = number_to_words_ptbr(h12)
    palavra_hora = "uma" if h12 == 1 else ("duas" if h12 == 2 else hora_extenso)

    if m == 0:
        plural = "hora" if h12 == 1 else "horas"
        return f"Agora são {palavra_hora} {plural} {periodo}."

    minuto_extenso = number_to_words_ptbr(m)
    return f"Agora são {palavra_hora} e {minuto_extenso} {periodo}."


def get_time_response(mensagem: str) -> Optional[str]:
    """Retorna resposta sobre as horas se a mensagem corresponder à intenção."""
    if not mensagem:
        return None
    if RE_TIME.search(mensagem.lower()):
        return format_time_ptbr(datetime.now())
    return None


# ==========================================
# CLIMA VIA OPENWEATHER
# ==========================================

def _weather_condition_ptbr(condition_id: int) -> str:
    """Converte o código OpenWeather em uma frase curta e natural em pt-BR."""
    return WEATHER_CONDITIONS_PT_BR.get(condition_id, "As condições do tempo variam.")

def get_weather_response(mensagem: str) -> Optional[str]:
    """Retorna previsão do tempo se a mensagem corresponder à intenção."""
    if not mensagem:
        return None

    if not RE_WEATHER.search(mensagem.lower()):
        return None

    if not OPENWEATHER_KEY:
        logger.warning("OPENWEATHER_KEY não configurada no ambiente.")
        return "Minha chave de previsão do tempo não está configurada."

    if requests is None:
        logger.error("Biblioteca 'requests' não instalada.")
        return "Biblioteca de conexão não disponível."

    cidade = OPENWEATHER_CITY
    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {
        "q": cidade,
        "appid": OPENWEATHER_KEY,
        "units": "metric",
        "lang": "pt_br"
    }

    try:
        logger.info("Consultando clima para '%s'...", cidade)
        resp = requests.get(url, params=params, timeout=OPENWEATHER_TIMEOUT)

        if resp.status_code != 200:
            logger.error(
                "Erro OpenWeather HTTP %s: %s",
                resp.status_code,
                sanitize_for_log(resp.text[:200]),
            )
            return "Não consegui obter o clima agora. Tente mais tarde."

        data = resp.json()
        main = data["main"]
        condition_id = int(data["weather"][0]["id"])
        temp = round(float(main["temp"]))
        feels_like = round(float(main["feels_like"]))
        humidity = int(main["humidity"])
        wind_speed = round(float(data["wind"]["speed"]) * 3.6)

        resposta = (
            f"Em {cidade}, {_weather_condition_ptbr(condition_id).lower()} "
            f"A temperatura está em {temp} graus, com sensação térmica de "
            f"{feels_like} graus. A umidade relativa do ar está em {humidity}%. "
            f"E os ventos estão a {wind_speed} quilômetros por hora."
        )

        return resposta

    except requests.exceptions.Timeout:
        logger.error("Timeout ao consultar OpenWeather.")
        return "O serviço de clima demorou muito para responder."
    except requests.exceptions.RequestException as error:
        logger.error("Erro de conexão ao consultar OpenWeather (%s).", type(error).__name__)
        return "Não consegui obter as informações de clima no momento."
    except (IndexError, KeyError, TypeError, ValueError) as e:
        logger.error("Resposta inválida do OpenWeather: %s", e)
        return "Não consegui obter as informações de clima no momento."
