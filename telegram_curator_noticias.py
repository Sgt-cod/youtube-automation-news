import os
import json
import requests
import time
import sys
from datetime import datetime

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')
CURACAO_FILE = 'curacao_pendente.json'
CURACAO_TEMAS_FILE = 'curacao_temas_pendente.json'
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
    
    # ========================================
    # CURADORIA DE TEMAS (NOVO - VÍDEOS LONGOS)
    # ========================================
    
    def solicitar_curacao_temas(self, noticias, timeout=3600):
        """Solicita curadoria dos temas (notícias) antes de gerar roteiros"""
        print("📋 Iniciando curadoria de TEMAS...")
        
        curacao_data = {
            'timestamp': datetime.now().isoformat(),
            'noticias': noticias,
            'status': 'aguardando',
            'aprovacoes': {},
            'rejeicoes': [],
            'substituicoes': {}
        }
        
        with open(CURACAO_TEMAS_FILE, 'w', encoding='utf-8') as f:
            json.dump(curacao_data, f, indent=2, ensure_ascii=False)
        
        mensagem_inicial = (
            f"🎬 <b>CURADORIA DE TEMAS - VÍDEO LONGO</b>\n\n"
            f"📰 {len(noticias)} notícias encontradas\n"
            f"⏰ {datetime.now().strftime('%H:%M:%S')}\n\n"
            f"<b>Vou enviar cada tema para você aprovar ou substituir.</b>\n\n"
            f"<b>Comandos:</b>\n"
            f"• <b>/aprovar_tudo</b> - Aprovar todos os temas restantes\n"
            f"• <b>/cancelar</b> - Cancelar curadoria\n"
            f"• <b>/status</b> - Ver progresso\n\n"
            f"⏳ Aguardo {timeout//60}min"
        )
        
        self.enviar_mensagem(mensagem_inicial)
        time.sleep(2)
        
        self._enviar_proximo_tema()
        
        print("✅ Primeiro tema enviado para curadoria")
        
        return self._aguardar_aprovacao_temas(timeout)
    
    def _enviar_proximo_tema(self):
        """Envia próximo tema para aprovação"""
        print("🔍 _enviar_proximo_tema() chamado")
        
        if not os.path.exists(CURACAO_TEMAS_FILE):
            print("❌ Arquivo de curadoria não existe!")
            return False
        
        try:
            with open(CURACAO_TEMAS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            print(f"📂 Dados carregados: {len(data['noticias'])} notícias")
            print(f"📊 Aprovações: {data['aprovacoes']}")
            
            noticias = data['noticias']
            aprovacoes = data['aprovacoes']
            
            proximo_indice = None
            for i, noticia in enumerate(noticias):
                if str(i) not in aprovacoes:
                    proximo_indice = i
                    break
            
            if proximo_indice is None:
                print("✅ Todas as notícias já foram aprovadas")
                self._finalizar_curacao_temas()
                return False
            
            noticia = noticias[proximo_indice]
            num = proximo_indice + 1
            total = len(noticias)
            
            print(f"📤 Preparando tema {num}/{total}")
            print(f"   Título: {noticia['titulo'][:50]}...")
            
            resumo = noticia['resumo'][:300] if len(noticia['resumo']) > 300 else noticia['resumo']
            
            mensagem = (
                f"📌 <b>Tema {num}/{total}</b>\n\n"
                f"📰 <b>{noticia['titulo']}</b>\n\n"
                f"📝 <i>{resumo}...</i>\n\n"
                f"<b>Este tema será usado no vídeo?</b>"
            )
            
            keyboard = {
                'inline_keyboard': [
                    [
                        {'text': '✅ Aprovar', 'callback_data': f'tema_aprovar_{num}'},
                        {'text': '🔄 Substituir', 'callback_data': f'tema_substituir_{num}'}
                    ]
                ]
            }
            
            print(f"📨 Enviando mensagem com botões...")
            resultado = self.enviar_mensagem(mensagem, keyboard)
            
            if resultado:
                print(f"✅ Tema {num}/{total} enviado com sucesso!")
                return True
            else:
                print(f"❌ Falha ao enviar tema {num}/{total}")
                print(f"   Mensagem tinha {len(mensagem)} caracteres")
                return False
                
        except Exception as e:
            print(f"❌ ERRO em _enviar_proximo_tema(): {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _finalizar_curacao_temas(self):
        """Finaliza curadoria de temas"""
        if not os.path.exists(CURACAO_TEMAS_FILE):
            return
        
        with open(CURACAO_TEMAS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        data['status'] = 'aprovado'
        
        with open(CURACAO_TEMAS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        aprovados = len(data['aprovacoes'])
        substituidos = len(data['substituicoes'])
        
        self.enviar_mensagem(
            f"🎉 <b>CURADORIA DE TEMAS CONCLUÍDA!</b>\n\n"
            f"✅ {aprovados} temas aprovados\n"
            f"🔄 {substituidos} temas substituídos\n\n"
            f"📝 Agora vou gerar os roteiros segmentados...\n"
            f"⏳ Em seguida, vem a curadoria de mídias"
        )
        
        print("✅ Curadoria de temas finalizada")
    
    def _aguardar_aprovacao_temas(self, timeout):
        """Aguarda aprovação dos temas"""
        print(f"⏳ Aguardando aprovação de temas...")
        print(f"⏰ Timeout: {timeout}s ({timeout//60}min)")
        
        inicio = time.time()
        ultima_verificacao = 0
        
        while True:
            tempo_decorrido = time.time() - inicio
            
            if tempo_decorrido >= timeout:
                print(f"⏰ Timeout após {tempo_decorrido/60:.1f}min")
                
                if os.path.exists(CURACAO_TEMAS_FILE):
                    with open(CURACAO_TEMAS_FILE, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    data['status'] = 'timeout'
                    
                    with open(CURACAO_TEMAS_FILE, 'w', encoding='utf-8') as f:
                        json.dump(data, f, indent=2, ensure_ascii=False)
                    
                    self.enviar_mensagem(
                        f"⏰ <b>TIMEOUT NA CURADORIA DE TEMAS</b>\n\n"
                        f"Aguardei {timeout//60}min sem resposta.\n"
                        f"Curadoria cancelada."
                    )
                
                return None
            
            if int(tempo_decorrido) % 60 == 0 and tempo_decorrido != ultima_verificacao:
                minutos = int(tempo_decorrido / 60)
                restantes = int((timeout - tempo_decorrido) / 60)
                print(f"⏱️ {minutos}min | {restantes}min restantes")
                ultima_verificacao = tempo_decorrido
            
            if os.path.exists(CURACAO_TEMAS_FILE):
                with open(CURACAO_TEMAS_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                if data['status'] == 'aprovado':
                    print("✅ Temas aprovados!")
                    
                    noticias_aprovadas = []
                    
                    for i, noticia in enumerate(data['noticias']):
                        if str(i) in data['aprovacoes']:
                            if str(i) in data['substituicoes']:
                                noticias_aprovadas.append(data['substituicoes'][str(i)])
                            else:
                                noticias_aprovadas.append(noticia)
                    
                    print(f"✅ {len(noticias_aprovadas)} temas finais")
                    
                    try:
                        os.remove(CURACAO_TEMAS_FILE)
                    except:
                        pass
                    
                    return noticias_aprovadas
                
                elif data['status'] == 'cancelado':
                    print("❌ Curadoria cancelada")
                    self.enviar_mensagem("🛑 <b>CURADORIA CANCELADA</b>")
                    sys.exit(1)
            
            self._processar_atualizacoes_temas()
            time.sleep(3)
    
    def _processar_atualizacoes_temas(self):
        """Processa updates do Telegram para curadoria de temas"""
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
            
            if updates:
                print(f"📨 {len(updates)} updates recebidos para temas")
            
            for update in updates:
                self.update_id_offset = update['update_id'] + 1
                
                if 'callback_query' in update:
                    print(f"   🔔 Callback detectado: {update['callback_query']['data']}")
                
                if 'message' in update:
                    self._processar_mensagem_temas(update['message'])
                elif 'callback_query' in update:
                    self._processar_callback_temas(update['callback_query'])
        except Exception as e:
            print(f"⚠️ Erro ao processar updates de temas: {e}")
    
    def _processar_mensagem_temas(self, message):
        """Processa mensagens na curadoria de temas"""
        text = message.get('text', '')
        
        if not os.path.exists(CURACAO_TEMAS_FILE):
            return
        
        with open(CURACAO_TEMAS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        print(f"📩 Comando: {text}")
        
        if text == '/cancelar':
            print("🛑 CANCELAR CURADORIA")
            data['status'] = 'cancelado'
            
            with open(CURACAO_TEMAS_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            self.enviar_mensagem(
                "🛑 <b>CANCELAMENTO TOTAL</b>\n\n"
                "❌ Curadoria cancelada\n"
                "❌ Vídeo cancelado"
            )
        
        elif text == '/status':
            total = len(data['noticias'])
            aprovados = len(data['aprovacoes'])
            substituidos = len(data['substituicoes'])
            
            self.enviar_mensagem(
                f"📊 <b>STATUS DA CURADORIA DE TEMAS</b>\n\n"
                f"📰 Total de temas: {total}\n"
                f"✅ Aprovados: {aprovados}\n"
                f"🔄 Substituídos: {substituidos}\n"
                f"⏳ Pendentes: {total - aprovados}\n\n"
                f"Status: {data['status']}"
            )
        
        elif text == '/aprovar_tudo':
            print("⏭️ Aprovar todos os temas restantes")
            
            for i in range(len(data['noticias'])):
                if str(i) not in data['aprovacoes']:
                    data['aprovacoes'][str(i)] = 'aprovado'
            
            data['status'] = 'aprovado'
            
            with open(CURACAO_TEMAS_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            self.enviar_mensagem("✅ <b>Todos os temas restantes aprovados!</b>")
        
        elif text.startswith('/substituir_'):
            try:
                partes = text.split(' ', 1)
                if len(partes) >= 2:
                    numero_parte = partes[0].replace('/substituir_', '')
                    indice = int(numero_parte) - 1
                    novo_titulo = partes[1].strip()
                    
                    if 0 <= indice < len(data['noticias']):
                        nova_noticia = {
                            'titulo': novo_titulo,
                            'resumo': f"Tema customizado pelo usuário: {novo_titulo}",
                            'link': ''
                        }
                        
                        data['substituicoes'][str(indice)] = nova_noticia
                        data['aprovacoes'][str(indice)] = 'substituido'
                        
                        with open(CURACAO_TEMAS_FILE, 'w', encoding='utf-8') as f:
                            json.dump(data, f, indent=2, ensure_ascii=False)
                        
                        self.enviar_mensagem(
                            f"✅ <b>Tema {indice+1} substituído!</b>\n\n"
                            f"🆕 {novo_titulo}"
                        )
                        
                        time.sleep(1)
                        self._enviar_proximo_tema()
                    else:
                        self.enviar_mensagem(f"❌ Índice {indice+1} inválido")
                else:
                    self.enviar_mensagem(
                        "❌ Formato incorreto.\n\n"
                        "<b>Use:</b> <code>/substituir_N Novo título</code>\n\n"
                        "<b>Exemplo:</b> <code>/substituir_1 Reforma tributária avança</code>"
                    )
            except Exception as e:
                print(f"Erro ao processar substituição: {e}")
                self.enviar_mensagem(
                    "❌ Erro ao processar.\n\n"
                    "<b>Formato correto:</b>\n"
                    "<code>/substituir_1 Novo título aqui</code>"
                )
    
    def _processar_callback_temas(self, callback):
        """Processa botões na curadoria de temas"""
        callback_data = callback['data']
        callback_id = callback['id']
        
        if not os.path.exists(CURACAO_TEMAS_FILE):
            self._responder_callback(callback_id, "⚠️ Expirado")
            return
        
        with open(CURACAO_TEMAS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        print(f"🖱️ Botão TEMAS: {callback_data}")
        
        self._responder_callback(callback_id, "✅ Processando...")
        
        try:
            if callback_data.startswith('tema_aprovar_'):
                num = int(callback_data.split('_')[2])
                self._aprovar_tema(data, num)
            
            elif callback_data.startswith('tema_substituir_'):
                num = int(callback_data.split('_')[2])
                self._solicitar_substituicao_tema(data, num)
            
            else:
                print(f"⚠️ Callback desconhecido: {callback_data}")
                
        except Exception as e:
            print(f"❌ Erro ao processar callback de tema: {e}")
            import traceback
            traceback.print_exc()
    
    def _aprovar_tema(self, data, num):
        """Aprova um tema"""
        idx = num - 1
        total = len(data['noticias'])
        
        print(f"✅ Aprovar tema {num}/{total}")
        
        data['aprovacoes'][str(idx)] = 'aprovado'
        
        with open(CURACAO_TEMAS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        self.enviar_mensagem(f"✅ <b>Tema {num} aprovado!</b>")
        
        time.sleep(1)
        self._enviar_proximo_tema()
    
    def _solicitar_substituicao_tema(self, data, num):
        """Solicita substituição de tema"""
        idx = num - 1
        
        print(f"🔄 Solicitar substituição tema {num}")
        
        self.enviar_mensagem(
            f"🔄 <b>Substituir Tema {num}</b>\n\n"
            f"Digite o NOVO tema que deseja:\n\n"
            f"<b>Formato:</b>\n"
            f"<code>/substituir_{num} Seu novo título aqui</code>\n\n"
            f"<b>Exemplo:</b>\n"
            f"<code>/substituir_{num} Reforma tributária avança no Senado</code>"
        )
    
    # ========================================
    # CURADORIA DE MÍDIAS (ORIGINAL)
    # ========================================
    
    def solicitar_curacao(self, segmentos_com_midias):
        """Inicia curadoria interativa DE MÍDIAS"""
        print("📱 Iniciando curadoria de MÍDIAS...")
        
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
            f"🎬 <b>CURADORIA DE MÍDIAS</b>\n\n"
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
        print("✅ Primeira mídia enviada para curadoria")
    
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
        
        caption = (
            f"📌 <b>Segmento {num}/{total}</b>\n\n"
            f"📝 <i>\"{texto_seg}...\"</i>\n\n"
            f"🔍 Keywords: {', '.join(keywords)}\n"
            f"📁 Pasta: {self._extrair_pasta(midia_info)}\n\n"
            f"<i>Se travar, use /retomar</i>"
        )
        
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
            f"🎉 <b>CURADORIA DE MÍDIAS CONCLUÍDA!</b>\n\n"
            f"✅ Todos os {len(data['segmentos'])} segmentos aprovados!\n"
            f"🎥 Criando e publicando vídeo...\n\n"
            f"Aguarde o link!"
        )
        
        print("✅ Curadoria de mídias finalizada")
    
    def aguardar_aprovacao(self, timeout=3600):
        """Aguarda aprovação"""
        print(f"⏳ Aguardando aprovação de mídias...")
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
            
            if int(tempo_decorrido) % 60 == 0 and tempo_decorrido != ultima_verificacao:
                minutos = int(tempo_decorrido / 60)
                restantes = int((timeout - tempo_decorrido) / 60)
                print(f"⏱️ {minutos}min | {restantes}min restantes")
                ultima_verificacao = tempo_decorrido
            
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
                
                if data['status'] == 'aprovado':
                    print("✅ Mídias aprovadas!")
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
    
    def _processar_callback(self, callback):
        """Processa botões"""
        callback_data = callback['data']
        callback_id = callback['id']
        
        if callback_data.startswith('tema_'):
            if os.path.exists(CURACAO_TEMAS_FILE):
                self._processar_callback_temas(callback)
            else:
                self._responder_callback(callback_id, "⚠️ Curadoria de temas expirada")
            return
        
        if not os.path.exists(CURACAO_FILE):
            self._responder_callback(callback_id, "⚠️ Expirado")
            return
        
        with open(CURACAO_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        print(f"🖱️ Botão MÍDIAS: {callback_data}")
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
    
    def _processar_mensagem(self, message):
        """Processa mensagens"""
        text = message.get('text', '')
        
        if os.path.exists(CURACAO_TEMAS_FILE):
            self._processar_mensagem_temas(message)
            return
        
        if not os.path.exists(CURACAO_FILE):
            if text == '/start':
                self.enviar_mensagem(
                    "👋 <b>Curador de Notícias</b>\n\n"
                    "Enviarei temas e mídias para você aprovar.\n"
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
            thumbnail_file = 'thumbnail_pendente.json'
            
            if os.path.exists(thumbnail_file):
                print("⏭️ Pular thumbnail")
                with open(thumbnail_file, 'r', encoding='utf-8') as f:
                    thumb_data = json.load(f)
                
                thumb_data['status'] = 'pulada'
                
                with open(thumbnail_file, 'w', encoding='utf-8') as f:
                    json.dump(thumb_data, f, indent=2, ensure_ascii=False)
                
                self.enviar_mensagem("⏭️ <b>Usando thumbnail automática</b>")
            
            elif os.path.exists(CURACAO_FILE):
                print("⏭️ Pular curadoria de mídias")
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
        
        elif 'photo' in message:
            thumbnail_file = 'thumbnail_pendente.json'
            
            if os.path.exists(thumbnail_file):
                self._processar_thumbnail(message)
            elif os.path.exists(CURACAO_FILE):
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
            photo = message['photo'][-1]
            file_id = photo['file_id']
            
            file_info_url = f"{self.base_url}/getFile?file_id={file_id}"
            file_response = requests.get(file_info_url, timeout=10)
            file_data = file_response.json()
            
            if not file_data.get('ok'):
                raise Exception("Erro ao obter info do arquivo")
            
            file_path = file_data['result']['file_path']
            download_url = f"https://api.telegram.org/file/bot{self.bot_token}/{file_path}"
            
            foto_response = requests.get(download_url, timeout=15)
            foto_filename = f'{ASSETS_DIR}/custom_{num}.jpg'
            
            with open(foto_filename, 'wb') as f:
                f.write(foto_response.content)
            
            print(f"✅ Foto salva: {foto_filename}")
            
            seg = data['segmentos'][idx]
            seg['midia'] = (foto_filename, 'foto_local')
            seg['customizado'] = True
            
            data['segmentos'][idx] = seg
            data['aprovacoes'][str(idx)] = 'aprovado'
            
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
            
            arquivos = [f for f in os.listdir(pasta)
                       if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
            
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
    
    # ========================================
    # CURADORIA DE THUMBNAIL
    # ========================================
    
    def solicitar_thumbnail(self, titulo, timeout=1200):
        """Solicita thumbnail customizada"""
        print("🖼️ Solicitando thumbnail...")
        
        thumbnail_file = 'thumbnail_pendente.json'
        
        data = {
            'titulo': titulo,
            'status': 'aguardando',
            'thumbnail_path': None,
            'timestamp': datetime.now().isoformat()
        }
        
        with open(thumbnail_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
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
        
        inicio = time.time()
        ultimo_aviso = 0
        
        while time.time() - inicio < timeout:
            tempo_decorrido = time.time() - inicio
            
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
            
            self._processar_atualizacoes()
            time.sleep(3)
        
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
            photo = message['photo'][-1]
            file_id = photo['file_id']
            
            file_info_url = f"{self.base_url}/getFile?file_id={file_id}"
            file_response = requests.get(file_info_url, timeout=10)
            file_data = file_response.json()
            
            if not file_data.get('ok'):
                raise Exception("Erro ao obter arquivo")
            
            file_path = file_data['result']['file_path']
            download_url = f"https://api.telegram.org/file/bot{self.bot_token}/{file_path}"
            
            foto_response = requests.get(download_url, timeout=15)
            thumbnail_path = f'{ASSETS_DIR}/thumbnail_custom.jpg'
            
            with open(thumbnail_path, 'wb') as f:
                f.write(foto_response.content)
            
            print(f"✅ Thumbnail salva: {thumbnail_path}")
            
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
