import os
import json
import random
import re
import asyncio
import time
from datetime import datetime
import requests
import feedparser
import edge_tts
from moviepy.editor import *
from google import generativeai as genai
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload
from PIL import Image, ImageDraw, ImageFont
import io

# Importar curadoria
try:
    from telegram_curator_noticias import TelegramCuratorNoticias
    CURACAO_DISPONIVEL = True
except ImportError:
    print("⚠️ telegram_curator_noticias.py não encontrado")
    CURACAO_DISPONIVEL = False

CONFIG_FILE = 'config.json'
VIDEOS_DIR = 'videos'
ASSETS_DIR = 'assets'
VIDEO_TYPE = os.environ.get('VIDEO_TYPE', 'short')

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
PEXELS_API_KEY = os.environ.get('PEXELS_API_KEY')
YOUTUBE_CREDENTIALS = os.environ.get('YOUTUBE_CREDENTIALS')

# Configuração de curadoria
USAR_CURACAO = os.environ.get('USAR_CURACAO', 'false').lower() == 'true' and CURACAO_DISPONIVEL
CURACAO_TIMEOUT = int(os.environ.get('CURACAO_TIMEOUT', '3600'))

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.0-flash-exp')

with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
    config = json.load(f)

def buscar_noticias():
    """Busca notícias dos feeds RSS configurados"""
    if config.get('tipo') != 'noticias':
        return None
    
    feeds = config.get('rss_feeds', [])
    todas_noticias = []
    
    for feed_url in feeds[:3]:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:3]:
                todas_noticias.append({
                    'titulo': entry.title,
                    'resumo': entry.get('summary', entry.title),
                    'link': entry.link
                })
        except:
            continue
    
    return random.choice(todas_noticias) if todas_noticias else None

def gerar_titulo_especifico(tema):
    """Gera título específico e keywords"""
    prompt = f"""Baseado no tema "{tema}", crie um título ESPECÍFICO e palavras-chave.

Retorne APENAS JSON: {{"titulo": "título aqui", "keywords": ["palavra1", "palavra2", "palavra3", "palavra4", "palavra5"]}}"""
    
    response = model.generate_content(prompt)
    texto = response.text.strip().replace('```json', '').replace('```', '').strip()
    
    inicio = texto.find('{')
    fim = texto.rfind('}') + 1
    
    if inicio == -1 or fim == 0:
        return {"titulo": tema, "keywords": ["politics", "news", "brazil", "government", "congress"]}
    
    try:
        return json.loads(texto[inicio:fim])
    except:
        return {"titulo": tema, "keywords": ["politics", "news", "brazil", "government", "congress"]}

def gerar_roteiro(duracao_alvo, titulo, noticia=None):
    """Gera roteiro de narração"""
    if duracao_alvo == 'short':
        palavras_alvo = 120
        tempo = '30-60 segundos'
    else:
        palavras_alvo = config.get('duracao_minutos', 10) * 150
        tempo = f"{config.get('duracao_minutos', 10)} minutos"
    
    if noticia:
        prompt = f"""Crie um script JORNALÍSTICO sobre: {titulo}

Resumo: {noticia['resumo']}

REGRAS:
- {tempo}, {palavras_alvo} palavras
- Tom noticioso e informativo
- Comece direto na notícia
- NÃO mencione apresentador ou elementos visuais
- Texto corrido para narração
- SEM formatação, asteriscos, marcadores ou emojis

Escreva APENAS o roteiro."""
    else:
        prompt = f"""Crie um script sobre: {titulo}

REGRAS:
- {tempo}, {palavras_alvo} palavras
- Tom informativo
- Comece contextualmente
- NÃO mencione elementos visuais
- Texto corrido
- SEM formatação

Escreva APENAS o roteiro."""
    
    response = model.generate_content(prompt)
    texto = response.text
    
    # Limpeza
    texto = re.sub(r'\*+', '', texto)
    texto = re.sub(r'#+\s', '', texto)
    texto = re.sub(r'^-\s', '', texto, flags=re.MULTILINE)
    texto = texto.replace('*', '').replace('#', '').replace('_', '').strip()
    
    return texto

async def criar_audio_async(texto, output_file):
    """Cria áudio com Edge TTS (async)"""
    voz = config.get('voz', 'pt-BR-FranciscaNeural')
    
    for tentativa in range(3):
        try:
            communicate = edge_tts.Communicate(texto, voz, rate="+0%", pitch="+0Hz")
            await asyncio.wait_for(communicate.save(output_file), timeout=120)
            print(f"✅ Edge TTS")
            return
        except asyncio.TimeoutError:
            print(f"⏱️ Timeout {tentativa + 1}")
            if tentativa < 2:
                await asyncio.sleep(10)
        except Exception as e:
            print(f"⚠️ Erro {tentativa + 1}: {e}")
            if tentativa < 2:
                await asyncio.sleep(10)
    
    raise Exception("Edge TTS falhou")

def criar_audio(texto, output_file):
    """Cria áudio"""
    print("🎙️ Criando narração...")
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(criar_audio_async(texto, output_file))
        loop.close()
        
        if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
            print(f"✅ Áudio criado")
            return output_file
    except Exception as e:
        print(f"❌ Edge TTS: {e}")
        from gtts import gTTS
        tts = gTTS(text=texto, lang='pt-br', slow=False)
        tts.save(output_file)
        print("⚠️ gTTS usado")
        return output_file

def extrair_keywords_do_texto(texto):
    """Extrai keywords"""
    prompt = f"""Extraia 3-5 palavras-chave deste texto:

"{texto[:200]}"

Nomes de políticos/instituições em PORTUGUÊS.
Senão, palavras em INGLÊS.

Retorne APENAS palavras separadas por vírgula."""
    
    try:
        response = model.generate_content(prompt)
        keywords = [k.strip().lower() for k in response.text.strip().split(',')]
        return keywords[:5]
    except:
        palavras = texto.lower().split()
        return [p for p in palavras if len(p) > 4][:3]

def buscar_imagens_local(keywords, quantidade=1):
    """Busca imagens no banco local"""
    
    mapa_politicos = {
        'lula': 'politicos/lula',
        'bolsonaro': 'politicos/bolsonaro',
        'moraes': 'politicos/alexandre_de_moraes',
        'alexandre': 'politicos/alexandre_de_moraes',
        'pacheco': 'politicos/rodrigo_pacheco',
        'lira': 'politicos/arthur_lira',
        'haddad': 'politicos/fernando_haddad',
        'tarcisio': 'politicos/tarcisio_de_freitas',
        'tarcísio': 'politicos/tarcisio_de_freitas',
        # ... outros políticos
    }
    
    mapa_instituicoes = {
        'congresso': 'instituicoes/congresso_nacional',
        'stf': 'instituicoes/stf',
        'supremo': 'instituicoes/stf',
        'senado': 'instituicoes/senado_federal',
        'camara': 'instituicoes/camara_dos_deputados',
        'câmara': 'instituicoes/camara_dos_deputados',
        'planalto': 'instituicoes/palacio_do_planalto',
        'brasilia': 'instituicoes/brasilia',
        'brasília': 'instituicoes/brasilia',
        # ... outras instituições
    }
    
    midias = []
    
    if isinstance(keywords, str):
        keywords = [keywords]
    
    keywords_lower = [k.lower() for k in keywords]
    keywords_texto = ' '.join(keywords_lower)
    
    pasta_encontrada = None
    
    # Checar políticos
    for termo, pasta in mapa_politicos.items():
        if termo in keywords_texto:
            pasta_encontrada = pasta
            print(f"   📁 Político: {termo} → {pasta}")
            break
    
    # Checar instituições
    if not pasta_encontrada:
        for termo, pasta in mapa_instituicoes.items():
            if termo in keywords_texto:
                pasta_encontrada = pasta
                print(f"   📁 Instituição: {termo} → {pasta}")
                break
    
    # Fallback
    if not pasta_encontrada:
        pasta_encontrada = 'genericas'
        print(f"   📁 Genérica")
    
    pasta_completa = f'{ASSETS_DIR}/{pasta_encontrada}'
    
    try:
        if os.path.exists(pasta_completa):
            arquivos = [f for f in os.listdir(pasta_completa) 
                       if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
            
            if arquivos:
                random.shuffle(arquivos)
                
                for arquivo in arquivos[:quantidade]:
                    caminho_completo = os.path.join(pasta_completa, arquivo)
                    if os.path.exists(caminho_completo):
                        midias.append((caminho_completo, 'foto_local'))
                
                if midias:
                    print(f"   ✅ {len(midias)} imagem(ns)")
                    return midias
    except Exception as e:
        print(f"   ⚠️ Erro: {e}")
    
    # Tentar genéricas
    if not midias and pasta_encontrada != 'genericas':
        pasta_completa = f'{ASSETS_DIR}/genericas'
        try:
            if os.path.exists(pasta_completa):
                arquivos = [f for f in os.listdir(pasta_completa) 
                           if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
                if arquivos:
                    random.shuffle(arquivos)
                    for arquivo in arquivos[:quantidade]:
                        caminho_completo = os.path.join(pasta_completa, arquivo)
                        if os.path.exists(caminho_completo):
                            midias.append((caminho_completo, 'foto_local'))
        except:
            pass
    
    return midias

def buscar_midias_final(keywords, quantidade=1):
    """Busca mídias"""
    print(f"🔍 Buscando: {keywords}")
    
    midias = []
    
    try:
        midias = buscar_imagens_local(keywords, quantidade)
    except Exception as e:
        print(f"   ❌ Erro: {e}")
    
    if not midias:
        print(f"   ⚠️ Nenhuma mídia")
    else:
        print(f"   ✅ {len(midias)}/{quantidade}")
    
    return midias

def gerar_legendas_do_roteiro(roteiro, duracao_audio):
    """Gera legendas sincronizadas com o áudio"""
    print("📝 Gerando legendas...")
    
    # Dividir em sentenças
    sentencas = re.split(r'[.!?]\s+', roteiro)
    sentencas = [s.strip() for s in sentencas if len(s.strip()) > 10]
    
    palavras_total = len(roteiro.split())
    palavras_por_segundo = palavras_total / duracao_audio
    
    legendas = []
    tempo_atual = 0
    
    for sentenca in sentencas:
        palavras = sentenca.split()
        duracao_sentenca = len(palavras) / palavras_por_segundo
        
        # Dividir sentença em chunks de 3-5 palavras
        chunk_size = 4
        chunks = [' '.join(palavras[i:i+chunk_size]) for i in range(0, len(palavras), chunk_size)]
        
        duracao_por_chunk = duracao_sentenca / len(chunks)
        
        for chunk in chunks:
            legendas.append({
                'texto': chunk.upper(),  # Maiúsculas para destaque
                'inicio': tempo_atual,
                'fim': tempo_atual + duracao_por_chunk
            })
            tempo_atual += duracao_por_chunk
    
    print(f"   ✅ {len(legendas)} legendas criadas")
    return legendas

def criar_clip_legenda(texto, duracao, largura, altura):
    """Cria um clip de texto animado para legenda"""
    
    def make_frame(t):
        # Criar imagem transparente
        img = Image.new('RGBA', (largura, altura), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        # Tentar carregar fonte, se não conseguir usa default
        try:
            # Fonte maior e bold
            font_size = 80 if VIDEO_TYPE == 'short' else 60
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
        except:
            font = ImageFont.load_default()
        
        # Quebrar texto em linhas se necessário
        palavras = texto.split()
        linhas = []
        linha_atual = []
        
        for palavra in palavras:
            teste = ' '.join(linha_atual + [palavra])
            bbox = draw.textbbox((0, 0), teste, font=font)
            largura_texto = bbox[2] - bbox[0]
            
            if largura_texto < largura - 100:
                linha_atual.append(palavra)
            else:
                if linha_atual:
                    linhas.append(' '.join(linha_atual))
                linha_atual = [palavra]
        
        if linha_atual:
            linhas.append(' '.join(linha_atual))
        
        # Calcular posição Y (parte inferior da tela)
        y_base = altura - 200 if VIDEO_TYPE == 'short' else altura - 150
        
        # Animação: fade in/out
        progresso = t / duracao
        if progresso < 0.1:  # Fade in nos primeiros 10%
            alpha = int(255 * (progresso / 0.1))
        elif progresso > 0.9:  # Fade out nos últimos 10%
            alpha = int(255 * ((1 - progresso) / 0.1))
        else:
            alpha = 255
        
        # Desenhar cada linha
        for i, linha in enumerate(linhas):
            # Medir texto
            bbox = draw.textbbox((0, 0), linha, font=font)
            largura_texto = bbox[2] - bbox[0]
            altura_texto = bbox[3] - bbox[1]
            
            # Centralizar horizontalmente
            x = (largura - largura_texto) // 2
            y = y_base + (i * (altura_texto + 10))
            
            # Sombra/contorno para legibilidade
            # Desenhar contorno preto
            for offset_x in [-2, 0, 2]:
                for offset_y in [-2, 0, 2]:
                    if offset_x != 0 or offset_y != 0:
                        draw.text((x + offset_x, y + offset_y), linha, 
                                font=font, fill=(0, 0, 0, alpha))
            
            # Texto branco principal
            draw.text((x, y), linha, font=font, fill=(255, 255, 255, alpha))
        
        # Converter para array numpy
        return np.array(img)
    
    return VideoClip(make_frame, duration=duracao)

def analisar_roteiro_e_buscar_midias(roteiro, duracao_audio):
    """Analisa roteiro e busca mídias sincronizadas COM CURADORIA"""
    print("📋 Analisando roteiro...")
    
    segmentos = re.split(r'[.!?]\s+', roteiro)
    segmentos = [s.strip() for s in segmentos if len(s.strip()) > 20]
    
    print(f"   {len(segmentos)} segmentos")
    
    palavras_total = len(roteiro.split())
    palavras_por_segundo = palavras_total / duracao_audio
    
    segmentos_com_tempo = []
    tempo_atual = 0
    
    for segmento in segmentos:
        palavras_segmento = len(segmento.split())
        duracao_segmento = palavras_segmento / palavras_por_segundo
        keywords = extrair_keywords_do_texto(segmento)
        
        segmentos_com_tempo.append({
            'texto': segmento[:50],
            'inicio': tempo_atual,
            'duracao': duracao_segmento,
            'keywords': keywords
        })
        
        tempo_atual += duracao_segmento
    
    midias_sincronizadas = []
    
    for i, seg in enumerate(segmentos_com_tempo):
        print(f"\n🔍 Seg {i+1}: '{seg['texto']}'...")
        print(f"   Keywords: {seg['keywords']}")
        
        midia = buscar_midias_final(seg['keywords'], quantidade=1)
        
        if midia and len(midia) > 0:
            midias_sincronizadas.append({
                'midia': midia[0],
                'inicio': seg['inicio'],
                'duracao': seg['duracao'],
                'texto': seg['texto'],
                'keywords': seg['keywords']
            })
            print(f"   ✅ OK")
        else:
            print(f"   ❌ Sem mídia")
    
    print(f"\n✅ Total: {len(midias_sincronizadas)}/{len(segmentos_com_tempo)}")
    
    # CURADORIA
    if USAR_CURACAO:
        print("\n" + "="*60)
        print("🎬 MODO CURADORIA ATIVADO")
        print("="*60)
        
        try:
            curator = TelegramCuratorNoticias()
            curator.solicitar_curacao(midias_sincronizadas)
            midias_aprovadas = curator.aguardar_aprovacao(timeout=CURACAO_TIMEOUT)
            
            if midias_aprovadas:
                print("✅ Aprovadas!")
                midias_sincronizadas = midias_aprovadas
            else:
                print("⏰ Timeout")
        except Exception as e:
            print(f"⚠️ Erro: {e}")
    
    return midias_sincronizadas

def criar_video_short_sincronizado(audio_path, midias_sincronizadas, output_file, duracao_total, roteiro):
    """Cria SHORT com legendas animadas"""
    print(f"📹 Criando short com legendas...")
    
    clips = []
    tempo_coberto = 0
    
    # Adicionar clips de imagem
    for i, item in enumerate(midias_sincronizadas):
        midia_info, midia_tipo = item['midia']
        inicio = item['inicio']
        duracao_clip = item['duracao']
        
        try:
            if midia_tipo == 'foto_local' and os.path.exists(midia_info):
                clip = ImageClip(midia_info).set_duration(duracao_clip)
                clip = clip.resize(height=1920)
                
                if clip.w > 1080:
                    clip = clip.crop(x_center=clip.w/2, width=1080, height=1920)
                
                # Animação sutil de zoom
                clip = clip.resize(lambda t: 1 + 0.05 * (t / duracao_clip))
                clip = clip.set_start(inicio)
                clips.append(clip)
                tempo_coberto = max(tempo_coberto, inicio + duracao_clip)
        except Exception as e:
            print(f"⚠️ Erro {i}: {e}")
    
    # Preencher lacunas
    if tempo_coberto < duracao_total:
        print(f"⚠️ Preenchendo {duracao_total - tempo_coberto:.1f}s")
        extras = buscar_midias_final(['brasil'], quantidade=3)
        duracao_restante = duracao_total - tempo_coberto
        duracao_por_extra = duracao_restante / len(extras) if extras else duracao_restante
        
        for idx, (midia_info, midia_tipo) in enumerate(extras):
            try:
                if midia_tipo == 'foto_local' and os.path.exists(midia_info):
                    clip = ImageClip(midia_info).set_duration(duracao_por_extra)
                    clip = clip.resize(height=1920)
                    if clip.w > 1080:
                        clip = clip.crop(x_center=clip.w/2, width=1080, height=1920)
                    clip = clip.set_start(tempo_coberto)
                    clips.append(clip)
                    tempo_coberto += duracao_por_extra
            except:
                continue
    
    if not clips:
        return None
    
    # Compor vídeo base
    video = CompositeVideoClip(clips, size=(1080, 1920))
    video = video.set_duration(duracao_total)
    
    # Adicionar áudio
    audio = AudioFileClip(audio_path)
    video = video.set_audio(audio)
    
    # ADICIONAR LEGENDAS ANIMADAS
    print("📝 Adicionando legendas animadas...")
    legendas = gerar_legendas_do_roteiro(roteiro, duracao_total)
    
    clips_legendas = []
    for legenda in legendas:
        duracao = legenda['fim'] - legenda['inicio']
        clip_legenda = criar_clip_legenda(
            legenda['texto'],
            duracao,
            1080,
            1920
        )
        clip_legenda = clip_legenda.set_start(legenda['inicio'])
        clip_legenda = clip_legenda.set_position(('center', 'bottom'))
        clips_legendas.append(clip_legenda)
    
    # Compor vídeo final com legendas
    if clips_legendas:
        video_final = CompositeVideoClip([video] + clips_legendas)
        video_final = video_final.set_duration(duracao_total)
        video_final = video_final.set_audio(audio)
    else:
        video_final = video
    
    print("💾 Renderizando...")
    video_final.write_videofile(
        output_file,
        fps=30,
        codec='libx264',
        audio_codec='aac',
        preset='medium',
        bitrate='8000k'
    )
    
    return output_file

def criar_video_long_sincronizado(audio_path, midias_sincronizadas, output_file, duracao_total, roteiro):
    """Cria vídeo longo com legendas"""
    print(f"📹 Criando long com legendas...")
    
    clips = []
    tempo_coberto = 0
    
    for i, item in enumerate(midias_sincronizadas):
        midia_info, midia_tipo = item['midia']
        inicio = item['inicio']
        duracao_clip = item['duracao']
        
        try:
            if midia_tipo == 'foto_local' and os.path.exists(midia_info):
                clip = ImageClip(midia_info).set_duration(duracao_clip)
                clip = clip.resize(height=1080)
                
                if clip.w < 1920:
                    clip = clip.resize(width=1920)
                
                clip = clip.crop(x_center=clip.w/2, y_center=clip.h/2, width=1920, height=1080)
                clip = clip.resize(lambda t: 1 + 0.03 * (t / duracao_clip))
                clip = clip.set_start(inicio)
                clips.append(clip)
                tempo_coberto = max(tempo_coberto, inicio + duracao_clip)
        except Exception as e:
            print(f"⚠️ Erro {i}: {e}")
    
    if tempo_coberto < duracao_total:
        extras = buscar_midias_final(['brasil'], quantidade=5)
        duracao_restante = duracao_total - tempo_coberto
        duracao_por_extra = duracao_restante / len(extras) if extras else duracao_restante
        
        for idx, (midia_info, midia_tipo) in enumerate(extras):
            try:
                if midia_tipo == 'foto_local' and os.path.exists(midia_info):
                    clip = ImageClip(midia_info).set_duration(duracao_por_extra)
                    clip = clip.resize(height=1080)
                    if clip.w < 1920:
                        clip = clip.resize(width=1920)
                    clip = clip.crop(x_center=clip.w/2, y_center=clip.h/2, width=1920, height=1080)
                    clip = clip.set_start(tempo_coberto)
                    clips.append(clip)
                    tempo_coberto += duracao_por_extra
            except:
                continue
    
    if not clips:
        return None
    
    video = CompositeVideoClip(clips, size=(1920, 1080))
    video = video.set_duration(duracao_total)
    
    audio = AudioFileClip(audio_path)
    video = video.set_audio(audio)
    
    # Legendas
    print("📝 Adicionando legendas...")
    legendas = gerar_legendas_do_roteiro(roteiro, duracao_total)
    
    clips_legendas = []
    for legenda in legendas:
        duracao = legenda['fim'] - legenda['inicio']
        clip_legenda = criar_clip_legenda(
            legenda['texto'],
            duracao,
            1920,
            1080
        )
        clip_legenda = clip_legenda.set_start(legenda['inicio'])
        clips_legendas.append(clip_legenda)
    
    if clips_legendas:
        video_final = CompositeVideoClip([video] + clips_legendas)
        video_final = video_final.set_duration(duracao_total)
        video_final = video_final.set_audio(audio)
    else:
        video_final = video
    
    print("💾 Renderizando...")
    video_final.write_videofile(
        output_file,
        fps=24,
        codec='libx264',
        audio_codec='aac',
        preset='medium',
        bitrate='5000k'
    )
    
    return output_file

def solicitar_thumbnail_telegram(titulo):
    """Solicita thumbnail via Telegram"""
    if not USAR_CURACAO:
        return None
    
    print("🖼️ Solicitando thumbnail...")
    
    try:
        curator = TelegramCuratorNoticias()
        thumbnail_path = curator.solicitar_thumbnail(titulo, timeout=CURACAO_TIMEOUT)
        
        if thumbnail_path and os.path.exists(thumbnail_path):
            print(f"✅ Thumbnail recebida: {thumbnail_path}")
            return thumbnail_path
        else:
            print("⚠️ Sem thumbnail")
            return None
    except Exception as e:
        print(f"❌ Erro thumbnail: {e}")
        return None

def fazer_upload_youtube(video_path, titulo, descricao, tags, thumbnail_path=None):
    """Faz upload com thumbnail opcional"""
    try:
        creds_dict = json.loads(YOUTUBE_CREDENTIALS)
        credentials = Credentials.from_authorized_user_info(creds_dict)
        youtube = build('youtube', 'v3', credentials=credentials)
        
        body = {
            'snippet': {
                'title': titulo,
                'description': descricao,
                'tags': tags,
                'categoryId': '27'
            },
            'status': {
                'privacyStatus': 'public',
                'selfDeclaredMadeForKids': False
            }
        }
        
        media = MediaFileUpload(video_path, resumable=True)
        request = youtube.videos().insert(
            part='snippet,status',
            body=body,
            media_body=media
        )
        response = request.execute()
        video_id = response['id']
        
        # Upload thumbnail se fornecida
        if thumbnail_path and os.path.exists(thumbnail_path):
            print("📤 Fazendo upload da thumbnail...")
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumbnail_path)
            ).execute()
            print("✅ Thumbnail configurada!")
        
        return video_id
    except Exception as e:
        print(f"❌ Erro upload: {e}")
        raise

def main():
    print(f"{'📱' if VIDEO_TYPE == 'short' else '🎬'} Iniciando...")
    os.makedirs(VIDEOS_DIR, exist_ok=True)
    os.makedirs(ASSETS_DIR, exist_ok=True)

    # Buscar notícia
    noticia = buscar_noticias()

    if noticia:
        titulo_video = noticia['titulo']
        keywords = titulo_video.split()[:5]
        print(f"📰 Notícia: {titulo_video}")
    else:
        tema = random.choice(config.get('temas', ['política brasileira']))
        print(f"📝 Tema: {tema}")
        
        info = gerar_titulo_especifico(tema)
        titulo_video = info['titulo']
        keywords = info['keywords']

    print(f"🎯 Título: {titulo_video}")

    # Gerar roteiro
    print("✍️ Gerando roteiro...")
    roteiro = gerar_roteiro(VIDEO_TYPE, titulo_video, noticia)

    # Criar áudio
    audio_path = f'{ASSETS_DIR}/audio.mp3'
    criar_audio(roteiro, audio_path)

    audio_clip = AudioFileClip(audio_path)
    duracao = audio_clip.duration
    audio_clip.close()

    print(f"⏱️ {duracao:.1f}s")

    # Buscar mídias
    midias_sincronizadas = analisar_roteiro_e_buscar_midias(roteiro, duracao)

    # Complementar se necessário
    if len(midias_sincronizadas) < 3:
        print("⚠️ Complementando...")
        extras = buscar_midias_final(['brasil'], quantidade=5)
        tempo_restante = duracao - sum([m['duracao'] for m in midias_sincronizadas])
        duracao_extra = tempo_restante / len(extras) if extras else 0
        
        for extra in extras:
            midias_sincronizadas.append({
                'midia': extra,
                'inicio': duracao - tempo_restante,
                'duracao': duracao_extra
            })
            tempo_restante -= duracao_extra

    # Montar vídeo
    print("🎥 Montando vídeo...")
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    video_path = f'{VIDEOS_DIR}/{VIDEO_TYPE}_{timestamp}.mp4'

    if VIDEO_TYPE == 'short':
        resultado = criar_video_short_sincronizado(
            audio_path,
            midias_sincronizadas,
            video_path,
            duracao,
            roteiro  # ← PASSA ROTEIRO PARA LEGENDAS
        )
    else:
        resultado = criar_video_long_sincronizado(
            audio_path,
            midias_sincronizadas,
            video_path,
            duracao,
            roteiro  # ← PASSA ROTEIRO PARA LEGENDAS
        )

    if not resultado:
        print("❌ Erro ao criar vídeo")
        return

    # Preparar metadados
    titulo = titulo_video[:60] if len(titulo_video) <= 60 else titulo_video[:57] + '...'

    if VIDEO_TYPE == 'short':
        titulo += ' #shorts'

    descricao = roteiro[:300] + '...\n\n🔔 Inscreva-se!\n#' + ('shorts' if VIDEO_TYPE == 'short' else 'noticias')

    tags = ['noticias', 'informacao', 'politica', 'brasil']
    if VIDEO_TYPE == 'short':
        tags.append('shorts')

    # SOLICITAR THUMBNAIL VIA TELEGRAM
    thumbnail_path = None
    if USAR_CURACAO:
        print("\n" + "="*60)
        print("🖼️ SOLICITANDO THUMBNAIL")
        print("="*60)
        thumbnail_path = solicitar_thumbnail_telegram(titulo)

    # Upload
    print("📤 Upload...")
    try:
        video_id = fazer_upload_youtube(
            video_path,
            titulo,
            descricao,
            tags,
            thumbnail_path  # ← PASSA THUMBNAIL
        )
        
        url = f'https://youtube.com/{"shorts" if VIDEO_TYPE == "short" else "watch?v="}{video_id}'
        
        # Log
        log_entry = {
            'data': datetime.now().isoformat(),
            'tipo': VIDEO_TYPE,
            'tema': titulo_video,
            'titulo': titulo,
            'duracao': duracao,
            'video_id': video_id,
            'url': url,
            'com_legendas': True,
            'com_thumbnail_custom': thumbnail_path is not None
        }
        
        log_file = 'videos_gerados.json'
        logs = []
        
        if os.path.exists(log_file):
            with open(log_file, 'r', encoding='utf-8') as f:
                logs = json.load(f)
        
        logs.append(log_entry)
        
        with open(log_file, 'w', encoding='utf-8') as f:
            json.dump(logs, f, indent=2, ensure_ascii=False)
        
        print(f"✅ Publicado!\n🔗 {url}")
        
        # Notificar
        if USAR_CURACAO:
            try:
                curator = TelegramCuratorNoticias()
                curator.notificar_publicacao({
                    'titulo': titulo,
                    'duracao': duracao,
                    'url': url
                })
            except:
                pass
        
        # Limpar
        for file in os.listdir(ASSETS_DIR):
            try:
                # Não deletar fotos customizadas
                if not file.startswith('custom_') and not file.startswith('thumbnail_'):
                    os.remove(os.path.join(ASSETS_DIR, file))
            except:
                pass
    except Exception as e:
        print(f"❌ Erro: {e}")

if __name__ == '__main__':
    main()
