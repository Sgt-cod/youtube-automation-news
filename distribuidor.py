"""
distribuidor.py
---------------
Distribui o vídeo publicado no YouTube para:
  1. Canal Telegram público (com thumbnail Canal 55)
  2. Blogger (com thumbnail Canal 55 embutida)
  3. Twitter/X (texto + link, plano free)
  4. Instagram (Reels via instagrapi)

Secrets necessários no GitHub:
  TELEGRAM_BOT_TOKEN          → token do bot
  TELEGRAM_CANAL_ID           → @username ou ID do canal público
  BLOGGER_BLOG_ID             → ID numérico do blog
  BLOGGER_CREDENTIALS         → JSON OAuth2 do Blogger
  TWITTER_API_KEY             → API Key do app no developer.x.com
  TWITTER_API_SECRET          → API Secret
  TWITTER_ACCESS_TOKEN        → Access Token (permissão Read+Write)
  TWITTER_ACCESS_TOKEN_SECRET → Access Token Secret
  INSTAGRAM_USERNAME          → usuário do Instagram
  INSTAGRAM_PASSWORD          → senha do Instagram
  CANAL_YOUTUBE_URL           → https://youtube.com/@canal55noticias
  KOFI_URL                    → https://ko-fi.com/canal55
  KIRVANO_URL                 → link da página de apoio na Kirvano
"""

import os
import re
import json
import time
import base64
import textwrap
import traceback
import requests
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

# ── Secrets ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN          = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CANAL_ID           = os.environ.get('TELEGRAM_CANAL_ID', '')
BLOGGER_BLOG_ID             = os.environ.get('BLOGGER_BLOG_ID', '')
BLOGGER_CREDENTIALS         = os.environ.get('BLOGGER_CREDENTIALS', '')
TWITTER_API_KEY             = os.environ.get('TWITTER_API_KEY', '')
TWITTER_API_SECRET          = os.environ.get('TWITTER_API_SECRET', '')
TWITTER_ACCESS_TOKEN        = os.environ.get('TWITTER_ACCESS_TOKEN', '')
TWITTER_ACCESS_TOKEN_SECRET = os.environ.get('TWITTER_ACCESS_TOKEN_SECRET', '')
INSTAGRAM_USERNAME          = os.environ.get('INSTAGRAM_USERNAME', '')
INSTAGRAM_PASSWORD          = os.environ.get('INSTAGRAM_PASSWORD', '')
INSTAGRAM_SESSION           = os.environ.get('INSTAGRAM_SESSION', '')
CANAL_YOUTUBE_URL           = os.environ.get('CANAL_YOUTUBE_URL', '')
KOFI_URL                    = os.environ.get('KOFI_URL', '')
KIRVANO_URL                 = os.environ.get('KIRVANO_URL', '')

LOGO_PATH = 'logo_canal55.png'


# ════════════════════════════════════════════════════════════════════════════
# UTILITÁRIOS
# ════════════════════════════════════════════════════════════════════════════

def _limpar_titulo(titulo: str) -> str:
    """Remove #shorts e variações do título para exibição externa."""
    titulo = re.sub(r'\s*#shorts?\s*$', '', titulo, flags=re.IGNORECASE)
    titulo = re.sub(r'\s*#short\s*$',  '', titulo, flags=re.IGNORECASE)
    return titulo.strip()


def _apoio_texto() -> str:
    """Retorna linha de apoio para texto simples (Telegram, Twitter)."""
    linha = ''
    if KIRVANO_URL:
        linha += f'\n☕ Apoie: {KIRVANO_URL}'
    if KOFI_URL:
        linha += f'\n💙 Ko-fi: {KOFI_URL}'
    return linha


def obter_primeira_midia_match(midias_sincronizadas: list) -> str | None:
    """
    Retorna a primeira foto com match real (não genérica).
    Fallback: última foto genérica disponível.
    """
    if not midias_sincronizadas:
        return None
    generica = None
    for item in midias_sincronizadas:
        midia = item.get('midia')
        if not midia:
            continue
        caminho, tipo = midia
        if not caminho or not os.path.exists(caminho):
            continue
        if tipo == 'video_local':
            continue
        if 'genericas' in caminho:
            generica = caminho
        else:
            return caminho
    return generica


# ════════════════════════════════════════════════════════════════════════════
# THUMBNAIL — imagem Canal 55 com fundo + título + logo
# ════════════════════════════════════════════════════════════════════════════

# ════════════════════════════════════════════════════════════════════════════
# CORREÇÃO 1 — No distribuidor.py
# Substitua a função gerar_thumbnail() inteira
# Título agora sempre aparece completo — fonte se ajusta automaticamente
# ════════════════════════════════════════════════════════════════════════════
 
def gerar_thumbnail(titulo: str, fundo_path: str | None = None,
                    output_path: str = '/tmp/thumbnail_canal55.jpg',
                    tamanho: tuple = (1080, 1080)) -> str | None:
    try:
        import textwrap
        from PIL import Image, ImageDraw, ImageFont
 
        W, H = tamanho
        titulo_limpo = titulo.replace(' #shorts', '').replace('#shorts', '').strip()
 
        # ── Fundo ─────────────────────────────────────────────────────────
        if fundo_path and os.path.exists(fundo_path):
            try:
                img = Image.open(fundo_path).convert('RGB')
                ratio = W / H
                iw, ih = img.size
                if iw / ih > ratio:
                    new_w = int(ih * ratio)
                    img = img.crop(((iw - new_w) // 2, 0, (iw + new_w) // 2, ih))
                else:
                    new_h = int(iw / ratio)
                    img = img.crop((0, (ih - new_h) // 2, iw, (ih + new_h) // 2))
                img = img.resize((W, H), Image.LANCZOS)
                overlay = Image.new('RGBA', (W, H), (0, 0, 0, 130))
                img = Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')
            except Exception:
                img = Image.new('RGB', (W, H), (15, 15, 30))
        else:
            img = Image.new('RGB', (W, H), (15, 15, 30))
 
        draw = ImageDraw.Draw(img)
 
        # ── Faixa vermelha no topo ─────────────────────────────────────────
        faixa_h = 95
        draw.rectangle([(0, 0), (W, faixa_h)], fill='#cc0000')
 
        def font(size, bold=True):
            nome = 'DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf'
            caminhos = [
                f'/usr/share/fonts/truetype/dejavu/{nome}',
                f'/usr/share/fonts/dejavu/{nome}',
            ]
            for c in caminhos:
                try:
                    return ImageFont.truetype(c, size)
                except Exception:
                    continue
            return ImageFont.load_default()
 
        # Texto da faixa
        f_faixa = font(50)
        canal_txt = 'CANAL 55 NOTÍCIAS'
        bb = draw.textbbox((0, 0), canal_txt, font=f_faixa)
        draw.text(((W - (bb[2]-bb[0])) // 2, (faixa_h - (bb[3]-bb[1])) // 2),
                  canal_txt, font=f_faixa, fill='white')
 
        # ── Área disponível para o título ──────────────────────────────────
        margem = 60
        area_w = W - (margem * 2)
        logo_h = 240
        area_y_ini = faixa_h + 40
        area_y_fim = H - logo_h - 40
        area_h = area_y_fim - area_y_ini
 
        # Ajusta tamanho da fonte para caber o título COMPLETO
        font_size = 82
        f_titulo = None
        linhas_titulo = []
        while font_size >= 32:
            f_titulo = font(font_size)
            chars_por_linha = max(8, int(area_w / (font_size * 0.54)))
            linhas_titulo = textwrap.wrap(titulo_limpo, width=chars_por_linha)
            line_h = font_size + 14
            if len(linhas_titulo) * line_h <= area_h:
                break
            font_size -= 4
 
        # Centraliza verticalmente
        line_h = font_size + 14
        total_h = len(linhas_titulo) * line_h
        y = area_y_ini + (area_h - total_h) // 2
 
        for linha in linhas_titulo:
            bb = draw.textbbox((0, 0), linha, font=f_titulo)
            lw = bb[2] - bb[0]
            x = (W - lw) // 2
            # Sombra
            draw.text((x + 3, y + 3), linha, font=f_titulo, fill=(0, 0, 0, 200))
            draw.text((x, y), linha, font=f_titulo, fill='white')
            y += line_h
 
        # ── Linha decorativa ───────────────────────────────────────────────
        linha_y = H - logo_h - 18
        draw.rectangle([(margem, linha_y), (W - margem, linha_y + 4)], fill='#cc0000')
 
        # ── Logo Canal 55 ──────────────────────────────────────────────────
        logo_paths = ['logo_canal55.png', 'assets/logo_canal55.png']
        logo_carregado = False
        for lp in logo_paths:
            if os.path.exists(lp):
                try:
                    logo = Image.open(lp).convert('RGBA')
                    logo_w = 200
                    logo_h_real = int(logo.height * logo_w / logo.width)
                    logo = logo.resize((logo_w, logo_h_real), Image.LANCZOS)
                    lx = (W - logo_w) // 2
                    ly = H - logo_h_real - 20
                    img.paste(logo, (lx, ly), logo)
                    logo_carregado = True
                    break
                except Exception:
                    pass
 
        if not logo_carregado:
            # Fallback: texto simples no lugar da logo
            f_logo = font(36)
            txt = 'Canal 55'
            bb = draw.textbbox((0, 0), txt, font=f_logo)
            draw.text(((W - (bb[2]-bb[0])) // 2, H - 80), txt, font=f_logo, fill='#cc0000')
 
        # ── Texto "LEIA NA LEGENDA" abaixo do logo ─────────────────────────
        f_legenda = font(34)
        txt_legenda = '👇 LEIA NA LEGENDA'
        bb = draw.textbbox((0, 0), txt_legenda, font=f_legenda)
        lw = bb[2] - bb[0]
        lh = bb[3] - bb[1]
        # Sombra
        draw.text(((W - lw) // 2 + 2, H - lh - 10 + 2), txt_legenda,
                  font=f_legenda, fill=(0, 0, 0, 180))
        draw.text(((W - lw) // 2, H - lh - 10), txt_legenda,
                  font=f_legenda, fill='white')
 
        img.save(output_path, 'JPEG', quality=95)
        print(f"  ✅ Thumbnail gerada: {output_path} (fonte {font_size}px, {len(linhas_titulo)} linhas)")
        return output_path
 
    except Exception as e:
        print(f"  ❌ Erro ao gerar thumbnail: {e}")
        import traceback
        traceback.print_exc()
        return None


# ════════════════════════════════════════════════════════════════════════════
# TELEGRAM — Canal público
# ════════════════════════════════════════════════════════════════════════════

def publicar_telegram_canal(titulo: str, roteiro: str, url_youtube: str,
                             thumbnail_path: str | None = None) -> bool:
    if not TELEGRAM_CANAL_ID:
        print("  ⚠️ TELEGRAM_CANAL_ID não configurado — pulando")
        return False

    print("\n📣 Publicando no canal Telegram...")

    resumo = (roteiro[:280].rsplit(' ', 1)[0] + '...'
              if len(roteiro) > 280 else roteiro)
    canal  = f'\n📺 {CANAL_YOUTUBE_URL}' if CANAL_YOUTUBE_URL else ''

    legenda = (
        f"🗞 <b>{titulo}</b>\n\n"
        f"{resumo}\n\n"
        f"▶️ <b>Assista agora:</b>\n{url_youtube}"
        f"{canal}"
        f"\n\n🔔 Inscreva-se e ative o sininho!"
        f"{_apoio_texto()}"
    )

    base = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

    if thumbnail_path and os.path.exists(thumbnail_path):
        try:
            with open(thumbnail_path, 'rb') as img:
                r = requests.post(
                    f"{base}/sendPhoto",
                    data={'chat_id': TELEGRAM_CANAL_ID,
                          'caption': legenda[:1024],
                          'parse_mode': 'HTML'},
                    files={'photo': img},
                    timeout=30
                )
            ok = r.json().get('ok', False)
            print(f"  {'✅ Publicado com imagem!' if ok else '❌ Falha: ' + str(r.json().get('description'))}")
            return ok
        except Exception as e:
            print(f"  ❌ Erro: {e}")

    # Fallback sem imagem
    try:
        r = requests.post(
            f"{base}/sendMessage",
            json={'chat_id': TELEGRAM_CANAL_ID, 'text': legenda,
                  'parse_mode': 'HTML', 'disable_web_page_preview': False},
            timeout=30
        )
        ok = r.json().get('ok', False)
        print(f"  {'✅ Publicado (sem imagem)' if ok else '❌ Falha'}")
        return ok
    except Exception as e:
        print(f"  ❌ Erro: {e}")
        return False


# ════════════════════════════════════════════════════════════════════════════
# BLOGGER
# ════════════════════════════════════════════════════════════════════════════

def _blogger_service():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    creds = Credentials.from_authorized_user_info(json.loads(BLOGGER_CREDENTIALS))
    return build('blogger', 'v3', credentials=creds)


def _upload_thumb_github(thumbnail_path: str) -> str | None:
    """
    Faz upload da thumbnail para o repositório GitHub (pasta thumbs/).
    Retorna URL pública raw.githubusercontent.com ou None se falhar.

    Secrets necessários:
      GITHUB_TOKEN → token com permissão de repo (já existe no workflow como GITHUB_TOKEN)
      GITHUB_REPO  → ex: Sgt-cod/youtube-automation-news
    """
    GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', '')
    GITHUB_REPO  = os.environ.get('GITHUB_REPO', '')

    if not GITHUB_TOKEN or not GITHUB_REPO:
        print("  ⚠️ GITHUB_TOKEN ou GITHUB_REPO não configurado")
        return None

    try:
        import base64
        from datetime import datetime

        nome_arquivo = f"thumb_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        caminho_repo = f"thumbs/{nome_arquivo}"

        with open(thumbnail_path, 'rb') as f:
            b64 = base64.b64encode(f.read()).decode()

        r = requests.put(
            f"https://api.github.com/repos/{GITHUB_REPO}/contents/{caminho_repo}",
            headers={
                'Authorization': f'token {GITHUB_TOKEN}',
                'Accept': 'application/vnd.github.v3+json'
            },
            json={
                'message': f'thumb: {nome_arquivo}',
                'content': b64
            },
            timeout=30
        )

        if r.status_code in (200, 201):
            url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/{caminho_repo}"
            print(f"  🖼️ Thumbnail no GitHub: {url}")
            return url
        else:
            print(f"  ⚠️ GitHub upload falhou: {r.status_code} {r.text[:200]}")
            return None

    except Exception as e:
        print(f"  ⚠️ Erro upload GitHub: {e}")
        return None


def publicar_blogger(titulo: str, roteiro: str, url_youtube: str,
                     tags: list, thumbnail_path: str | None = None) -> str | None:
    if not BLOGGER_BLOG_ID or not BLOGGER_CREDENTIALS:
        print("  ⚠️ Blogger não configurado — pulando")
        return None

    print("\n📝 Publicando no Blogger...")

    try:
        import base64, traceback
        from datetime import datetime

        # ── Thumbnail: URL pública via GitHub ────────────────────────────────
        thumb_html = ''
        if thumbnail_path and os.path.exists(thumbnail_path):
            thumb_url = _upload_thumb_github(thumbnail_path)

            if thumb_url:
                # URL pública — Blogger extrai como miniatura do post ✅
                thumb_html = (
                    f'<div style="text-align:center;margin-bottom:24px">'
                    f'<img src="{thumb_url}" alt="{titulo}" '
                    f'style="max-width:100%;border-radius:10px;'
                    f'box-shadow:0 4px 16px rgba(0,0,0,.25)"></div>'
                )
            else:
                # Fallback base64 (imagem aparece no artigo mas não na listagem)
                with open(thumbnail_path, 'rb') as f:
                    b64 = base64.b64encode(f.read()).decode()
                thumb_html = (
                    f'<div style="text-align:center;margin-bottom:24px">'
                    f'<img src="data:image/jpeg;base64,{b64}" alt="{titulo}" '
                    f'style="max-width:100%;border-radius:10px;'
                    f'box-shadow:0 4px 16px rgba(0,0,0,.25)"></div>'
                )

        # Botão assistir no YouTube
        assistir_btn = (
            f'<div style="text-align:center;margin:24px 0">'
            f'<a href="{url_youtube}" target="_blank" style="'
            f'background:#ff0000;color:#fff;padding:14px 32px;'
            f'border-radius:8px;text-decoration:none;font-weight:bold;'
            f'font-size:16px;display:inline-block">'
            f'▶ Assistir no YouTube</a></div>'
        )

        tags_html = ' '.join([
            f'<span style="background:#cc0000;color:#fff;padding:3px 9px;'
            f'border-radius:12px;font-size:13px;margin:2px;'
            f'display:inline-block">#{t}</span>' for t in tags
        ])

        paragrafos = '\n'.join(
            f'<p style="line-height:1.75;margin:0 0 16px;font-size:16px">'
            f'{p.strip()}</p>'
            for p in roteiro.split('\n\n') if p.strip()
        )

        links_apoio = []
        if KIRVANO_URL:
            links_apoio.append(
                f'<a href="{KIRVANO_URL}" target="_blank" style="background:#cc0000;'
                f'color:#fff;padding:10px 22px;border-radius:6px;'
                f'text-decoration:none;font-weight:bold;margin:4px;'
                f'display:inline-block">☕ Apoie no Kirvano</a>')
        if KOFI_URL:
            links_apoio.append(
                f'<a href="{KOFI_URL}" target="_blank" style="background:#29abe0;'
                f'color:#fff;padding:10px 22px;border-radius:6px;'
                f'text-decoration:none;font-weight:bold;margin:4px;'
                f'display:inline-block">💙 Ko-fi</a>')

        apoio_bloco = ''
        if links_apoio:
            apoio_bloco = (
                f'<div style="background:#fff8f8;border:1px solid #cc0000;'
                f'border-radius:8px;padding:20px;margin:28px 0;text-align:center">'
                f'<p style="margin:0 0 12px;font-size:15px;font-weight:bold">'
                f'💰 Apoie o Canal 55 Notícias</p>'
                + ''.join(links_apoio) + '</div>'
            )

        inscricao = ''
        if CANAL_YOUTUBE_URL:
            inscricao = (
                f'<div style="background:#fff3e0;border:1px solid #ff9800;'
                f'border-radius:8px;padding:16px;margin:24px 0;text-align:center">'
                f'<p style="margin:0 0 10px;font-size:15px">🔔 '
                f'<strong>Não perca nenhuma notícia!</strong></p>'
                f'<a href="{CANAL_YOUTUBE_URL}?sub_confirmation=1" target="_blank" '
                f'style="background:#ff0000;color:#fff;padding:10px 22px;'
                f'border-radius:6px;text-decoration:none;font-weight:bold">'
                f'▶ Inscreva-se no YouTube</a></div>'
            )

        html = f"""<div style="font-family:Georgia,serif;max-width:800px;margin:0 auto;color:#1e293b">
  {thumb_html}
  {assistir_btn}
  {inscricao}
  <div style="margin:24px 0">{paragrafos}</div>
  <div style="margin:20px 0">{tags_html}</div>
  {apoio_bloco}
  <hr style="border:none;border-top:1px solid #e2e8f0;margin:28px 0">
  <p style="font-size:12px;color:#94a3b8;text-align:center">
    Canal 55 Notícias — Política brasileira com atualização contínua.<br>
    Publicado em {datetime.now().strftime('%d/%m/%Y às %H:%M')}
  </p>
</div>"""

        service = _blogger_service()
        post = service.posts().insert(
            blogId=BLOGGER_BLOG_ID,
            body={'title': titulo, 'content': html, 'labels': tags},
            isDraft=False
        ).execute()

        url_post = post.get('url', '')
        print(f"  ✅ Post publicado: {url_post}")
        return url_post

    except Exception as e:
        print(f"  ❌ Erro Blogger: {e}")
        traceback.print_exc()
        return None


# ════════════════════════════════════════════════════════════════════════════
# TWITTER / X
# ════════════════════════════════════════════════════════════════════════════

def publicar_twitter(titulo: str, url_youtube: str) -> bool:
    # A API do X exige plano pago (Basic $100/mês) para postar via API.
    # Desativado até o canal crescer e justificar o custo.
    print("\n🐦 Twitter/X — desativado (plano pago necessário)")
    return False


# ════════════════════════════════════════════════════════════════════════════
# INSTAGRAM — Reels via instagrapi
# ════════════════════════════════════════════════════════════════════════════

def publicar_instagram_reels(video_path: str, titulo: str, roteiro: str,
                              url_youtube: str,
                              thumbnail_path: str | None = None) -> bool:
    if not INSTAGRAM_USERNAME or not INSTAGRAM_PASSWORD:
        print("  ⚠️ Instagram não configurado — pulando")
        return False
    if not video_path or not os.path.exists(video_path):
        print("  ⚠️ Vídeo não encontrado — pulando Instagram")
        return False
 
    print("\n📸 Publicando no Instagram (Reels)...")
 
    try:
        from instagrapi import Client as InstaClient
 
        cl = InstaClient()
        cl.delay_range = [2, 5]
 
        # Carrega sessão salva como secret (não expira entre execuções)
        if INSTAGRAM_SESSION:
            try:
                session_data = json.loads(INSTAGRAM_SESSION)
                cl.set_settings(session_data)
                cl.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)
                cl.get_timeline_feed()
                print("  🔑 Sessão carregada do secret")
            except Exception as e:
                print(f"  ⚠️ Sessão inválida ({e}), fazendo login...")
                cl = InstaClient()
                cl.delay_range = [2, 5]
                cl.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)
                print("  🔑 Login realizado — atualize o secret INSTAGRAM_SESSION")
        else:
            cl.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)
            print("  🔑 Login sem sessão — adicione secret INSTAGRAM_SESSION")
 
        resumo = (roteiro[:300].rsplit(' ', 1)[0] + '...'
                  if len(roteiro) > 300 else roteiro)
        legenda = (
            f"🗞 {titulo}\n\n{resumo}\n\n"
            f"▶️ Assista no YouTube:\n{url_youtube}\n"
            f"{'📺 ' + CANAL_YOUTUBE_URL if CANAL_YOUTUBE_URL else ''}\n\n"
            f"🔔 Inscreva-se e ative o sininho!\n"
            f"{_apoio_texto()}\n\n"
            f"#Política #Brasil #Notícias #Canal55 #PoliticaBrasileira "
            f"#Congresso #STF #Governo"
        )
 
        cover = (Path(thumbnail_path)
                 if thumbnail_path and os.path.exists(thumbnail_path) else None)
        media = cl.clip_upload(Path(video_path), caption=legenda, thumbnail=cover)
        print(f"  ✅ Reel publicado! ID: {media.pk}")
        return True
 
    except ImportError:
        print("  ❌ instagrapi não instalado — adicione ao requirements.txt")
        return False
    except Exception as e:
        print(f"  ❌ Erro Instagram: {e}")
        traceback.print_exc()
        return False


# ════════════════════════════════════════════════════════════════════════════
# FUNÇÃO PRINCIPAL
# ════════════════════════════════════════════════════════════════════════════

def distribuir(titulo: str, roteiro: str, url_youtube: str, tags: list,
               thumbnail_path: str | None = None,
               video_path: str | None = None,
               midias_sincronizadas: list | None = None) -> dict:
    """
    Chamada no generate_video.py após upload YouTube.
    Retorna dict com resultados E caminho da thumbnail gerada.
    """
    titulo = _limpar_titulo(titulo)
 
    print("\n" + "="*60)
    print("🚀 DISTRIBUIÇÃO — Canal 55 Notícias")
    print("="*60)
 
    res = {
        'thumbnail':      None,
        'thumbnail_916':  None,   # ← versão 9:16 para YouTube
        'telegram_canal': False,
        'blogger_url':    None,
        'twitter':        False,
        'instagram':      False,
        'timestamp':      datetime.now().isoformat()
    }
 
    # Gerar thumbnail quadrada (Telegram + Blogger)
    print("\n🖼️ Gerando thumbnails...")
    fundo = obter_primeira_midia_match(midias_sincronizadas) if midias_sincronizadas else None
    if fundo:
        print(f"  📁 Fundo: {fundo}")
    else:
        print("  ⚠️ Sem match — fundo sólido")
 
    thumb_1x1 = gerar_thumbnail(titulo, fundo, '/tmp/thumbnail_canal55.jpg',
                                 tamanho=(1080, 1080))
    res['thumbnail'] = thumb_1x1
 
    # Gerar thumbnail 9:16 (YouTube Shorts)
    thumb_916 = gerar_thumbnail(titulo, fundo, '/tmp/thumbnail_canal55_916.jpg',
                                tamanho=(1080, 1920))
    res['thumbnail_916'] = thumb_916
 
    thumb = thumb_1x1  # Telegram e Blogger usam a quadrada
 
    # Distribuição
    res['telegram_canal'] = publicar_telegram_canal(titulo, roteiro, url_youtube, thumb)
    time.sleep(2)
    res['blogger_url']    = publicar_blogger(titulo, roteiro, url_youtube, tags, thumb)
    time.sleep(2)
    res['twitter']        = publicar_twitter(titulo, url_youtube)
    time.sleep(2)
    if video_path:
        res['instagram']  = publicar_instagram_reels(
            video_path, titulo, roteiro, url_youtube, thumb)
 
    # Resumo
    print("\n" + "="*60)
    print("📊 RESULTADO DA DISTRIBUIÇÃO")
    print(f"  🖼️  Thumbnail 1:1 : {'✅' if res['thumbnail'] else '❌'}")
    print(f"  🖼️  Thumbnail 9:16: {'✅' if res['thumbnail_916'] else '❌'}")
    print(f"  📣  Telegram      : {'✅' if res['telegram_canal'] else '❌'}")
    print(f"  📝  Blogger       : {'✅' if res['blogger_url'] else '❌'}")
    print(f"  🐦  Twitter/X     : {'✅' if res['twitter'] else '❌'}")
    print(f"  📸  Instagram     : {'✅' if res['instagram'] else '❌'}")
    print("="*60)
 
    return res
