"""
distribuidor.py
---------------
Distribui o vídeo publicado no YouTube para:
  1. Canal Telegram público
  2. Blogger (blogspot)
  3. (futuro) Instagram / Twitter

Chamado no final de generate_video.py, depois do upload YouTube.

Variáveis de ambiente necessárias (adicionar nos GitHub Secrets):
  TELEGRAM_CANAL_ID        → ID ou @username do canal público  (ex: @politicaemfoco)
  BLOGGER_BLOG_ID          → ID numérico do blog no Blogger
  BLOGGER_CREDENTIALS      → JSON com credenciais OAuth2 do Blogger
  PIX_CHAVE                → Apelido/chave PIX para exibir nas mensagens
  CANAL_YOUTUBE_URL        → URL base do canal (ex: https://youtube.com/@politicaemfoco)
"""

import os
import json
import time
import requests
from datetime import datetime

# ── Configurações vindas dos Secrets ────────────────────────────────────────
TELEGRAM_BOT_TOKEN   = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CANAL_ID    = os.environ.get('TELEGRAM_CANAL_ID', '')          # canal público
BLOGGER_BLOG_ID      = os.environ.get('BLOGGER_BLOG_ID', '')
BLOGGER_CREDENTIALS  = os.environ.get('BLOGGER_CREDENTIALS', '')
PIX_CHAVE            = os.environ.get('PIX_CHAVE', '')
CANAL_YOUTUBE_URL    = os.environ.get('CANAL_YOUTUBE_URL', '')


# ════════════════════════════════════════════════════════════════════════════
# TELEGRAM — Canal público
# ════════════════════════════════════════════════════════════════════════════

def _telegram_post(payload: dict) -> dict | None:
    """Envia requisição para a API do Telegram."""
    method = payload.pop('_method')
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"
    try:
        r = requests.post(url, json=payload, timeout=30)
        result = r.json()
        if not result.get('ok'):
            print(f"  ⚠️ Telegram erro: {result.get('description')}")
        return result
    except Exception as e:
        print(f"  ❌ Telegram request falhou: {e}")
        return None


def publicar_telegram_canal(titulo: str, roteiro: str, url_youtube: str,
                             thumbnail_path: str | None = None) -> bool:
    """
    Publica no CANAL PÚBLICO do Telegram.
    Formato: thumbnail + texto com link para o YouTube + CTA inscrição.
    """
    if not TELEGRAM_CANAL_ID:
        print("  ⚠️ TELEGRAM_CANAL_ID não configurado — pulando canal público")
        return False

    print(f"\n📣 Publicando no canal Telegram público...")

    # Resumo do roteiro (primeiros 300 chars)
    resumo = roteiro[:300].rsplit(' ', 1)[0] + '...' if len(roteiro) > 300 else roteiro

    pix_linha = f"\n\n💰 Apoie: PIX <code>{PIX_CHAVE}</code>" if PIX_CHAVE else ""
    canal_linha = f"\n📺 Canal: {CANAL_YOUTUBE_URL}" if CANAL_YOUTUBE_URL else ""

    texto = (
        f"🗞 <b>{titulo}</b>\n\n"
        f"{resumo}\n\n"
        f"▶️ <b>Assista completo:</b>\n{url_youtube}"
        f"{canal_linha}"
        f"\n\n🔔 Inscreva-se e ative o sininho!"
        f"{pix_linha}"
    )

    # Tenta enviar com thumbnail; se não tiver, envia só texto
    if thumbnail_path and os.path.exists(thumbnail_path):
        with open(thumbnail_path, 'rb') as img:
            r = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto",
                data={'chat_id': TELEGRAM_CANAL_ID,
                      'caption': texto[:1024],
                      'parse_mode': 'HTML'},
                files={'photo': img},
                timeout=30
            )
        result = r.json()
    else:
        payload = {
            '_method': 'sendMessage',
            'chat_id': TELEGRAM_CANAL_ID,
            'text': texto,
            'parse_mode': 'HTML',
            'disable_web_page_preview': False   # mostra preview do YouTube
        }
        result = _telegram_post(payload)

    ok = result and result.get('ok')
    print(f"  {'✅ Publicado no canal!' if ok else '❌ Falha ao publicar no canal'}")
    return bool(ok)


# ════════════════════════════════════════════════════════════════════════════
# BLOGGER
# ════════════════════════════════════════════════════════════════════════════

def _get_blogger_service():
    """Retorna cliente autenticado do Blogger v3."""
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds_dict = json.loads(BLOGGER_CREDENTIALS)
    creds = Credentials.from_authorized_user_info(creds_dict)
    return build('blogger', 'v3', credentials=creds)


def _gerar_html_post(titulo: str, roteiro: str, url_youtube: str,
                     tags: list[str], pix_chave: str, canal_yt: str) -> str:
    """Monta o HTML do post para o Blogger."""

    # Embed do YouTube — funciona tanto para Shorts quanto para vídeos normais
    if '/shorts/' in url_youtube:
        video_id = url_youtube.split('/shorts/')[-1].split('?')[0]
        embed_url = f"https://www.youtube.com/embed/{video_id}"
    else:
        video_id = url_youtube.split('v=')[-1].split('&')[0]
        embed_url = f"https://www.youtube.com/embed/{video_id}"

    tags_html = ' '.join([f'<span style="background:#1a73e8;color:#fff;padding:3px 8px;border-radius:12px;font-size:13px;margin:2px;display:inline-block">#{t}</span>' for t in tags])

    pix_bloco = ''
    if pix_chave:
        pix_bloco = f"""
<div style="background:#f0f9f0;border:1px solid #4caf50;border-radius:8px;padding:16px;margin:24px 0;text-align:center">
  <p style="margin:0;font-size:15px">💰 <strong>Apoie o canal com um PIX</strong></p>
  <p style="margin:8px 0 0;font-size:18px;font-family:monospace;color:#1a6e1a">{pix_chave}</p>
  <p style="margin:4px 0 0;font-size:12px;color:#666">Qualquer valor ajuda a manter o canal no ar!</p>
</div>"""

    inscricao_bloco = ''
    if canal_yt:
        inscricao_bloco = f"""
<div style="background:#fff3e0;border:1px solid #ff9800;border-radius:8px;padding:16px;margin:24px 0;text-align:center">
  <p style="margin:0;font-size:15px">🔔 <strong>Fique por dentro de tudo!</strong></p>
  <p style="margin:8px 0 0">
    <a href="{canal_yt}?sub_confirmation=1" target="_blank"
       style="background:#ff0000;color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none;font-weight:bold">
      ▶ Inscreva-se no YouTube
    </a>
  </p>
</div>"""

    # Parágrafos do roteiro
    paragrafos = roteiro.split('\n\n')
    corpo_html = '\n'.join(
        f'<p style="line-height:1.7;margin:0 0 16px">{p.strip()}</p>'
        for p in paragrafos if p.strip()
    )

    return f"""
<div style="font-family:Georgia,serif;max-width:780px;margin:0 auto;color:#212121">

  <!-- Vídeo embed -->
  <div style="position:relative;padding-bottom:56.25%;height:0;overflow:hidden;border-radius:10px;margin-bottom:24px">
    <iframe src="{embed_url}"
      style="position:absolute;top:0;left:0;width:100%;height:100%;border:0"
      allowfullscreen loading="lazy" title="{titulo}"></iframe>
  </div>

  {inscricao_bloco}

  <!-- Conteúdo / Roteiro -->
  <div style="font-size:16px">
    {corpo_html}
  </div>

  <!-- Tags -->
  <div style="margin:24px 0">
    {tags_html}
  </div>

  {pix_bloco}

  <!-- Footer -->
  <hr style="border:none;border-top:1px solid #e0e0e0;margin:24px 0">
  <p style="font-size:13px;color:#999;text-align:center">
    Política em Foco — Notícias políticas do Brasil com atualização contínua.<br>
    Publicado em {datetime.now().strftime('%d/%m/%Y às %H:%M')}
  </p>

</div>
"""


def publicar_blogger(titulo: str, roteiro: str, url_youtube: str,
                     tags: list[str]) -> str | None:
    """
    Cria um post no Blogger e retorna a URL do post publicado.
    Retorna None em caso de falha.
    """
    if not BLOGGER_BLOG_ID or not BLOGGER_CREDENTIALS:
        print("  ⚠️ BLOGGER_BLOG_ID ou BLOGGER_CREDENTIALS não configurados — pulando Blogger")
        return None

    print(f"\n📝 Publicando no Blogger...")

    try:
        service = _get_blogger_service()

        html_content = _gerar_html_post(
            titulo=titulo,
            roteiro=roteiro,
            url_youtube=url_youtube,
            tags=tags,
            pix_chave=PIX_CHAVE,
            canal_yt=CANAL_YOUTUBE_URL
        )

        body = {
            'title': titulo,
            'content': html_content,
            'labels': tags
        }

        post = service.posts().insert(
            blogId=BLOGGER_BLOG_ID,
            body=body,
            isDraft=False
        ).execute()

        url_post = post.get('url', '')
        print(f"  ✅ Post publicado no Blogger!")
        print(f"  🔗 {url_post}")
        return url_post

    except Exception as e:
        print(f"  ❌ Erro ao publicar no Blogger: {e}")
        import traceback
        traceback.print_exc()
        return None


# ════════════════════════════════════════════════════════════════════════════
# FUNÇÃO PRINCIPAL — chamar no final de generate_video.py
# ════════════════════════════════════════════════════════════════════════════

def distribuir(titulo: str, roteiro: str, url_youtube: str,
               tags: list[str], thumbnail_path: str | None = None) -> dict:
    """
    Executa toda a distribuição e retorna dict com resultados.

    Uso em generate_video.py (depois do fazer_upload_youtube):

        from distribuidor import distribuir
        resultado = distribuir(
            titulo=titulo,
            roteiro=roteiro,
            url_youtube=url,
            tags=tags,
            thumbnail_path=thumbnail_path
        )
    """
    print("\n" + "="*60)
    print("🚀 INICIANDO DISTRIBUIÇÃO MULTIPLATAFORMA")
    print("="*60)

    resultados = {
        'telegram_canal': False,
        'blogger_url': None,
        'timestamp': datetime.now().isoformat()
    }

    # 1. Canal Telegram público
    resultados['telegram_canal'] = publicar_telegram_canal(
        titulo=titulo,
        roteiro=roteiro,
        url_youtube=url_youtube,
        thumbnail_path=thumbnail_path
    )

    time.sleep(2)

    # 2. Blogger
    resultados['blogger_url'] = publicar_blogger(
        titulo=titulo,
        roteiro=roteiro,
        url_youtube=url_youtube,
        tags=tags
    )

    # 3. Resumo
    print("\n" + "="*60)
    print("📊 RESULTADO DA DISTRIBUIÇÃO")
    print("="*60)
    print(f"  📣 Canal Telegram : {'✅' if resultados['telegram_canal'] else '❌'}")
    print(f"  📝 Blogger        : {'✅ ' + resultados['blogger_url'] if resultados['blogger_url'] else '❌'}")
    print("="*60)

    return resultados
