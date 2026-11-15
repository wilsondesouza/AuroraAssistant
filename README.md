# 🤖 Aurora Voice Assistant 2.0

Assistente virtual de voz doméstico, inteligente e modular, projetado especialmente para funcionar com alto desempenho e baixo consumo de recursos no **Orange Pi 3 LTS**.

A Aurora combina **reconhecimento de voz** (Speech Recognition ), **automação residencial** (Home Assistant), **streaming de música** (Navidrome/Subsonic), **síntese de voz em alta definição** (Google Cloud TTS) e **inteligência artificial generativa** através de um cliente universal pluggável (Groq, Google Gemini, OpenRouter, Cerebras e Ollama local).

---

## 🌟 Principais Funcionalidades

### 🎙️ Reconhecimento de Voz & Wake Word Local
- **Wake Word determinística**: Escuta contínua pela palavra de ativação `"aurora"`.
- **Transcrição Local via Whisper**: Usa `faster-whisper` (`tiny`, CPU), garantindo baixa latência e privacidade sem depender de APIs externas para escutar comandos.
- **Fallback Automático**: Se o Whisper local falhar, recorre ao Google Speech Recognition.
- **Gestão Limpa de Recursos**: Gravação temporária de áudio em WAV com descarte garantido via context managers (`try...finally`).

### 🏠 Automação Residencial Confiável (Home Assistant)
- **Fast-Path Local**: Comandos diretos e inequívocos (ex: *"ligar a luz da sala"*, *"desligar ar condicionado"*, *"abrir youtube na TV"*) são resolvidos e disparados localmente, sem latência de rede da LLM.
- **Segurança Rigorosa**: O `entity_id` e o domínio são resolvidos **estritamente a partir do registro local de dispositivos** (`DEVICE_REGISTRY`). Parâmetros vindos de IA passam por whitelist e **nunca** sobrescrevem entidades autorizadas.
- **Prevenção de Falsos Positivos**: Parser com expressões regulares de fronteira (`\b`), precedência estrita de desligamento antes de ligamento e rejeição automática de comandos negativos (*"não ligar a luz"*).

### 🧠 Cérebro LLM Pluggável & Multi-Provedores
- **Independência de API**: Alterne facilmente o provedor de IA no arquivo `.env` sem alterar uma única linha de código.
- **Provedores Nativamente Suportados**:
  - **Groq Cloud** *(Altamente Recomendado)*: Inferência ultra-rápida (~500 tokens/s) no tier gratuito para gpt-os e qwen 3.8.
  - **Google Gemini** *(AI Studio)*: Tier gratuito oficial (15 RPM / 1.500 req/dia) via endpoint OpenAI para `gemini-2.0-flash` e `gemini-1.5-flash`.
  - **OpenRouter**: Acesso a modelos com sufixo `:free`.
  - **Cerebras**: Velocidade recorde para Llama 3.1.
  - **Ollama (Rede Local)**: 100% gratuito, offline e sem limites, consultando um PC na mesma rede Wi-Fi.
- **Fallback Automático de Rate Limit**: Se o provedor primário retornar HTTP 429 (limite de requisições excedido) ou instabilidade temporária, o sistema redireciona a chamada instantaneamente para o provedor secundário de reserva.
- **Personalidade Humanizada e Acolhedora**: Prompt afinado para linguagem oral, sem markdown, sem emojis e com respostas curtas e didáticas, ideal para pessoas idosas ou sem familiaridade com tecnologia.

### 🎵 Streaming de Música Local (Navidrome)
- **Integração Subsonic API**: Busca faixas aleatórias no servidor Navidrome local.
- **Reprodução Concorrente Thread-Safe**: Controlador thread-safe (`MusicPlayer`) que suporta parada, avanço de faixa, reprodução única e modo contínuo.
- **Proteção de Credenciais**: Senhas e tokens nunca são salvos em logs nem em arquivos de playlist; autenticação moderna via salt/token MD5.
- **Compatibilidade de Reprodutores**: Seleção automática entre `mpg123`, `ffplay`, `vlc` ou reprodutor do sistema.

### 🗣️ Síntese de Voz Pluggável & Prosódia Expressiva (TTS)
- **Cliente TTS Multi-Provedor (`tts_client.py`)**: Alterne via `.env` (`TTS_PROVIDER`) entre:
  - **Google Cloud TTS (`google`)**: Voz neural de alta fidelidade em português brasileiro (`pt-BR-Chirp3-HD-Erinome`).
  - **ElevenLabs (`elevenlabs`)**: Suporte nativo aos modelos `eleven_multilingual_v2` (atuação rica em pt-BR), `eleven_flash_v2_5` (baixa latência) e `eleven_v3`, com controle fino de `stability` e `style`.
  - **OpenRouter Audio Speech (`openrouter`)**: Integração via `/api/v1/audio/speech` (ex: `openai/gpt-4o-mini-tts-2025-12-15` com `instructions` de direção vocal carioca e empacotamento automático WAV para modelos PCM).
- **Cadeia de Fallback Automático**: Configure `TTS_FALLBACK_PROVIDERS=elevenlabs,openrouter` para contingência automática em caso de queda ou limite de cota; se todos falharem (ou sem internet), reproduz o áudio estático de contingência (`config/music/falha_tts.wav`).
- **Prosódia Conversacional Carioca (pt-BR / RJ)**: System prompt e pipeline fonético otimizados para preservar pausas dramáticas (`—`), atuação vocal em citações (`'...'`), reticências (`...`), entonação de pergunta final (`?`) e leitura natural por extenso de horários e medidas.

### ⏱️ Habilidades Rápidas, Timers, Memória da Casa & Conversa Contínua
- **Hora Certa por Extenso e Clima (OpenWeather)**: Respostas imediatas em português natural.
- **Janela de Contexto Deslizante + Conversa Contínua**: Mantém memória curta dos últimos turnos em RAM (com expiração automática de 3 min) e abre escuta automática com bip quando a Aurora encerra uma fala fazendo uma pergunta (`?`).
- **Multi-Comando e Anáfora no Home Assistant**: Suporta comandos compostos (*"apaga a luz da sala e liga o ar condicionado"*) e referências ao último dispositivo (*"agora apaga ela"*), além de consultar estados (*"tem alguma luz ligada em casa?"*).
- **Memória da Casa (Mini-RAG Ultra-Leve em SQLite)**: Guarda e recupera notas permanentes da família por voz (*"Aurora, lembra que o remédio da vó é às 8h na caixa azul"*) usando `sqlite3` FTS5 nativo + Embeddings semânticos gratuitos opcionais via Gemini API (0 MB de peso em IA local no Orange Pi).
- **Timers Falados, Música Atual e Tool Calling Seletivo**: Cronômetros em thread (*"me avisa daqui a 10 minutos pra olhar o forno"*), consulta da faixa atual do Navidrome e *Sentence-Level Streaming* da LLM para o TTS.

---

## 🧱 Arquitetura e Estrutura do Projeto

O projeto foi totalmente refatorado e modularizado na pasta [`refatored`].

```plaintext
AuroraAssistant/
├── .env                              ← Arquivo de configuração ativo (chaves, URLs e credenciais)
├── .env.example                      ← Modelo limpo para novas instalações
├── requirements.txt                  ← Dependências Python do projeto
├── passo-a-passo(inicio-automatico).txt ← Guia de configuração do serviço systemd
├── README.md                         ← Esta documentação
│
├── refatored/                        ← Nova arquitetura modular e segura v2.0
│   ├── app.py                        ← Ponto de entrada (Modo Voz e Modo CLI de teste)
│   ├── config.py                     ← Carregamento de ambiente, caminhos e sanitização de logs
│   ├── llm_client.py                 ← Cliente LLM universal (Structured JSON, Tool Calling <=2 passos e Streaming SSE)
│   ├── intent_router.py              ← Roteador central (Fast-path local + Contexto + Mini-RAG + LLM sob demanda)
│   ├── conversation_memory.py        ← Janela deslizante curta em RAM com TTL, anáfora HA e suporte a Prompt Caching
│   ├── memory_store.py               ← Memória da Casa (Mini-RAG em SQLite FTS5 + Embeddings Gemini em Python puro)
│   ├── skills.py                     ← Timers falados em thread, consulta de música atual e registro de Tools
│   ├── home_assistant.py             ← Registry seguro, parser simples/multi/anafórico, lote JSON e consulta de estado HA
│   ├── music.py                      ← Controlador thread-safe do player e Navidrome
│   ├── speech_input.py               ← Microfone, ruído ambiente, wake word e Whisper local
│   ├── tts_client.py                 ← Cliente TTS universal pluggável (Google, ElevenLabs, OpenRouter) + normalização prosódica
│   ├── speech_output.py              ← Gerenciador de fala, boost de volume ALSA, player e fallback de áudio estático
│   ├── local_intents.py              ← Intenções locais rápidas (Hora por extenso e OpenWeather)
│   ├── prompts.py                    ← Prompts otimizados e versionados
│   │
│   └── tests/                        ← Suíte com 42 testes unitários automatizados
│       ├── test_llm_client.py        ← Testes de troca de provedor LLM e fallback
│       ├── test_json_extractor.py    ← Testes de extração JSON com chaves aninhadas
│       ├── test_local_parser.py      ← Testes de ligar vs. desligar e rejeição de negações
│       ├── test_home_assistant.py    ← Testes de segurança contra injeção de entity_id
│       ├── test_music_commands.py    ← Testes de comandos musicais e falsos positivos
│       ├── test_local_intents.py     ← Testes de formatação de data/hora e clima
│       └── test_intent_router.py     ← Testes de integração do fluxo de roteamento
│
├── config/
│   ├── gTTS/                         ← Chaves de serviço e credenciais GCP
│   └── music/                        ← Áudios de confirmação, erro e playlists de cache
│
└── [arquivos legados na raiz]         ← aurora-gpt.py, aurora.py, etc. (mantidos intactos)
```

---

## 🛠️ Instalação e Pré-requisitos

### 1. Dependências do Sistema Operacional (Orange Pi / Linux Debian/Armbian)
Instale os pacotes de áudio e ferramentas necessárias:
```bash
sudo apt update
sudo apt install -y python3-venv python3-pip portaudio19-dev libasound2-dev alsa-utils mpg123 ffmpeg
```

### 2. Configuração do Ambiente Virtual Python
Na pasta do projeto:
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## ⚙️ Configuração das Variáveis de Ambiente (`.env`)

Copie o modelo de exemplo (.env.example) para editar o arquivo [`.env`](.env) na raiz do projeto:

Durante a fala do TTS, a Aurora aumenta temporariamente o controle ALSA configurado e restaura o volume anterior ao terminar. Ajuste `TTS_VOLUME_LEVEL` (0–100, padrão `100`) e `TTS_VOLUME_CONTROL` (padrão `Master`) no `.env` se necessário. O pacote `alsa-utils` fornece o comando `amixer`; sem ele ou sem um controle ALSA disponível, a reprodução segue com o volume atual e o motivo é registrado no log.

---

## 🚀 Como Executar

### 1. Modo Principal de Voz (Microfone + Wake Word)
Inicia o reconhecimento contínuo. Basta falar `"Aurora"` para que o assistente emita o bip de confirmação e aguarde o comando:
```bash
python refatored/app.py
```

### 2. Modo Interativo de Terminal (CLI)
Ideal para desenvolvimento, testes de novas automações ou uso em computadores sem microfone configurado:
```bash
python refatored/app.py --cli
```
*Digite qualquer comando (ex: `que horas são`, `ligar a luz da sala`, `tocar música`, `quem foi Santos Dumont`) e veja a resposta instantaneamente no terminal.*