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
from googleapiclient.http import MediaFileUpload
from PIL import Image, ImageDraw, ImageFont

CONFIG_FILE = 'config.json'
VIDEOS_DIR = 'videos'
ASSETS_DIR = 'assets'
VIDEO_TYPE = os.environ.get('VIDEO_TYPE', 'short')

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
PEXELS_API_KEY = os.environ.get('PEXELS_API_KEY')
YOUTUBE_CREDENTIALS = os.environ.get('YOUTUBE_CREDENTIALS')

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.5-flash')

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
    """Gera título específico e keywords para temas genéricos"""
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
    
    persona = config.get('persona', None)
    
    if persona == 'alien_solkara':
        prompt = f"""Você é Vorlathi, do planeta Solkara (Kepler-1649c).

Script sobre: {titulo}

- Primeira pessoa como alien
- Tom: misterioso, fascinante
- Comece: "Humanos... eu sou Vorlathi, do planeta Solkara..."
- Mencione que terráqueos chamam de "Kepler-1649c"
- Use: "vocês terráqueos", "minha civilização de Solkara"
- Enigmático sobre intenções
- Finalize: "Logo vocês compreenderão..."
- {tempo}, {palavras_alvo} palavras, texto puro"""
    
    elif noticia:
        prompt = f"""Crie um script JORNALÍSTICO sobre: {titulo}

Resumo da notícia: {noticia['resumo']}

REGRAS IMPORTANTES:
- {tempo} de duração, aproximadamente {palavras_alvo} palavras
- Tom: noticioso, imparcial, informativo
- Comece direto na notícia (ex: "Nesta {('semana' if duracao_alvo != 'short' else 'terça-feira')},...")
- NÃO mencione "apresentador", "reportagem", "matéria", "slides"
- NÃO use frases como "vamos ver", "como podem ver na tela"
- Fale diretamente sobre os fatos
- Para SHORTS: seja direto e objetivo
- Para LONGS: desenvolva contexto e repercussões
- Texto corrido para narração
- SEM formatação, asteriscos ou marcadores
- SEM emojis

Escreva APENAS o roteiro de narração."""
    
    else:
        if duracao_alvo == 'short':
            prompt = f"""Crie um script para SHORT sobre: {titulo}

REGRAS IMPORTANTES:
- {palavras_alvo} palavras aproximadamente
- Comece com "Você sabia que..." ou "Sabia que..." ou contexto direto
- Tom informativo e envolvente
- NÃO mencione apresentador, slides, ou elementos visuais
- NÃO use frases como "vamos ver", "próximo slide", "na tela"
- Fale diretamente com o espectador
- Texto corrido para narração
- SEM formatação, asteriscos ou marcadores
- SEM emojis

Escreva APENAS o roteiro de narração."""
        else:
            prompt = f"""Crie um script sobre: {titulo}

REGRAS IMPORTANTES:
- {tempo} de duração, aproximadamente {palavras_alvo} palavras
- Comece com "Olá!" ou introdução contextual
- Tom informativo e conversacional
- NÃO mencione apresentador, slides, gráficos ou elementos visuais
- NÃO use frases como "vamos ver agora", "na próxima parte", "como vocês podem ver"
- Fale naturalmente como se estivesse explicando a notícia
- Divida o conteúdo em pequenos parágrafos naturais
- Texto corrido para narração
- SEM formatação, asteriscos ou marcadores
- SEM emojis
- Finalize com chamada para inscrição no canal

Escreva APENAS o roteiro de narração."""
    
    response = model.generate_content(prompt)
    texto = response.text
    
    # Limpeza do texto
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
            print(f"✅ Edge TTS (tent {tentativa + 1})")
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
    """Cria áudio com Edge TTS ou gTTS (fallback)"""
    print("🎙️ Criando narração...")
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(criar_audio_async(texto, output_file))
        loop.close()
        
        if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
            print(f"✅ Edge TTS: {os.path.getsize(output_file)} bytes")
            return output_file
    except Exception as e:
        print(f"❌ Edge TTS: {e}")
        print("🔄 Fallback gTTS...")
        from gtts import gTTS
        tts = gTTS(text=texto, lang='pt-br', slow=False)
        tts.save(output_file)
        print("⚠️ gTTS")
        return output_file

def extrair_keywords_do_texto(texto):
    """Extrai keywords importantes de um texto para buscar mídias"""
    prompt = f"""Extraia 3-5 palavras-chave IMPORTANTES deste texto de notícia política brasileira:

"{texto[:200]}"

Se houver nomes de políticos ou instituições, retorne EM PORTUGUÊS.
Caso contrário, retorne palavras em INGLÊS para buscar imagens genéricas.

Retorne APENAS palavras separadas por vírgula.
Exemplos: 
- "lula, congresso, brasil"
- "moraes, stf, supremo"
- "politics, government, congress"
"""
    
    try:
        response = model.generate_content(prompt)
        keywords = [k.strip().lower() for k in response.text.strip().split(',')]
        return keywords[:5]
    except:
        palavras = texto.lower().split()
        return [p for p in palavras if len(p) > 4][:3]

def buscar_imagens_local(keywords, quantidade=1):
    """PRIORIDADE 1: Busca imagens no banco local"""
    
    # Mapeamento expandido de keywords
    mapa_politicos = {
        'lula': 'politicos/lula',
        'luiz inacio': 'politicos/lula',
        'presidente lula': 'politicos/lula',
        'bolsonaro': 'politicos/bolsonaro',
        'jair bolsonaro': 'politicos/bolsonaro',
        'moraes': 'politicos/alexandre_de_moraes',
        'alexandre': 'politicos/alexandre_de_moraes',
        'alexandre de moraes': 'politicos/alexandre_de_moraes',
        'pacheco': 'politicos/rodrigo_pacheco',
        'rodrigo pacheco': 'politicos/rodrigo_pacheco',
        'lira': 'politicos/arthur_lira',
        'arthur lira': 'politicos/arthur_lira',
        'ramagem': 'politicos/alexandre_ramagem',
        'alexandre ramagem': 'politicos/alexandre_ramagem',
        'tarcisio': 'politicos/tarcisio_de_freitas',
        'tarcísio': 'politicos/tarcisio_de_freitas',
        'haddad': 'politicos/fernando_haddad',
        'fernando haddad': 'politicos/fernando_haddad',
        'dilma': 'politicos/dilma_roussef',
        'temer': 'politicos/_michel_temer',
        'ciro': 'politicos/ciro_gomes',
        'dino': 'politicos/flavio_dino',
        'flavio dino': 'politicos/flavio_dino',
        'carmen lucia': 'politicos/carmen_lucia',
        'davi alcolumbre': 'politicos/davi_alcolumbre',
        'dias toffoli': 'politicos/dias_toffoli',
        'donald trump': 'politicos/donald_trump',
        'geraldo alckmin': ''politicos/geraldo_alckmin',
        'alckmin': 'politicos/geraldo_alckmin',
        'gilmar mendes': 'politicos/gilmar_mendes',
        'hugo mota': 'politicos/hugo_mota',
        'javier milei': 'politicos/javier_milei',
        'milei': 'politicos/javier_milei',
        'joe biden': 'politicos/joe_biden',
        'biden': 'politicos/joe_biden',
        'ministro barroso'; 'politicos/luis_roberto_barroso
        'barroso'; 'politicos/luis_roberto_barroso',
        'luiz roberto barroso'; 'politicos/luis_roberto_barroso',
        'macron': 'politicos/macron',
        'nayib bukele': 'politicos/nayib_bukele',
        'bukele': 'politicos/nayib_bukele',
        'netanyahu': 'politicos/netanyahu',
        'nicolas maduro': 'politicos/nicolas_maduro',
        'putin': 'politicos/putin',
        'xi jinping': 'politicos/xi_jinping',
        'zanin': 'politicos/zanin',
        
    }
    
    mapa_instituicoes = {
        'congresso': 'instituicoes/congresso_nacional',
        'congresso nacional': 'instituicoes/congresso_nacional',
        'planalto': 'instituicoes/palacio_do_planalto',
        'palacio': 'instituicoes/palacio_do_planalto',
        'palácio': 'instituicoes/palacio_do_planalto',
        'stf': 'instituicoes/stf',
        'supremo': 'instituicoes/stf',
        'supremo tribunal': 'instituicoes/stf',
        'senado': 'instituicoes/senado_federal',
        'senado federal': 'instituicoes/senado_federal',
        'camara': 'instituicoes/camara_dos_deputados',
        'câmara': 'instituicoes/camara_dos_deputados',
        'camara dos deputados': 'instituicoes/camara_dos_deputados',
        'brasilia': 'instituicoes/brasilia',
        'brasília': 'instituicoes/brasilia',
        'governo': 'instituicoes/governo',
        'governo federal': 'instituicoes/governo',
        'brasil': 'genericas',
        'brazilian': 'genericas',
        'policia federal': 'instituicoes/policia_federal',
        'banco central': 'instituicoes/banco_central',
        'casa branca': 'instituicoes/casa-branca',
        'cia': 'instituicoes/cia',
        'esplanada': 'instituicoes/esplanada_dos_ministerios',
        'fbi': 'instituicoes/fbi',
        'mi6': 'instituicoes/mi6',
        'mossad': 'instituicoes/mossad',
        'nsa': 'instituicoes/nsa',
        'onu': 'instituicoes/onu',
        'otan': 'instituicoes/otan,
        
    }
    
    midias = []
    
    if isinstance(keywords, str):
        keywords = [keywords]
    
    keywords_lower = [k.lower() for k in keywords]
    keywords_texto = ' '.join(keywords_lower)
    
    pasta_encontrada = None
    
    # Checar políticos primeiro
    for termo, pasta in mapa_politicos.items():
        if termo in keywords_texto:
            pasta_encontrada = pasta
            print(f"   📁 Detectado: '{termo}' → {pasta}")
            break
    
    # Checar instituições
    if not pasta_encontrada:
        for termo, pasta in mapa_instituicoes.items():
            if termo in keywords_texto:
                pasta_encontrada = pasta
                print(f"   📁 Detectado: '{termo}' → {pasta}")
                break
    
    # Fallback para genéricas
    if not pasta_encontrada:
        pasta_encontrada = 'genericas'
        print(f"   📁 Usando pasta genérica")
    
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
                    print(f"   ✅ Banco LOCAL: {len(midias)} imagem(ns)")
                    return midias
            else:
                print(f"   ⚠️ Pasta existe mas está vazia: {pasta_completa}")
        else:
            print(f"   ⚠️ Pasta não existe: {pasta_completa}")
    except Exception as e:
        print(f"   ⚠️ Erro banco local: {e}")
    
    return midias

def buscar_imagens_google(termos, quantidade=10):
    """PRIORIDADE 2: Busca imagens no Google Images"""
    from urllib.parse import quote
    
    if isinstance(termos, list):
        termo = ' '.join(termos[:3])
    else:
        termo = str(termos)
    
    # Adicionar "brasil" para filtrar melhor
    termo_encoded = quote(termo + ' brasil')
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8',
        'Referer': 'https://www.google.com/',
        'DNT': '1'
    }
    
    midias = []
    
    try:
        url = f'https://www.google.com/search?q={termo_encoded}&tbm=isch&tbs=sur:fmc'
        print(f"   🔍 GOOGLE: Buscando '{termo}'")
        
        response = requests.get(url, headers=headers, timeout=20)
        
        if response.status_code != 200:
            print(f"   ⚠️ Google retornou status {response.status_code}")
            return midias
        
        # Múltiplos padrões de extração
        urls = re.findall(r'"ou":"(https?://[^"]+)"', response.text)
        
        if not urls:
            urls = re.findall(r'src="(https?://[^"]+\.(?:jpg|jpeg|png))"', response.text)
        
        if not urls:
            urls = re.findall(r'"(https?://[^"]*\.(?:jpg|jpeg|png)[^"]*)"', response.text)
        
        print(f"   📸 {len(urls)} URLs encontradas")
        
        for idx, url_img in enumerate(urls[:quantidade * 3]):
            if len(midias) >= quantidade:
                break
            
            # Filtros
            skip_terms = ['.gif', '.svg', 'icon', 'logo', 'gstatic', 'ggpht', 'encrypted-tbn']
            if any(x in url_img.lower() for x in skip_terms):
                continue
            
            try:
                img_response = requests.get(
                    url_img, 
                    timeout=8, 
                    headers=headers,
                    stream=True,
                    allow_redirects=True
                )
                
                if img_response.status_code == 200:
                    content_type = img_response.headers.get('content-type', '')
                    if 'image' not in content_type.lower():
                        continue
                    
                    temp_file = f'{ASSETS_DIR}/google_{len(midias)}_{idx}.jpg'
                    
                    with open(temp_file, 'wb') as f:
                        for chunk in img_response.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                    
                    if os.path.getsize(temp_file) > 15000:
                        try:
                            img = Image.open(temp_file)
                            width, height = img.size
                            img.close()
                            
                            if width >= 400 and height >= 300:
                                midias.append((temp_file, 'foto_local'))
                                print(f"   ✅ GOOGLE: {len(midias)}/{quantidade} ({width}x{height})")
                            else:
                                os.remove(temp_file)
                        except:
                            os.remove(temp_file)
                    else:
                        os.remove(temp_file)
                        
            except:
                continue
            
            time.sleep(0.3)
        
    except Exception as e:
        print(f"   ❌ Erro GOOGLE: {e}")
    
    return midias

def buscar_imagens_wikimedia(termos, quantidade=10):
    """PRIORIDADE 3: Busca na Wikimedia Commons"""
    
    if isinstance(termos, list):
        termo = ' '.join(termos[:3])
    else:
        termo = str(termos)
    
    midias = []
    
    try:
        print(f"   📚 WIKIMEDIA: Buscando '{termo}'")
        
        url = 'https://commons.wikimedia.org/w/api.php'
        params = {
            'action': 'query',
            'format': 'json',
            'list': 'search',
            'srsearch': termo + ' brazil OR brasil',
            'srnamespace': 6,
            'srlimit': quantidade * 2
        }
        
        response = requests.get(url, params=params, timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            results = data.get('query', {}).get('search', [])
            
            print(f"   📚 {len(results)} resultados")
            
            for result in results[:quantidade * 2]:
                if len(midias) >= quantidade:
                    break
                
                title = result['title']
                
                params_img = {
                    'action': 'query',
                    'format': 'json',
                    'titles': title,
                    'prop': 'imageinfo',
                    'iiprop': 'url',
                    'iiurlwidth': 1920
                }
                
                try:
                    response_img = requests.get(url, params=params_img, timeout=10)
                    
                    if response_img.status_code == 200:
                        data_img = response_img.json()
                        pages = data_img.get('query', {}).get('pages', {})
                        
                        for page in pages.values():
                            imageinfo = page.get('imageinfo', [])
                            if imageinfo:
                                url_img = imageinfo[0].get('thumburl') or imageinfo[0].get('url')
                                
                                if url_img:
                                    try:
                                        img_response = requests.get(url_img, timeout=10, stream=True)
                                        
                                        if img_response.status_code == 200:
                                            temp_file = f'{ASSETS_DIR}/wiki_{len(midias)}.jpg'
                                            
                                            with open(temp_file, 'wb') as f:
                                                for chunk in img_response.iter_content(chunk_size=8192):
                                                    if chunk:
                                                        f.write(chunk)
                                            
                                            if os.path.getsize(temp_file) > 10000:
                                                midias.append((temp_file, 'foto_local'))
                                                print(f"   ✅ WIKIMEDIA: {len(midias)}/{quantidade}")
                                            else:
                                                os.remove(temp_file)
                                    except:
                                        continue
                except:
                    continue
                
                time.sleep(0.2)
                
    except Exception as e:
        print(f"   ❌ Erro WIKIMEDIA: {e}")
    
    return midias

def buscar_midia_pexels(keywords, tipo='foto', quantidade=1):
    """PRIORIDADE 4: Pexels (último recurso)"""
    
    if not PEXELS_API_KEY:
        print("   ⚠️ PEXELS_API_KEY não configurada")
        return []
    
    headers = {'Authorization': PEXELS_API_KEY}
    
    if isinstance(keywords, str):
        keywords = [keywords]
    
    palavra_busca = ' '.join(keywords[:3])
    pagina = random.randint(1, 3)
    midias = []
    
    try:
        print(f"   📸 PEXELS: Buscando '{palavra_busca}'")
        
        if tipo == 'video':
            orientacao = 'portrait' if VIDEO_TYPE == 'short' else 'landscape'
            url = f'https://api.pexels.com/videos/search?query={palavra_busca}&per_page=30&page={pagina}&orientation={orientacao}'
            
            response = requests.get(url, headers=headers, timeout=15)
            if response.status_code == 200:
                videos = response.json().get('videos', [])
                random.shuffle(videos)
                
                for video in videos:
                    for file in video['video_files']:
                        if VIDEO_TYPE == 'short':
                            if file.get('height', 0) > file.get('width', 0):
                                midias.append((file['link'], 'video'))
                                break
                        else:
                            if file.get('width', 0) >= 1280:
                                midias.append((file['link'], 'video'))
                                break
                    
                    if len(midias) >= quantidade:
                        break
        
        if len(midias) < quantidade:
            orientacao = 'portrait' if VIDEO_TYPE == 'short' else 'landscape'
            url = f'https://api.pexels.com/v1/search?query={palavra_busca}&per_page=50&page={pagina}&orientation={orientacao}'
            
            response = requests.get(url, headers=headers, timeout=15)
            if response.status_code == 200:
                fotos = response.json().get('photos', [])
                random.shuffle(fotos)
                
                for foto in fotos[:quantidade * 2]:
                    midias.append((foto['src']['large2x'], 'foto'))
                    if len(midias) >= quantidade:
                        break
    
    except Exception as e:
        print(f"   ❌ Erro PEXELS: {e}")
    
    if midias:
        print(f"   ✅ PEXELS: {len(midias)} mídias")
    
    random.shuffle(midias)
    return midias[:quantidade]

def buscar_midias_final(keywords, quantidade=1):
    """🎯 BUSCA HÍBRIDA: Local → Google → Wikimedia → Pexels"""
    
    midias = []
    
    print(f"🔍 Buscando mídias: {keywords}")
    
    # 1. Banco local
    try:
        midias = buscar_imagens_local(keywords, quantidade)
        if len(midias) >= quantidade:
            return midias
    except Exception as e:
        print(f"   ⚠️ Erro local: {e}")
    
    # 2. Google
    if len(midias) < quantidade:
        try:
            print(f"   ⚠️ Local: {len(midias)}/{quantidade}, tentando Google...")
            midias_google = buscar_imagens_google(keywords, quantidade - len(midias))
            midias.extend(midias_google)
            
            if len(midias) >= quantidade:
                return midias
        except Exception as e:
            print(f"   ⚠️ Erro Google: {e}")
    
    # 3. Wikimedia
    if len(midias) < quantidade:
        try:
            print(f"   ⚠️ Google: {len(midias)}/{quantidade}, tentando Wikimedia...")
            midias_wiki = buscar_imagens_wikimedia(keywords, quantidade - len(midias))
            midias.extend(midias_wiki)
            
            if len(midias) >= quantidade:
                return midias
        except Exception as e:
            print(f"   ⚠️ Erro Wikimedia: {e}")
    
    # 4. Pexels
    if len(midias) < quantidade:
        try:
            print(f"   ⚠️ Wikimedia: {len(midias)}/{quantidade}, usando Pexels...")
            midias_pexels = buscar_midia_pexels(keywords, tipo='foto', quantidade=quantidade - len(midias))
            midias.extend(midias_pexels)
        except Exception as e:
            print(f"   ⚠️ Erro Pexels: {e}")
    
    if not midias:
        print(f"   ❌ NENHUMA mídia encontrada")
    else:
        print(f"   ✅ TOTAL: {len(midias)}/{quantidade} mídias")
    
    return midias

def analisar_roteiro_e_buscar_midias(roteiro, duracao_audio):
    """Analisa roteiro e busca mídias sincronizadas"""
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
        print(f"\n🔍 Seg {i+1}/{len(segmentos_com_tempo)}: '{seg['texto']}'...")
        print(f"   Keywords: {seg['keywords']}")
        
        midia = buscar_midias_final(seg['keywords'], quantidade=1)
        
        if midia and len(midia) > 0:
            midias_sincronizadas.append({
                'midia': midia[0],
                'inicio': seg['inicio'],
                'duracao': seg['duracao']
            })
            print(f"   ✅ Mídia OK")
        else:
            print(f"   ❌ Sem mídia")
    
    print(f"\n✅ Total: {len(midias_sincronizadas)}/{len(segmentos_com_tempo)} mídias")
    return midias_sincronizadas

def baixar_midia(url, filename):
    """Baixa mídia da URL"""
    try:
        response = requests.get(url, stream=True, timeout=30)
        with open(filename, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return filename
    except:
        return None

def criar_video_short_sincronizado(audio_path, midias_sincronizadas, output_file, duracao_total):
    """Cria SHORT com imagens sincronizadas"""
    print(f"📹 Criando short com {len(midias_sincronizadas)} mídias")
    
    clips = []
    tempo_coberto = 0
    
    for i, item in enumerate(midias_sincronizadas):
        midia_info, midia_tipo = item['midia']
        inicio = item['inicio']
        duracao_clip = item['duracao']
        
        if not midia_info:
            continue
        
        try:
            if midia_tipo == 'foto_local':
                if not os.path.exists(midia_info):
                    print(f"⚠️ Arquivo não encontrado: {midia_info}")
                    continue
                
                clip = ImageClip(midia_info).set_duration(duracao_clip)
                clip = clip.resize(height=1920)
                
                if clip.w > 1080:
                    clip = clip.crop(x_center=clip.w/2, width=1080, height=1920)
                
                clip = clip.resize(lambda t: 1 + 0.1 * (t / duracao_clip))
                clip = clip.set_start(inicio)
                clips.append(clip)
                tempo_coberto = max(tempo_coberto, inicio + duracao_clip)
                print(f"✅ Imagem {i+1} adicionada")
            
            elif midia_tipo == 'video':
                video_temp = f'{ASSETS_DIR}/v_{i}.mp4'
                if baixar_midia(midia_info, video_temp):
                    vclip = VideoFileClip(video_temp, audio=False)
                    
                    ratio = 9/16
                    if vclip.w / vclip.h > ratio:
                        new_w = int(vclip.h * ratio)
                        vclip = vclip.crop(x_center=vclip.w/2, width=new_w, height=vclip.h)
                    else:
                        new_h = int(vclip.w / ratio)
                        vclip = vclip.crop(y_center=vclip.h/2, width=vclip.w, height=new_h)
                    
                    vclip = vclip.resize((1080, 1920))
                    vclip = vclip.set_duration(min(duracao_clip, vclip.duration))
                    vclip = vclip.set_start(inicio)
                    clips.append(vclip)
                    tempo_coberto = max(tempo_coberto, inicio + duracao_clip)
            
            elif midia_tipo == 'foto':
                foto_temp = f'{ASSETS_DIR}/pexels_{i}.jpg'
                if baixar_midia(midia_info, foto_temp):
                    clip = ImageClip(foto_temp).set_duration(duracao_clip)
                    clip = clip.resize(height=1920)
                    if clip.w > 1080:
                        clip = clip.crop(x_center=clip.w/2, width=1080, height=1920)
                    clip = clip.resize(lambda t: 1 + 0.1 * (t / duracao_clip))
                    clip = clip.set_start(inicio)
                    clips.append(clip)
                    tempo_coberto = max(tempo_coberto, inicio + duracao_clip)
        
        except Exception as e:
            print(f"⚠️ Erro mídia {i}: {e}")
    
    # Preencher lacunas
    if tempo_coberto < duracao_total:
        print(f"⚠️ Preenchendo {duracao_total - tempo_coberto:.1f}s restantes")
        
        extras = buscar_midias_final(['brasil', 'politica', 'governo'], quantidade=3)
        
        duracao_restante = duracao_total - tempo_coberto
        duracao_por_extra = duracao_restante / len(extras) if extras else duracao_restante
        
        for idx, (midia_info, midia_tipo) in enumerate(extras):
            try:
                if midia_tipo == 'foto_local' and os.path.exists(midia_info):
                    clip = ImageClip(midia_info).set_duration(duracao_por_extra)
                    clip = clip.resize(height=1920)
                    if clip.w > 1080:
                        clip = clip.crop(x_center=clip.w/2, width=1080, height=1920)
                    clip = clip.resize(lambda t: 1 + 0.1 * (t / duracao_por_extra))
                    clip = clip.set_start(tempo_coberto)
                    clips.append(clip)
                    tempo_coberto += duracao_por_extra
                elif midia_tipo == 'foto':
                    foto_temp = f'{ASSETS_DIR}/extra_{idx}.jpg'
                    if baixar_midia(midia_info, foto_temp):
                        clip = ImageClip(foto_temp).set_duration(duracao_por_extra)
                        clip = clip.resize(height=1920)
                        if clip.w > 1080:
                            clip = clip.crop(x_center=clip.w/2, width=1080, height=1920)
                        clip = clip.resize(lambda t: 1 + 0.1 * (t / duracao_por_extra))
                        clip = clip.set_start(tempo_coberto)
                        clips.append(clip)
                        tempo_coberto += duracao_por_extra
            except:
                continue
    
    if not clips:
        print("❌ Nenhum clip criado!")
        return None
    
    print(f"✅ {len(clips)} clips, {tempo_coberto:.1f}s/{duracao_total:.1f}s")
    
    video = CompositeVideoClip(clips, size=(1080, 1920))
    video = video.set_duration(duracao_total)
    
    audio = AudioFileClip(audio_path)
    video = video.set_audio(audio)
    
    video.write_videofile(output_file, fps=30, codec='libx264', audio_codec='aac', preset='medium', bitrate='8000k')
    
    return output_file

def criar_video_long_sincronizado(audio_path, midias_sincronizadas, output_file, duracao_total):
    """Cria vídeo LONGO com imagens sincronizadas"""
    print(f"📹 Criando long com {len(midias_sincronizadas)} mídias")
    
    clips = []
    tempo_coberto = 0
    
    for i, item in enumerate(midias_sincronizadas):
        midia_info, midia_tipo = item['midia']
        inicio = item['inicio']
        duracao_clip = item['duracao']
        
        if not midia_info:
            continue
        
        try:
            if midia_tipo == 'foto_local':
                if not os.path.exists(midia_info):
                    continue
                
                clip = ImageClip(midia_info).set_duration(duracao_clip)
                clip = clip.resize(height=1080)
                
                if clip.w < 1920:
                    clip = clip.resize(width=1920)
                
                clip = clip.crop(x_center=clip.w/2, y_center=clip.h/2, width=1920, height=1080)
                clip = clip.resize(lambda t: 1 + 0.05 * (t / duracao_clip))
                clip = clip.set_start(inicio)
                clips.append(clip)
                tempo_coberto = max(tempo_coberto, inicio + duracao_clip)
            
            elif midia_tipo == 'video':
                video_temp = f'{ASSETS_DIR}/v_{i}.mp4'
                if baixar_midia(midia_info, video_temp):
                    vclip = VideoFileClip(video_temp, audio=False)
                    vclip = vclip.resize(height=1080)
                    
                    if vclip.w < 1920:
                        vclip = vclip.resize(width=1920)
                    
                    vclip = vclip.crop(x_center=vclip.w/2, y_center=vclip.h/2, width=1920, height=1080)
                    vclip = vclip.set_duration(min(duracao_clip, vclip.duration))
                    vclip = vclip.set_start(inicio)
                    clips.append(vclip)
                    tempo_coberto = max(tempo_coberto, inicio + duracao_clip)
            
            elif midia_tipo == 'foto':
                foto_temp = f'{ASSETS_DIR}/pexels_{i}.jpg'
                if baixar_midia(midia_info, foto_temp):
                    clip = ImageClip(foto_temp).set_duration(duracao_clip)
                    clip = clip.resize(height=1080)
                    if clip.w < 1920:
                        clip = clip.resize(width=1920)
                    clip = clip.crop(x_center=clip.w/2, y_center=clip.h/2, width=1920, height=1080)
                    clip = clip.resize(lambda t: 1 + 0.05 * (t / duracao_clip))
                    clip = clip.set_start(inicio)
                    clips.append(clip)
                    tempo_coberto = max(tempo_coberto, inicio + duracao_clip)
        
        except Exception as e:
            print(f"⚠️ Erro mídia {i}: {e}")
    
    # Preencher lacunas
    if tempo_coberto < duracao_total:
        print(f"⚠️ Preenchendo {duracao_total - tempo_coberto:.1f}s")
        
        extras = buscar_midias_final(['brasil', 'governo', 'politica'], quantidade=5)
        
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
                    clip = clip.resize(lambda t: 1 + 0.05 * (t / duracao_por_extra))
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
    
    video.write_videofile(output_file, fps=24, codec='libx264', audio_codec='aac', preset='medium', bitrate='5000k')
    
    return output_file

def fazer_upload_youtube(video_path, titulo, descricao, tags):
    """Faz upload do vídeo para o YouTube"""
    try:
        creds_dict = json.loads(YOUTUBE_CREDENTIALS)
        credentials = Credentials.from_authorized_user_info(creds_dict)
        youtube = build('youtube', 'v3', credentials=credentials)
        
        body = {
            'snippet': {'title': titulo, 'description': descricao, 'tags': tags, 'categoryId': '27'},
            'status': {'privacyStatus': 'public', 'selfDeclaredMadeForKids': False}
        }
        
        media = MediaFileUpload(video_path, resumable=True)
        request = youtube.videos().insert(part='snippet,status', body=body, media_body=media)
        response = request.execute()
        
        return response['id']
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
    print(f"🔍 Keywords: {', '.join(map(str, keywords))}")

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

    # Buscar mídias sincronizadas
    midias_sincronizadas = analisar_roteiro_e_buscar_midias(roteiro, duracao)

    # Complementar se necessário
    if len(midias_sincronizadas) < 3:
        print("⚠️ Poucas mídias, complementando...")
        
        extras = buscar_midias_final(['brasil', 'politica', 'governo'], quantidade=5)
        
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
        resultado = criar_video_short_sincronizado(audio_path, midias_sincronizadas, video_path, duracao)
    else:
        resultado = criar_video_long_sincronizado(audio_path, midias_sincronizadas, video_path, duracao)

    if not resultado:
        print("❌ Erro ao criar vídeo")
        return

    # Preparar metadados
    titulo = titulo_video[:60] if len(titulo_video) <= 60 else titulo_video[:57] + '...'

    if VIDEO_TYPE == 'short':
        titulo += ' #shorts'

    descricao = roteiro[:300] + '...\n\n🔔 Inscreva-se!\n📰 Notícias Políticas do Brasil\n#' + ('shorts' if VIDEO_TYPE == 'short' else 'noticias')

    tags = ['noticias', 'informacao', 'politica', 'brasil']
    if VIDEO_TYPE == 'short':
        tags.append('shorts')

    # Upload
    print("📤 Upload...")
    try:
        video_id = fazer_upload_youtube(video_path, titulo, descricao, tags)
        
        url = f'https://youtube.com/{"shorts" if VIDEO_TYPE == "short" else "watch?v="}{video_id}'
        
        # Log
        log_entry = {
            'data': datetime.now().isoformat(),
            'tipo': VIDEO_TYPE,
            'tema': titulo_video,
            'titulo': titulo,
            'duracao': duracao,
            'video_id': video_id,
            'url': url
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
        
        # Limpar assets
        for file in os.listdir(ASSETS_DIR):
            try:
                os.remove(os.path.join(ASSETS_DIR, file))
            except:
                pass
    except Exception as e:
        print(f"❌ Erro: {e}")

if __name__ == '__main__':
    main()
