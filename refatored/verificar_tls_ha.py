"""Execute da raiz, com o Python do serviço: python -m refatored.verificar_tls_ha."""
import sys
from urllib.parse import urlsplit

from refatored import home_assistant as ha


def main():
    if ha.requests is None:
        print('requests ausente: use o interpretador do auroraassistant.service.')
        return 2
    try:
        options = ha._transport_options(authenticated=False)
        if urlsplit(ha.HA_URL).scheme != 'https':
            print('HA_URL não é HTTPS. Diagnóstico interrompido antes da conexão.')
            return 2
        print('Verificando o nome e a cadeia TLS, sem token HA e sem seguir redirects.')
        print('CA:', ha.HA_CA_BUNDLE or 'confiança padrão de requests')
        # Não consulta entidades, não exibe corpo/headers e não testa o token.
        with ha.requests.get(ha.HA_URL + '/api/', stream=True, **options) as response:
            code = response.status_code
        print(f'TLS validado. GET /api/ sem autenticação: HTTP {code}.')
        if code in (401, 403):
            print('Recusa de acesso esperada sem credencial. Agora teste pelo Domus.')
        elif code != 200:
            print('Confira rota/proxy do HA. Um status HTTP não é erro de certificado.')
        return 0
    except ha.HAConfigError as exc:
        print(exc)
    except ha.requests.exceptions.SSLError as exc:
        print('Erro de TLS; confira a CA, intermediárias do servidor, SAN e relógio.')
        print(ha.sanitize_for_log(str(exc)))
    except (ha.requests.exceptions.RequestException, OSError, ValueError) as exc:
        print(f'Falha de conexão ou de configuração ({type(exc).__name__}). Confira DNS, porta e acesso ao PEM.')
    return 1


if __name__ == '__main__':
    sys.exit(main())
