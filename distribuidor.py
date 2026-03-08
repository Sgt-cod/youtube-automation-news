"""
distribuidor.py
---------------
Distribui o vídeo publicado no YouTube para:
  1. Canal Telegram público (com thumbnail Canal 55)
  2. Blogger (com thumbnail Canal 55 embutida)
  3. Twitter/X (texto + imagem + link)
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
import json
import time
import textwrap
import requests
import traceback
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
CANAL_YOUTUBE_URL           = os.environ.get('CANAL_YOUTUBE_URL', '')
KOFI_URL                    = os.environ.get('KOFI_URL', '')
KIRVANO_URL                 = os.environ.get('KIRVANO_URL', '')

LOGO_PATH = 'logo_canal55.png'   # logo na raiz do repositório


# ════════════════════════════════════════════════════════════════════════════
# THUMBNAIL — imagem Canal 55 com fundo + título + logo
# ════════════════════════════════════════════════════════════════════════════

def gerar_thumbnail(titulo: str, imagem_fundo_path: str | None,
                    output_path: str, tamanho: tuple = (1080, 1080)) -> str | None:
    try:
        W, H = tamanho

        # 1. Fundo
        if imagem_fundo_path and os.path.exists(imagem_fundo_path):
            fundo = Image.open(imagem_fundo_path).convert('RGB')
        else:
            fundo = Image.new('RGB', (W, H), color=(25, 25, 35))

        fr, ar = fundo.width / fundo.height, W / H
        nh, nw = (H, int(H * fr)) if fr > ar else (int(W / fr), W)
        fundo = fundo.resize((nw, nh), Image.LANCZOS)
        fundo = fundo.crop(((nw-W)//2, (nh-H)//2, (nw-W)//2+W, (nh-H)//2+H))
        fundo = ImageEnhance.Brightness(fundo).enhance(0.52)
        canvas = fundo.copy().convert('RGBA')

        # 2. Gradiente escuro inferior
        grad = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        gd = ImageDraw.Draw(grad)
        for y in range(H // 2, H):
            a = int(210 * ((y - H // 2) / (H // 2)))
            gd.line([(0, y), (W, y)], fill=(0, 0, 0, a))
        canvas = Image.alpha_composite(canvas, grad)

        # 3. Faixa vermelha superior
        faixa = Image.new('RGBA', (W, 72), (204, 0, 0, 235))
        canvas.paste(faixa, (0, 0), faixa)
        draw = ImageDraw.Draw(canvas)

        # 4. Texto faixa superior
        try:
            f_tag = ImageFont.truetype(
                '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 30)
        except Exception:
            f_tag = ImageFont.load_default()

        tag = "CANAL 55 NOTÍCIAS"
        bb = draw.textbbox((0, 0), tag, font=f_tag)
        draw.text(((W - (bb[2]-bb[0])) // 2, 18), tag,
                  font=f_tag, fill=(255, 255, 255))

        # 5. Título centralizado
        try:
            f_tit = ImageFont.truetype(
                '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 64)
            f_sm = ImageFont.truetype(
                '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 52)
        except Exception:
            f_tit = f_sm = ImageFont.load_default()

        linhas = textwrap.wrap(titulo, width=22)[:4]
        if len(linhas) == 4 and len(linhas[-1]) > 18:
            linhas[-1] = linhas[-1][:18] + '...'

        font = f_tit if len(linhas) <= 3 else f_sm
        lh = 78 if font == f_tit else 64
        y0 = int(H * 0.42) - (len(linhas) * lh) // 2

        for i, ln in enumerate(linhas):
            y = y0 + i * lh
            bb = draw.textbbox((0, 0), ln, font=font)
            x = (W - (bb[2]-bb[0])) // 2
            draw.text((x+3, y+3), ln, font=font, fill=(0, 0, 0, 180))
            draw.text((x, y), ln, font=font, fill=(255, 255, 255))

        # 6. Linha vermelha decorativa
        ly = H - 290
        draw.rectangle([(W//2-90, ly), (W//2+90, ly+5)], fill=(204, 0, 0))

        # 7. Logo Canal 55
        if os.path.exists(LOGO_PATH):
            logo = Image.open(LOGO_PATH).convert('RGBA')
            logo = logo.resize((220, 220), Image.LANCZOS)
            lx, ly2 = (W-220)//2, H-280
            sombra = Image.new('RGBA', (240, 240), (0, 0, 0, 0))
            ImageDraw.Draw(sombra).ellipse([5, 5, 235, 235], fill=(0, 0, 0, 70))
            sombra = sombra.filter(ImageFilter.GaussianBlur(8))
            canvas.paste(sombra, (lx-10, ly2-10), sombra)
            canvas.paste(logo, (lx, ly2), logo)

        canvas.convert('RGB').save(output_path, 'JPEG', quality=92)
        print(f"  ✅ Thumbnail gerada: {output_path}")
        return output_path

    except Exception as e:
        print(f"  ❌ Erro ao gerar thumbnail: {e}")
        traceback.print_exc()
        return None


def obter_primeira_midia_match(midias_sincronizadas: list) -> str | None:
    """Retorna a primeira foto com match real (não genérica).
    Fallback: última foto genérica disponível."""
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

    apoio = ''
    if KIRVANO_URL:
        apoio += f'\n☕ Apoie: {KIRVANO_URL}'
    if KOFI_URL:
        apoio += f'\n💙 Ko-fi: {KOFI_URL}'

    canal = f'\n📺 {CANAL_YOUTUBE_URL}' if CANAL_YOUTUBE_URL else ''

    legenda = (
        f"🗞 <b>{titulo}</b>\n\n"
        f"{resumo}\n\n"
        f"▶️ <b>Assista agora:</b>\n{url_youtube}"
        f"{canal}"
        f"\n\n🔔 Inscreva-se e ative o sininho!"
        f"{apoio}"
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
        r = requests.post(f"{base}/sendMessage",
                          json={'chat_id': TELEGRAM_CANAL_ID,
                                'text': legenda, 'parse_mode': 'HTML',
                                'disable_web_page_preview': False},
                          timeout=30)
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


def _thumb_base64(path: str) -> str:
    import base64
    with open(path, 'rb') as f:
        return "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()


def publicar_blogger(titulo: str, roteiro: str, url_youtube: str,
                     tags: list, thumbnail_path: str | None = None) -> str | None:
    if not BLOGGER_BLOG_ID or not BLOGGER_CREDENTIALS:
        print("  ⚠️ Blogger não configurado — pulando")
        return None

    print("\n📝 Publicando no Blogger...")

    try:
        # Embed
        if '/shorts/' in url_youtube:
            vid = url_youtube.split('/shorts/')[-1].split('?')[0]
        else:
            vid = url_youtube.split('v=')[-1].split('&')[0]

        # Thumbnail embutida como base64
        thumb_html = ''
        if thumbnail_path and os.path.exists(thumbnail_path):
            b64 = _thumb_base64(thumbnail_path)
            thumb_html = (
                f'<div style="text-align:center;margin-bottom:24px">'
                f'<img src="{b64}" alt="{titulo}" '
                f'style="max-width:100%;border-radius:10px;'
                f'box-shadow:0 4px 16px rgba(0,0,0,.25)"></div>'
            )

        tags_html = ' '.join([
            f'<span style="background:#cc0000;color:#fff;padding:3px 9px;'
            f'border-radius:12px;font-size:13px;margin:2px;'
            f'display:inline-block">#{t}</span>' for t in tags])

        paragrafos = '\n'.join(
            f'<p style="line-height:1.75;margin:0 0 16px;font-size:16px">'
            f'{p.strip()}</p>'
            for p in roteiro.split('\n\n') if p.strip())

        # Blocos de apoio
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
                + ''.join(links_apoio) + '</div>')

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
                f'▶ Inscreva-se no YouTube</a></div>')

        html = f"""
<div style="font-family:Georgia,serif;max-width:800px;margin:0 auto;color:#1e293b">
  {thumb_html}
  {inscricao}
  <div style="position:relative;padding-bottom:56.25%;height:0;
              overflow:hidden;border-radius:10px;margin:24px 0">
    <iframe src="https://www.youtube.com/embed/{vid}"
      style="position:absolute;top:0;left:0;width:100%;height:100%;border:0"
      allowfullscreen loading="lazy" title="{titulo}"></iframe>
  </div>
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

def publicar_twitter(titulo: str, url_youtube: str,
                     thumbnail_path: str | None = None) -> bool:
    if not all([TWITTER_API_KEY, TWITTER_API_SECRET,
                TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_TOKEN_SECRET]):
        print("  ⚠️ Twitter não configurado — pulando")
        return False

    print("\n🐦 Publicando no Twitter/X...")

    try:
        import tweepy

        hashtags = '#Política #Brasil #Notícias #Canal55'
        texto    = f"{titulo}\n\n▶️ {url_youtube}\n\n{hashtags}"
        if len(texto) > 280:
            texto = f"{titulo[:180]}...\n\n▶️ {url_youtube}\n\n{hashtags}"

        # Upload de imagem via API v1.1
        media_id = None
        if thumbnail_path and os.path.exists(thumbnail_path):
            try:
                auth  = tweepy.OAuth1UserHandler(
                    TWITTER_API_KEY, TWITTER_API_SECRET,
                    TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_TOKEN_SECRET)
                api   = tweepy.API(auth)
                media = api.media_upload(filename=thumbnail_path)
                media_id = media.media_id
                print(f"  📸 Imagem enviada (id: {media_id})")
            except Exception as e:
                print(f"  ⚠️ Falha ao enviar imagem: {e} — postando só texto")

        client = tweepy.Client(
            consumer_key=TWITTER_API_KEY,
            consumer_secret=TWITTER_API_SECRET,
            access_token=TWITTER_ACCESS_TOKEN,
            access_token_secret=TWITTER_ACCESS_TOKEN_SECRET
        )
        kwargs = {'text': texto}
        if media_id:
            kwargs['media_ids'] = [media_id]

        resp     = client.create_tweet(**kwargs)
        tweet_id = resp.data['id']
        print(f"  ✅ Tweet: https://x.com/i/web/status/{tweet_id}")
        return True

    except Exception as e:
        print(f"  ❌ Erro Twitter: {e}")
        traceback.print_exc()
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

        session_file = '/tmp/insta_session.json'
        cl = InstaClient()
        cl.delay_range = [2, 5]

        logged = False
        if os.path.exists(session_file):
            try:
                cl.load_settings(session_file)
                cl.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)
                cl.get_timeline_feed()
                logged = True
                print("  🔑 Sessão reutilizada")
            except Exception:
                logged = False

        if not logged:
            cl.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)
            cl.dump_settings(session_file)
            print("  🔑 Login realizado")

        resumo = (roteiro[:300].rsplit(' ', 1)[0] + '...'
                  if len(roteiro) > 300 else roteiro)
        apoio = ''
        if KIRVANO_URL:
            apoio += f'\n☕ Apoie: {KIRVANO_URL}'
        if KOFI_URL:
            apoio += f'\n💙 Ko-fi: {KOFI_URL}'

        legenda = (
            f"🗞 {titulo}\n\n{resumo}\n\n"
            f"▶️ Assista no YouTube:\n{url_youtube}\n"
            f"{'📺 ' + CANAL_YOUTUBE_URL if CANAL_YOUTUBE_URL else ''}\n\n"
            f"🔔 Inscreva-se e ative o sininho!\n{apoio}\n\n"
            f"#Política #Brasil #Notícias #Canal55 #PoliticaBrasileira "
            f"#Congresso #STF #Governo"
        )

        cover  = Path(thumbnail_path) if thumbnail_path and os.path.exists(thumbnail_path) else None
        media  = cl.clip_upload(Path(video_path), caption=legenda, thumbnail=cover)
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
    Chamada no generate_video.py após upload YouTube:

        from distribuidor import distribuir
        distribuir(
            titulo=titulo,
            roteiro=roteiro,
            url_youtube=url,
            tags=tags,
            thumbnail_path=thumbnail_path,
            video_path=video_path,
            midias_sincronizadas=midias_sincronizadas
        )
    """
    print("\n" + "="*60)
    print("🚀 DISTRIBUIÇÃO — Canal 55 Notícias")
    print("="*60)

    res = {'thumbnail': None, 'telegram_canal': False,
           'blogger_url': None, 'twitter': False,
           'instagram': False, 'timestamp': datetime.now().isoformat()}

    # Thumbnail
    print("\n🖼️ Gerando thumbnail...")
    fundo = obter_primeira_midia_match(midias_sincronizadas) if midias_sincronizadas else None
    if fundo:
        print(f"  📁 Fundo: {fundo}")
    thumb = gerar_thumbnail(titulo, fundo, '/tmp/thumbnail_canal55.jpg')
    res['thumbnail'] = thumb

    # Distribuição
    res['telegram_canal'] = publicar_telegram_canal(titulo, roteiro, url_youtube, thumb)
    time.sleep(2)
    res['blogger_url']    = publicar_blogger(titulo, roteiro, url_youtube, tags, thumb)
    time.sleep(2)
    res['twitter']        = publicar_twitter(titulo, url_youtube, thumb)
    time.sleep(2)
    if video_path:
        res['instagram']  = publicar_instagram_reels(
            video_path, titulo, roteiro, url_youtube, thumb)

    # Resumo
    print("\n" + "="*60)
    print("📊 RESULTADO")
    print(f"  🖼️  Thumbnail  : {'✅' if res['thumbnail'] else '❌'}")
    print(f"  📣  Telegram   : {'✅' if res['telegram_canal'] else '❌'}")
    print(f"  📝  Blogger    : {'✅' if res['blogger_url'] else '❌'}")
    print(f"  🐦  Twitter/X  : {'✅' if res['twitter'] else '❌'}")
    print(f"  📸  Instagram  : {'✅' if res['instagram'] else '❌'}")
    print("="*60)
    return res
