import os
import json
import random
import re
import asyncio
import time
import sys
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
model = genai.GenerativeModel('gemini-3-flash-preview')

with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
    config = json.load(f)

def buscar_noticias(quantidade=1):
    """Busca notícias dos feeds RSS configurados"""
    if config.get('tipo') != 'noticias':
        return None
    
    feeds = config.get('rss_feeds', [])
    todas_noticias = []
    titulos_vistos = set()
    
    noticias_por_feed = 10 if quantidade > 1 else 3
    
    print(f"🔍 Buscando notícias de {len(feeds)} feeds RSS...")
    
    for feed_url in feeds[:3]:
        try:
            print(f"   📡 Feed: {feed_url[:50]}...")
            feed = feedparser.parse(feed_url)
            
            noticias_feed = 0
            for entry in feed.entries[:noticias_por_feed]:
                titulo = entry.title.strip()
                titulo_normalizado = titulo.lower().strip('.,!?;: ')
                
                if titulo_normalizado not in titulos_vistos:
                    todas_noticias.append({
                        'titulo': titulo,
                        'resumo': entry.get('summary', titulo),
                        'link': entry.link
                    })
                    titulos_vistos.add(titulo_normalizado)
                    noticias_feed += 1
                else:
                    print(f"   ⚠️ Notícia duplicada ignorada: {titulo[:50]}...")
            
            print(f"   ✅ {noticias_feed} notícias únicas deste feed")
            
        except Exception as e:
            print(f"   ❌ Erro ao buscar feed: {e}")
            continue
    
    if not todas_noticias:
        print("   ⚠️ Nenhuma notícia encontrada!")
        return None
    
    print(f"\n✅ Total: {len(todas_noticias)} notícias únicas encontradas")
    
    if quantidade == 1:
        return random.choice(todas_noticias)
    
    random.shuffle(todas_noticias)
    noticias_selecionadas = todas_noticias[:min(quantidade, len(todas_noticias))]
    
    print(f"📰 Selecionadas {len(noticias_selecionadas)} notícias para o vídeo:")
    for i, noticia in enumerate(noticias_selecionadas, 1):
        print(f"   {i}. {noticia['titulo'][:60]}...")
    
    return noticias_selecionadas

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

def gerar_roteiro_segmentado(noticias, duracao_por_noticia=120):
    """Gera roteiro segmentado para vídeo longo com múltiplas notícias"""
    print(f"\n✍️ Gerando roteiros segmentados...")
    print(f"   {len(noticias)} notícias aprovadas")
    print(f"   ~{duracao_por_noticia}s por notícia")
    
    palavras_por_segundo = 2.5
    palavras_por_noticia = int(duracao_por_noticia * palavras_por_segundo)
    
    roteiros_individuais = []
    tempo_atual = 0
    
    for i, noticia in enumerate(noticias):
        print(f"\n   📝 Gerando roteiro {i+1}/{len(noticias)}: {noticia['titulo'][:50]}...")
        
        prompt = f"""Crie um script JORNALÍSTICO sobre esta notícia:

TÍTULO: {noticia['titulo']}
RESUMO: {noticia['resumo']}

REGRAS IMPORTANTES:
- Aproximadamente {palavras_por_noticia} palavras (2 minutos de narração)
- Tom noticioso e informativo
- Este é o segmento {i+1} de {len(noticias)} notícias
- {"Comece com 'Em outras notícias' ou 'Também destaque de hoje' para criar transição" if i > 0 else "Comece direto na notícia"}
- NÃO mencione apresentador, elementos visuais ou "vamos para"
- Aproximadamente 200 palavras
- Texto corrido para narração
- SEM formatação, asteriscos, marcadores ou emojis
- TERMINE o segmento de forma conclusiva para esta notícia específica

Escreva APENAS o roteiro deste segmento."""

        try:
            response = model.generate_content(prompt)
            roteiro = response.text
            
            roteiro = re.sub(r'\*+', '', roteiro)
            roteiro = re.sub(r'#+\s', '', roteiro)
            roteiro = re.sub(r'^-\s', '', roteiro, flags=re.MULTILINE)
            roteiro = roteiro.replace('*', '').replace('#', '').replace('_', '').strip()
            
            palavras = len(roteiro.split())
            duracao_estimada = palavras / palavras_por_segundo
            
            roteiros_individuais.append({
                'noticia': noticia,
                'roteiro': roteiro,
                'palavras': palavras,
                'duracao_estimada': duracao_estimada,
                'inicio': tempo_atual,
                'fim': tempo_atual + duracao_estimada
            })
            
            tempo_atual += duracao_estimada
            print(f"   ✅ {palavras} palavras (~{duracao_estimada:.1f}s)")
            
        except Exception as e:
            print(f"   ❌ Erro: {e}")
            continue
    
    roteiro_completo = "\n\n".join([r['roteiro'] for r in roteiros_individuais])
    
    print(f"\n✅ Roteiro completo gerado:")
    print(f"   {len(roteiros_individuais)} segmentos")
    print(f"   {len(roteiro_completo.split())} palavras totais")
    print(f"   ~{tempo_atual:.1f}s (~{tempo_atual/60:.1f}min)")
    
    return {
        'segmentos': roteiros_individuais,
        'roteiro_completo': roteiro_completo,
        'duracao_total_estimada': tempo_atual
    }

def gerar_roteiro(duracao_alvo, titulo, noticias=None):
    """Gera roteiro de narração APENAS PARA SHORTS"""
    if duracao_alvo != 'short':
        raise Exception("Use gerar_roteiro_segmentado() para vídeos longos")
    
    palavras_alvo = 200
    tempo = '60-90 segundos'
    
    if noticias and (isinstance(noticias, dict) or (isinstance(noticias, list) and len(noticias) == 1)):
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
    
    texto = re.sub(r'\*+', '', texto)
    texto = re.sub(r'#+\s', '', texto)
    texto = re.sub(r'^-\s', '', texto, flags=re.MULTILINE)
    texto = texto.replace('*', '').replace('#', '').replace('_', '').strip()
    
    return texto

async def criar_audio_async(texto, output_file):
    """Cria áudio com Edge TTS (async)"""
    voz = config.get('voz', 'pt-BR-ThalitaMultilingualNeural')
    
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
        'carmen': 'politicos/carmen_lucia',
        'alcolumbre': 'politicos/davi_alcolumbre',
        'toffoli': 'politicos/dias_toffoli',
        'dilma': 'politicos/dilma_roussef',
        'trump': 'politicos/donald_trump',
        'dino': 'politicos/flavio_dino',
        'alckmin': 'politicos/geraldo_alckmin',
        'gilmar': 'politicos/gilmar_mendes',
        'hugo': 'politicos/hugo_mota',
        'milei': 'politicos/javier_milei',
        'barroso': 'politicos/luis_roberto_barroso',
        'macron': 'politicos/macron',
        'biden': 'politicos/joe_biden',
        'bukele': 'politicos/nayib_bukele',
        'netanyahu': 'politicos/netanyahu',
        'maduro': 'politicos/nicolas_maduro',
        'putin': 'politicos/putin',
        'jinping': 'politicos/xi_jinping',
        'zanin': 'politicos/zanin',
        'fux': 'politicos/fux',
        'fachin': 'politicos/fachin',
        'mendonça': 'politicos/mendonça',
        'nunes': 'politicos/nunes',
        
        
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
    
    for termo, pasta in mapa_politicos.items():
        if termo in keywords_texto:
            pasta_encontrada = pasta
            print(f"  📁 Político: {termo} → {pasta}")
            break
    
    if not pasta_encontrada:
        for termo, pasta in mapa_instituicoes.items():
            if termo in keywords_texto:
                pasta_encontrada = pasta
                print(f"  📁 Instituição: {termo} → {pasta}")
                break
    
    if not pasta_encontrada:
        pasta_encontrada = 'genericas'
        print(f"  📁 Genérica")
    
    pasta_completa = f'{ASSETS_DIR}/{pasta_encontrada}'
    
    try:
        if os.path.exists(pasta_completa):
            arquivos_foto = [f for f in os.listdir(pasta_completa)
                     if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
            arquivos_video = [f for f in os.listdir(pasta_completa)
                      if f.lower().endswith(('.mp4', '.mov', '.avi', '.mkv'))]
            arquivos = arquivos_foto + arquivos_video
            
            if arquivos:
                random.shuffle(arquivos)
                for arquivo in arquivos[:quantidade]:
                    caminho_completo = os.path.join(pasta_completa, arquivo)
                    if os.path.exists(caminho_completo):
                        tipo = 'video_local' if arquivo.lower().endswith(('.mp4', '.mov', '.avi', '.mkv')) else 'foto_local'
                        midias.append((caminho_completo, tipo))
                
                if midias:
                    print(f"  ✅ {len(midias)} imagem(ns)")
                    return midias
    except Exception as e:
        print(f"  ⚠️ Erro: {e}")
    
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
    print(f"   {len(segmentos)} segmentos identificados")
    
    palavras_total = len(roteiro.split())
    palavras_por_segundo = palavras_total / duracao_audio
    
    segmentos_com_tempo = []
    tempo_atual = 0
    
    for i, segmento in enumerate(segmentos):
        palavras_segmento = len(segmento.split())
        duracao_segmento = palavras_segmento / palavras_por_segundo
        keywords = extrair_keywords_do_texto(segmento)
        
        segmentos_com_tempo.append({
            'texto': segmento[:50],           # Resumo curto (compatibilidade)
            'texto_completo': segmento,        # ALTERAÇÃO: texto integral do segmento
            'inicio': tempo_atual,
            'duracao': duracao_segmento,
            'keywords': keywords
        })
        tempo_atual += duracao_segmento
    
    midias_sincronizadas = []
    
    for i, seg in enumerate(segmentos_com_tempo):
        midia = buscar_midias_final(seg['keywords'], quantidade=1)
        
        if midia and len(midia) > 0:
            midias_sincronizadas.append({
                'midia': midia[0],
                'inicio': seg['inicio'],
                'duracao': seg['duracao'],
                'texto': seg['texto'],
                'texto_completo': seg['texto_completo'],  # ALTERAÇÃO: incluir texto completo
                'keywords': seg['keywords']
            })
    
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


# ========================================
# FUNÇÕES AUXILIARES PARA PROCESSAMENTO DE VÍDEO
# ========================================

def obter_duracao_video(video_path):
    """Obtém duração de um arquivo de vídeo em segundos"""
    try:
        clip = VideoFileClip(video_path)
        duracao = clip.duration
        clip.close()
        return duracao
    except Exception as e:
        print(f"  ⚠️ Não foi possível obter duração do vídeo: {e}")
        return None

def preparar_clip_video(video_path, duracao_alvo, orientacao='short'):
    """
    Carrega e prepara um clip de vídeo, cortando o excedente se necessário.
    
    Args:
        video_path: caminho para o arquivo de vídeo
        duracao_alvo: duração em segundos que o clip deve ter
        orientacao: 'short' (1080x1920 vertical) ou 'long' (1920x1080 horizontal)
    
    Returns:
        VideoFileClip preparado e dimensionado, ou None em caso de erro
    """
    try:
        clip = VideoFileClip(video_path)
        duracao_original = clip.duration
        
        print(f"  🎬 Vídeo: {duracao_original:.1f}s | Segmento: {duracao_alvo:.1f}s")
        
        # CORTE: se o vídeo for mais longo que o segmento, cortar o excedente
        if duracao_original > duracao_alvo:
            print(f"  ✂️ Cortando vídeo de {duracao_original:.1f}s → {duracao_alvo:.1f}s")
            clip = clip.subclip(0, duracao_alvo)
        
        # Redimensionar para o formato correto
        if orientacao == 'short':
            # Vertical 1080x1920
            clip = clip.resize(height=1920)
            if clip.w > 1080:
                clip = clip.crop(x_center=clip.w / 2, width=1080, height=1920)
            elif clip.w < 1080:
                clip = clip.resize(width=1080)
            if clip.size != (1080, 1920):
                clip = clip.resize((1080, 1920))
        else:
            # Horizontal 1920x1080
            clip = clip.resize(height=1080)
            if clip.w < 1920:
                clip = clip.resize(width=1920)
            clip = clip.crop(x_center=clip.w / 2, y_center=clip.h / 2, width=1920, height=1080)
            if clip.size != (1920, 1080):
                clip = clip.resize((1920, 1080))
        
        # Remover áudio do clip de vídeo (o áudio vem da narração)
        clip = clip.without_audio()
        
        return clip
        
    except Exception as e:
        print(f"  ❌ Erro ao preparar clip de vídeo: {e}")
        return None


def criar_video_short_sem_legendas(audio_path, midias_sincronizadas, output_file, duracao_total):
    """Cria SHORT SEM legendas - suporta fotos E vídeos"""
    print(f"📹 Criando short (sem legendas)...")
    
    clips_imagem = []
    tempo_coberto = 0
    
    for i, item in enumerate(midias_sincronizadas):
        midia_info, midia_tipo = item['midia']
        inicio = item['inicio']
        duracao_clip = item['duracao']
        
        try:
            # ALTERAÇÃO: verificar se é vídeo ou foto
            if midia_tipo == 'video_local' and os.path.exists(midia_info):
                # Processar clip de vídeo
                print(f"  🎬 Clip {i+1}: vídeo → {os.path.basename(midia_info)}")
                clip = preparar_clip_video(midia_info, duracao_clip, orientacao='short')
                
                if clip is None:
                    print(f"  ⚠️ Falha no vídeo {i+1}, tentando fallback para imagem...")
                    raise Exception("Falha no clip de vídeo")
                
                clip = clip.set_start(inicio)
                clips_imagem.append(clip)
                tempo_coberto = max(tempo_coberto, inicio + clip.duration)
            
            elif midia_tipo == 'foto_local' and os.path.exists(midia_info):
                # Processar foto (comportamento original)
                clip = ImageClip(midia_info, duration=duracao_clip)
                clip = clip.resize(height=1920)
                if clip.w > 1080:
                    clip = clip.crop(x_center=clip.w/2, width=1080, height=1920)
                elif clip.w < 1080:
                    clip = clip.resize(width=1080)
                
                if clip.size != (1080, 1920):
                    clip = clip.resize((1080, 1920))
                
                clip = clip.resize(lambda t: 1 + 0.05 * (t / duracao_clip))
                clip = clip.set_start(inicio)
                
                clips_imagem.append(clip)
                tempo_coberto = max(tempo_coberto, inicio + duracao_clip)
                
        except Exception as e:
            print(f"  ⚠️ Erro mídia {i}: {e}")
    
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
    
    print("🎬 Compondo vídeo...")
    video_base = CompositeVideoClip(clips_imagem, size=(1080, 1920))
    video_base = video_base.set_duration(duracao_total)
    
    print("🎵 Adicionando áudio...")
    audio = AudioFileClip(audio_path)
    video_final = video_base.set_audio(audio)
    
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
    
    print("🧹 Limpando memória...")
    video_final.close()
    audio.close()
    for clip in clips_imagem:
        clip.close()
    
    return output_file

def criar_video_long_sem_legendas(audio_path, midias_sincronizadas, output_file, duracao_total):
    """Cria vídeo longo SEM legendas - suporta fotos E vídeos"""
    print(f"📹 Criando vídeo longo...")
    
    clips_imagem = []
    tempo_coberto = 0
    
    for i, item in enumerate(midias_sincronizadas):
        midia_info, midia_tipo = item['midia']
        inicio = item['inicio']
        duracao_clip = item['duracao']
        
        try:
            # ALTERAÇÃO: verificar se é vídeo ou foto
            if midia_tipo == 'video_local' and os.path.exists(midia_info):
                # Processar clip de vídeo
                print(f"  🎬 Clip {i+1}: vídeo → {os.path.basename(midia_info)}")
                clip = preparar_clip_video(midia_info, duracao_clip, orientacao='long')
                
                if clip is None:
                    print(f"  ⚠️ Falha no vídeo {i+1}, pulando...")
                    continue
                
                clip = clip.set_start(inicio)
                clips_imagem.append(clip)
                tempo_coberto = max(tempo_coberto, inicio + clip.duration)
            
            elif midia_tipo == 'foto_local' and os.path.exists(midia_info):
                # Processar foto (comportamento original)
                clip = ImageClip(midia_info, duration=duracao_clip)
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
            print(f"  ⚠️ Erro {i}: {e}")
    
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
    video_base = video_base.set_audio(audio)
    
    print("💾 Renderizando...")
    video_base.write_videofile(
        output_file,
        fps=24,
        codec='libx264',
        audio_codec='aac',
        preset='medium',
        bitrate='5000k',
        threads=4
    )
    
    video_base.close()
    audio.close()
    for clip in clips_imagem:
        clip.close()
    
    return output_file

def fazer_upload_youtube(video_path, titulo, descricao, tags, thumbnail_path=None):
    """Faz upload para YouTube"""
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
        
        # Upload thumbnail
        if thumbnail_path and os.path.exists(thumbnail_path):
            print("📤 Fazendo upload da thumbnail...")
            try:
                youtube.thumbnails().set(
                    videoId=video_id,
                    media_body=MediaFileUpload(thumbnail_path)
                ).execute()
                print("✅ Thumbnail configurada!")
            except Exception as e:
                print(f"❌ Erro thumbnail: {e}")
        
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
    
    # Definir video_path ANTES de criar o vídeo
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    video_path = f'{VIDEOS_DIR}/{VIDEO_TYPE}_{timestamp}.mp4'
    print(f"📹 Arquivo: {video_path}")
    
    # Montar vídeo
    print("🎥 Montando vídeo...")
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
        
        print("✅ Vídeo criado!")
        
    except Exception as e:
        print(f"❌ Erro: {e}")
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
    
    # Thumbnail
    thumbnail_path = None
    if USAR_CURACAO:
        print("\n" + "="*60)
        print("🖼️ VERIFICANDO THUMBNAIL")
        print("="*60)
        
        thumbnail_custom = f'{ASSETS_DIR}/thumbnail_custom.jpg'
        if os.path.exists(thumbnail_custom):
            print("✅ Thumbnail já recebida")
            thumbnail_path = thumbnail_custom
        else:
            try:
                curator = TelegramCuratorNoticias()
                thumbnail_path = curator.solicitar_thumbnail(titulo, timeout=1200)
                
                if thumbnail_path:
                    print(f"✅ Thumbnail: {thumbnail_path}")
                else:
                    print("⚠️ Thumbnail automática")
            except Exception as e:
                print(f"⚠️ Erro: {e}")
    
    # Upload YouTube
    print("\n📤 Upload YouTube...")
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
        
        # ENVIAR VÍDEO PARA TELEGRAM
        if USAR_CURACAO:
            print("\n" + "="*60)
            print("📱 ENVIANDO PARA TELEGRAM")
            print("="*60)
    
            try:
                curator = TelegramCuratorNoticias()
        
                # Verificar tamanho do vídeo
                tamanho_mb = os.path.getsize(video_path) / (1024 * 1024)
                print(f"   📦 Tamanho do vídeo: {tamanho_mb:.2f} MB")
        
                if tamanho_mb <= 50:
                    # Vídeo pequeno: enviar arquivo direto
                    print("   📤 Vídeo ≤ 50 MB - enviando arquivo direto...")
            
                    sucesso = curator.enviar_video_publicado(
                        video_path=video_path,
                        titulo=titulo,
                        descricao=descricao,
                        tags=tags,
                        url_youtube=url
                    )
            
                    if sucesso:
                        print("✅ Vídeo enviado diretamente!")
                        print("\n" + "="*60)
                        print("✅ WORKFLOW CONCLUÍDO COM SUCESSO!")
                        print("="*60)
                        sys.exit(0)
                    else:
                        print("⚠️ Falha ao enviar vídeo")
                        sys.exit(1)
                
                else:
                    # Vídeo grande: criar release e enviar link
                    print("   📦 Vídeo > 50 MB - criando release no GitHub...")
            
                    from create_release import criar_release_com_video
            
                    release_info = criar_release_com_video(
                        video_path=video_path,
                        titulo=titulo,
                        descricao=descricao
                    )
            
                    if release_info:
                        download_url = release_info['download_url']
                        tag_name = release_info['tag_name']
                
                        print("   ✅ Release criada!")
                        print(f"   🔗 {download_url}")
                        print(f"   🏷️ Tag: {tag_name}")
                
                        sucesso = curator.enviar_link_download(
                            download_url=download_url,
                            titulo=titulo,
                            descricao=descricao,
                            tags=tags,
                            url_youtube=url,
                            duracao=duracao,
                            tamanho_mb=tamanho_mb,
                            tag_name=tag_name
                        )
                
                        if sucesso:
                            print("✅ Link enviado com botão de confirmação!")
                    
                            print("\n⏳ Aguardando você confirmar o download...")
                            confirmado = curator.aguardar_confirmacao_download(timeout=7200)
                    
                            if confirmado:
                                print("✅ Download confirmado! Release será deletada.")
                            else:
                                print("⏰ Timeout - release permanecerá no GitHub")
                                print("   💡 Delete manualmente se já baixou: Settings > Releases")
                        else:
                            print("⚠️ Falha ao enviar link")
                    else:
                        print("❌ Erro ao criar release")
                        print("   Tentando enviar só metadados...")
                
                        curator.enviar_mensagem(
                            f"⚠️ <b>Vídeo muito grande ({tamanho_mb:.2f} MB)</b>\n\n"
                            f"📺 {titulo}\n\n"
                            f"🔗 YouTube: {url}\n\n"
                            f"📁 Vídeo disponível nos GitHub Actions Artifacts por 7 dias"
                        )
        
            except Exception as e:
                print(f"⚠️ Erro ao processar envio: {e}")
                import traceback
                traceback.print_exc()
        
    except Exception as e:
        print(f"❌ Erro no upload: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()
