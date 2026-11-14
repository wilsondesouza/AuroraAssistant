# 🤖 Aurora Assistant 2.0 (Refatorado)

Esta pasta contém a versão refatorada, modular e segura do **Aurora Voice Assistant**, projetada especificamente para operar de maneira rápida, confiável e com baixo consumo de recursos no Orange Pi 3 LTS.

Os arquivos originais na raiz foram mantidos intactos como legados para histórico.

---

## 🎯 Melhorias e Correções Implementadas

Com base no relatório técnico e na revisão do código original (`aurora-gpt.py`), foram realizadas as seguintes correções críticas e arquiteturais:

### 1. Correções Críticas de Segurança e Confiabilidade
- **Prevenção de sobrescrita de `entity_id`**: O `entity_id` agora é resolvido **exclusivamente** a partir do `DEVICE_REGISTRY`. Mesmo que uma LLM retorne um campo `entity_id` dentro de `parameters`, ele é descartado por meio de uma whitelist de parâmetros estrita.
- **Correção no Parser Determinístico (Ligar vs. Desligar)**: No código legado, a busca por substring `ligar` ocorria antes de `desligar`, fazendo com que comandos como *"desligar a luz"* fossem interpretados como `turn_on`. O novo parser usa expressões regulares com limites de palavra (`\b`) e verifica `desligar` antes de `ligar`. Além disso, frases negativas (*"não ligar a luz"*) são rejeitadas por segurança.
- **Extração de JSON Balanceada**: O regex original `\{.*?\}` cortava a resposta no primeiro `}`. A nova função `extrair_json()` implementa um algoritmo de contagem de profundidade de chaves que lida com objetos aninhados (ex: `parameters: {"brightness_pct": 50}`), além de suportar blocos Markdown e validar esquemas.
- **Proteção de Credenciais**:
  - A chave da OpenWeather foi removida do código-fonte e passa a ser lida da variável `OPENWEATHER_KEY` no arquivo de ambiente.
  - As URLs de streaming do Navidrome não expõem senhas em texto puro nos logs nem no arquivo `current_song.json`. Foi implementada sanitização em todas as saídas de depuração e autenticação por salt/token (padrão Subsonic).

### 2. Otimização de Desempenho e Fluxo de Decisão (LLM)
- **Fast-Path Local Antes da LLM**:
  - Comandos inequívocos de automação residencial (ligar/desligar luzes, acionar automações de TV ou ar-condicionado), hora certa, previsão do tempo e controle de música são processados **localmente sem latência de rede**.
  - Economiza de 2 a 4 segundos por comando e permite que comandos locais funcionem mesmo se o serviço de IA externa estiver indisponível.
- **Roteamento Inteligente com LLM**: Apenas comandos que não casam com os parsers locais determinísticos recorrem à LLM (para desambiguação e extração estruturada de JSON ou bate-papo amigável).
- **Tratamento de Quedas de Rede**: Se a LLM remota estiver fora do ar ou sofrer timeout, a Aurora responde com uma mensagem de áudio amigável, sem converter falhas de rede em alucinações de conversa.

### 3. Síntese de Voz (TTS)
- **Google Cloud TTS como Primário**: Conforme solicitado, utiliza `google-cloud-texttospeech` com a voz configurada (`pt-BR-Chirp3-HD-Erinome`).
- **Volume temporário para fala**: Antes de reproduzir uma resposta TTS, aumenta o controle ALSA configurado e restaura volume e estado de mudo ao final. Configure `TTS_VOLUME_LEVEL` (0–100, padrão `100`), `TTS_VOLUME_CONTROL` (padrão `Master`) e, se necessário, `TTS_VOLUME_CARD` no `.env`; o pacote de sistema `alsa-utils` fornece o `amixer`.
- **Limpeza Garantida de Arquivos Temporários**: Todos os arquivos de áudio temporários (`.mp3` e `.wav`) são gerenciados com context managers / blocos `finally`, garantindo que o disco do Orange Pi não fique lotado.
- **Fallback de Áudio Estático**: Se o Google TTS não inicializar ou falhar, o sistema reproduz `config/music/falha_tts.wav`.

### 4. Reprodução de áudio e logs
- **Saída configurável**: `AUDIO_OUTPUT_DRIVER` e `AUDIO_OUTPUT_DEVICE` definem, respectivamente, o driver mpg123 (por exemplo, `alsa` ou `pulse`) e o dispositivo (por exemplo, `plughw:2,0`). Os valores padrão vazios preservam a seleção padrão do sistema. No Orange Pi, confira o dispositivo real com `aplay -l` antes de configurar; não copie o número de placa dos exemplos.
- **Cache de música validado**: URLs HTTP(S) e arquivos locais existentes são aceitos; caminhos locais antigos que não existem são descartados para permitir a atualização da playlist pelo Navidrome.
- **Logs ALSA**: por padrão, as mensagens do ALSA permanecem visíveis. `SUPPRESS_ALSA_ERRORS=1` silencia todas as mensagens C do ALSA e pode ocultar erros reais; use apenas se já tiver confirmado que o ruído é inofensivo.

---

## 📁 Estrutura de Arquivos

```text
refatored/
├── __init__.py
├── config.py             # Configurações de ambiente, caminhos, logs e validação
├── app.py                # Ponto de entrada, orquestrador do loop de eventos e modo CLI
├── llm_client.py         # Cliente LLM universal pluggável (OpenRouter, Groq, Gemini, Ollama, etc.)
├── speech_input.py       # Microfone, calibração, wake word ('aurora') e Whisper local
├── speech_output.py      # Google Cloud TTS (primário), fallback de áudio estático e player de som
├── intent_router.py      # Orquestrador do fluxo: fast-path local + roteamento LLM
├── home_assistant.py     # Registro de dispositivos, parser determinístico e cliente HA seguro
├── music.py              # Controlador thread-safe do player de música e Navidrome
├── local_intents.py      # Hora por extenso e clima (OpenWeather)
├── prompts.py            # Prompts estruturados e versionados
├── README.md             # Esta documentação
```

---

## 🚀 Como Executar

### Sincronização do status de música com SmartLume
Ao iniciar ou parar uma faixa, a Aurora atualiza `config/music/current_song.json` e também `SmartLume/ultima_musica.json`, mantendo apenas título, artista e álbum nos arquivos compartilhados (sem persistir a URL autenticada do Navidrome). Por padrão, o SmartLume é localizado como pasta irmã da pasta `Aurora`; se estiver em outro local, configure `SMARTLUME_STATUS_FILE` com o caminho completo para `ultima_musica.json`.

### 1. Execução por Voz (Modo Principal)
Para iniciar o assistente ouvindo a palavra de ativação `"aurora"` no microfone:
```bash
python refatored/app.py
```

### 2. Execução Interativa via Terminal (Modo CLI)
Ideal para testar comandos pelo teclado, sem necessitar de microfone ou quando estiver desenvolvendo remotamente:
```bash
python refatored/app.py --cli
```

---

## 🧪 Suíte de Testes Automatizados

Para rodar todos os testes unitários (executa em menos de 1 segundo, sem requisições de rede externas):
```bash
python -m unittest discover refatored/tests
```

### Consulta do clima

A resposta do clima usa descrições curtas em português brasileiro, além de temperatura, sensação térmica, umidade e velocidade do vento.

Os testes cobrem:
- Parsing de "ligar" vs "desligar" e rejeição de negações.
- Prevenção de injeção de parâmetros maliciosos sobre `entity_id`.
- Extração de JSONs aninhados e blocos Markdown.
- Roteamento e chamadas determinísticas sem LLM.
- Comandos musicais e imunidade a falsos positivos (ex: "música para relaxar").
- Formatação de horários em português.
