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
TOPICO_GERAL = "users/online"
TOPICO_MENSAGENS = "messages"

class ClienteChat:
    def __init__(self, root):
        self.root = root
        self.root.title("Chat de Proximidade")
        self.root.geometry("600x500")

        # Variáveis
        self.username = tk.StringVar()
        self.latitude = tk.DoubleVar()
        self.longitude = tk.DoubleVar()
        self.ip_local = obter_ip_local()
        self.porta_rpc = 8000 + np.random.randint(100)  # Porta aleatória para evitar conflito
        self.usuarios = {}  # {username: (latitude, longitude, ip, porta_rpc)}
        self.mensagens = []  # Histórico de mensagens
        
        # MQTT Client
        self.client = mqtt.Client()
        self.client.on_message = self.on_message
        self.client.connect(BROKER)
        self.client.loop_start()

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

        tk.Button(frame_top, text="Atualizar Localização", command=self.publicar_localizacao).grid(row=4, column=1)

        frame_mid = tk.Frame(self.root, padx=10, pady=10)
        frame_mid.pack(fill="x")

        tk.Label(frame_mid, text="Usuários Próximos:", font=("Arial", 10)).pack(anchor="w")
        self.combobox_usuarios = ttk.Combobox(frame_mid, state="readonly", width=50)
        self.combobox_usuarios.pack(pady=5, anchor="w")

        tk.Label(frame_mid, text="Mensagem:", font=("Arial", 10)).pack(anchor="w")
        self.entry_msg = tk.Entry(frame_mid, width=50)
        self.entry_msg.pack(pady=5, anchor="w")

        tk.Button(frame_mid, text="Enviar", command=self.enviar_mensagem).pack(anchor="w")

        frame_bottom = tk.Frame(self.root, padx=10, pady=10)
        frame_bottom.pack(fill="both", expand=True)

        tk.Label(frame_bottom, text="Histórico do Chat:", font=("Arial", 10)).pack(anchor="w")

        self.text_chat = tk.Text(frame_bottom, height=10, width=70, wrap="word")
        self.text_chat.pack(fill="both", expand=True, pady=5)

        scrollbar = ttk.Scrollbar(frame_bottom, command=self.text_chat.yview)
        scrollbar.pack(side="right", fill="y")
        self.text_chat.config(yscrollcommand=scrollbar.set)

        tk.Button(self.root, text="🔄 Refresh", command=self.monitorar_vizinhos).pack(pady=5)

    def iniciar_servidor_rpc(self):
        servidor = SimpleXMLRPCServer(("0.0.0.0", self.porta_rpc), allow_none=True)
        servidor.register_function(self.receber_mensagem, "receber_mensagem")
        servidor.serve_forever()

    def receber_mensagem(self, remetente, mensagem, timestamp):
        """Recebe mensagens via XML-RPC e as exibe no chat."""
        self.mensagens.append(f"{timestamp} - {remetente}: {mensagem}")
        self.atualizar_chat()
        return True

    def enviar_mensagem(self):
        """Envia uma mensagem para o usuário selecionado."""
        destinatario = self.combobox_usuarios.get().split(" ")[0]  # Pega o nome antes do espaço
        mensagem = self.entry_msg.get()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if destinatario in self.usuarios:
            ip_destino, porta_destino = self.usuarios[destinatario][2:4]
            try:
                proxy = xmlrpc.client.ServerProxy(f"http://{ip_destino}:{porta_destino}/")
                proxy.receber_mensagem(self.username.get(), mensagem, timestamp)
                self.mensagens.append(f"{timestamp} - Você → {destinatario}: {mensagem}")
                self.atualizar_chat()
            except Exception:
                self.armazenar_mensagem_mom(destinatario, mensagem, timestamp)
        else:
            self.armazenar_mensagem_mom(destinatario, mensagem, timestamp)

        self.entry_msg.delete(0, tk.END)

    def armazenar_mensagem_mom(self, destinatario, mensagem, timestamp):
        """Armazena mensagens pendentes na fila MQTT."""
        payload = json.dumps({"remetente": self.username.get(), "mensagem": f"{timestamp} - {mensagem}"})
        self.client.publish(f"{TOPICO_MENSAGENS}/{destinatario}", payload, retain=True)

    def publicar_localizacao(self):
        """Publica localização via MQTT."""
        payload = json.dumps({
            "username": self.username.get(),
            "latitude": self.latitude.get(),
            "longitude": self.longitude.get(),
            "ip": self.ip_local,
            "port": self.porta_rpc
        })
        self.client.publish(TOPICO_GERAL, payload, retain=True)
        print(payload)

    def monitorar_vizinhos(self):
        """Atualiza lista de usuários e exibe no ComboBox."""
        print(self.usuarios.items())
        lista_usuarios = []
        for user, (lat, lon, ip, port) in self.usuarios.items():
            distancia = np.linalg.norm(np.array([self.latitude.get(), self.longitude.get()]) - np.array([lat, lon])) * 111139
            lista_usuarios.append(f"{user} ({distancia:.2f}m)")
        self.combobox_usuarios["values"] = lista_usuarios

    def atualizar_chat(self):
        """Atualiza a caixa de texto com o histórico do chat."""
        self.text_chat.delete(1.0, tk.END)
        self.text_chat.insert(tk.END, "\n".join(self.mensagens))
        self.text_chat.yview(tk.END)

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

            elif msg.topic.startswith(f"{TOPICO_MENSAGENS}/{self.username}"):
                remetente = payload.get("remetente")
                mensagem = payload.get("mensagem")
                if remetente and mensagem:
                    print(f"\n📩 (ENTREGUE) Mensagens de {remetente}:\n{mensagem}")

        except Exception as e:
            print(f"Erro ao processar mensagem: {e}")

def obter_ip_local():
    """Obtém o IP local."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    return s.getsockname()[0]

if __name__ == "__main__":
    root = tk.Tk()
    app = ClienteChat(root)
    root.mainloop()
