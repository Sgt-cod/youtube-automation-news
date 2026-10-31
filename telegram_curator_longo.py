"""
telegram_curator_longo.py
-------------------------
Curadoria via Telegram para o VÍDEO LONGO (resumo do dia).

Fluxo (uma pergunta por vez):
  1. Resumo: quantas notícias e quantos segundos cada uma ocupa.
  2. Para cada notícia: "imagens do repositório" OU "vou enviar um vídeo".
  3. Thumbnail (opcional).
  4. Quando publicar: agora ou em um horário de hoje/amanhã (Brasília).

Usa a Bot API diretamente (requests), sem depender do outro curador.

Variáveis de ambiente (usa a primeira que existir):
  Token:   TELEGRAM_LONG_BOT_TOKEN, TELEGRAM_BOT_TOKEN, TELEGRAM_TOKEN
  Chat ID: TELEGRAM_LONG_CHAT_ID,   TELEGRAM_CHAT_ID,   TELEGRAM_USER_ID

Limitação da Bot API: o bot só consegue BAIXAR arquivos de até 20 MB.
Por isso os vídeos devem ser enviados como "vídeo" (o Telegram comprime),
e não como "arquivo".
"""
import html
import os
import re
import time
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

TZ_BR = ZoneInfo('America/Sao_Paulo')
LIMITE_DOWNLOAD_BYTES = 20 * 1024 * 1024
ANTECEDENCIA_MINIMA = timedelta(minutes=30)


def _env(*nomes):
    for nome in nomes:
        valor = os.environ.get(nome)
        if valor:
            return valor
    return None


def _seg(valor):
    return f"{int(round(valor))}s"


class TelegramCuratorLongo:
    def __init__(self):
        self.token = _env('TELEGRAM_LONG_BOT_TOKEN', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_TOKEN')
        self.chat_id = _env('TELEGRAM_LONG_CHAT_ID', 'TELEGRAM_CHAT_ID', 'TELEGRAM_USER_ID')
        if not self.token or not self.chat_id:
            raise RuntimeError(
                "Defina o token e o chat id do Telegram "
                "(TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)."
            )
        self.chat_id = str(self.chat_id)
        self.base_url = f'https://api.telegram.org/bot{self.token}'
        self.sessao = uuid.uuid4().hex[:6]   # ignora botões de execuções antigas
        self.offset = None
        self._descartar_pendentes()

    # ------------------------------------------------------------------
    # Baixo nível
    # ------------------------------------------------------------------
    def _api(self, metodo, _http_timeout=30, **params):
        # Nunca propaga a mensagem original do requests: ela inclui a URL com o token.
        try:
            resp = requests.post(f'{self.base_url}/{metodo}', json=params,
                                 timeout=_http_timeout)
            dados = resp.json()
        except Exception as e:
            raise RuntimeError(f"Telegram {metodo}: falha de rede ({type(e).__name__})") from None
        if not dados.get('ok'):
            raise RuntimeError(f"Telegram {metodo}: {dados.get('description')}")
        return dados['result']

    def _descartar_pendentes(self):
        """Ignora tudo que chegou antes desta execução."""
        try:
            ultimos = self._api('getUpdates', offset=-1, timeout=0)
            if ultimos:
                self.offset = ultimos[-1]['update_id'] + 1
        except Exception as e:
            print(f"   ⚠️ Não consegui limpar updates pendentes: {e}")

    @staticmethod
    def _chat_do_update(up):
        msg = up.get('message') or (up.get('callback_query') or {}).get('message') or {}
        return str((msg.get('chat') or {}).get('id'))

    def _aguardar(self, filtro, timeout):
        """Long-polling até `filtro(update)` devolver algo != None, ou timeout."""
        fim = time.time() + timeout
        falhas = 0
        while True:
            restante = fim - time.time()
            if restante <= 0:
                return None
            espera = int(min(25, max(1, restante)))
            params = {'timeout': espera, 'allowed_updates': ['message', 'callback_query']}
            if self.offset is not None:
                params['offset'] = self.offset
            try:
                updates = self._api('getUpdates', _http_timeout=espera + 15, **params)
                falhas = 0
            except Exception as e:
                falhas += 1
                print(f"   ⚠️ {e}")
                if falhas >= 5:
                    raise RuntimeError(
                        "getUpdates falhando repetidamente "
                        "(outro processo usando o mesmo bot?)") from None
                time.sleep(3)
                continue

            for up in updates:
                self.offset = up['update_id'] + 1
                if self._chat_do_update(up) != self.chat_id:
                    continue
                resultado = filtro(up)
                if resultado is not None:
                    return resultado

    def _botao_meu(self, up):
        """Se o update é um clique de botão desta sessão, devolve o valor."""
        cq = up.get('callback_query')
        if not cq:
            return None
        dados = cq.get('data', '')
        if not dados.startswith(self.sessao + '|'):
            return None
        try:
            self._api('answerCallbackQuery', callback_query_id=cq['id'])
        except Exception:
            pass
        return dados.split('|', 1)[1]

    def _remover_botoes(self, message_id):
        try:
            self._api('editMessageReplyMarkup', chat_id=self.chat_id,
                      message_id=message_id, reply_markup={'inline_keyboard': []})
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Mensagens
    # ------------------------------------------------------------------
    def enviar_mensagem(self, texto, opcoes=None):
        """opcoes: lista de (rótulo, valor); cada uma vira uma linha de botão."""
        params = dict(chat_id=self.chat_id, text=texto, parse_mode='HTML',
                      disable_web_page_preview=True)
        if opcoes:
            params['reply_markup'] = {'inline_keyboard': [
                [{'text': rotulo, 'callback_data': f'{self.sessao}|{valor}'}]
                for rotulo, valor in opcoes
            ]}
        return self._api('sendMessage', **params)

    def perguntar_botoes(self, texto, opcoes, timeout):
        """Devolve o valor do botão tocado, ou None se der timeout."""
        msg = self.enviar_mensagem(texto, opcoes)
        validos = {valor for _, valor in opcoes}

        def filtro(up):
            valor = self._botao_meu(up)
            return valor if valor in validos else None

        try:
            return self._aguardar(filtro, timeout)
        finally:
            self._remover_botoes(msg['message_id'])

    # ------------------------------------------------------------------
    # Perguntas do fluxo
    # ------------------------------------------------------------------
    def enviar_resumo(self, itens):
        """itens: lista de (titulo, duracao_em_segundos)."""
        total = sum(d for _, d in itens)
        linhas = [f"🎬 <b>Vídeo longo — resumo do dia</b>",
                  f"{len(itens)} notícias • ~{total / 60:.1f} min de narração", ""]
        for i, (titulo, dur) in enumerate(itens, 1):
            linhas.append(f"<b>{i}.</b> {_seg(dur)} — {html.escape(titulo[:80])}")
        linhas += ["", "Vou perguntar, uma por vez, como montar cada notícia."]
        self.enviar_mensagem('\n'.join(linhas))

    def _filtro_video(self, up):
        valor = self._botao_meu(up)
        if valor == 'img':
            return ('img', None)
        msg = up.get('message') or {}
        arquivo = msg.get('video') or msg.get('animation')
        if not arquivo:
            doc = msg.get('document')
            if doc and (doc.get('mime_type') or '').startswith('video/'):
                arquivo = doc
        if arquivo:
            return ('video', {'file_id': arquivo['file_id'],
                              'file_size': arquivo.get('file_size') or 0})
        return None

    def _baixar(self, file_id, destino_base):
        info = self._api('getFile', file_id=file_id)
        caminho_remoto = info['file_path']
        extensao = os.path.splitext(caminho_remoto)[1] or '.mp4'
        destino = destino_base + extensao
        try:
            url = f'https://api.telegram.org/file/bot{self.token}/{caminho_remoto}'
            with requests.get(url, stream=True, timeout=120) as r:
                r.raise_for_status()
                with open(destino, 'wb') as f:
                    for pedaco in r.iter_content(256 * 1024):
                        f.write(pedaco)
        except Exception as e:
            raise RuntimeError(f"download falhou ({type(e).__name__})") from None
        return destino

    def perguntar_fonte(self, indice, total, titulo, duracao, destino_base,
                        validar, timeout=1200):
        """
        Pergunta como montar UMA notícia.
        Devolve o caminho do vídeo enviado, ou None para usar imagens do repositório.
        `validar(caminho)` -> (ok: bool, mensagem: str)
        """
        texto = (f"📰 <b>Notícia {indice}/{total}</b> — <b>{_seg(duracao)}</b>\n"
                 f"{html.escape(titulo[:120])}\n\nComo você quer montar esta parte?")
        escolha = self.perguntar_botoes(
            texto,
            [("🖼️ Imagens do repositório", 'img'), ("🎬 Vou enviar um vídeo", 'vid')],
            timeout)
        if escolha != 'vid':
            if escolha is None:
                self.enviar_mensagem("⏰ Sem resposta — vou usar imagens do repositório nesta notícia.")
            return None

        msg = self.enviar_mensagem(
            f"🎬 Envie agora o vídeo da notícia {indice} (pelo menos <b>{_seg(duracao)}</b>; "
            f"se for maior eu corto).\n"
            f"Envie como <b>vídeo</b> (não como arquivo), até 20 MB.",
            [("🖼️ Usar imagens do repositório", 'img')])
        fim = time.time() + timeout
        try:
            while True:
                restante = fim - time.time()
                if restante <= 0:
                    self.enviar_mensagem("⏰ Tempo esgotado — usando imagens do repositório nesta notícia.")
                    return None
                recebido = self._aguardar(self._filtro_video, restante)
                if recebido is None:
                    continue
                tipo, info = recebido
                if tipo == 'img':
                    return None
                if info['file_size'] > LIMITE_DOWNLOAD_BYTES:
                    self.enviar_mensagem(
                        f"⚠️ Esse arquivo tem {info['file_size'] / 1048576:.0f} MB e o Telegram só "
                        f"permite que o bot baixe até 20 MB. Reenvie como <b>vídeo</b> "
                        f"(compactado) ou toque em “Usar imagens”.")
                    continue
                self.enviar_mensagem("⬇️ Baixando o vídeo...")
                try:
                    caminho = self._baixar(info['file_id'], destino_base)
                except Exception as e:
                    self.enviar_mensagem(f"⚠️ Não consegui baixar ({html.escape(str(e))[:120]}). Tente de novo.")
                    continue
                ok, mensagem = validar(caminho)
                if ok:
                    self.enviar_mensagem(f"✅ {html.escape(mensagem)}")
                    return caminho
                self.enviar_mensagem(f"⚠️ {html.escape(mensagem)}\n"
                                     f"Reenvie outro vídeo ou toque em “Usar imagens”.")
                try:
                    os.remove(caminho)
                except OSError:
                    pass
        finally:
            self._remover_botoes(msg['message_id'])

    def _filtro_imagem(self, up):
        valor = self._botao_meu(up)
        if valor == 'auto':
            return ('auto', None)
        msg = up.get('message') or {}
        fotos = msg.get('photo')
        if fotos:
            maior = fotos[-1]
            return ('img', {'file_id': maior['file_id'], 'file_size': maior.get('file_size') or 0})
        doc = msg.get('document')
        if doc and (doc.get('mime_type') or '').startswith('image/'):
            return ('img', {'file_id': doc['file_id'], 'file_size': doc.get('file_size') or 0})
        return None

    def solicitar_thumbnail(self, titulo, destino_base, timeout=1200):
        """Devolve o caminho da imagem enviada, ou None (YouTube escolhe o frame)."""
        msg = self.enviar_mensagem(
            f"🖼️ <b>Thumbnail</b> do vídeo longo:\n{html.escape(titulo)}\n\n"
            f"Envie a imagem agora (ideal 1280×720) ou toque em “Sem thumbnail”.",
            [("⏭️ Sem thumbnail (YouTube escolhe)", 'auto')])
        fim = time.time() + timeout
        try:
            while True:
                restante = fim - time.time()
                if restante <= 0:
                    self.enviar_mensagem("⏰ Sem thumbnail recebida — o YouTube vai escolher um frame.")
                    return None
                recebido = self._aguardar(self._filtro_imagem, restante)
                if recebido is None:
                    continue
                tipo, info = recebido
                if tipo == 'auto':
                    return None
                if info['file_size'] > LIMITE_DOWNLOAD_BYTES:
                    self.enviar_mensagem("⚠️ Imagem grande demais (>20 MB). Envie outra.")
                    continue
                try:
                    caminho = self._baixar(info['file_id'], destino_base)
                except Exception as e:
                    self.enviar_mensagem(f"⚠️ Não consegui baixar ({html.escape(str(e))[:120]}). Tente de novo.")
                    continue
                self.enviar_mensagem("✅ Thumbnail recebida.")
                return caminho
        finally:
            self._remover_botoes(msg['message_id'])

    # ------------------------------------------------------------------
    # Agendamento
    # ------------------------------------------------------------------
    @staticmethod
    def interpretar_horario(texto, agora=None):
        """
        Aceita: '18', '18:30', '18h', '18h30', 'amanhã 08:00'.
        Devolve datetime com fuso de Brasília, ou None se não entender.
        """
        agora = agora or datetime.now(TZ_BR)
        t = texto.strip().lower()
        amanha = False
        m = re.match(r'^amanh[ãa]\s+(.*)$', t)
        if m:
            amanha = True
            t = m.group(1).strip()
        m = re.match(r'^(\d{1,2})(?:\s*[:h]\s*(\d{2})?)?$', t)
        if not m:
            return None
        hora, minuto = int(m.group(1)), int(m.group(2) or 0)
        if not (0 <= hora <= 23 and 0 <= minuto <= 59):
            return None
        dt = agora.replace(hour=hora, minute=minuto, second=0, microsecond=0)
        if amanha:
            dt += timedelta(days=1)
        return dt

    def _filtro_horario(self, up):
        if self._botao_meu(up) == 'agora':
            return 'agora'
        texto = (up.get('message') or {}).get('text')
        return texto.strip() if texto else None

    def perguntar_agendamento(self, timeout=1200):
        """Devolve datetime (fuso de Brasília) para agendar, ou None para publicar agora."""
        escolha = self.perguntar_botoes(
            "🗓️ <b>Quando publicar?</b>",
            [("🚀 Publicar agora", 'agora'), ("🕒 Escolher horário", 'hora')],
            timeout)
        if escolha != 'hora':
            if escolha is None:
                self.enviar_mensagem("⏰ Sem resposta — vou publicar assim que o vídeo ficar pronto.")
            return None

        for _ in range(4):
            msg = self.enviar_mensagem(
                "Digite o horário (Brasília), por exemplo <code>18:30</code> (hoje) ou "
                "<code>amanhã 08:00</code>.\n"
                "A montagem leva cerca de 20–30 min, então escolha um horário depois disso.",
                [("🚀 Publicar agora", 'agora')])
            try:
                resposta = self._aguardar(self._filtro_horario, timeout)
            finally:
                self._remover_botoes(msg['message_id'])
            if resposta is None or resposta == 'agora':
                if resposta is None:
                    self.enviar_mensagem("⏰ Sem resposta — vou publicar assim que o vídeo ficar pronto.")
                return None
            agora = datetime.now(TZ_BR)
            dt = self.interpretar_horario(resposta, agora)
            if dt is None:
                self.enviar_mensagem("Não entendi esse horário. Exemplos: <code>18:30</code>, <code>18h</code>, <code>amanhã 08:00</code>.")
                continue
            if dt < agora + ANTECEDENCIA_MINIMA:
                self.enviar_mensagem("Esse horário já passou ou está muito próximo (mínimo 30 min a partir de agora).")
                continue
            self.enviar_mensagem(f"✅ Publicação agendada para <b>{dt.strftime('%d/%m às %H:%M')}</b> (Brasília).")
            return dt

        self.enviar_mensagem("Não consegui um horário válido — vou publicar assim que o vídeo ficar pronto.")
        return None
