"""
compilar_shorts.py
------------------
Toda segunda-feira, pega os Shorts da semana anterior publicados no YouTube,
baixa os vídeos via GitHub Releases (já existentes no seu pipeline),
concatena em um vídeo longo horizontal (1920x1080) com intro/outro,
e publica no YouTube como vídeo longo normal.

GitHub Action: .github/workflows/compilar_shorts.yml
Roda toda segunda às 10h BRT (13h UTC).
"""

import os
import json
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google import generativeai as genai

# ── Secrets ──────────────────────────────────────────────────────────────────
YOUTUBE_CREDENTIALS = os.environ.get('YOUTUBE_CREDENTIALS', '')
GEMINI_API_KEY      = os.environ.get('GEMINI_API_KEY', '')
TELEGRAM_BOT_TOKEN  = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID    = os.environ.get('TELEGRAM_CHAT_ID', '')
TELEGRAM_CANAL_ID   = os.environ.get('TELEGRAM_CANAL_ID', '')
CANAL_YOUTUBE_URL   = os.environ.get('CANAL_YOUTUBE_URL', '')
PIX_CHAVE           = os.environ.get('PIX_CHAVE', '')
GITHUB_TOKEN        = os.environ.get('GITHUB_TOKEN', '')
GITHUB_REPOSITORY   = os.environ.get('GITHUB_REPOSITORY', '')

VIDEOS_DIR = Path('videos')
ASSETS_DIR = Path('assets')
LOG_FILE   = Path('videos_gerados.json')

# Duração mínima de shorts para incluir na compilação (segundos)
DURACAO_MINIMA = 20
# Máximo de shorts por compilação
MAX_SHORTS = 10
# Mínimo para gerar compilação
MIN_SHORTS = 3


# ════════════════════════════════════════════════════════════════════════════
# YOUTUBE — buscar Shorts da semana
# ════════════════════════════════════════════════════════════════════════════

def _youtube_service():
    creds = Credentials.from_authorized_user_info(json.loads(YOUTUBE_CREDENTIALS))
    return build('youtube', 'v3', credentials=creds)


def buscar_shorts_semana() -> list[dict]:
    """
    Busca no log local os Shorts publicados nos últimos 7 dias.
    Retorna lista com info de cada short.
    """
    print("📋 Buscando Shorts da semana no log...")

    if not LOG_FILE.exists():
        print("  ⚠️ videos_gerados.json não encontrado")
        return []

    with open(LOG_FILE, encoding='utf-8') as f:
        logs = json.load(f)

    semana_atras = datetime.now() - timedelta(days=7)
    shorts = []

    for entry in logs:
        if entry.get('tipo') != 'short':
            continue
        data_entry = datetime.fromisoformat(entry['data'])
        if data_entry < semana_atras:
            continue
        shorts.append(entry)

    # Ordena do mais antigo para o mais recente
    shorts.sort(key=lambda x: x['data'])
    shorts = shorts[:MAX_SHORTS]

    print(f"  ✅ {len(shorts)} shorts encontrados esta semana")
    for s in shorts:
        print(f"     • {s['titulo'][:60]}")

    return shorts


def baixar_video_youtube(video_id: str, destino: Path) -> bool:
    """
    Baixa o vídeo do YouTube usando yt-dlp (instalado no workflow).
    """
    print(f"  ⬇️ Baixando {video_id}...")
    try:
        cmd = [
            'yt-dlp',
            '-f', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            '--merge-output-format', 'mp4',
            '-o', str(destino),
            f'https://www.youtube.com/shorts/{video_id}'
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if destino.exists() and destino.stat().st_size > 0:
            print(f"  ✅ Baixado: {destino.name}")
            return True
        print(f"  ❌ yt-dlp falhou: {result.stderr[-200:]}")
        return False
    except Exception as e:
        print(f"  ❌ Erro: {e}")
        return False


# ════════════════════════════════════════════════════════════════════════════
# FFMPEG — converter e concatenar
# ════════════════════════════════════════════════════════════════════════════

def converter_para_horizontal(input_path: Path, output_path: Path) -> bool:
    """
    Converte vídeo vertical (1080x1920) para horizontal (1920x1080)
    usando blur no fundo (técnica "pillarbox" com background desfocado).
    """
    cmd = [
        'ffmpeg', '-y', '-i', str(input_path),
        '-vf', (
            # Fundo: escala para preencher 1920x1080 e aplica blur
            '[0:v]scale=1920:1080:force_original_aspect_ratio=increase,'
            'crop=1920:1080,gblur=sigma=20[bg];'
            # Frente: vídeo original centralizado
            '[0:v]scale=-1:1080[fg];'
            '[bg][fg]overlay=(W-w)/2:(H-h)/2'
        ),
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
        '-c:a', 'aac', '-b:a', '128k',
        str(output_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    ok = output_path.exists() and output_path.stat().st_size > 0
    if not ok:
        print(f"  ❌ ffmpeg erro: {result.stderr[-300:]}")
    return ok


def criar_intro_outro(titulo_compilacao: str, output_dir: Path) -> tuple[Path | None, Path | None]:
    """
    Gera intro e outro simples usando ffmpeg + texto.
    Retorna (intro_path, outro_path).
    """
    intro = output_dir / 'intro.mp4'
    outro = output_dir / 'outro.mp4'

    texto_intro = titulo_compilacao.replace("'", "\\'")[:50]
    canal = "Política em Foco"

    # Intro: fundo escuro + título + subtítulo (3 segundos)
    cmd_intro = [
        'ffmpeg', '-y',
        '-f', 'lavfi', '-i', 'color=c=#0d1117:size=1920x1080:duration=3:rate=30',
        '-vf', (
            f"drawtext=text='{canal}':fontsize=60:fontcolor=white:"
            f"x=(w-text_w)/2:y=(h-text_h)/2-50:fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf,"
            f"drawtext=text='{texto_intro}':fontsize=32:fontcolor=#aaaaaa:"
            f"x=(w-text_w)/2:y=(h-text_h)/2+40:fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        ),
        '-c:v', 'libx264', '-preset', 'fast', '-an',
        str(intro)
    ]

    # Outro: fundo escuro + CTA (4 segundos)
    cta = "Inscreva-se e ative o sininho! 🔔"
    cmd_outro = [
        'ffmpeg', '-y',
        '-f', 'lavfi', '-i', 'color=c=#0d1117:size=1920x1080:duration=4:rate=30',
        '-vf', (
            f"drawtext=text='Gostou? Inscreva-se no canal!':fontsize=52:fontcolor=white:"
            f"x=(w-text_w)/2:y=(h-text_h)/2-40:fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf,"
            f"drawtext=text='🔔 Ative o sininho para não perder nada':fontsize=30:fontcolor=#ffcc00:"
            f"x=(w-text_w)/2:y=(h-text_h)/2+40:fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        ),
        '-c:v', 'libx264', '-preset', 'fast', '-an',
        str(outro)
    ]

    intro_ok = subprocess.run(cmd_intro, capture_output=True, timeout=30).returncode == 0
    outro_ok = subprocess.run(cmd_outro, capture_output=True, timeout=30).returncode == 0

    return (intro if intro_ok else None), (outro if outro_ok else None)


def concatenar_videos(lista_videos: list[Path], output_path: Path) -> bool:
    """
    Concatena lista de vídeos MP4 usando ffmpeg concat demuxer.
    """
    concat_file = output_path.parent / 'concat_list.txt'
    with open(concat_file, 'w') as f:
        for v in lista_videos:
            f.write(f"file '{v.resolve()}'\n")

    cmd = [
        'ffmpeg', '-y',
        '-f', 'concat', '-safe', '0',
        '-i', str(concat_file),
        '-c', 'copy',
        str(output_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    ok = output_path.exists() and output_path.stat().st_size > 0
    if not ok:
        print(f"  ❌ Concatenação falhou: {result.stderr[-300:]}")
    concat_file.unlink(missing_ok=True)
    return ok


# ════════════════════════════════════════════════════════════════════════════
# GEMINI — gerar título/descrição da compilação
# ════════════════════════════════════════════════════════════════════════════

def gerar_metadados_compilacao(titulos_shorts: list[str]) -> dict:
    """Usa Gemini para criar título, descrição e tags para a compilação."""
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-2.0-flash-preview')

    lista = '\n'.join(f"- {t}" for t in titulos_shorts)
    semana = datetime.now().strftime('%d/%m/%Y')

    prompt = f"""Você é editor de um canal de notícias políticas chamado "Política em Foco".
    
Esta semana foram publicados os seguintes shorts:
{lista}

Crie metadados para uma COMPILAÇÃO SEMANAL desses conteúdos.

Retorne APENAS JSON válido (sem markdown):
{{
  "titulo": "título atraente até 80 chars com emojis",
  "descricao": "descrição completa de 300-500 chars com resumo dos temas, CTA para inscrição e hashtags",
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5", "notícias", "política", "brasil"]
}}"""

    try:
        response = model.generate_content(prompt)
        texto = response.text.strip().replace('```json', '').replace('```', '').strip()
        inicio = texto.find('{')
        fim = texto.rfind('}') + 1
        return json.loads(texto[inicio:fim])
    except Exception as e:
        print(f"  ⚠️ Gemini falhou, usando metadados padrão: {e}")
        semana_str = datetime.now().strftime('%d/%m')
        return {
            'titulo': f'📰 Resumo Semanal de Política — Semana de {semana_str}',
            'descricao': f'Os principais acontecimentos políticos da semana em um único vídeo. '
                         f'Inscreva-se para acompanhar tudo sobre política brasileira!\n\n'
                         f'#política #brasil #noticias #resumosemanal',
            'tags': ['política', 'brasil', 'noticias', 'resumo', 'semanal',
                     'politicaemfoco', 'congress', 'governo']
        }


# ════════════════════════════════════════════════════════════════════════════
# YOUTUBE — publicar compilação
# ════════════════════════════════════════════════════════════════════════════

def publicar_compilacao_youtube(video_path: Path, metadados: dict) -> str | None:
    """Faz upload da compilação no YouTube como vídeo longo."""
    try:
        creds = Credentials.from_authorized_user_info(json.loads(YOUTUBE_CREDENTIALS))
        yt = build('youtube', 'v3', credentials=creds)

        body = {
            'snippet': {
                'title': metadados['titulo'],
                'description': metadados['descricao'],
                'tags': metadados['tags'],
                'categoryId': '27'
            },
            'status': {
                'privacyStatus': 'public',
                'selfDeclaredMadeForKids': False
            }
        }

        media = MediaFileUpload(str(video_path), resumable=True)
        request = yt.videos().insert(part='snippet,status', body=body, media_body=media)
        response = request.execute()
        video_id = response['id']
        url = f'https://www.youtube.com/watch?v={video_id}'
        print(f"  ✅ Compilação publicada: {url}")
        return url

    except Exception as e:
        print(f"  ❌ Erro upload YouTube: {e}")
        return None


# ════════════════════════════════════════════════════════════════════════════
# NOTIFICAÇÃO TELEGRAM
# ════════════════════════════════════════════════════════════════════════════

def _tg_send(chat_id: str, texto: str):
    if not TELEGRAM_BOT_TOKEN or not chat_id:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={'chat_id': chat_id, 'text': texto,
                                  'parse_mode': 'HTML', 'disable_web_page_preview': False},
                      timeout=15)
    except Exception:
        pass


def notificar_compilacao(url_yt: str, metadados: dict, n_shorts: int):
    """Notifica bot pessoal e canal público."""
    texto_bot = (
        f"🎬 <b>COMPILAÇÃO SEMANAL PUBLICADA</b>\n\n"
        f"📺 {metadados['titulo']}\n"
        f"📊 {n_shorts} shorts compilados\n"
        f"🔗 {url_yt}"
    )
    pix = f"\n\n💰 Apoie: PIX <code>{PIX_CHAVE}</code>" if PIX_CHAVE else ""
    texto_canal = (
        f"📰 <b>{metadados['titulo']}</b>\n\n"
        f"Os {n_shorts} principais acontecimentos políticos desta semana em um único vídeo!\n\n"
        f"▶️ {url_yt}\n"
        f"🔔 Inscreva-se para não perder nada!"
        f"{pix}"
    )
    _tg_send(TELEGRAM_CHAT_ID, texto_bot)
    time.sleep(2)
    if TELEGRAM_CANAL_ID:
        _tg_send(TELEGRAM_CANAL_ID, texto_canal)


# ════════════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════════════

def main():
    print("🎬 COMPILAÇÃO SEMANAL DE SHORTS")
    print("=" * 60)

    VIDEOS_DIR.mkdir(exist_ok=True)
    tmp_dir = Path(tempfile.mkdtemp(prefix='compilacao_'))

    # 1. Buscar shorts da semana
    shorts = buscar_shorts_semana()

    if len(shorts) < MIN_SHORTS:
        print(f"⚠️ Apenas {len(shorts)} shorts esta semana (mínimo: {MIN_SHORTS}). Abortando.")
        _tg_send(TELEGRAM_CHAT_ID,
                 f"⚠️ Compilação cancelada: apenas {len(shorts)} shorts esta semana.")
        return

    # 2. Baixar vídeos
    print("\n⬇️ Baixando vídeos...")
    videos_baixados: list[Path] = []
    titulos_validos: list[str] = []

    for short in shorts:
        video_id = short.get('video_id', '')
        if not video_id:
            continue
        destino = tmp_dir / f"{video_id}.mp4"
        if baixar_video_youtube(video_id, destino):
            videos_baixados.append(destino)
            titulos_validos.append(short['titulo'])

    if len(videos_baixados) < MIN_SHORTS:
        print(f"❌ Apenas {len(videos_baixados)} vídeos baixados. Abortando.")
        return

    print(f"✅ {len(videos_baixados)} vídeos prontos")

    # 3. Gerar metadados com Gemini
    print("\n✍️ Gerando metadados com Gemini...")
    metadados = gerar_metadados_compilacao(titulos_validos)
    print(f"  Título: {metadados['titulo']}")

    # 4. Converter para horizontal
    print("\n🔄 Convertendo para formato horizontal...")
    videos_horizontais: list[Path] = []

    for i, v in enumerate(videos_baixados):
        saida = tmp_dir / f"h_{i:02d}.mp4"
        if converter_para_horizontal(v, saida):
            videos_horizontais.append(saida)
            print(f"  ✅ {v.name} → horizontal")
        else:
            print(f"  ⚠️ Falha em {v.name}, pulando")

    if not videos_horizontais:
        print("❌ Nenhum vídeo convertido. Abortando.")
        return

    # 5. Criar intro e outro
    print("\n🎨 Criando intro e outro...")
    intro_path, outro_path = criar_intro_outro(metadados['titulo'], tmp_dir)

    # Montar lista final de vídeos
    lista_final: list[Path] = []
    if intro_path:
        lista_final.append(intro_path)
    lista_final.extend(videos_horizontais)
    if outro_path:
        lista_final.append(outro_path)

    print(f"  📋 {len(lista_final)} segmentos para concatenar")

    # 6. Concatenar
    print("\n🔗 Concatenando...")
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_path = VIDEOS_DIR / f"compilacao_{timestamp}.mp4"

    if not concatenar_videos(lista_final, output_path):
        print("❌ Falha na concatenação. Abortando.")
        return

    tamanho_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"✅ Compilação pronta: {output_path.name} ({tamanho_mb:.1f} MB)")

    # 7. Publicar no YouTube
    print("\n📤 Publicando no YouTube...")
    url_yt = publicar_compilacao_youtube(output_path, metadados)

    if not url_yt:
        print("❌ Falha no upload. Abortando.")
        return

    # 8. Publicar no Blogger + notificar Telegram
    print("\n📣 Distribuindo...")
    try:
        from distribuidor import publicar_blogger, publicar_telegram_canal
        publicar_blogger(
            titulo=metadados['titulo'],
            roteiro=metadados['descricao'],
            url_youtube=url_yt,
            tags=metadados['tags']
        )
        time.sleep(2)
        publicar_telegram_canal(
            titulo=metadados['titulo'],
            roteiro=metadados['descricao'],
            url_youtube=url_yt
        )
    except Exception as e:
        print(f"  ⚠️ Distribuição parcial: {e}")

    notificar_compilacao(url_yt, metadados, len(videos_horizontais))

    # 9. Log
    entry = {
        'data': datetime.now().isoformat(),
        'tipo': 'compilacao_semanal',
        'titulo': metadados['titulo'],
        'url': url_yt,
        'shorts_incluidos': len(videos_horizontais),
        'titulos_shorts': titulos_validos
    }
    logs = json.loads(LOG_FILE.read_text(encoding='utf-8')) if LOG_FILE.exists() else []
    logs.append(entry)
    LOG_FILE.write_text(json.dumps(logs, indent=2, ensure_ascii=False), encoding='utf-8')

    print("\n" + "=" * 60)
    print("✅ COMPILAÇÃO SEMANAL CONCLUÍDA!")
    print(f"🔗 {url_yt}")
    print("=" * 60)


if __name__ == '__main__':
    main()
