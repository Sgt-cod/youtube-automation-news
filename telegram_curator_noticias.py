import os
import json
import requests
import time
import sys
from datetime import datetime

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')
CURACAO_FILE = 'curacao_pendente.json'
ASSETS_DIR = 'assets'

class TelegramCuratorNoticias:
    def __init__(self):
        self.bot_token = TELEGRAM_BOT_TOKEN
        self.chat_id = TELEGRAM_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.update_id_offset = self._obter_ultimo_update_id()
        
    def _obter_ultimo_update_id(self):
        """Obtém o último update_id"""
        try:
            url = f"{self.base_url}/getUpdates"
            response = requests.get(url, params={'offset': -1}, timeout=5)
            result = response.json()
            
            if result.get('ok') and result.get('result'):
                return result['result'][0]['update_id'] + 1
            return 0
        except:
            return 0
        
    def enviar_mensagem(self, texto, reply_markup=None):
        """Envia mensagem de texto"""
        url = f"{self.base_url}/sendMessage"
        data = {
            'chat_id': self.chat_id,
            'text': texto,
            'parse_mode': 'HTML'
        }
        
        if reply_markup:
            data['reply_markup'] = json.dumps(reply_markup)
        
        try:
            response = requests.post(url, json=data, timeout=10)
            result = response.json()
            if result.get('ok'):
                return result
            else:
                print(f"⚠️ Erro: {result}")
                return None
        except Exception as e:
            print(f"❌ Erro: {e}")
            return None
    
    def enviar_foto(self, foto_path, caption, reply_markup=None):
        """Envia foto LOCAL com legenda"""
        url = f"{self.base_url}/sendPhoto"
        
        try:
            with open(foto_path, 'rb') as photo:
                files = {'photo': photo}
                data = {
                    'chat_id': self.chat_id,
                    'caption': caption,
                    'parse_mode': 'HTML'
                }
                
                if reply_markup:
                    data['reply_markup'] = json.dumps(reply_markup)
                
                response = requests.post(url, files=files, data=data, timeout=15)
                result = response.json()
                
                if result.get('ok'):
                    return result
                else:
                    print(f"⚠️ Erro: {result}")
                    return None
        except Exception as e:
            print(f"❌ Erro: {e}")
            return None
    
    def solicitar_curacao(self, segmentos_com_midias):
        """Inicia curadoria interativa"""
        print("📱 Iniciando curadoria com imagens locais...")
        
        curacao_data = {
            'timestamp': datetime.now().isoformat(),
            'segmentos': segmentos_com_midias,
            'status': 'aguardando',
            'segmento_atual': 0,
            'aprovacoes': {},
            'aguardando_foto': False,
            'ultimo_envio': None
        }
        
        with open(CURACAO_FILE, 'w', encoding='utf-8') as f:
            json.dump(curacao_data, f, indent=2, ensure_ascii=False)
        
        self.enviar_mensagem(
            f"🎬 <b>NOVA CURADORIA - NOTÍCIAS</b>\n\n"
            f"📝 {len(segmentos_com_midias)} segmentos encontrados\n"
            f"⏰ {datetime.now().strftime('%H:%M:%S')}\n\n"
            f"🖼️ <b>Imagens do banco local</b>\n\n"
            f"<b>Comandos:</b>\n"
            f"• <b>/cancelar</b> - Cancela TUDO\n"
            f"• <b>/status</b> - Ver progresso\n"
            f"• <b>/pular</b> - Aprovar restantes\n"
            f"• <b>/retomar</b> - Se travar\n\n"
            f"💡 <b>Pode enviar foto do celular!</b>"
        )
        
        time.sleep(2)
        self._enviar_proximo_segmento()
        print("✅ Primeiro segmento enviado!")
    
    def _enviar_proximo_segmento(self):
        """Envia próximo segmento"""
        if not os.path.exists(CURACAO_FILE):
            return False
        
        with open(CURACAO_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        segmento_atual = data['segmento_atual']
        segmentos = data['segmentos']
        total = len(segmentos)
        
        if segmento_atual >= total:
            self._finalizar_curacao()
            return False
        
        seg = segmentos[segmento_atual]
        num = segmento_atual + 1
        
        midia_info, midia_tipo = seg['midia']
        texto_seg = seg['texto']
        keywords = seg.get('keywords', [])
        
        # Caption
        caption = (
            f"📌 <b>Segmento {num}/{total}</b>\n\n"
            f"📝 <i>\"{texto_seg}...\"</i>\n\n"
            f"🔍 Keywords: {', '.join(keywords)}\n"
            f"📁 Pasta: {self._extrair_pasta(midia_info)}\n\n"
            f"<i>Se travar, use /retomar</i>"
        )
        
        # Botões
        keyboard = {
            'inline_keyboard': [
                [
                    {'text': '✅ Aprovar', 'callback_data': f'aprovar_{num}'},
                    {'text': '🔄 Buscar outra', 'callback_data': f'buscar_{num}'}
                ],
                [
                    {'text': '📤 Enviar minha foto', 'callback_data': f'foto_{num}'}
                ]
            ]
        }
        
        print(f"📤 Enviando segmento {num}/{total}...")
        
        # Enviar foto LOCAL
        resultado = self.enviar_foto(midia_info, caption, keyboard)
        
        if resultado:
            data['ultimo_envio'] = datetime.now().isoformat()
            with open(CURACAO_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            print(f"✅ Segmento {num} enviado")
            return True
        else:
            print(f"❌ Falha ao enviar {num}")
            return False
    
    def _extrair_pasta(self, caminho):
        """Extrai nome da pasta do caminho"""
        try:
            partes = caminho.split('/')
            if len(partes) >= 2:
                return partes[-2]
            return "local"
        except:
            return "local"
    
    def _finalizar_curacao(self):
        """Finaliza curadoria"""
        if not os.path.exists(CURACAO_FILE):
            return
            
        with open(CURACAO_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        data['status'] = 'aprovado'
        
        with open(CURACAO_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        self.enviar_mensagem(
            f"🎉 <b>CURADORIA CONCLUÍDA!</b>\n\n"
            f"✅ Todos os {len(data['segmentos'])} segmentos aprovados!\n"
            f"🎥 Criando e publicando vídeo...\n\n"
            f"Aguarde o link!"
        )
        
        print("✅ Curadoria finalizada")
    
    def aguardar_aprovacao(self, timeout=3600):
        """Aguarda aprovação"""
        print(f"⏳ Aguardando aprovação...")
        print(f"⏰ Timeout: {timeout}s")
        
        inicio = time.time()
        ultima_verificacao = 0
        ultimo_aviso = 0
        
        while True:
            tempo_decorrido = time.time() - inicio
            
            if tempo_decorrido >= timeout:
                print(f"⏰ Timeout após {tempo_decorrido/60:.1f}min")
                
                if os.path.exists(CURACAO_FILE):
                    with open(CURACAO_FILE, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    data['status'] = 'timeout'
                    with open(CURACAO_FILE, 'w', encoding='utf-8') as f:
                        json.dump(data, f, indent=2, ensure_ascii=False)
                
                self.enviar_mensagem(
                    f"⏰ <b>TIMEOUT</b>\n\n"
                    f"Aguardei {timeout/60:.0f}min sem resposta.\n"
                    f"Curadoria cancelada."
                )
                
                return None
            
            # Progresso
            if int(tempo_decorrido) % 60 == 0 and tempo_decorrido != ultima_verificacao:
                minutos = int(tempo_decorrido / 60)
                restantes = int((timeout - tempo_decorrido) / 60)
                print(f"⏱️ {minutos}min | {restantes}min restantes")
                ultima_verificacao = tempo_decorrido
            
            # Verificar travamento
            if os.path.exists(CURACAO_FILE):
                with open(CURACAO_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                if data.get('ultimo_envio'):
                    ultimo_envio = datetime.fromisoformat(data['ultimo_envio'])
                    tempo_sem_resposta = (datetime.now() - ultimo_envio).total_seconds()
                    
                    if tempo_sem_resposta > 120 and tempo_sem_resposta - ultimo_aviso > 120:
                        minutos_travado = int(tempo_sem_resposta / 60)
                        seg_atual = data['segmento_atual'] + 1
                        total = len(data['segmentos'])
                        
                        self.enviar_mensagem(
                            f"⚠️ <b>PODE ESTAR TRAVADO</b>\n\n"
                            f"Sem resposta há {minutos_travado}min\n"
                            f"Segmento: {seg_atual}/{total}\n\n"
                            f"Use <b>/retomar</b> se necessário"
                        )
                        
                        ultimo_aviso = tempo_sem_resposta
                        print(f"⚠️ Travamento? {minutos_travado}min")
            
            # Status
            if os.path.exists(CURACAO_FILE):
                with open(CURACAO_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                if data['status'] == 'aprovado':
                    print("✅ Aprovado!")
                    return data['segmentos']
                
                elif data['status'] == 'cancelado':
                    print("❌ Cancelado")
                    self.enviar_mensagem("🛑 <b>WORKFLOW CANCELADO</b>")
                    sys.exit(1)
            
            self._processar_atualizacoes()
            time.sleep(3)
    
    def _processar_atualizacoes(self):
        """Processa updates do Telegram"""
        url = f"{self.base_url}/getUpdates"
        params = {
            'offset': self.update_id_offset,
            'timeout': 1
        }
        
        try:
            response = requests.get(url, params=params, timeout=5)
            result = response.json()
            
            if not result.get('ok'):
                return
            
            updates = result.get('result', [])
            
            for update in updates:
                self.update_id_offset = update['update_id'] + 1
                
                if 'message' in update:
                    self._processar_mensagem(update['message'])
                
                elif 'callback_query' in update:
                    self._processar_callback(update['callback_query'])
        
        except:
            pass
    
    def _processar_mensagem(self, message):
        """Processa mensagens"""
        text = message.get('text', '')
        
        if not os.path.exists(CURACAO_FILE):
            if text == '/start':
                self.enviar_mensagem(
                    "👋 <b>Curador de Notícias</b>\n\n"
                    "Enviarei segmentos para você aprovar.\n"
                    "Você pode enviar fotos do celular!\n\n"
                    "Aguarde próxima execução."
                )
            return
        
        with open(CURACAO_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        print(f"📩 Comando: {text}")
        
        if text == '/cancelar':
            print("🛑 CANCELAR TUDO")
            
            data['status'] = 'cancelado'
            with open(CURACAO_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            self.enviar_mensagem(
                "🛑 <b>CANCELAMENTO TOTAL</b>\n\n"
                "❌ Curadoria cancelada\n"
                "❌ Vídeo cancelado\n"
                "❌ Workflow encerrado"
            )
        
        elif text == '/status':
            atual = data['segmento_atual']
            total = len(data['segmentos'])
            aprovados = len(data.get('aprovacoes', {}))
            
            ultimo_envio_str = "Nunca"
            if data.get('ultimo_envio'):
                ultimo_envio = datetime.fromisoformat(data['ultimo_envio'])
                tempo = (datetime.now() - ultimo_envio).total_seconds()
                ultimo_envio_str = f"{int(tempo / 60)}min atrás"
            
            self.enviar_mensagem(
                f"📊 <b>STATUS</b>\n\n"
                f"✅ Aprovados: {aprovados}\n"
                f"📍 Atual: {atual + 1}/{total}\n"
                f"⏳ Status: {data['status']}\n"
                f"🕐 Último: {ultimo_envio_str}\n\n"
                f"<i>Se travou: /retomar</i>"
            )
        
        elif text == '/pular':
            # Verificar se é para thumbnail ou curadoria
            thumbnail_file = 'thumbnail_pendente.json'
            
            if os.path.exists(thumbnail_file):
                # Pular thumbnail
                print("⏭️ Pular thumbnail")
                
                with open(thumbnail_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                data['status'] = 'pulada'
                
                with open(thumbnail_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                
                self.enviar_mensagem("⏭️ <b>Usando thumbnail automática</b>")
            
            elif os.path.exists(CURACAO_FILE):
                # Pular curadoria
                print("⏭️ Pular curadoria")
                data['status'] = 'aprovado'
                with open(CURACAO_FILE, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                
                self.enviar_mensagem("⏭️ <b>Restantes aprovados!</b>")
        
        elif text == '/retomar':
            print("🔄 Retomar")
            
            atual = data['segmento_atual']
            total = len(data['segmentos'])
            
            self.enviar_mensagem(
                f"🔄 <b>RETOMANDO</b>\n\n"
                f"Forçando segmento {atual + 1}/{total}..."
            )
            
            time.sleep(1)
            
            if self._enviar_proximo_segmento():
                self.enviar_mensagem("✅ Reenviado!")
            else:
                self.enviar_mensagem("❌ Todos enviados")
        
        # Verificar se é FOTO ENVIADA
        elif 'photo' in message:
            # Verificar se é para thumbnail ou curadoria
            thumbnail_file = 'thumbnail_pendente.json'
            
            if os.path.exists(thumbnail_file):
                # É thumbnail
                self._processar_thumbnail(message)
            elif os.path.exists(CURACAO_FILE):
                # É foto de curadoria
                self._processar_foto_enviada(message)
    
    def _processar_foto_enviada(self, message):
        """Processa foto enviada pelo usuário"""
        if not os.path.exists(CURACAO_FILE):
            return
        
        with open(CURACAO_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if not data.get('aguardando_foto'):
            self.enviar_mensagem("⚠️ Não estou aguardando foto. Use o botão 📤")
            return
        
        idx = data['foto_segmento']
        total = len(data['segmentos'])
        num = idx + 1
        
        print(f"📸 Foto recebida para segmento {num}")
        
        self.enviar_mensagem(f"📥 Baixando sua foto...")
        
        try:
            # Pegar maior resolução
            photo = message['photo'][-1]
            file_id = photo['file_id']
            
            # Obter file_path
            file_info_url = f"{self.base_url}/getFile?file_id={file_id}"
            file_response = requests.get(file_info_url, timeout=10)
            file_data = file_response.json()
            
            if not file_data.get('ok'):
                raise Exception("Erro ao obter info do arquivo")
            
            file_path = file_data['result']['file_path']
            
            # Baixar foto
            download_url = f"https://api.telegram.org/file/bot{self.bot_token}/{file_path}"
            foto_response = requests.get(download_url, timeout=15)
            
            # Salvar
            foto_filename = f'{ASSETS_DIR}/custom_{num}.jpg'
            with open(foto_filename, 'wb') as f:
                f.write(foto_response.content)
            
            print(f"✅ Foto salva: {foto_filename}")
            
            # Atualizar segmento
            seg = data['segmentos'][idx]
            seg['midia'] = (foto_filename, 'foto_local')
            seg['customizado'] = True
            data['segmentos'][idx] = seg
            
            # Registrar aprovação
            data['aprovacoes'][str(idx)] = 'aprovado'
            
            # Incrementar
            if idx + 1 < total:
                data['segmento_atual'] = idx + 1
            else:
                data['segmento_atual'] = total
            
            data['aguardando_foto'] = False
            
            with open(CURACAO_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            self.enviar_mensagem(f"✅ <b>Foto customizada aplicada!</b>")
            
            time.sleep(2)
            self._enviar_proximo_segmento()
            
        except Exception as e:
            print(f"❌ Erro ao processar foto: {e}")
            self.enviar_mensagem(f"❌ Erro ao processar foto: {e}")
    
    def _processar_callback(self, callback):
        """Processa botões"""
        callback_data = callback['data']
        callback_id = callback['id']
        
        if not os.path.exists(CURACAO_FILE):
            self._responder_callback(callback_id, "⚠️ Expirado")
            return
        
        with open(CURACAO_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        print(f"🖱️ Botão: {callback_data}")
        
        self._responder_callback(callback_id, "✅ Processando...")
        
        if callback_data.startswith('aprovar_'):
            num = int(callback_data.split('_')[1])
            self._aprovar_segmento(data, num)
        
        elif callback_data.startswith('buscar_'):
            num = int(callback_data.split('_')[1])
            self._buscar_nova_midia(data, num)
        
        elif callback_data.startswith('foto_'):
            num = int(callback_data.split('_')[1])
            self._solicitar_foto(data, num)
    
    def _aprovar_segmento(self, data, num):
        """Aprova segmento"""
        idx = num - 1
        total = len(data['segmentos'])
        
        print(f"✅ Aprovar {num}/{total}")
        
        data['aprovacoes'][str(idx)] = 'aprovado'
        
        if idx + 1 < total:
            data['segmento_atual'] = idx + 1
        else:
            data['segmento_atual'] = total
        
        with open(CURACAO_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        self.enviar_mensagem(f"✅ <b>Segmento {num} aprovado!</b>")
        
        time.sleep(2)
        self._enviar_proximo_segmento()
    
    def _buscar_nova_midia(self, data, num):
        """Busca outra imagem da mesma pasta"""
        idx = num - 1
        seg = data['segmentos'][idx]
        
        print(f"🔄 Buscar nova para {num}")
        
        self.enviar_mensagem(f"🔄 Buscando outra imagem...")
        
        try:
            caminho_atual = seg['midia'][0]
            pasta = os.path.dirname(caminho_atual)
            
            # Listar arquivos da pasta
            arquivos = [f for f in os.listdir(pasta) 
                       if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
            
            # Remover a atual
            nome_atual = os.path.basename(caminho_atual)
            if nome_atual in arquivos:
                arquivos.remove(nome_atual)
            
            if arquivos:
                import random
                nova_foto = random.choice(arquivos)
                novo_caminho = os.path.join(pasta, nova_foto)
                
                seg['midia'] = (novo_caminho, 'foto_local')
                data['segmentos'][idx] = seg
                data['segmento_atual'] = idx
                
                with open(CURACAO_FILE, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                
                print(f"✅ Nova imagem encontrada")
                time.sleep(2)
                self._enviar_proximo_segmento()
            else:
                self.enviar_mensagem("⚠️ Sem mais imagens nesta pasta. Use 📤!")
        
        except Exception as e:
            print(f"❌ Erro: {e}")
            self.enviar_mensagem(f"❌ Erro. Use 📤 Enviar foto!")
    
    def _solicitar_foto(self, data, num):
        """Solicita foto do usuário"""
        idx = num - 1
        
        print(f"📤 Solicitar foto para {num}")
        
        data['aguardando_foto'] = True
        data['foto_segmento'] = idx
        
        with open(CURACAO_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        self.enviar_mensagem(
            f"📤 <b>Envie sua foto agora</b>\n\n"
            f"📱 Escolha uma foto da galeria\n"
            f"📸 Ou tire uma foto\n\n"
            f"💡 Será usada no segmento {num}"
        )
    
    def _responder_callback(self, callback_id, texto):
        """Responde callback"""
        url = f"{self.base_url}/answerCallbackQuery"
        try:
            requests.post(url, json={
                'callback_query_id': callback_id,
                'text': texto,
                'show_alert': False
            }, timeout=5)
        except:
            pass

        return None
    
    def solicitar_thumbnail(self, titulo, timeout=1200):
        print("🖼️ Solicitando thumbnail...")
        
        # Criar arquivo de controle
        thumbnail_file = 'thumbnail_pendente.json'
        data = {
            'titulo': titulo,
            'status': 'aguardando',
            'thumbnail_path': None,
            'timestamp': datetime.now().isoformat()
        }
        
        with open(thumbnail_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        # Enviar solicitação com instruções claras
        self.enviar_mensagem(
            f"🖼️ <b>THUMBNAIL CUSTOMIZADA</b>\n\n"
            f"📺 <b>Vídeo:</b>\n"
            f"<i>{titulo}</i>\n\n"
            f"📤 <b>Envie a imagem AGORA</b>\n\n"
            f"💡 <b>Recomendações:</b>\n"
            f"• Resolução: 1280x720 ou superior\n"
            f"• Formato: JPG ou PNG\n"
            f"• Texto grande e legível\n"
            f"• Cores vibrantes\n\n"
            f"⏱️ Tempo: {timeout//60} minutos\n"
            f"⏭️ Use /pular para thumbnail automática"
        )
        
        # Aguardar com indicadores de progresso
        inicio = time.time()
        ultimo_aviso = 0
        
        while time.time() - inicio < timeout:
            tempo_decorrido = time.time() - inicio
            
            # Avisos de progresso a cada 5 minutos
            if int(tempo_decorrido) // 300 > ultimo_aviso:
                minutos_restantes = int((timeout - tempo_decorrido) / 60)
                self.enviar_mensagem(
                    f"⏳ Ainda aguardando thumbnail...\n"
                    f"⏰ {minutos_restantes} minutos restantes\n"
                    f"Use /pular se não quiser enviar"
                )
                ultimo_aviso = int(tempo_decorrido) // 300
            
            if os.path.exists(thumbnail_file):
                with open(thumbnail_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                if data['status'] == 'recebida':
                    print("✅ Thumbnail recebida!")
                    thumbnail_path = data['thumbnail_path']
                    
                    # Limpar arquivo de controle
                    try:
                        os.remove(thumbnail_file)
                    except:
                        pass
                    
                    return thumbnail_path
                
                elif data['status'] == 'pulada':
                    print("⏭️ Thumbnail pulada pelo usuário")
                    try:
                        os.remove(thumbnail_file)
                    except:
                        pass
                    
                    return None
            
            # Processar atualizações do Telegram
            self._processar_atualizacoes()
            time.sleep(3)  # Verificar a cada 3 segundos
        
        # Timeout
        print("⏰ Timeout ao aguardar thumbnail")
        self.enviar_mensagem("⏰ <b>Tempo esgotado</b>\n\nUsando thumbnail automática do YouTube")
        
        try:
            os.remove(thumbnail_file)
        except:
            pass
        
        return None
    
    def _processar_thumbnail(self, message):
        """Processa thumbnail enviada"""
        thumbnail_file = 'thumbnail_pendente.json'
        
        if not os.path.exists(thumbnail_file):
            return
        
        print("📸 Thumbnail recebida")
        
        self.enviar_mensagem("📥 Baixando thumbnail...")
        
        try:
            # Pegar maior resolução
            photo = message['photo'][-1]
            file_id = photo['file_id']
            
            # Obter file_path
            file_info_url = f"{self.base_url}/getFile?file_id={file_id}"
            file_response = requests.get(file_info_url, timeout=10)
            file_data = file_response.json()
            
            if not file_data.get('ok'):
                raise Exception("Erro ao obter arquivo")
            
            file_path = file_data['result']['file_path']
            
            # Baixar
            download_url = f"https://api.telegram.org/file/bot{self.bot_token}/{file_path}"
            foto_response = requests.get(download_url, timeout=15)
            
            # Salvar
            thumbnail_path = f'{ASSETS_DIR}/thumbnail_custom.jpg'
            with open(thumbnail_path, 'wb') as f:
                f.write(foto_response.content)

        except:
            pass
        
        return None

        print(f"✅ Thumbnail salva: {thumbnail_path}")
        
        # Atualizar status
        with open(thumbnail_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        data['status'] = 'recebida'
        data['thumbnail_path'] = thumbnail_path
        
        with open(thumbnail_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        self.enviar_mensagem("✅ <b>Thumbnail recebida!</b>\n\nContinuando...")
        
    except Exception as e:
        print(f"❌ Erro: {e}")
        self.enviar_mensagem(f"❌ Erro ao processar thumbnail: {e}")

def notificar_publicacao(self, video_info):
    """Notifica publicação"""
    mensagem = (
        f"🎉 <b>VÍDEO PUBLICADO!</b>\n\n"
        f"📺 {video_info['titulo']}\n"
        f"⏱️ {video_info['duracao']:.1f}s\n"
        f"🔗 {video_info['url']}\n\n"
        f"✅ No ar!"
    )
    self.enviar_mensagem(mensagem)
    print("📤 Notificação enviada")
