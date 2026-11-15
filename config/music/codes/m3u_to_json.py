import re
import json

m3u_path = "Tudo.m3u"
output_path = "music_playlist.txt"

playlist = []
current = {}

with open(m3u_path, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line.startswith("#EXTINF:"):
            # Exemplo: #EXTINF:270,Maria Marçal - Deixa - Louvorzão 93 (Ao Vivo) - 2023
            match = re.match(r'#EXTINF:(-?\d+),(.*?)(?: - )?(.*)', line)
            if match:
                # Tenta separar artista e título
                info = match.group(2)
                if " - " in info:
                    artist, title = info.split(" - ", 1)
                else:
                    artist = "[Unknown Artist]"
                    title = info
                current = {"artist": artist.strip(), "title": title.strip()}
        elif line and not line.startswith("#"):
            # Linha do arquivo ou URL
            if current:
                current["url"] = line
                playlist.append(current)
                current = {}

# Salva como JSON em uma linha só
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(playlist, f, ensure_ascii=False)

print(f"Playlist salva em {output_path}")