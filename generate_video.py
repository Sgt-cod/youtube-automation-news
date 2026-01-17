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
model = genai.GenerativeModel('gemini-3-flash-preview')

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
    titulos_vistos = set()  # Para evitar duplicatas
    
    # Para vídeos longos, buscar mais notícias
    noticias_por_feed = 10 if quantidade > 1 else 3
    
    print(f"🔍 Buscando notícias de {len(feeds)} feeds RSS...")
    
    for feed_url in feeds[:3]:
        try:
            print(f"   📡 Feed: {feed_url[:50]}...")
            feed = feedparser.parse(feed_url)
            
            noticias_feed = 0
            for entry in feed.entries[:noticias_por_feed]:
                titulo = entry.title.strip()
                
                # Verificar se título já foi visto (evitar duplicatas)
                # Normalizar: remover pontuação extra e minúsculas
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
    
    # Para short: retorna 1 notícia
    if quantidade == 1:
        return random.choice(todas_noticias)
    
    # Para long: retorna até a quantidade solicitada (sem duplicatas)
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
    """Gera roteiro segmentado para vídeo longo com múltiplas notícias
    
    Args:
        noticias: lista de notícias aprovadas
        duracao_por_noticia: segundos por notícia (~2 minutos = 120s)
    
    Returns:
        dict com roteiros individuais e roteiro completo
    """
    print(f"\n✍️ Gerando roteiros segmentados...")
    print(f"   {len(noticias)} notícias aprovadas")
    print(f"   ~{duracao_por_noticia}s por notícia")
    
    palavras_por_segundo = 2.5  # velocidade média de fala
    palavras_por_noticia = int(duracao_por_noticia * palavras_por_segundo)
    
    roteiros_individuais = []
    segmentos_tempo = []
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
- Texto corrido para narração
- SEM formatação, asteriscos, marcadores ou emojis
- TERMINE o segmento de forma conclusiva para esta notícia específica

Escreva APENAS o roteiro deste segmento."""

        try:
            response = model.generate_content(prompt)
            roteiro = response.text
            
            # Limpeza
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
    
    # Juntar todos os roteiros
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
    """Gera roteiro de narração APENAS PARA SHORTS
    
    Args:
        duracao_alvo: 'short' apenas (long usa gerar_roteiro_segmentado)
        titulo: título do vídeo
        noticias: notícia única para o short
    """
    if duracao_alvo != 'short':
        raise Exception("Use gerar_roteiro_segmentado() para vídeos longos")
    
    palavras_alvo = 120
    tempo = '30-60 segundos'
    
    # Para short com 1 notícia
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
    print(f"   Duração total do áudio: {duracao_audio:.1f}s")
    print(f"   USAR_CURACAO: {USAR_CURACAO}")
    print(f"   CURACAO_DISPONIVEL: {CURACAO_DISPONIVEL}")
    
    segmentos = re.split(r'[.!?]\s+', roteiro)
    segmentos = [s.strip() for s in segmentos if len(s.strip()) > 20]
    print(f"   {len(segmentos)} segmentos identificados")
    
    palavras_total = len(roteiro.split())
    palavras_por_segundo = palavras_total / duracao_audio
    print(f"   Ritmo: {palavras_por_segundo:.2f} palavras/segundo")
    
    segmentos_com_tempo = []
    tempo_atual = 0
    
    for i, segmento in enumerate(segmentos):
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
        
        if i < 3:  # Mostrar primeiros 3 segmentos
            print(f"   Seg {i+1}: {duracao_segmento:.1f}s - '{segmento[:40]}...'")
    
    midias_sincronizadas = []
    
    print(f"\n🔍 Buscando mídias para {len(segmentos_com_tempo)} segmentos...")
    
    for i, seg in enumerate(segmentos_com_tempo):
        print(f"\n   Segmento {i+1}/{len(segmentos_com_tempo)}")
        print(f"   Texto: '{seg['texto']}'...")
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
            print(f"   ✅ Mídia encontrada")
        else:
            print(f"   ❌ Sem mídia")
    
    print(f"\n✅ Total de mídias encontradas: {len(midias_sincronizadas)}/{len(segmentos_com_tempo)}")
    
    # CURADORIA - FORÇAR SEMPRE QUE USAR_CURACAO=True
    if USAR_CURACAO and CURACAO_DISPONIVEL:
        print("\n" + "="*60)
        print("🎬 INICIANDO CURADORIA")
        print("="*60)
        print(f"   Mídias para curadoria: {len(midias_sincronizadas)}")
        print(f"   Timeout configurado: {CURACAO_TIMEOUT}s ({CURACAO_TIMEOUT//60}min)")
        
        try:
            curator = TelegramCuratorNoticias()
            
            print("   📤 Enviando solicitação ao Telegram...")
            curator.solicitar_curacao(midias_sincronizadas)
            
            print(f"   ⏳ Aguardando aprovação (timeout: {CURACAO_TIMEOUT//60}min)...")
            midias_aprovadas = curator.aguardar_aprovacao(timeout=CURACAO_TIMEOUT)
            
            if midias_aprovadas:
                print("   ✅ Curadoria aprovada!")
                print(f"   {len(midias_aprovadas)} mídias aprovadas")
                midias_sincronizadas = midias_aprovadas
            else:
                print("   ⏰ Timeout na curadoria")
                print("   ⚠️ Usando mídias originais")
        except Exception as e:
            print(f"   ❌ Erro na curadoria: {e}")
            import traceback
            traceback.print_exc()
            print("   ⚠️ Continuando com mídias originais")
    else:
        print("\n⚠️ CURADORIA DESATIVADA")
        if not USAR_CURACAO:
            print("   Motivo: USAR_CURACAO=False")
        if not CURACAO_DISPONIVEL:
            print("   Motivo: telegram_curator_noticias.py não disponível")
    
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
    """Cria vídeo longo SEM legendas - COM VÍDEO DE ABERTURA"""
    print(f"📹 Criando vídeo longo (sem legendas)...")
    
    # VERIFICAR SE EXISTE VÍDEO DE ABERTURA
    video_abertura_path = f'{ASSETS_DIR}/abertura.mp4'
    tem_abertura = os.path.exists(video_abertura_path)
    
    if tem_abertura:
        print(f"🎬 Vídeo de abertura encontrado: {video_abertura_path}")
    else:
        print(f"⚠️ Vídeo de abertura não encontrado em {video_abertura_path}")
        print(f"   Para adicionar abertura, coloque um vídeo em: {video_abertura_path}")
    
    clips_imagem = []
    tempo_coberto = 0
    
    # ADICIONAR VÍDEO DE ABERTURA NO INÍCIO (se existir)
    if tem_abertura:
        try:
            print("📽️ Processando vídeo de abertura...")
            clip_abertura = VideoFileClip(video_abertura_path)
            
            # Redimensionar para 1920x1080 mantendo aspecto
            if clip_abertura.size != (1920, 1080):
                print(f"   Redimensionando de {clip_abertura.size} para 1920x1080")
                clip_abertura = clip_abertura.resize(height=1080)
                
                if clip_abertura.w > 1920:
                    clip_abertura = clip_abertura.crop(x_center=clip_abertura.w/2, width=1920, height=1080)
                elif clip_abertura.w < 1920:
                    # Adicionar barras laterais pretas
                    clip_abertura = clip_abertura.margin(
                        left=(1920-clip_abertura.w)//2,
                        right=(1920-clip_abertura.w)//2,
                        color=(0,0,0)
                    )
            
            # Garantir que tem áudio (mesmo que silêncio)
            if clip_abertura.audio is None:
                print("   ⚠️ Abertura sem áudio, adicionando silêncio")
                from moviepy.audio.AudioClip import AudioClip
                audio_silencio = AudioClip(lambda t: [0, 0], duration=clip_abertura.duration, fps=44100)
                clip_abertura = clip_abertura.set_audio(audio_silencio)
            
            duracao_abertura = clip_abertura.duration
            print(f"   ✅ Abertura: {duracao_abertura:.1f}s")
            
            # Adicionar no início (tempo 0)
            clip_abertura = clip_abertura.set_start(0)
            clips_imagem.append(clip_abertura)
            
            tempo_coberto = duracao_abertura
            
            print(f"   🎬 Vídeo de abertura adicionado ({duracao_abertura:.1f}s)")
            
        except Exception as e:
            print(f"   ❌ Erro ao processar abertura: {e}")
            import traceback
            traceback.print_exc()
            tem_abertura = False
            tempo_coberto = 0
    
    # ADICIONAR CLIPS DE IMAGEM (começando após a abertura)
    print(f"\n📸 Adicionando {len(midias_sincronizadas)} mídias...")
    
    for i, item in enumerate(midias_sincronizadas):
        midia_info, midia_tipo = item['midia']
        inicio_original = item['inicio']
        duracao_clip = item['duracao']
        
        # AJUSTAR TEMPO: somar duração da abertura
        inicio_ajustado = inicio_original + (tempo_coberto if tem_abertura else 0)
        
        try:
            if midia_tipo == 'foto_local' and os.path.exists(midia_info):
                print(f"   📷 Mídia {i+1}: {os.path.basename(midia_info)} (início: {inicio_ajustado:.1f}s)")
                
                clip = ImageClip(midia_info, duration=duracao_clip)
                
                # Resize para 1920x1080 (16:9)
                clip = clip.resize(height=1080)
                if clip.w < 1920:
                    clip = clip.resize(width=1920)
                
                clip = clip.crop(x_center=clip.w/2, y_center=clip.h/2, width=1920, height=1080)
                
                if clip.size != (1920, 1080):
                    clip = clip.resize((1920, 1080))
                
                # Animação zoom suave
                clip = clip.resize(lambda t: 1 + 0.03 * (t / duracao_clip))
                
                # Definir início ajustado
                clip = clip.set_start(inicio_ajustado)
                
                clips_imagem.append(clip)
                tempo_coberto = max(tempo_coberto, inicio_ajustado + duracao_clip)
                
        except Exception as e:
            print(f"   ⚠️ Erro mídia {i}: {e}")
    
    # Preencher lacunas se necessário
    duracao_total_com_abertura = duracao_total + (tempo_coberto if tem_abertura else 0)
    
    if tempo_coberto < duracao_total_com_abertura:
        print(f"\n⚠️ Preenchendo {duracao_total_com_abertura - tempo_coberto:.1f}s")
        extras = buscar_midias_final(['brasil'], quantidade=5)
        duracao_restante = duracao_total_com_abertura - tempo_coberto
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
        print("❌ Nenhum clip criado!")
        return None
    
    # COMPOR VÍDEO
    print(f"\n🎬 Compondo vídeo...")
    print(f"   Total de clips: {len(clips_imagem)}")
    print(f"   Duração total: {tempo_coberto:.1f}s ({tempo_coberto/60:.1f}min)")
    
    video_base = CompositeVideoClip(clips_imagem, size=(1920, 1080))
    video_base = video_base.set_duration(tempo_coberto)
    
    # ADICIONAR ÁUDIO
    print("🎵 Adicionando áudio...")
    audio = AudioFileClip(audio_path)
    
    # Se tem abertura, criar silêncio no início do áudio
    if tem_abertura:
        print(f"   🔇 Adicionando {duracao_abertura:.1f}s de silêncio no início do áudio")
        from moviepy.audio.AudioClip import AudioClip
        
        # Criar silêncio
        audio_silencio = AudioClip(lambda t: [0, 0], duration=duracao_abertura, fps=44100)
        
        # Concatenar: silêncio + áudio original
        from moviepy.audio.AudioClip import concatenate_audioclips
        audio_final = concatenate_audioclips([audio_silencio, audio])
        
        video_base = video_base.set_audio(audio_final)
    else:
        video_base = video_base.set_audio(audio)
    
    # RENDERIZAR
    print("\n💾 Renderizando vídeo final...")
    print(f"   Resolução: 1920x1080")
    print(f"   FPS: 24")
    print(f"   Duração: {tempo_coberto:.1f}s")
    
    video_base.write_videofile(
        output_file,
        fps=24,
        codec='libx264',
        audio_codec='aac',
        preset='medium',
        bitrate='5000k',
        threads=4
    )
    
    # LIMPAR
    print("🧹 Limpando memória...")
    video_base.close()
    audio.close()
    for clip in clips_imagem:
        clip.close()
    
    print("✅ Vídeo longo criado com sucesso!")
    return output_file

def comprimir_thumbnail(input_path, max_size_mb=2, is_short=False):
    """Comprime thumbnail para no máximo 2MB mantendo qualidade
    
    Args:
        input_path: caminho da imagem original
        max_size_mb: tamanho máximo em MB
        is_short: True se for short (9:16), False se for vídeo normal (16:9)
    """
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
        
        # Redimensionar se muito grande
        # YouTube Shorts: 720x1280 (9:16)
        # YouTube Normal: 1280x720 (16:9)
        if is_short:
            max_width, max_height = 720, 1280
            print(f"   📱 Formato Short (9:16)")
        else:
            max_width, max_height = 1280, 720
            print(f"   🖥️ Formato Normal (16:9)")
        
        if img.width > max_width or img.height > max_height:
            # Manter aspect ratio
            ratio = min(max_width / img.width, max_height / img.height)
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

def fazer_upload_youtube(video_path, titulo, descricao, tags, thumbnail_path=None, is_short=False):
    """Faz upload com thumbnail opcional
    
    Args:
        video_path: caminho do vídeo
        titulo: título do vídeo
        descricao: descrição
        tags: lista de tags
        thumbnail_path: caminho da thumbnail (opcional)
        is_short: True se for short, False se for vídeo normal
    """
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
        
        print(f"✅ Vídeo enviado! ID: {video_id}")
        
        # Upload thumbnail se fornecida
        if thumbnail_path and os.path.exists(thumbnail_path):
            print("\n" + "-"*60)
            print("📤 PROCESSANDO THUMBNAIL")
            print("-"*60)
            print(f"   Caminho: {thumbnail_path}")
            print(f"   Tipo de vídeo: {'SHORT (9:16)' if is_short else 'NORMAL (16:9)'}")
            
            try:
                # Comprimir se necessário (passa is_short)
                thumbnail_final = comprimir_thumbnail(thumbnail_path, max_size_mb=2, is_short=is_short)
                
                if not os.path.exists(thumbnail_final):
                    raise Exception(f"Arquivo comprimido não existe: {thumbnail_final}")
                
                print(f"   📂 Arquivo final: {thumbnail_final}")
                print(f"   📦 Tamanho final: {os.path.getsize(thumbnail_final) / (1024 * 1024):.2f}MB")
                
                # Verificar se é uma imagem válida
                try:
                    from PIL import Image
                    img = Image.open(thumbnail_final)
                    print(f"   🖼️ Dimensões: {img.size[0]}x{img.size[1]}")
                    print(f"   🎨 Formato: {img.format}")
                    img.close()
                except Exception as e:
                    print(f"   ⚠️ Aviso: não pôde verificar imagem: {e}")
                
                # Fazer upload
                print(f"   ⬆️ Enviando thumbnail para o YouTube...")
                youtube.thumbnails().set(
                    videoId=video_id,
                    media_body=MediaFileUpload(thumbnail_final)
                ).execute()
                print("   ✅ Thumbnail configurada no YouTube!")
                
                # Limpar arquivo comprimido se foi criado
                if thumbnail_final != thumbnail_path and os.path.exists(thumbnail_final):
                    try:
                        os.remove(thumbnail_final)
                        print("   🧹 Arquivo comprimido temporário removido")
                    except:
                        pass
                        
            except Exception as e:
                print(f"   ❌ ERRO ao fazer upload da thumbnail: {e}")
                import traceback
                traceback.print_exc()
                print("   ⚠️ Vídeo publicado MAS thumbnail falhou")
        elif thumbnail_path and not os.path.exists(thumbnail_path):
            print(f"⚠️ Thumbnail especificada mas arquivo não existe: {thumbnail_path}")
        else:
            print("ℹ️ Nenhuma thumbnail customizada - YouTube usará frame automático")
        
        return video_id
        
    except Exception as e:
        print(f"❌ Erro upload: {e}")
        raise

def main():
    print("="*60)
    print(f"{'📱 INICIANDO GERAÇÃO DE SHORT' if VIDEO_TYPE == 'short' else '🎬 INICIANDO GERAÇÃO DE VÍDEO LONGO'}")
    print("="*60)
    
    # Debug de configurações
    print("\n🔧 CONFIGURAÇÕES:")
    print(f"   VIDEO_TYPE: {VIDEO_TYPE}")
    print(f"   USAR_CURACAO: {USAR_CURACAO}")
    print(f"   CURACAO_DISPONIVEL: {CURACAO_DISPONIVEL}")
    print(f"   CURACAO_TIMEOUT: {CURACAO_TIMEOUT}s ({CURACAO_TIMEOUT//60}min)")
    
    if USAR_CURACAO and not CURACAO_DISPONIVEL:
        print("\n⚠️ AVISO: USAR_CURACAO=True mas telegram_curator_noticias.py não encontrado!")
    
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
        # Para vídeos longos: múltiplas notícias
        duracao_minutos = config.get('duracao_minutos', 10)
        
        # Calcular quantas notícias buscar (aproximadamente 2min por notícia)
        # Mas buscar mais para ter opções e filtrar duplicatas
        quantidade_desejada = max(5, min(7, duracao_minutos // 2))
        
        print(f"\n🔍 Buscando até {quantidade_desejada} notícias únicas...")
        noticias = buscar_noticias(quantidade=quantidade_desejada)
        
        if noticias and len(noticias) > 1:
            # Ajustar título baseado no número real de notícias
            data_str = datetime.now().strftime('%d/%m/%Y')
            titulo_video = f"Resumo de {len(noticias)} Notícias - {data_str}"
            keywords = ['política', 'brasil', 'notícias', 'atualidades']
            print(f"📰 {len(noticias)} notícias únicas encontradas para vídeo longo")
            
            # Ajustar duração esperada baseado no número real de notícias
            # ~2min por notícia
            duracao_estimada = len(noticias) * 2
            print(f"⏱️ Duração estimada: ~{duracao_estimada} minutos")
            
        elif noticias and len(noticias) == 1:
            titulo_video = noticias[0]['titulo']
            keywords = titulo_video.split()[:5]
            print(f"📰 Notícia única: {titulo_video}")
        else:
            # Fallback se não encontrar notícias
            tema = random.choice(config.get('temas', ['política brasileira']))
            print(f"📝 Sem notícias disponíveis, usando tema: {tema}")
            info = gerar_titulo_especifico(tema)
            titulo_video = info['titulo']
            keywords = info['keywords']
            noticias = None
    
    print(f"🎯 Título: {titulo_video}")
    
    # ==========================================
    # FLUXO DIFERENCIADO: SHORT vs LONG
    # ==========================================
    
    if VIDEO_TYPE == 'short':
        # ===== FLUXO PARA SHORTS =====
        print("\n" + "="*60)
        print("📱 FLUXO DE SHORTS (SEM CURADORIA DE TEMAS)")
        print("="*60)
        
        # Gerar roteiro
        print("\n✍️ Gerando roteiro...")
        roteiro = gerar_roteiro(VIDEO_TYPE, titulo_video, noticias)
        print(f"📝 Roteiro gerado: {len(roteiro.split())} palavras")
        
        # Criar áudio
        audio_path = f'{ASSETS_DIR}/audio.mp3'
        criar_audio(roteiro, audio_path)
        
        audio_clip = AudioFileClip(audio_path)
        duracao = audio_clip.duration
        audio_clip.close()
        print(f"⏱️ Duração do áudio: {duracao:.1f}s")
        
    else:
        # ===== FLUXO PARA VÍDEOS LONGOS =====
        print("\n" + "="*60)
        print("🎬 FLUXO DE VÍDEOS LONGOS (COM CURADORIA DE TEMAS)")
        print("="*60)
        
        if not noticias or len(noticias) < 1:
            print("❌ Erro: Nenhuma notícia disponível para vídeo longo")
            return
        
        # CURADORIA DE TEMAS via Telegram
        if USAR_CURACAO and CURACAO_DISPONIVEL:
            print("\n🎯 INICIANDO CURADORIA DE TEMAS...")
            
            try:
                curator = TelegramCuratorNoticias()
                
                # Solicitar aprovação dos temas (notícias)
                noticias_aprovadas = curator.solicitar_curacao_temas(
                    noticias, 
                    timeout=CURACAO_TIMEOUT
                )
                
                if noticias_aprovadas and len(noticias_aprovadas) > 0:
                    print(f"✅ {len(noticias_aprovadas)} temas aprovados")
                    noticias = noticias_aprovadas
                else:
                    print("⏰ Timeout ou cancelamento na curadoria de temas")
                    print("⚠️ Usando temas originais")
                    
            except Exception as e:
                print(f"❌ Erro na curadoria de temas: {e}")
                import traceback
                traceback.print_exc()
                print("⚠️ Continuando com temas originais")
        else:
            print("⚠️ Curadoria desativada - usando temas sem aprovação")
        
        # Gerar roteiros segmentados
        print("\n✍️ Gerando roteiros segmentados...")
        resultado_roteiros = gerar_roteiro_segmentado(noticias, duracao_por_noticia=120)
        
        roteiro = resultado_roteiros['roteiro_completo']
        segmentos_roteiro = resultado_roteiros['segmentos']
        duracao_estimada = resultado_roteiros['duracao_total_estimada']
        
        print(f"\n📝 Roteiro completo:")
        print(f"   {len(roteiro.split())} palavras")
        print(f"   {len(segmentos_roteiro)} segmentos")
        print(f"   ~{duracao_estimada:.1f}s (~{duracao_estimada/60:.1f}min) estimados")
        
        # Criar áudio do roteiro completo
        audio_path = f'{ASSETS_DIR}/audio.mp3'
        criar_audio(roteiro, audio_path)
        
        audio_clip = AudioFileClip(audio_path)
        duracao = audio_clip.duration
        audio_clip.close()
        
        print(f"⏱️ Duração real do áudio: {duracao:.1f}s ({duracao/60:.1f}min)")
    
    # ==========================================
    # CONTINUA IGUAL PARA AMBOS
    # ==========================================
    
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
        is_short = (VIDEO_TYPE == 'short')
        
        video_id = fazer_upload_youtube(
            video_path,
            titulo,
            descricao,
            tags,
            thumbnail_path,
            is_short=is_short  # Passa o tipo de vídeo
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
