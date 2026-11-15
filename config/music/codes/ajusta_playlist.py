import json
import os

CAMINHO_BASE = "/caminho/para/music/"

def extrair_info(url):
    # Remove caminho base
    rel_path = url[len(CAMINHO_BASE):]
    partes = rel_path.split('/')
    if len(partes) == 2:
        artista = partes[0]
        musica = partes[1]
    else:
        musica = partes[0]
        artista = ""
    # Remove extensão
    musica_nome = os.path.splitext(musica)[0]
    # Tenta separar artista e título pelo padrão "Artista - Música"
    if " - " in musica_nome:
        possivel_artista, possivel_titulo = musica_nome.split(" - ", 1)
        # Se o artista da pasta for igual ao do arquivo, usa ele
        if artista and artista in possivel_artista:
            return artista, possivel_titulo
        # Se não, usa o do arquivo
        return possivel_artista, possivel_titulo
    else:
        # Se não tem separador, usa o nome da pasta como artista
        return artista if artista else "[Unknown Artist]", musica_nome

with open("music_playlist.txt", encoding="utf-8") as f:
    playlist = json.load(f)

for item in playlist:
    url = item["url"]
    if url.startswith(CAMINHO_BASE):
        artista, titulo = extrair_info(url)
        item["artist"] = artista.strip()
        item["title"] = titulo.strip()
        item["url"] = url.strip()

with open("music_playlist.txt", "w", encoding="utf-8") as f:
    json.dump(playlist, f, ensure_ascii=False)

print("Arquivo music_playlist.txt atualizado!")