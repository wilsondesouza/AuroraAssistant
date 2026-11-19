import os
import sys
from pathlib import Path

# Garantir que a raiz do projeto esteja no sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import time
import signal
import logging
import argparse

from refatored.config import (
    setup_logging,
    validate_config,
    CONTINUOUS_CONVERSATION,
    CONTINUOUS_MAX_TURNS,
    CONTINUOUS_LISTEN_TIMEOUT,
)
from refatored.domus_bridge import TURN_LOCK, running_bridge, stop_mobile_intake
from refatored.speech_input import speech_input
from refatored.speech_output import play_confirmation, play_error, falar
from refatored.intent_router import intent_router
from refatored.music import music_player
from refatored.skills import timer_manager

logger = logging.getLogger("aurora.app")


def print_banner():
    banner = """
    ╔═════════════════════════════════════════════════╗
    ║             AURORA ASSISTANT 2.5                ║
    ║   Automação | Música | Memória | Conversa Viva  ║
    ╚═════════════════════════════════════════════════╝
    """
    print(banner)


def configure_output_encoding():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")


def _shutdown_services():
    """Encerra reprodução de música e timers pendentes com segurança."""
    stop_mobile_intake()  # um POST não pode recriar um timer/player após a limpeza
    music_player.stop()
    timer_manager.cancel_all()


def _install_signal_handlers():
    """
    Garante desligamento limpo quando o systemd envia SIGTERM (systemctl stop/restart).
    Sem isso, o processo morre deixando o mpg123 tocando e timers órfãos.
    """
    def _handle(signum, _frame):
        logger.info("Sinal %s recebido; encerrando serviços com segurança...", signum)
        _shutdown_services()
        raise SystemExit(0)

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _handle)
        except (ValueError, OSError):
            logger.debug("Não foi possível registrar handler para o sinal %s.", sig)


def _is_continuous_conversation_enabled() -> bool:
    env_val = os.getenv("CONTINUOUS_CONVERSATION")
    if env_val is not None:
        return env_val.lower().strip() in ("1", "true", "yes", "on")
    return CONTINUOUS_CONVERSATION


def _executar_loop_followup_voz(resultado_inicial: dict) -> None:
    """
    Quando a resposta da Aurora termina em pergunta ('?'), toca o bip de confirmação
    e escuta a resposta do usuário por alguns segundos sem exigir repetir 'Aurora'.
    """
    if not _is_continuous_conversation_enabled():
        return

    max_turns = max(
        1, int(os.getenv("CONTINUOUS_MAX_TURNS", str(CONTINUOUS_MAX_TURNS)))
    )
    listen_timeout = float(
        os.getenv("CONTINUOUS_LISTEN_TIMEOUT", str(CONTINUOUS_LISTEN_TIMEOUT))
    )

    resultado = resultado_inicial or {}
    turno = 0

    while resultado.get("expect_followup") and turno < max_turns:
        turno += 1
        logger.info(
            f"Conversa contínua ({turno}/{max_turns}): Aurora fez uma pergunta; "
            f"emitindo bip e aguardando resposta por {listen_timeout:.1f}s..."
        )
        play_confirmation(blocking=True)
        resposta_usuario = speech_input.escutar_comando(timeout=listen_timeout)

        if not resposta_usuario:
            logger.info("Silêncio na janela de continuação; retornando à escuta da wake word.")
            break

        resultado = intent_router.processar_mensagem(
            resposta_usuario,
            is_followup=True,
        )


def run_cli_mode():
    """Modo interativo por terminal para testes rápidos sem depender de microfone."""
    logger.info("Iniciando Aurora Assistant em modo texto (CLI)...")
    print("\nModo texto ativado. Digite seus comandos ou 'sair' para encerrar.\n")

    em_followup = False
    while True:
        try:
            prompt_label = "\n[Você (continuação)]: " if em_followup else "\n[Você]: "
            comando = input(prompt_label).strip()
            if not comando:
                em_followup = False
                continue
            if comando.lower() in ("sair", "exit", "quit"):
                print("Encerrando Aurora Assistant.")
                _shutdown_services()
                break

            with TURN_LOCK:
                resultado = intent_router.processar_mensagem(comando, is_followup=em_followup)
            print(f"[Aurora]: {resultado.get('message')}")
            em_followup = bool(
                _is_continuous_conversation_enabled() and resultado.get("expect_followup")
            )

        except KeyboardInterrupt:
            print("\nEncerrando.")
            _shutdown_services()
            break
        except Exception as e:
            logger.error(f"Erro no processamento: {e}")
            em_followup = False


def run_voice_mode():
    """Modo principal contínuo acionado por voz (wake word 'aurora' + follow-up inteligente)."""
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
                # Não abrir o microfone sobre uma resposta móvel; não segurar o lock
                # durante a espera ociosa pela palavra de ativação.
                if not TURN_LOCK.acquire(blocking=False):
                    continue
                try:
                    play_confirmation(blocking=True)
                    logger.info("Escutando comando do usuário...")
                    comando = speech_input.escutar_comando()

                    if comando:
                        resultado = intent_router.processar_mensagem(comando, is_followup=False)
                        _executar_loop_followup_voz(resultado)
                    else:
                        logger.debug("Nenhum comando detectado após ativação.")
                finally:
                    TURN_LOCK.release()
            else:
                time.sleep(0.15)

        except KeyboardInterrupt:
            logger.info("Interrupção pelo usuário (Ctrl+C). Encerrando...")
            _shutdown_services()
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
    _install_signal_handlers()
    print_banner()

    # Validar e exibir status das configurações
    status = validate_config()
    logger.info("Status dos serviços configurados:")
    for servico, ok in status.items():
        marcador = "✓" if ok else "✗"
        logger.info(f"  [{marcador}] {servico.upper()}")

    with running_bridge():
        if args.cli:
            run_cli_mode()
        else:
            run_voice_mode()


if __name__ == "__main__":
    main()
