import json
import time
import threading
import numpy as np
import paho.mqtt.client as mqtt
from xmlrpc.server import SimpleXMLRPCServer
import xmlrpc.client
import socket
from datetime import datetime
import tkinter as tk
from tkinter import ttk

BROKER = "test.mosquitto.org"
DISTANCIA_LIMITE = 200  # metros
TOPICO_GERAL = "users/onlinee"  # Tópico onde todos publicam suas informações
TOPICO_MENSAGENS = "messages"  # Base para mensagens pendentes
TOPICO_RECEBE = "recebe"

class ClienteChat:
    def __init__(self, root):
        self.root = root
        self.root.title("Location Based Chat")
        self.root.geometry("600x800")

        self.username = tk.StringVar()
        self.latitude = tk.DoubleVar()
        self.longitude = tk.DoubleVar()
        self.porta_rpc = tk.IntVar(value=8000)  
        # self.localizacao = np.array([self.latitude.get(), self.longitude.get()])
        self.usuarios = {}  # {username: (latitude, longitude, ip, porta_rpc)}
        # self.porta_rpc = 8000 + np.random.randint(100)
        self.mensagens_acumuladas = {}  # {destinatario: "timestamp | msg1\n timestamp | msg2\n ..."}
        self.mensagens = []  # Histórico de mensagens
        self.ip_local = tk.StringVar(value=obter_ip_local())

        # Interface Gráfica
        self.criar_interface()
    
    def criar_interface(self):
        """Cria a interface gráfica."""
        frame_top = tk.Frame(self.root, padx=10, pady=10)
        frame_top.pack(fill="x")

        tk.Label(frame_top, text="Nome:", font=("Arial", 10)).grid(row=0, column=0)
        self.entry_username = tk.Entry(frame_top, textvariable=self.username)
        self.entry_username.grid(row=0, column=1)

        tk.Label(frame_top, text="IP:", font=("Arial", 10)).grid(row=1, column=0)
        self.entry_ip = tk.Entry(frame_top, textvariable=self.ip_local)
        self.entry_ip.grid(row=1, column=1)
        self.entry_ip.config(state='disabled')

        tk.Label(frame_top, text="Porta RPC:", font=("Arial", 10)).grid(row=2, column=0)
        self.entry_porta = tk.Entry(frame_top, textvariable=self.porta_rpc)
        self.entry_porta.grid(row=2, column=1)

        tk.Label(frame_top, text="Latitude:", font=("Arial", 10)).grid(row=3, column=0)
        tk.Entry(frame_top, textvariable=self.latitude).grid(row=3, column=1)

        tk.Label(frame_top, text="Longitude:", font=("Arial", 10)).grid(row=4, column=0)
        tk.Entry(frame_top, textvariable=self.longitude).grid(row=4, column=1)

        self.botao_iniciar = tk.Button(frame_top, text="Iniciar", command=self.iniciar_ou_editar)
        self.botao_iniciar.grid(row=5, column=1)

        frame_mid = tk.Frame(self.root, padx=10, pady=10)
        frame_mid.pack(fill="x")

        tk.Label(frame_mid, text="Usuários Próximos:", font=("Arial", 10)).pack(anchor="w")
        self.combobox_usuarios = ttk.Combobox(frame_mid, state="readonly", width=50)
        self.combobox_usuarios.pack(pady=5, anchor="w")

        tk.Label(frame_mid, text="Mensagem:", font=("Arial", 10)).pack(anchor="w")
        self.entry_msg = tk.Entry(frame_mid, width=50)
        self.entry_msg.pack(pady=5, anchor="w")

        tk.Button(frame_mid, text="Enviar", command=self.enviar_mensagem_gui).pack(anchor="w")

        frame_bottom = tk.Frame(self.root, padx=10, pady=10)
        frame_bottom.pack(fill="both", expand=True)

        tk.Label(frame_bottom, text="Histórico do Chat:", font=("Arial", 10)).pack(anchor="w")

        self.text_chat = tk.Text(frame_bottom, height=10, width=70, wrap="word")
        self.text_chat.pack(fill="both", expand=True, pady=5)
        # Estilização das mensagens enviadas (verde, alinhada à direita)
        self.text_chat.tag_config("SENT", foreground="green", justify="right")
        self.text_chat.tag_config("PENDING", foreground="yellow", justify="right")

        # Estilização das mensagens recebidas (preto, alinhada à esquerda - padrão)
        self.text_chat.tag_config("RECEIVED", foreground="white", justify="left")
        self.text_chat.tag_config("MOM", foreground="yellow", justify="left")

        scrollbar = ttk.Scrollbar(frame_bottom, command=self.text_chat.yview)
        scrollbar.pack(side="right", fill="y")
        self.text_chat.config(yscrollcommand=scrollbar.set)

        tk.Button(self.root, text="Refresh", command=self.monitorar_vizinhos).pack(pady=5)

    def iniciar_ou_editar(self):
        # Verifica se o botão foi clicado pela primeira vez (Iniciar)
        if self.botao_iniciar['text'] == "Iniciar":
            # Desativa os campos Nome, IP e Porta
            self.entry_username.config(state='disabled')
            self.entry_ip.config(state='disabled')
            self.entry_porta.config(state='disabled')
            
            # Altera o nome do botão para "Editar"
            self.botao_iniciar.config(text="Editar")

            self.iniciar()
        else:
            # Caso seja a opção "Editar", chama a função para publicar a localização
            self.publicar_localizacao()
    
    def iniciar(self):
        # Conectar ao broker MQTT
        self.client = mqtt.Client()
        self.client.on_message = self.on_message
        self.client.connect(BROKER)

        # Assinar tópicos
        self.client.subscribe(TOPICO_GERAL)
        self.client.subscribe(f"{TOPICO_MENSAGENS}/{self.username.get()}")  # Mensagens pendentes
        self.client.subscribe(f"{self.username.get()}/{TOPICO_RECEBE}")
        self.client.loop_start()

        self.publicar_localizacao()
        threading.Thread(target=self.iniciar_servidor_rpc, daemon=True).start()
        threading.Thread(target=self.refresh_a_cada_2min, daemon=True).start()

    def iniciar_servidor_rpc(self):
        servidor = SimpleXMLRPCServer(("0.0.0.0", self.porta_rpc.get()), allow_none=True)
        servidor.register_function(self.receber_mensagem, "receber_mensagem")
        print(f"📡 Servidor XML-RPC iniciado na porta {self.porta_rpc.get()}")
        servidor.serve_forever()

    def receber_mensagem(self, usuario, mensagem, timestamp, tipo=None):
        """Recebe mensagens via XML-RPC e as exibe no chat."""
        if tipo == "RECEIVED":
            msg_formatada = f"{timestamp} - [RECEIVED] - {usuario}: {mensagem}"
        elif tipo == "SENT":
            msg_formatada = f"{mensagem} :{usuario} - [SENT] - {timestamp}"
        elif tipo == "PENDING":
            msg_formatada = f"{mensagem} :{usuario} - [PENDING] - {timestamp}"
        elif tipo == "MOM":
             msg_formatada = f"{timestamp} - [MOM] - {usuario}: {mensagem}"
        else:
            msg_formatada = f"{timestamp} - [INFO]: {mensagem}"

        if msg_formatada not in self.mensagens:
            self.mensagens.append(msg_formatada)
        self.atualizar_chat()
        return True

    def enviar_mensagem(self, destinatario, mensagem):
        """Envia mensagem via XML-RPC ou armazena no MQTT acumulando mensagens com timestamp."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")  # Gera timestamp

        if destinatario in self.usuarios:
            distancia = self.distancia(self.usuarios[destinatario][:2])

            if distancia <= DISTANCIA_LIMITE:
                ip_destino = self.usuarios[destinatario][2]
                porta_destino = self.usuarios[destinatario][3]
                try:
                    proxy = xmlrpc.client.ServerProxy(f"http://{ip_destino}:{porta_destino}/")
                    proxy.receber_mensagem(self.username.get(), mensagem, timestamp, "RECEIVED")
                    print(f"✅ {timestamp} - Mensagem enviada para {destinatario}: {mensagem}")

                    self.receber_mensagem(destinatario, mensagem, timestamp, "SENT")
                except Exception as e:
                    print(f"⚠️ {timestamp} - Erro ao enviar mensagem para {destinatario}: {e}")
                    self.armazenar_mensagem_mom(destinatario, mensagem, timestamp)
            else:
                print(f"⚠️ {timestamp} - {destinatario} está fora da zona de visão! Armazenando mensagem.")
                self.armazenar_mensagem_mom(destinatario, mensagem, timestamp)
        else:
            print(f"⚠️ {timestamp} - Destinatário {destinatario} não encontrado!")

    def enviar_mensagem_gui(self):
        """Função chamada ao clicar no botão de Enviar."""
        destinatario_selecionado = self.combobox_usuarios.get()

        if not destinatario_selecionado:
            print("⚠️ Nenhum destinatário selecionado!")
            return

        # Extrai apenas o nome do usuário (remove a parte " (100.00m)")
        destinatario = destinatario_selecionado.split(" ")[0]

        mensagem = self.entry_msg.get().strip()

        if not mensagem:
            print("⚠️ Mensagem vazia!")
            return

        # Chama a função original de envio de mensagens
        self.enviar_mensagem(destinatario, mensagem)

        # Limpa a caixa de texto após o envio
        self.entry_msg.delete(0, tk.END)

    def atualizar_chat(self):
        """Atualiza a caixa de texto do chat, formatando as mensagens."""
        self.text_chat.config(state=tk.NORMAL)  # Permite edição temporária
        self.text_chat.delete(1.0, tk.END)  # Limpa a caixa de texto

        for mensagem in self.mensagens:
            if "[SENT]" in mensagem:  # Se for uma mensagem enviada (contém "→")
                self.text_chat.insert(tk.END, mensagem + "\n", "SENT")
            elif "[PENDING]" in mensagem:  # Se for uma mensagem enviada (contém "→")
                self.text_chat.insert(tk.END, mensagem + "\n", "PENDING")
            elif "[MOM]" in mensagem:  # Se for uma mensagem enviada (contém "→")
                self.text_chat.insert(tk.END, mensagem + "\n", "MOM")
            else:  # Se for uma mensagem recebida
                self.text_chat.insert(tk.END, mensagem + "\n", "RECEIVED")

        self.text_chat.config(state=tk.DISABLED)  # Bloqueia edição
        self.text_chat.yview(tk.END)  # Rola para a última mensagem

    def armazenar_mensagem_mom(self, destinatario, mensagem, timestamp):
        """Recupera mensagens anteriores e acumula antes de publicar, incluindo timestamp."""
        print("chamou armazenar msg mom")
        print(self.mensagens_acumuladas)
        topico_mensagem = f"{TOPICO_MENSAGENS}/{destinatario}"

        # Nova mensagem formatada com timestamp
        nova_mensagem = f"{timestamp} | {mensagem}"

        # Se já houver mensagens acumuladas, recupera e concatena
        ultima_mensagem = self.mensagens_acumuladas.get(destinatario, "")
        mensagem_acumulada = f"{ultima_mensagem}\n{nova_mensagem}" if ultima_mensagem else nova_mensagem

        # Atualiza o cache local
        self.mensagens_acumuladas[destinatario] = mensagem_acumulada

        # Publica mensagem acumulada com retain=True
        payload = json.dumps({"remetente": self.username.get(), "mensagem": mensagem_acumulada})
        self.client.publish(topico_mensagem, payload, retain=True)
        self.receber_mensagem(destinatario, mensagem, timestamp, "PENDING")

    def buscar_mensagens_pendentes(self):
        """Verifica mensagens pendentes quando o usuário volta para a área."""
        self.client.subscribe(f"{TOPICO_MENSAGENS}/{self.username.get()}")  # Busca mensagens
        time.sleep(5)  # Pequeno delay para garantir que mensagens cheguem
        self.client.unsubscribe(f"{TOPICO_MENSAGENS}/{self.username.get()}")  # Depois se desinscreve

    def publicar_localizacao(self, topico = TOPICO_GERAL):
        """Publica localização e IP via MQTT com retain=True."""
        payload = json.dumps({
            "username": self.username.get(),
            "latitude": self.latitude.get(),
            "longitude": self.longitude.get(),
            "ip": obter_ip_local(),
            "port": self.porta_rpc.get()
        })
        print(f"📤 Publicando localização no tópico {topico}: {payload}")
        self.client.publish(topico, payload)
        # self.monitorar_vizinhos()

    def monitorar_vizinhos(self):
        """Atualiza vizinhos e verifica mensagens pendentes."""
        print("\n🔄 Atualizando distâncias:")

        for user, (lat, lon, ip, port) in self.usuarios.items():
            distancia = self.distancia((lat, lon))
            status = "✅ Dentro da zona" if distancia <= DISTANCIA_LIMITE else "❌ Fora da zona"
            print(f"   - {user} ({ip}:{port}): {distancia:.2f}m ({status})")

            # Se o usuário voltou para a zona, buscar mensagens pendentes
            if distancia <= DISTANCIA_LIMITE:
                print(f"📨 {user} está na área! Buscando mensagens pendentes...")
                self.buscar_mensagens_pendentes()
        self.atualizar_usuarios_combobox()
    
    def refresh_a_cada_2min(self):
        while True:
            time.sleep(120)
            self.monitorar_vizinhos()

    def distancia(self, localizacao):
        return np.linalg.norm(np.array([self.latitude.get(), self.longitude.get()]) - np.array(localizacao)) * 111139

    def atualizar_usuarios_combobox(self):
        """Atualiza a lista de usuários disponíveis no Combobox."""
        lista_usuarios = [f"{user} ({self.distancia((lat, lon)):.2f}m)"
                          for user, (lat, lon, _, _) in self.usuarios.items()]
        
        self.combobox_usuarios["values"] = lista_usuarios

    def on_message(self, client, userdata, msg):
        """Processa mensagens MQTT recebidas no tópico geral e nas mensagens acumuladas."""
        try:
            payload = json.loads(msg.payload.decode())

            if msg.topic.startswith(TOPICO_GERAL):
                username = payload.get("username")
                latitude = payload.get("latitude")
                longitude = payload.get("longitude")
                ip = payload.get("ip")
                porta_rpc = payload.get("port")

                if None in (username, latitude, longitude, ip, porta_rpc):
                    print(f"⚠️ Mensagem inválida: {payload}")
                    return

                if username != self.username.get():
                    self.usuarios[username] = (latitude, longitude, ip, porta_rpc)
                    print(f"✅ {username} foi adicionado!")
                    self.publicar_localizacao(f"{username}/{TOPICO_RECEBE}")
                    # self.publicar_localizacao()

                self.monitorar_vizinhos()

            elif msg.topic.startswith(f"{TOPICO_MENSAGENS}/{self.username.get()}"):
                remetente = payload.get("remetente")
                mensagem = payload.get("mensagem")
                if remetente and mensagem:
                    msg = mensagem.split("|")
                    self.receber_mensagem(remetente, msg[1].strip(), msg[0].strip(), "MOM")
            elif msg.topic.startswith(f"{self.username.get()}/{TOPICO_RECEBE}"):
                username = payload.get("username")
                latitude = payload.get("latitude")
                longitude = payload.get("longitude")
                ip = payload.get("ip")
                porta_rpc = payload.get("port")

                if None in (username, latitude, longitude, ip, porta_rpc):
                    print(f"⚠️ Mensagem inválida: {payload}")
                    return

                if username != self.username.get():
                    self.usuarios[username] = (latitude, longitude, ip, porta_rpc)
                    print(f"✅ {username} foi adicionado!")
                    self.monitorar_vizinhos()

        except Exception as e:
            print(f"Erro ao processar mensagem: {e}")

def obter_ip_local():
    """Obtém o IP local correto."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip_local = s.getsockname()[0]
        s.close()
        return ip_local
    except:
        return "127.0.0.1"

if __name__ == "__main__":
    root = tk.Tk()
    app = ClienteChat(root)
    root.mainloop()