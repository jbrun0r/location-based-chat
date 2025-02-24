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
TOPICO_GERAL = "users/online"  # Tópico onde todos publicam suas informações
TOPICO_MENSAGENS = "messages"  # Base para mensagens pendentes

class ClienteChat:
    def __init__(self, root):
        self.root = root
        self.root.title("Chat de Proximidade")
        self.root.geometry("600x500")

        self.username = tk.StringVar()
        self.latitude = tk.DoubleVar()
        self.longitude = tk.DoubleVar()
        self.localizacao = np.array([self.latitude.get(), self.longitude.get()])
        self.usuarios = {}  # {username: (latitude, longitude, ip, porta_rpc)}
        self.porta_rpc = 8000 + np.random.randint(100)
        self.mensagens_acumuladas = {}  # {destinatario: "timestamp | msg1\n timestamp | msg2\n ..."}
        self.mensagens = []  # Histórico de mensagens
        self.ip_local = obter_ip_local()

        # Interface Gráfica
        self.criar_interface()
    
    def criar_interface(self):
        """Cria a interface gráfica."""
        frame_top = tk.Frame(self.root, padx=10, pady=10)
        frame_top.pack(fill="x")

        tk.Label(frame_top, text="Nome:", font=("Arial", 10)).grid(row=0, column=0)
        tk.Entry(frame_top, textvariable=self.username).grid(row=0, column=1)

        tk.Label(frame_top, text="IP Local:", font=("Arial", 10)).grid(row=1, column=0)
        tk.Label(frame_top, text=f"{self.ip_local}:{self.porta_rpc}", font=("Arial", 10, "bold")).grid(row=1, column=1)

        tk.Label(frame_top, text="Latitude:", font=("Arial", 10)).grid(row=2, column=0)
        tk.Entry(frame_top, textvariable=self.latitude).grid(row=2, column=1)

        tk.Label(frame_top, text="Longitude:", font=("Arial", 10)).grid(row=3, column=0)
        tk.Entry(frame_top, textvariable=self.longitude).grid(row=3, column=1)

        tk.Button(frame_top, text="Iniciar", command=self.iniciar).grid(row=4, column=1)

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

        # Estilização das mensagens recebidas (preto, alinhada à esquerda - padrão)
        self.text_chat.tag_config("RECEIVED", foreground="black", justify="left")


        scrollbar = ttk.Scrollbar(frame_bottom, command=self.text_chat.yview)
        scrollbar.pack(side="right", fill="y")
        self.text_chat.config(yscrollcommand=scrollbar.set)

        tk.Button(self.root, text="🔄 Refresh", command=self.print_users).pack(pady=5)

    
    def iniciar(self):
        # Conectar ao broker MQTT
        self.client = mqtt.Client()
        self.client.on_message = self.on_message
        self.client.connect(BROKER)

        # Assinar tópicos
        self.client.subscribe(TOPICO_GERAL)
        self.client.subscribe(f"{TOPICO_MENSAGENS}/{self.username}")  # Mensagens pendentes
        self.client.loop_start()

        self.publicar_localizacao()
        threading.Thread(target=self.iniciar_servidor_rpc, daemon=True).start()
        threading.Thread(target=self.monitorar_vizinhos, daemon=True).start()

    def iniciar_servidor_rpc(self):
        servidor = SimpleXMLRPCServer(("0.0.0.0", self.porta_rpc), allow_none=True)
        servidor.register_function(self.receber_mensagem, "receber_mensagem")
        print(f"📡 Servidor XML-RPC iniciado na porta {self.porta_rpc}")
        servidor.serve_forever()

    def receber_mensagem(self, remetente, mensagem, timestamp):
        """Recebe mensagens via XML-RPC e as exibe no chat."""
        msg_formatada = f"{timestamp} - {remetente}: {mensagem}"
        print(msg_formatada)
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

                print(ip_destino)
                print(porta_destino)

                try:
                    proxy = xmlrpc.client.ServerProxy(f"http://{ip_destino}:{porta_destino}/")
                    proxy.receber_mensagem(self.username.get(), mensagem, timestamp)
                    print(f"✅ {timestamp} - Mensagem enviada para {destinatario}: {mensagem}")

                    # Adiciona mensagem ao histórico
                    msg_formatada = f"{mensagem} :{destinatario} ⬅ Você - {timestamp}"
                    self.mensagens.append(msg_formatada)
                    self.atualizar_chat()
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
            if "⬅ Você" in mensagem:  # Se for uma mensagem enviada (contém "→")
                self.text_chat.insert(tk.END, mensagem + "\n", "SENT")
            else:  # Se for uma mensagem recebida
                self.text_chat.insert(tk.END, mensagem + "\n", "RECEIVED")

        self.text_chat.config(state=tk.DISABLED)  # Bloqueia edição
        self.text_chat.yview(tk.END)  # Rola para a última mensagem



    def armazenar_mensagem_mom(self, destinatario, mensagem, timestamp):
        """Recupera mensagens anteriores e acumula antes de publicar, incluindo timestamp."""
        topico_mensagem = f"{TOPICO_MENSAGENS}/{destinatario}"

        # Nova mensagem formatada com timestamp
        nova_mensagem = f"{timestamp} | {mensagem}"

        # Se já houver mensagens acumuladas, recupera e concatena
        ultima_mensagem = self.mensagens_acumuladas.get(destinatario, "")
        mensagem_acumulada = f"{ultima_mensagem}\n{nova_mensagem}" if ultima_mensagem else nova_mensagem

        # Atualiza o cache local
        self.mensagens_acumuladas[destinatario] = mensagem_acumulada

        # Publica mensagem acumulada com retain=True
        payload = json.dumps({"remetente": self.username, "mensagem": mensagem_acumulada})
        self.client.publish(topico_mensagem, payload, retain=True)

    def buscar_mensagens_pendentes(self):
        """Verifica mensagens pendentes quando o usuário volta para a área."""
        self.client.subscribe(f"{TOPICO_MENSAGENS}/{self.username}")  # Busca mensagens
        time.sleep(2)  # Pequeno delay para garantir que mensagens cheguem
        self.client.unsubscribe(f"{TOPICO_MENSAGENS}/{self.username}")  # Depois se desinscreve

    def publicar_localizacao(self):
        """Publica localização e IP via MQTT com retain=True."""
        payload = json.dumps({
            "username": self.username.get(),
            "latitude": self.latitude.get(),
            "longitude": self.longitude.get(),
            "ip": obter_ip_local(),
            "port": self.porta_rpc
        })
        print(f"📤 Publicando localização no tópico geral: {payload}")
        self.client.publish(TOPICO_GERAL, payload, retain=True)

    def monitorar_vizinhos(self):
        """Atualiza vizinhos e verifica mensagens pendentes."""
        while True:
            time.sleep(30)
            print("\n🔄 Atualizando distâncias:")

            for user, (lat, lon, ip, port) in self.usuarios.items():
                distancia = self.distancia((lat, lon))
                status = "✅ Dentro da zona" if distancia <= DISTANCIA_LIMITE else "❌ Fora da zona"
                print(f"   - {user} ({ip}:{port}): {distancia:.2f}m ({status})")

                # Se o usuário voltou para a zona, buscar mensagens pendentes
                if distancia <= DISTANCIA_LIMITE:
                    print(f"📨 {user} está na área! Buscando mensagens pendentes...")
                    self.buscar_mensagens_pendentes()
    
    def print_users(self):
        print(self.usuarios.items())

    def distancia(self, localizacao):
        return np.linalg.norm(self.localizacao - np.array(localizacao)) * 111139

    def atualizar_usuarios_combobox(self):
        """Atualiza a lista de usuários disponíveis no Combobox."""
        lista_usuarios = [f"{user} ({self.distancia((lat, lon)):.2f}m)"
                          for user, (lat, lon, _, _) in self.usuarios.items()]
        
        self.combobox_usuarios["values"] = lista_usuarios
        if lista_usuarios:
            self.combobox_usuarios.current(0)  # Seleciona automaticamente o primeiro usuário


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

                if username != self.username:
                    self.usuarios[username] = (latitude, longitude, ip, porta_rpc)
                    print(f"✅ {username} foi adicionado!")

                    self.root.after(0, self.atualizar_usuarios_combobox)

            elif msg.topic.startswith(f"{TOPICO_MENSAGENS}/{self.username}"):
                remetente = payload.get("remetente")
                mensagem = payload.get("mensagem")
                if remetente and mensagem:
                    print(f"\n📩 (ENTREGUE) Mensagens de {remetente}:\n{mensagem}")

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
    # username = input("Digite seu nome: ")
    # lat = float(input("Digite sua latitude: "))
    # lon = float(input("Digite sua longitude: "))
    # porta_rpc = input("Digite sua porta RPC: ")

    # cliente = ClienteChat(username, lat, lon, porta_rpc)

    # while True:
    #     cmd = input("\n📨 Digite 'm' para enviar mensagem ou 'l' para atualizar localização: ")

    #     if cmd == "m":
    #         dest = input("Digite o destinatário: ")
    #         msg = input("Digite a mensagem: ")
    #         cliente.enviar_mensagem(dest, msg)

    #     elif cmd == "l":
    #         lat = float(input("Nova latitude: "))
    #         lon = float(input("Nova longitude: "))
    #         cliente.localizacao = np.array([lat, lon])
    #         cliente.publicar_localizacao()
    #         print("📍 Localização atualizada!")
