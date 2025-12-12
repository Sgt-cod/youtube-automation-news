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

# ========== CONFIGURAÇÕES ==========
CONFIG_FILE = 'config.json'
VIDEOS_DIR = 'videos'
ASSETS_DIR = 'assets'
VIDEO_TYPE = os.environ.get('VIDEO_TYPE', 'short')

# APIs
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
PEXELS_API_KEY = os.environ.get('PEXELS_API_KEY')
YOUTUBE_CREDENTIALS = os.environ.get('YOUTUBE_CREDENTIALS')

# Configurar Gemini
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.5-flash')

# Carregar configurações
with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
    config = json.load(f)

# ========== FUNÇÕES DE CONTEÚDO ==========

def buscar_noticias():
    """Busca notícias via RSS"""
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

def gerar_roteiro(duracao_alvo, noticia=None):
    """Gera roteiro usando Gemini"""
    
    if duracao_alvo == 'short':
        palavras_alvo = 120
        tempo = '30-60 segundos'
    else:
        palavras_alvo = config.get('duracao_minutos', 10) * 150
        tempo = f"{config.get('duracao_minutos', 10)} minutos"
    
    if noticia:
        prompt = f"""
        Crie um script para vídeo sobre esta notícia:
        
        Título: {noticia['titulo']}
        Resumo: {noticia['resumo']}
        
        Requisitos:
        - Duração: {tempo} (aproximadamente {palavras_alvo} palavras)
        - Tom: noticioso, objetivo e informativo
        - Comece com: "Atenção! Notícia importante..."
        - Finalize com: "Fonte completa na descrição"
        - Apenas texto puro para narração
        - SEM asteriscos, hífens, hashtags ou formatação
        - Use apenas pontos finais e vírgulas
        
        Retorne APENAS o texto para narração.
        """
    else:
        tema = random.choice(config['temas'])
        
        if duracao_alvo == 'short':
            prompt = f"""
            Crie um script de SHORT sobre: {tema}
            
            Requisitos:
            - Exatamente {palavras_alvo} palavras
            - Comece com gancho: "Você sabia que..."
            - 1 curiosidade completa e fascinante
            - Tom empolgante
            - Finalize com: "Incrível, né?"
            - Apenas texto puro, SEM símbolos, asteriscos, hífens
            - Use apenas pontos e vírgulas
            
            Retorne APENAS o texto para narração.
            """
        else:
            prompt = f"""
            Crie um script completo sobre: {tema}
            
            Requisitos:
            - Duração: {tempo} (aproximadamente {palavras_alvo} palavras)
            - Comece direto: "Olá! Hoje vamos explorar..."
            - 10-15 curiosidades fascinantes
            - Tom envolvente e natural
            - Transições suaves entre tópicos
            - Finalize com: "Qual curiosidade mais te surpreendeu?"
            - Apenas texto puro, SEM formatação, asteriscos, hífens
            - Use apenas pontos e vírgulas
            
            Retorne APENAS o texto para narração.
            """
    
    response = model.generate_content(prompt)
    texto = response.text
    
    # Limpar formatação
    texto = re.sub(r'\*+', '', texto)
    texto = re.sub(r'#+\s', '', texto)
    texto = re.sub(r'^-\s', '', texto, flags=re.MULTILINE)
    texto = texto.replace('*', '').replace('#', '').replace('_', '')
    texto = texto.strip()
    
    return texto, tema if not noticia else noticia['titulo']

# ========== VOZ COM EDGE TTS ==========

def criar_audio(texto, output_file):
    """Wrapper síncrono com fallback e debug"""
    print("=" * 50)
    print("🎙️ TENTANDO EDGE TTS...")
    print("=" * 50)
    
    try:
        # Testar se asyncio funciona
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        print("✓ Loop de eventos criado")
        
        loop.run_until_complete(criar_audio_async(texto, output_file))
        loop.close()
        
        # Verificar se arquivo foi criado
        if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
            print("✅ SUCESSO! Áudio criado com Edge TTS")
            print(f"   Tamanho: {os.path.getsize(output_file)} bytes")
            return output_file
        else:
            raise Exception("Arquivo não criado ou vazio")
            
    except Exception as e:
        print("=" * 50)
        print(f"❌ EDGE TTS FALHOU!")
        print(f"   Erro: {type(e).__name__}: {e}")
        print("=" * 50)
        print("🔄 Usando gTTS como backup...")
        
        from gtts import gTTS
        tts = gTTS(text=texto, lang='pt-br', slow=False)
        tts.save(output_file)
        
        print("⚠️ Áudio criado com gTTS (voz robótica)")
        return output_file

def criar_audio(texto, output_file):
    """Wrapper síncrono com fallback para gTTS"""
    try:
        asyncio.run(criar_audio_async(texto, output_file))
        print("✅ Áudio criado com Edge TTS")
    except Exception as e:
        print(f"⚠️ Edge TTS falhou: {e}")
        print("🔄 Usando gTTS como backup...")
        
        from gtts import gTTS
        tts = gTTS(text=texto, lang='pt-br', slow=False)
        tts.save(output_file)
        print("✅ Áudio criado com gTTS")
    
    return output_file

# ========== BUSCA DE MÍDIAS ==========

def buscar_midia_pexels(palavras_chave, tipo='video', quantidade=1):
    """Busca vídeos com VARIEDADE e randomização"""
    headers = {'Authorization': PEXELS_API_KEY}
    
    # Expandir traduções
    traducoes = {
        'tecnologia': ['technology innovation', 'modern tech', 'digital future', 'ai robot', 'gadgets'],
        'espaço': ['space galaxy', 'astronomy stars', 'cosmos universe', 'planets nebula', 'astronaut'],
        'oceano': ['ocean waves', 'underwater sea', 'marine life', 'coral reef', 'deep sea'],
        'animais': ['wild animals', 'wildlife nature', 'safari africa', 'jungle forest', 'animal planet'],
        'ciência': ['science lab', 'laboratory research', 'experiment', 'chemistry', 'scientist'],
        'natureza': ['nature landscape', 'mountain forest', 'waterfall', 'beautiful scenery', 'wilderness']
    }
    
    palavra_original = palavras_chave[0] if palavras_chave else 'nature'
    
    # Pegar LISTA de traduções (não só uma)
    termos_busca = traducoes.get(palavra_original.lower(), [palavra_original])
    
    # RANDOMIZAR termo de busca
    palavra_busca = random.choice(termos_busca)
    
    # RANDOMIZAR página (não pegar sempre as primeiras)
    pagina = random.randint(1, 3)
    
    print(f"🔍 Buscando: '{palavra_busca}' (página {pagina})")
    
    midias = []
    
    if tipo == 'video':
        orientacao = 'portrait' if VIDEO_TYPE == 'short' else 'landscape'
        url = f'https://api.pexels.com/videos/search?query={palavra_busca}&per_page=30&page={pagina}&orientation={orientacao}'
        
        try:
            response = requests.get(url, headers=headers, timeout=15)
            if response.status_code == 200:
                data = response.json()
                videos = data.get('videos', [])
                
                # EMBARALHAR resultados
                random.shuffle(videos)
                
                for video in videos:
                    for file in video['video_files']:
                        if VIDEO_TYPE == 'short':
                            # Aceitar mais resoluções verticais
                            if file.get('width', 0) <= 1080 and file.get('height', 0) >= 1920:
                                midias.append((file['link'], 'video'))
                                break
                            # Fallback: qualquer vertical
                            elif file.get('height', 0) > file.get('width', 0):
                                midias.append((file['link'], 'video'))
                                break
                        else:
                            if file.get('width', 0) >= 1280 and file.get('height', 0) >= 720:
                                midias.append((file['link'], 'video'))
                                break
                    
                    if len(midias) >= quantidade:
                        break
                        
                print(f"   ✓ Encontrou {len(midias)} vídeos")
                
        except Exception as e:
            print(f"   ⚠️ Erro ao buscar vídeos: {e}")
    
    # SEMPRE complementar com fotos
    if len(midias) < quantidade:
        orientacao = 'portrait' if VIDEO_TYPE == 'short' else 'landscape'
        url = f'https://api.pexels.com/v1/search?query={palavra_busca}&per_page=50&page={pagina}&orientation={orientacao}'
        
        try:
            response = requests.get(url, headers=headers, timeout=15)
            if response.status_code == 200:
                data = response.json()
                fotos = data.get('photos', [])
                
                # EMBARALHAR fotos
                random.shuffle(fotos)
                
                for foto in fotos[:quantidade - len(midias) + 5]:  # Pegar extras
                    midias.append((foto['src']['large2x'], 'foto'))
                
                print(f"   ✓ Adicionou {len(midias) - len([m for m in midias if m[1] == 'video'])} fotos")
                
        except Exception as e:
            print(f"   ⚠️ Erro ao buscar fotos: {e}")
    
    # Garantir quantidade mínima
    if len(midias) < quantidade:
        print(f"   ⚠️ Só encontrou {len(midias)}, tentando busca genérica...")
        midias_extras = buscar_midia_pexels(['beautiful nature'], tipo, quantidade - len(midias))
        midias.extend(midias_extras)
    
    # EMBARALHAR resultado final
    random.shuffle(midias)
    
    print(f"   ✅ Total: {len(midias)} mídias")
    return midias[:quantidade]  # Retornar exatamente a quantidade pedida

def baixar_midia(url, filename):
    """Baixa mídia"""
    try:
        response = requests.get(url, stream=True, timeout=30)
        with open(filename, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return filename
    except:
        return None

# ========== CRIAÇÃO DE VÍDEO ==========

def criar_video_short(audio_path, midias, output_file, duracao):
    """Cria short vertical (9:16) - 1080x1920"""
    clips = []

    print(f"📹 Processando {len(midias)} mídias para {duracao:.1f}s")
    
    # Se tiver poucas mídias, duplicar
    if len(midias) < 4:
        print("⚠️ Poucas mídias, duplicando...")
        midias = midias * 3  # Triplicar
    
    duracao_por_midia = duracao / len(midias)
    print(f"   Cada mídia: {duracao_por_midia:.1f}s")
    
    for i, (midia_url, midia_tipo) in enumerate(midias[:5]):
        if not midia_url:
            continue
            
        duracao_clip = duracao / len(midias)
        
        try:
            if midia_tipo == 'video':
                video_temp = f'{ASSETS_DIR}/video_{i}.mp4'
                if baixar_midia(midia_url, video_temp):
                    clip = VideoFileClip(video_temp, audio=False)
                    
                    target_ratio = 9/16
                    video_ratio = clip.w / clip.h
                    
                    if video_ratio > target_ratio:
                        new_width = int(clip.h * target_ratio)
                        x_center = clip.w / 2
                        clip = clip.crop(x_center=x_center, width=new_width, height=clip.h)
                    else:
                        new_height = int(clip.w / target_ratio)
                        y_center = clip.h / 2
                        clip = clip.crop(y_center=y_center, width=clip.w, height=new_height)
                    
                    clip = clip.resize((1080, 1920))
                    clip = clip.set_duration(min(duracao_clip, clip.duration))
                    
                    if i > 0:
                        clip = clip.crossfadein(0.3)
                    
                    clips.append(clip)
            else:
                foto_temp = f'{ASSETS_DIR}/foto_{i}.jpg'
                if baixar_midia(midia_url, foto_temp):
                    clip = ImageClip(foto_temp).set_duration(duracao_clip)
                    clip = clip.resize(height=1920)
                    if clip.w > 1080:
                        clip = clip.crop(x_center=clip.w/2, width=1080, height=1920)
                    clip = clip.resize(lambda t: 1 + 0.15 * (t / duracao_clip))
                    clips.append(clip)
        except Exception as e:
            print(f"⚠️ Erro ao processar mídia {i}: {e}")
            continue
    
    if not clips:
        print("❌ Nenhuma mídia válida")
        return None
    
    video = concatenate_videoclips(clips, method="compose")
    video = video.set_duration(duracao)
    
    audio = AudioFileClip(audio_path)
    video = video.set_audio(audio)
    
    video.write_videofile(
        output_file,
        fps=30,
        codec='libx264',
        audio_codec='aac',
        preset='medium',
        bitrate='8000k'
    )
    
    return output_file

def criar_video_long(audio_path, midias, output_file, duracao):
    """Cria vídeo longo horizontal (16:9) - 1920x1080"""
    clips = []
    duracao_por_midia = duracao / len(midias)
    
    for i, (midia_url, midia_tipo) in enumerate(midias):
        if not midia_url:
            continue
        
        try:
            if midia_tipo == 'video':
                video_temp = f'{ASSETS_DIR}/video_{i}.mp4'
                if baixar_midia(midia_url, video_temp):
                    clip = VideoFileClip(video_temp, audio=False)
                    clip = clip.resize(height=1080)
                    if clip.w < 1920:
                        clip = clip.resize(width=1920)
                    clip = clip.crop(x_center=clip.w/2, y_center=clip.h/2, width=1920, height=1080)
                    clip = clip.set_duration(min(duracao_por_midia, clip.duration))
                    
                    if i > 0:
                        clip = clip.crossfadein(0.5)
                    
                    clips.append(clip)
            else:
                foto_temp = f'{ASSETS_DIR}/foto_{i}.jpg'
                if baixar_midia(midia_url, foto_temp):
                    clip = ImageClip(foto_temp).set_duration(duracao_por_midia)
                    clip = clip.resize(height=1080)
                    if clip.w < 1920:
                        clip = clip.resize(width=1920)
                    clip = clip.crop(x_center=clip.w/2, y_center=clip.h/2, width=1920, height=1080)
                    clip = clip.resize(lambda t: 1 + 0.08 * (t / duracao_por_midia))
                    
                    if i > 0:
                        clip = clip.crossfadein(0.5)
                    
                    clips.append(clip)
        except Exception as e:
            print(f"⚠️ Erro ao processar mídia {i}: {e}")
            continue
    
    if not clips:
        print("❌ Nenhuma mídia válida")
        return None
    
    video = concatenate_videoclips(clips, method="compose")
    video = video.set_duration(duracao)
    
    audio = AudioFileClip(audio_path)
    video = video.set_audio(audio)
    
    video.write_videofile(
        output_file,
        fps=24,
        codec='libx264',
        audio_codec='aac',
        preset='medium',
        bitrate='5000k'
    )
    
    return output_file

# ========== THUMBNAIL ==========

def criar_thumbnail(titulo, output_file, tipo='short'):
    """Cria thumbnail"""
    tamanho = (1080, 1920) if tipo == 'short' else (1280, 720)
    font_size = 90 if tipo == 'short' else 80
    
    img = Image.new('RGB', tamanho, color=(25, 25, 45))
    draw = ImageDraw.Draw(img)
    
    for i in range(tamanho[1]):
        cor = (25 + i//25, 25 + i//35, 45 + i//20)
        draw.rectangle([(0, i), (tamanho[0], i+1)], fill=cor)
    
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", font_size//2)
    except:
        font = ImageFont.load_default()
        font_small = font
    
    palavras = titulo.split()[:8]
    texto = ' '.join(palavras)
    
    linhas = []
    linha_atual = ""
    for palavra in palavras:
        teste = f"{linha_atual} {palavra}" if linha_atual else palavra
        if len(teste) < 20:
            linha_atual = teste
        else:
            linhas.append(linha_atual)
            linha_atual = palavra
    if linha_atual:
        linhas.append(linha_atual)
    
    y_start = tamanho[1] // 3
    for linha in linhas[:3]:
        bbox = draw.textbbox((0, 0), linha, font=font)
        w = bbox[2] - bbox[0]
        x = (tamanho[0] - w) // 2
        
        draw.text((x+3, y_start+3), linha, font=font, fill=(0, 0, 0))
        draw.text((x, y_start), linha, font=font, fill=(255, 255, 255))
        y_start += font_size + 20
    
    emoji = "🔥" if tipo == 'short' else "📚"
    bbox = draw.textbbox((0, 0), emoji, font=font_small)
    w = bbox[2] - bbox[0]
    draw.text(((tamanho[0]-w)//2, y_start + 50), emoji, font=font_small, fill=(255, 200, 0))
    
    img.save(output_file, quality=95)
    return output_file

# ========== YOUTUBE ==========

def gerar_titulo_descricao(roteiro, tema):
    """Gera título e descrição"""
    titulo = tema[:60] if len(tema) <= 60 else tema[:57] + '...'
    
    if VIDEO_TYPE == 'short':
        titulo += ' #shorts'
    
    descricao = roteiro[:300] + '...' if len(roteiro) > 300 else roteiro
    descricao += '\n\n🔔 Inscreva-se!\n'
    descricao += f'#{"shorts" if VIDEO_TYPE == "short" else "curiosidades"} #fatos'
    
    tags = ['curiosidades', 'fatos', 'conhecimento']
    if VIDEO_TYPE == 'short':
        tags.append('shorts')
    
    return titulo, descricao, tags

def fazer_upload_youtube(video_path, titulo, descricao, tags):
    """Upload no YouTube"""
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
    request = youtube.videos().insert(part='snippet,status', body=body, media_body=media)
    response = request.execute()
    
    return response['id']

# ========== MAIN ==========

def main():
    icone = '📱' if VIDEO_TYPE == 'short' else '🎬'
    tipo_nome = 'SHORT' if VIDEO_TYPE == 'short' else 'VÍDEO LONGO'
    
    print(f"{icone} Iniciando geração de {tipo_nome}...")
    
    os.makedirs(VIDEOS_DIR, exist_ok=True)
    os.makedirs(ASSETS_DIR, exist_ok=True)
    
    noticia = buscar_noticias()
    
    print("✍️ Gerando roteiro...")
    roteiro, tema = gerar_roteiro(VIDEO_TYPE, noticia)
    print(f"📝 Tema: {tema}")
    
    print("🎙️ Criando narração...")
    audio_path = f'{ASSETS_DIR}/audio.mp3'
    criar_audio(roteiro, audio_path)
    
    audio_clip = AudioFileClip(audio_path)
    duracao = audio_clip.duration
    audio_clip.close()
    print(f"⏱️ Duração: {duracao:.1f}s")
    
    print("🖼️ Buscando mídias...")
    palavras = config.get('palavras_chave_imagens', [tema.split()[0]])
    
    quantidade = 6 if VIDEO_TYPE == 'short' else max(50, int(duracao / 12))
    
    midias = buscar_midia_pexels(palavras, tipo='video', quantidade=quantidade)
    print(f"✅ {len(midias)} mídias encontradas")

    # VERIFICAR se tem mídias suficientes
if len(midias) < 3:
    print("⚠️ POUCAS MÍDIAS! Buscando mais...")
    midias_extras = buscar_midia_pexels(['nature landscape'], tipo='foto', quantidade=5)
    midias.extend(midias_extras)
    
    print(f"🎥 Montando {tipo_nome}...")
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    video_path = f'{VIDEOS_DIR}/{VIDEO_TYPE}_{timestamp}.mp4'
    
    if VIDEO_TYPE == 'short':
        resultado = criar_video_short(audio_path, midias, video_path, duracao)
    else:
        resultado = criar_video_long(audio_path, midias, video_path, duracao)
    
    if not resultado:
        print("❌ Erro ao criar vídeo")
        return
    
    print("🖼️ Criando thumbnail...")
    thumbnail_path = f'{VIDEOS_DIR}/thumb_{timestamp}.jpg'
    criar_thumbnail(tema, thumbnail_path, VIDEO_TYPE)
    
    titulo, descricao, tags = gerar_titulo_descricao(roteiro, tema)
    
    print("📤 Fazendo upload no YouTube...")
    video_id = fazer_upload_youtube(video_path, titulo, descricao, tags)
    
    url = f'https://youtube.com/{"shorts" if VIDEO_TYPE == "short" else "watch?v="}{video_id}'
    
    log_entry = {
        'data': datetime.now().isoformat(),
        'tipo': VIDEO_TYPE,
        'tema': tema,
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
    
    print(f"✅ {tipo_nome} publicado!")
    print(f"🔗 {url}")
    
    for file in os.listdir(ASSETS_DIR):
        try:
            os.remove(os.path.join(ASSETS_DIR, file))
        except:
            pass

if __name__ == '__main__':
    main()
