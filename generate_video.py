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
import numpy as np
from moviepy.editor import *
from google import generativeai as genai
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from PIL import Image

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

def buscar_noticias(quantidade=1):
    """Busca notícias dos feeds RSS configurados
    
    Args:
        quantidade: número de notícias a retornar (1 para short, várias para long)
    """
    if config.get('tipo') != 'noticias':
        return None
    
    feeds = config.get('rss_feeds', [])
    todas_noticias = []
    
    # Para vídeos longos, buscar mais notícias
    noticias_por_feed = 5 if quantidade > 1 else 3
    
    for feed_url in feeds[:3]:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:noticias_por_feed]:
                todas_noticias.append({
                    'titulo': entry.title,
                    'resumo': entry.get('summary', entry.title),
                    'link': entry.link
                })
        except:
            continue
    
    if not todas_noticias:
        return None
    
    # Para short: retorna 1 notícia
    # Para long: retorna várias notícias
    if quantidade == 1:
        return random.choice(todas_noticias)
    else:
        random.shuffle(todas_noticias)
        return todas_noticias[:quantidade]

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

def gerar_roteiro(duracao_alvo, titulo, noticias=None):
    """Gera roteiro de narração
    
    Args:
        duracao_alvo: 'short' ou 'long'
        titulo: título do vídeo
        noticias: pode ser uma notícia (dict) ou lista de notícias (list) ou None
    """
    if duracao_alvo == 'short':
        palavras_alvo = 120
        tempo = '30-60 segundos'
    else:
        palavras_alvo = config.get('duracao_minutos', 10) * 150
        tempo = f"{config.get('duracao_minutos', 10)} minutos"
    
    # Para vídeo longo com múltiplas notícias
    if isinstance(noticias, list) and len(noticias) > 1:
        resumos = "\n\n".join([f"- {n['titulo']}: {n['resumo'][:100]}..." for n in noticias[:5]])
        
        prompt = f"""Crie um script JORNALÍSTICO sobre MÚLTIPLAS NOTÍCIAS:

NOTÍCIAS:
{resumos}

REGRAS:
- {tempo}, aproximadamente {palavras_alvo} palavras
- Cubra todas as notícias de forma equilibrada
- Tom noticioso e informativo
- Comece com uma introdução contextual
- Aborde cada notícia em ordem
- NÃO mencione apresentador ou elementos visuais
- Texto corrido para narração
- SEM formatação, asteriscos, marcadores ou emojis

Escreva APENAS o roteiro."""
    
    # Para short ou vídeo longo com 1 notícia
    elif noticias and (isinstance(noticias, dict) or (isinstance(noticias, list) and len(noticias) == 1)):
        noticia = noticias if isinstance(noticias, dict) else noticias[0]
        
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
            print(f"  📁 Político: {termo} → {pasta}")
            break
    
    # Checar instituições
    if not pasta_encontrada:
        for termo, pasta in mapa_instituicoes.items():
            if termo in keywords_texto:
                pasta_encontrada = pasta
                print(f"  📁 Instituição: {termo} → {pasta}")
                break
    
    # Fallback
    if not pasta_encontrada:
        pasta_encontrada = 'genericas'
        print(f"  📁 Genérica")
    
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
                    print(f"  ✅ {len(midias)} imagem(ns)")
                    return midias
    except Exception as e:
        print(f"  ⚠️ Erro: {e}")
    
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
        print(f"  ❌ Erro: {e}")
    
    if not midias:
        print(f"  ⚠️ Nenhuma mídia")
    else:
        print(f"  ✅ {len(midias)}/{quantidade}")
    
    return midias

def analisar_roteiro_e_buscar_midias(roteiro, duracao_audio):
    """Analisa roteiro e busca mídias sincronizadas COM CURADORIA"""
    print("📋 Analisando roteiro...")
    
    segmentos = re.split(r'[.!?]\s+', roteiro)
    segmentos = [s.strip() for s in segmentos if len(s.strip()) > 20]
    print(f"  {len(segmentos)} segmentos")
    
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
        print(f"  Keywords: {seg['keywords']}")
        
        midia = buscar_midias_final(seg['keywords'], quantidade=1)
        
        if midia and len(midia) > 0:
            midias_sincronizadas.append({
                'midia': midia[0],
                'inicio': seg['inicio'],
                'duracao': seg['duracao'],
                'texto': seg['texto'],
                'keywords': seg['keywords']
            })
            print(f"  ✅ OK")
        else:
            print(f"  ❌ Sem mídia")
    
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

def criar_video_short_sem_legendas(audio_path, midias_sincronizadas, output_file, duracao_total):
    """Cria SHORT SEM legendas - VERSÃO SIMPLIFICADA"""
    print(f"📹 Criando short (sem legendas)...")
    
    clips_imagem = []
    tempo_coberto = 0
    
    # Adicionar clips de imagem
    for i, item in enumerate(midias_sincronizadas):
        midia_info, midia_tipo = item['midia']
        inicio = item['inicio']
        duracao_clip = item['duracao']
        
        try:
            if midia_tipo == 'foto_local' and os.path.exists(midia_info):
                print(f"  📸 Imagem {i+1}: {os.path.basename(midia_info)}")
                
                # Carregar imagem
                clip = ImageClip(midia_info, duration=duracao_clip)
                
                # Resize para 1080x1920 (9:16)
                clip = clip.resize(height=1920)
                if clip.w > 1080:
                    clip = clip.crop(x_center=clip.w/2, width=1080, height=1920)
                elif clip.w < 1080:
                    clip = clip.resize(width=1080)
                
                # Garantir dimensões exatas
                if clip.size != (1080, 1920):
                    clip = clip.resize((1080, 1920))
                
                # Animação zoom suave
                clip = clip.resize(lambda t: 1 + 0.05 * (t / duracao_clip))
                clip = clip.set_start(inicio)
                
                clips_imagem.append(clip)
                tempo_coberto = max(tempo_coberto, inicio + duracao_clip)
                
        except Exception as e:
            print(f"  ⚠️ Erro imagem {i}: {e}")
            import traceback
            traceback.print_exc()
    
    # Preencher lacunas
    if tempo_coberto < duracao_total:
        print(f"⚠️ Preenchendo {duracao_total - tempo_coberto:.1f}s")
        extras = buscar_midias_final(['brasil'], quantidade=3)
        duracao_restante = duracao_total - tempo_coberto
        duracao_por_extra = duracao_restante / len(extras) if extras else duracao_restante
        
        for idx, (midia_info, midia_tipo) in enumerate(extras):
            try:
                if midia_tipo == 'foto_local' and os.path.exists(midia_info):
                    clip = ImageClip(midia_info, duration=duracao_por_extra)
                    clip = clip.resize(height=1920)
                    if clip.w > 1080:
                        clip = clip.crop(x_center=clip.w/2, width=1080, height=1920)
                    elif clip.w < 1080:
                        clip = clip.resize(width=1080)
                    
                    if clip.size != (1080, 1920):
                        clip = clip.resize((1080, 1920))
                    
                    clip = clip.set_start(tempo_coberto)
                    clips_imagem.append(clip)
                    tempo_coberto += duracao_por_extra
            except:
                continue
    
    if not clips_imagem:
        print("❌ Nenhum clip de imagem criado!")
        return None
    
    # Compor vídeo
    print("🎬 Compondo vídeo...")
    video_base = CompositeVideoClip(clips_imagem, size=(1080, 1920))
    video_base = video_base.set_duration(duracao_total)
    
    # Adicionar áudio
    print("🎵 Adicionando áudio...")
    audio = AudioFileClip(audio_path)
    video_final = video_base.set_audio(audio)
    
    # Renderizar
    print("💾 Renderizando...")
    video_final.write_videofile(
        output_file,
        fps=30,
        codec='libx264',
        audio_codec='aac',
        preset='medium',
        bitrate='8000k',
        threads=4
    )
    
    # Limpar
    print("🧹 Limpando memória...")
    video_final.close()
    audio.close()
    for clip in clips_imagem:
        clip.close()
    
    return output_file

def criar_video_long_sem_legendas(audio_path, midias_sincronizadas, output_file, duracao_total):
    """Cria vídeo longo SEM legendas - VERSÃO SIMPLIFICADA"""
    print(f"📹 Criando vídeo longo (sem legendas)...")
    
    clips_imagem = []
    tempo_coberto = 0
    
    for i, item in enumerate(midias_sincronizadas):
        midia_info, midia_tipo = item['midia']
        inicio = item['inicio']
        duracao_clip = item['duracao']
        
        try:
            if midia_tipo == 'foto_local' and os.path.exists(midia_info):
                clip = ImageClip(midia_info, duration=duracao_clip)
                
                # Resize para 1920x1080 (16:9)
                clip = clip.resize(height=1080)
                if clip.w < 1920:
                    clip = clip.resize(width=1920)
                
                clip = clip.crop(x_center=clip.w/2, y_center=clip.h/2, width=1920, height=1080)
                
                if clip.size != (1920, 1080):
                    clip = clip.resize((1920, 1080))
                
                clip = clip.resize(lambda t: 1 + 0.03 * (t / duracao_clip))
                clip = clip.set_start(inicio)
                
                clips_imagem.append(clip)
                tempo_coberto = max(tempo_coberto, inicio + duracao_clip)
                
        except Exception as e:
            print(f"⚠️ Erro {i}: {e}")
    
    # Preencher lacunas
    if tempo_coberto < duracao_total:
        extras = buscar_midias_final(['brasil'], quantidade=5)
        duracao_restante = duracao_total - tempo_coberto
        duracao_por_extra = duracao_restante / len(extras) if extras else duracao_restante
        
        for idx, (midia_info, midia_tipo) in enumerate(extras):
            try:
                if midia_tipo == 'foto_local' and os.path.exists(midia_info):
                    clip = ImageClip(midia_info, duration=duracao_por_extra)
                    clip = clip.resize(height=1080)
                    if clip.w < 1920:
                        clip = clip.resize(width=1920)
                    
                    clip = clip.crop(x_center=clip.w/2, y_center=clip.h/2, width=1920, height=1080)
                    
                    if clip.size != (1920, 1080):
                        clip = clip.resize((1920, 1080))
                    
                    clip = clip.set_start(tempo_coberto)
                    clips_imagem.append(clip)
                    tempo_coberto += duracao_por_extra
            except:
                continue
    
    if not clips_imagem:
        return None
    
    video_base = CompositeVideoClip(clips_imagem, size=(1920, 1080))
    video_base = video_base.set_duration(duracao_total)
    
    audio = AudioFileClip(audio_path)
    video_final = video_base.set_audio(audio)
    
    print("💾 Renderizando...")
    video_final.write_videofile(
        output_file,
        fps=24,
        codec='libx264',
        audio_codec='aac',
        preset='medium',
        bitrate='5000k',
        threads=4
    )
    
    video_final.close()
    audio.close()
    for clip in clips_imagem:
        clip.close()
    
    return output_file

def comprimir_thumbnail(input_path, max_size_mb=2):
    """Comprime thumbnail para no máximo 2MB mantendo qualidade"""
    print(f"🔍 Verificando tamanho da thumbnail...")
    
    # Verificar tamanho atual
    tamanho_atual = os.path.getsize(input_path) / (1024 * 1024)  # MB
    print(f"   Tamanho atual: {tamanho_atual:.2f}MB")
    
    if tamanho_atual <= max_size_mb:
        print(f"   ✅ Thumbnail OK (menor que {max_size_mb}MB)")
        return input_path
    
    print(f"   ⚠️ Thumbnail muito grande! Comprimindo...")
    
    # Criar caminho para thumbnail comprimida
    output_path = input_path.replace('.jpg', '_compressed.jpg').replace('.png', '_compressed.jpg')
    
    try:
        # Abrir imagem
        img = Image.open(input_path)
        
        # Converter para RGB se necessário (PNG com alpha)
        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = background
        
        # Redimensionar se muito grande (YouTube recomenda 1280x720)
        max_dimension = 1280
        if img.width > max_dimension or img.height > max_dimension:
            ratio = min(max_dimension / img.width, max_dimension / img.height)
            new_size = (int(img.width * ratio), int(img.height * ratio))
            img = img.resize(new_size, Image.LANCZOS)
            print(f"   📏 Redimensionada para: {new_size[0]}x{new_size[1]}")
        
        # Comprimir com qualidade progressiva
        quality = 95
        while quality > 60:
            img.save(output_path, 'JPEG', quality=quality, optimize=True)
            tamanho_novo = os.path.getsize(output_path) / (1024 * 1024)
            
            if tamanho_novo <= max_size_mb:
                print(f"   ✅ Comprimida: {tamanho_novo:.2f}MB (qualidade {quality})")
                return output_path
            
            quality -= 5
        
        # Se ainda muito grande, reduzir mais
        if tamanho_novo > max_size_mb:
            img = img.resize((int(img.width * 0.8), int(img.height * 0.8)), Image.LANCZOS)
            img.save(output_path, 'JPEG', quality=85, optimize=True)
            tamanho_final = os.path.getsize(output_path) / (1024 * 1024)
            print(f"   ✅ Compressão forçada: {tamanho_final:.2f}MB")
        
        return output_path
        
    except Exception as e:
        print(f"   ❌ Erro ao comprimir: {e}")
        return input_path

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
            try:
                # Comprimir se necessário
                thumbnail_final = comprimir_thumbnail(thumbnail_path, max_size_mb=2)
                
                # Fazer upload
                youtube.thumbnails().set(
                    videoId=video_id,
                    media_body=MediaFileUpload(thumbnail_final)
                ).execute()
                print("✅ Thumbnail configurada!")
                
                # Limpar arquivo comprimido se foi criado
                if thumbnail_final != thumbnail_path and os.path.exists(thumbnail_final):
                    try:
                        os.remove(thumbnail_final)
                    except:
                        pass
                        
            except Exception as e:
                print(f"⚠️ Erro ao fazer upload da thumbnail: {e}")
                import traceback
                traceback.print_exc()
        
        return video_id
        
    except Exception as e:
        print(f"❌ Erro upload: {e}")
        raise

def main():
    print(f"{'📱' if VIDEO_TYPE == 'short' else '🎬'} Iniciando...")
    
    os.makedirs(VIDEOS_DIR, exist_ok=True)
    os.makedirs(ASSETS_DIR, exist_ok=True)
    
    # Buscar notícia(s) baseado no tipo de vídeo
    if VIDEO_TYPE == 'short':
        # Para shorts: 1 notícia apenas
        noticias = buscar_noticias(quantidade=1)
        
        if noticias:
            titulo_video = noticias['titulo']
            keywords = titulo_video.split()[:5]
            print(f"📰 Notícia: {titulo_video}")
        else:
            tema = random.choice(config.get('temas', ['política brasileira']))
            print(f"📝 Tema: {tema}")
            info = gerar_titulo_especifico(tema)
            titulo_video = info['titulo']
            keywords = info['keywords']
            noticias = None
    else:
        # Para vídeos longos: múltiplas notícias (5-7)
        duracao_minutos = config.get('duracao_minutos', 10)
        quantidade_noticias = max(5, min(7, duracao_minutos // 2))  # ~2min por notícia
        
        noticias = buscar_noticias(quantidade=quantidade_noticias)
        
        if noticias and len(noticias) > 1:
            titulo_video = f"Resumo de Notícias: {datetime.now().strftime('%d/%m/%Y')}"
            keywords = ['política', 'brasil', 'notícias', 'atualidades']
            print(f"📰 {len(noticias)} notícias encontradas para vídeo longo")
        elif noticias and len(noticias) == 1:
            titulo_video = noticias[0]['titulo']
            keywords = titulo_video.split()[:5]
            print(f"📰 Notícia única: {titulo_video}")
        else:
            tema = random.choice(config.get('temas', ['política brasileira']))
            print(f"📝 Tema: {tema}")
            info = gerar_titulo_especifico(tema)
            titulo_video = info['titulo']
            keywords = info['keywords']
            noticias = None
    
    print(f"🎯 Título: {titulo_video}")
    
    # Gerar roteiro (agora aceita lista de notícias)
    print("✍️ Gerando roteiro...")
    roteiro = gerar_roteiro(VIDEO_TYPE, titulo_video, noticias)
    
    print(f"📝 Roteiro gerado: {len(roteiro.split())} palavras")
    
    # Criar áudio
    audio_path = f'{ASSETS_DIR}/audio.mp3'
    criar_audio(roteiro, audio_path)
    
    audio_clip = AudioFileClip(audio_path)
    duracao = audio_clip.duration
    audio_clip.close()
    
    print(f"⏱️ Duração do áudio: {duracao:.1f}s ({duracao/60:.1f}min)")
    
    # Buscar mídias COM CURADORIA
    print("\n" + "="*60)
    print(f"🔍 INICIANDO BUSCA DE MÍDIAS PARA {VIDEO_TYPE.upper()}")
    print("="*60)
    
    midias_sincronizadas = analisar_roteiro_e_buscar_midias(roteiro, duracao)
    
    print(f"\n✅ {len(midias_sincronizadas)} mídias sincronizadas")
    
    # Complementar se necessário
    minimo_midias = 3 if VIDEO_TYPE == 'short' else 8
    
    if len(midias_sincronizadas) < minimo_midias:
        print(f"⚠️ Complementando para mínimo de {minimo_midias}...")
        extras = buscar_midias_final(['brasil'], quantidade=10)
        tempo_restante = duracao - sum([m['duracao'] for m in midias_sincronizadas])
        duracao_extra = tempo_restante / len(extras) if extras and tempo_restante > 0 else 0
        
        for extra in extras:
            if len(midias_sincronizadas) >= minimo_midias:
                break
            
            midias_sincronizadas.append({
                'midia': extra,
                'inicio': duracao - tempo_restante,
                'duracao': max(duracao_extra, 3)  # mínimo 3s por mídia
            })
            tempo_restante -= duracao_extra
    
    # Montar vídeo
    print("\n" + "="*60)
    print("🎥 MONTANDO VÍDEO")
    print("="*60)
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    video_path = f'{VIDEOS_DIR}/{VIDEO_TYPE}_{timestamp}.mp4'
    
    try:
        if VIDEO_TYPE == 'short':
            resultado = criar_video_short_sem_legendas(
                audio_path,
                midias_sincronizadas,
                video_path,
                duracao
            )
        else:
            resultado = criar_video_long_sem_legendas(
                audio_path,
                midias_sincronizadas,
                video_path,
                duracao
            )
        
        if not resultado:
            print("❌ Erro ao criar vídeo")
            return
        
        print("✅ Vídeo criado com sucesso!")
        
    except Exception as e:
        print(f"❌ Erro ao criar vídeo: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Preparar metadados
    titulo = titulo_video[:60] if len(titulo_video) <= 60 else titulo_video[:57] + '...'
    if VIDEO_TYPE == 'short':
        titulo += ' #shorts'
    
    descricao = roteiro[:300] + '...\n\n🔔 Inscreva-se!\n#' + ('shorts' if VIDEO_TYPE == 'short' else 'noticias')
    
    tags = ['noticias', 'informacao', 'politica', 'brasil']
    if VIDEO_TYPE == 'short':
        tags.append('shorts')
    
    # SOLICITAR THUMBNAIL
    thumbnail_path = None
    if USAR_CURACAO:
        print("\n" + "="*60)
        print("🖼️ SOLICITANDO THUMBNAIL")
        print("="*60)
        
        try:
            curator = TelegramCuratorNoticias()
            thumbnail_path = curator.solicitar_thumbnail(titulo, timeout=1200)
            
            if thumbnail_path:
                print(f"✅ Thumbnail recebida: {thumbnail_path}")
            else:
                print("⚠️ Usando thumbnail automática (YouTube)")
        except Exception as e:
            print(f"⚠️ Erro ao solicitar thumbnail: {e}")
            print("⚠️ Continuando com thumbnail automática")
    
    # Upload
    print("\n📤 Fazendo upload para YouTube...")
    try:
        video_id = fazer_upload_youtube(
            video_path,
            titulo,
            descricao,
            tags,
            thumbnail_path
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
            'com_legendas': False,
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
                if not file.startswith('custom_') and not file.startswith('thumbnail_'):
                    os.remove(os.path.join(ASSETS_DIR, file))
            except:
                pass
                
    except Exception as e:
        print(f"❌ Erro no upload: {e}")
        import traceback
        traceback.print_exc()
        raise

if __name__ == '__main__':
    main()
