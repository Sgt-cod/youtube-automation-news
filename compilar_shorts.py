"""
compilar_shorts.py — Vídeo Longo Semanal
-----------------------------------------
Toda segunda-feira gera um vídeo longo original com os principais
temas da semana, baseado nos títulos dos shorts publicados.

Fluxo:
  1. Lê videos_gerados.json para obter temas da semana
  2. Gemini gera roteiro longo (~5 min) cobrindo todos os temas
  3. Edge TTS narra o roteiro
  4. Imagens do assets/ ilustram o vídeo (igual aos shorts)
  5. Publica no YouTube como vídeo longo
  6. Distribui no Telegram e Blogger
"""

import os, json, random, time, glob
from datetime import datetime, timedelta
from pathlib import Path

import requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google import generativeai as genai

# ── Secrets ───────────────────────────────────────────────────────────────
GEMINI_API_KEY       = os.environ.get('GEMINI_API_KEY', '')
YOUTUBE_CREDENTIALS  = os.environ.get('YOUTUBE_CREDENTIALS', '')
TELEGRAM_BOT_TOKEN   = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID     = os.environ.get('TELEGRAM_CHAT_ID', '')
TELEGRAM_CANAL_ID    = os.environ.get('TELEGRAM_CANAL_ID', '')
BLOGGER_BLOG_ID      = os.environ.get('BLOGGER_BLOG_ID', '')
BLOGGER_CREDENTIALS  = os.environ.get('BLOGGER_CREDENTIALS', '')
CANAL_YOUTUBE_URL    = os.environ.get('CANAL_YOUTUBE_URL', '')

VIDEOS_DIR  = 'videos'
ASSETS_DIR  = 'assets'
LOG_FILE    = 'videos_gerados.json'
MIN_TEMAS   = 3


# ════════════════════════════════════════════════════════════════════════════
# 1. LER TEMAS DA SEMANA
# ════════════════════════════════════════════════════════════════════════════

def buscar_temas_semana() -> list[dict]:
    print("📋 Buscando temas da semana no log...")
    if not os.path.exists(LOG_FILE):
        print("  ⚠️ videos_gerados.json não encontrado")
        return []

    with open(LOG_FILE, encoding='utf-8') as f:
        logs = json.load(f)

    semana_atras = datetime.now() - timedelta(days=7)
    temas = []
    for entry in logs:
        if entry.get('tipo') != 'short':
            continue
        try:
            data_entry = datetime.fromisoformat(entry['data'])
        except Exception:
            continue
        if data_entry < semana_atras:
            continue
        temas.append({
            'titulo': entry.get('tema', entry.get('titulo', '')),
            'url': entry.get('url', ''),
            'data': entry['data']
        })

    temas.sort(key=lambda x: x['data'])
    print(f"  ✅ {len(temas)} temas encontrados")
    for t in temas:
        print(f"     • {t['titulo'][:70]}")
    return temas


# ════════════════════════════════════════════════════════════════════════════
# 2. GEMINI — gerar roteiro longo
# ════════════════════════════════════════════════════════════════════════════

def gerar_roteiro_semanal(temas: list[dict]) -> dict:
    print("\n✍️ Gerando roteiro semanal com Gemini...")
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-2.5-flash-lite')

    lista = '\n'.join(f"- {t['titulo']}" for t in temas)
    semana_str = datetime.now().strftime('%d/%m/%Y')

    prompt = f"""Você é um jornalista político brasileiro do canal "Canal 55 Notícias".

Esta semana foram publicados os seguintes shorts sobre política:
{lista}

Crie um ROTEIRO COMPLETO para um vídeo longo de resumo semanal (5 a 7 minutos de duração).

Regras:
- Comece com uma introdução apresentando o resumo da semana
- Dedique um parágrafo para cada tema, aprofundando a análise
- Use linguagem jornalística clara, direta e imparcial
- Termine com uma conclusão sobre o cenário político da semana
- NÃO use markdown, bullets ou formatação especial — só texto corrido
- Escreva como se fosse narrado em voz alta

Retorne APENAS JSON válido:
{{
  "titulo": "título do vídeo até 80 chars com emojis",
  "roteiro": "texto completo do roteiro para narração",
  "descricao": "descrição para YouTube de 300-500 chars com hashtags",
  "tags": ["tag1", "tag2", "politica", "brasil", "noticias", "resumo", "semanal"]
}}"""

    try:
        response = model.generate_content(prompt)
        texto = response.text.strip().replace('```json','').replace('```','').strip()
        inicio = texto.find('{')
        fim = texto.rfind('}') + 1
        dados = json.loads(texto[inicio:fim])
        print(f"  ✅ Roteiro gerado: {len(dados['roteiro'])} chars")
        print(f"  📺 Título: {dados['titulo']}")
        return dados
    except Exception as e:
        print(f"  ⚠️ Gemini falhou: {e} — usando fallback")
        semana = datetime.now().strftime('%d/%m')
        titulos_str = '. '.join(t['titulo'] for t in temas)
        return {
            'titulo': f'📰 Resumo Político Semanal — {semana}',
            'roteiro': f"Esta semana foi marcada por importantes acontecimentos políticos no Brasil. {titulos_str}. Acompanhe o Canal 55 Notícias para não perder nenhuma atualização.",
            'descricao': f'Resumo dos principais acontecimentos políticos da semana. #política #brasil #noticias #resumosemanal',
            'tags': ['política', 'brasil', 'noticias', 'resumo', 'semanal', 'canal55']
        }


# ════════════════════════════════════════════════════════════════════════════
# 3. ÁUDIO — Edge TTS
# ════════════════════════════════════════════════════════════════════════════

def criar_audio(roteiro: str, output_path: str) -> bool:
    print("\n🎙️ Gerando áudio...")
    import asyncio, edge_tts

    async def _gerar():
        communicate = edge_tts.Communicate(
            roteiro,
            voice="pt-BR-AntonioNeural",
            rate="+5%"
        )
        await communicate.save(output_path)

    try:
        asyncio.run(_gerar())
        tamanho = os.path.getsize(output_path) / 1024
        print(f"  ✅ Áudio gerado: {tamanho:.0f} KB")
        return True
    except Exception as e:
        print(f"  ❌ Erro TTS: {e}")
        return False


# ════════════════════════════════════════════════════════════════════════════
# 4. VÍDEO — montar com imagens do assets
# ════════════════════════════════════════════════════════════════════════════

def montar_video(audio_path: str, output_path: str) -> bool:
    print("\n🎬 Montando vídeo longo...")
    try:
        from moviepy.editor import (AudioFileClip, ImageClip,
                                    CompositeVideoClip, concatenate_videoclips)
        import itertools

        audio = AudioFileClip(audio_path)
        duracao = audio.duration
        print(f"  ⏱️ Duração: {duracao:.1f}s")

        # Buscar todas as imagens disponíveis
        imagens = (
            glob.glob(f'{ASSETS_DIR}/politicos/**/*.jpg', recursive=True) +
            glob.glob(f'{ASSETS_DIR}/politicos/**/*.png', recursive=True) +
            glob.glob(f'{ASSETS_DIR}/instituicoes/**/*.jpg', recursive=True) +
            glob.glob(f'{ASSETS_DIR}/instituicoes/**/*.png', recursive=True) +
            glob.glob(f'{ASSETS_DIR}/genericas/*.jpg') +
            glob.glob(f'{ASSETS_DIR}/genericas/*.png')
        )

        if not imagens:
            print("  ⚠️ Sem imagens — usando fundo sólido")
            from moviepy.editor import ColorClip
            clip = ColorClip(size=(1920, 1080), color=(15, 15, 30), duration=duracao)
            video = clip.set_audio(audio)
        else:
            random.shuffle(imagens)
            duracao_por_img = 6.0
            clips = []
            tempo = 0.0

            for img_path in itertools.cycle(imagens):
                if tempo >= duracao:
                    break
                dur = min(duracao_por_img, duracao - tempo)
                try:
                    clip = ImageClip(img_path, duration=dur)
                    clip = clip.resize(height=1080)
                    if clip.w < 1920:
                        clip = clip.resize(width=1920)
                    clip = clip.crop(x_center=clip.w/2, y_center=clip.h/2,
                                     width=1920, height=1080)
                    if clip.size != (1920, 1080):
                        clip = clip.resize((1920, 1080))
                    # Zoom suave
                    clip = clip.resize(lambda t: 1 + 0.02 * (t / dur))
                    clip = clip.set_start(tempo)
                    clips.append(clip)
                    tempo += dur
                except Exception as e:
                    print(f"  ⚠️ Erro imagem {img_path}: {e}")
                    continue

            if not clips:
                print("  ❌ Nenhum clip criado")
                return False

            video_base = CompositeVideoClip(clips, size=(1920, 1080))
            video_base = video_base.set_duration(duracao)
            video = video_base.set_audio(audio)

        os.makedirs(VIDEOS_DIR, exist_ok=True)
        print("  💾 Renderizando...")
        video.write_videofile(
            output_path,
            fps=24,
            codec='libx264',
            audio_codec='aac',
            preset='fast',
            bitrate='4000k',
            threads=4,
            logger=None
        )
        print(f"  ✅ Vídeo: {output_path}")
        return True

    except Exception as e:
        print(f"  ❌ Erro ao montar vídeo: {e}")
        import traceback; traceback.print_exc()
        return False


# ════════════════════════════════════════════════════════════════════════════
# 5. YOUTUBE — publicar
# ════════════════════════════════════════════════════════════════════════════

def publicar_youtube(video_path: str, metadados: dict) -> str | None:
    print("\n📤 Publicando no YouTube...")
    try:
        creds = Credentials.from_authorized_user_info(json.loads(YOUTUBE_CREDENTIALS))
        yt = build('youtube', 'v3', credentials=creds)

        body = {
            'snippet': {
                'title':       metadados['titulo'][:100],
                'description': metadados['descricao'],
                'tags':        metadados['tags'],
                'categoryId':  '27'
            },
            'status': {
                'privacyStatus':          'public',
                'selfDeclaredMadeForKids': False
            }
        }
        media = MediaFileUpload(video_path, resumable=True)
        req = yt.videos().insert(part='snippet,status', body=body, media_body=media)
        resp = req.execute()
        url = f"https://www.youtube.com/watch?v={resp['id']}"
        print(f"  ✅ Publicado: {url}")
        return url
    except Exception as e:
        print(f"  ❌ Erro YouTube: {e}")
        return None


# ════════════════════════════════════════════════════════════════════════════
# 6. DISTRIBUIÇÃO — Telegram + Blogger
# ════════════════════════════════════════════════════════════════════════════

def _tg(chat_id, texto):
    if not TELEGRAM_BOT_TOKEN or not chat_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={'chat_id': chat_id, 'text': texto,
                  'parse_mode': 'HTML', 'disable_web_page_preview': False},
            timeout=15
        )
    except Exception:
        pass


def distribuir(titulo, roteiro, url_yt, tags):
    print("\n📣 Distribuindo...")

    # Telegram pessoal
    _tg(TELEGRAM_CHAT_ID,
        f"🎬 <b>VÍDEO LONGO PUBLICADO</b>\n\n{titulo}\n\n🔗 {url_yt}")
    time.sleep(2)

    # Canal Telegram
    if TELEGRAM_CANAL_ID:
        _tg(TELEGRAM_CANAL_ID,
            f"📰 <b>{titulo}</b>\n\n"
            f"{roteiro[:600]}...\n\n"
            f"▶️ Assista completo:\n{url_yt}\n\n"
            f"🔔 Inscreva-se!\n"
            f"{'📺 ' + CANAL_YOUTUBE_URL if CANAL_YOUTUBE_URL else ''}")
    time.sleep(2)

    # Blogger
    if BLOGGER_BLOG_ID and BLOGGER_CREDENTIALS:
        try:
            from distribuidor import publicar_blogger
            publicar_blogger(titulo=titulo, roteiro=roteiro,
                             url_youtube=url_yt, tags=tags)
        except Exception as e:
            print(f"  ⚠️ Blogger: {e}")


# ════════════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════════════

def main():
    print("🎬 VÍDEO LONGO SEMANAL — Canal 55 Notícias")
    print("=" * 60)

    os.makedirs(VIDEOS_DIR, exist_ok=True)

    # 1. Temas da semana
    temas = buscar_temas_semana()
    if len(temas) < MIN_TEMAS:
        print(f"\n⚠️ Apenas {len(temas)} temas esta semana (mínimo: {MIN_TEMAS}). Abortando.")
        _tg(TELEGRAM_CHAT_ID,
            f"⚠️ Vídeo longo cancelado: apenas {len(temas)} shorts esta semana.")
        return

    # 2. Roteiro
    metadados = gerar_roteiro_semanal(temas)

    # 3. Áudio
    audio_path = f'{ASSETS_DIR}/audio_semanal.mp3'
    if not criar_audio(metadados['roteiro'], audio_path):
        print("❌ Falha no áudio. Abortando.")
        return

    # 4. Vídeo
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    video_path = f'{VIDEOS_DIR}/semanal_{timestamp}.mp4'
    if not montar_video(audio_path, video_path):
        print("❌ Falha no vídeo. Abortando.")
        return

    # 5. YouTube
    url_yt = publicar_youtube(video_path, metadados)
    if not url_yt:
        print("❌ Falha no upload. Abortando.")
        return

    # 6. Distribuir
    distribuir(metadados['titulo'], metadados['roteiro'], url_yt, metadados['tags'])

    # 7. Log
    logs = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, encoding='utf-8') as f:
            logs = json.load(f)
    logs.append({
        'data':    datetime.now().isoformat(),
        'tipo':    'semanal',
        'titulo':  metadados['titulo'],
        'url':     url_yt,
        'temas':   [t['titulo'] for t in temas]
    })
    with open(LOG_FILE, 'w', encoding='utf-8') as f:
        json.dump(logs, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 60)
    print("✅ VÍDEO LONGO SEMANAL CONCLUÍDO!")
    print(f"🔗 {url_yt}")
    print("=" * 60)


if __name__ == '__main__':
    main()
