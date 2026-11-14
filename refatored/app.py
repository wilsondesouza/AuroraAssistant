import sys
from pathlib import Path

# Garantir que a raiz do projeto esteja no sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import time
import logging
import argparse

from refatored.config import setup_logging, validate_config
from refatored.speech_input import speech_input
from refatored.speech_output import play_confirmation, play_error, falar
from refatored.intent_router import intent_router
from refatored.music import music_player

logger = logging.getLogger("aurora.app")


def print_banner():
    banner = """
    ╔═════════════════════════════════════════════════╗
    ║             AURORA ASSISTANT 2.0                ║
    ║   Automação Residencial | Música | Conversa     ║
    ╚═════════════════════════════════════════════════╝
    """
    print(banner)


def configure_output_encoding():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")


def run_cli_mode():
    """Modo interativo por terminal para testes rápidos sem depender de microfone."""
    logger.info("Iniciando Aurora Assistant em modo texto (CLI)...")
    print("\nModo texto ativado. Digite seus comandos ou 'sair' para encerrar.\n")

    while True:
        try:
            comando = input("\n[Você]: ").strip()
            if not comando:
                continue
            if comando.lower() in ("sair", "exit", "quit"):
                print("Encerrando Aurora Assistant.")
                music_player.stop()
                break

            resultado = intent_router.processar_mensagem(comando)
            print(f"[Aurora]: {resultado.get('message')}")

        except KeyboardInterrupt:
            print("\nEncerrando.")
            music_player.stop()
            break
        except Exception as e:
            logger.error(f"Erro no processamento: {e}")


def run_voice_mode():
    """Modo principal contínuo acionado por voz (wake word 'aurora')."""
    logger.info("Iniciando Aurora Assistant em modo de voz...")

    # 1. Inicializar entrada de voz e calibrar microfone
    if not speech_input.initialize():
        logger.error("Falha ao inicializar subsistema de voz. Encerrando.")
        return

    speech_input.calibrate_ambient_noise()
    logger.info("Aurora pronta e aguardando pela palavra de ativação...")
    print("\nPronto! Diga 'Aurora' para ativar...\n")

    while True:
        try:
            if speech_input.aguardar_ativacao():
                play_confirmation(blocking=True)
                logger.info("Escutando comando do usuário...")
                comando = speech_input.escutar_comando()

                if comando:
                    intent_router.processar_mensagem(comando)
                else:
                    logger.debug("Nenhum comando detectado após ativação.")
            else:
                time.sleep(0.15)

        except KeyboardInterrupt:
            logger.info("Interrupção pelo usuário (Ctrl+C). Encerrando...")
            music_player.stop()
            break
        except Exception as e:
            logger.error(f"Erro inesperado no loop principal: {e}")
            time.sleep(0.5)


def main():
    configure_output_encoding()

    parser = argparse.ArgumentParser(description="Aurora Voice Assistant")
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Executar em modo texto interativo (sem microfone)"
    )
    args = parser.parse_args()

    # Configurar logging padronizado
    setup_logging(level=logging.INFO)
    print_banner()

    # Validar e exibir status das configurações
    status = validate_config()
    logger.info("Status dos serviços configurados:")
    for servico, ok in status.items():
        marcador = "✓" if ok else "✗"
        logger.info(f"  [{marcador}] {servico.upper()}")

    if args.cli:
        run_cli_mode()
    else:
        run_voice_mode()


if __name__ == "__main__":
    main()
