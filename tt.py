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
        self.porta_rpc = tk.IntVar(value=8000)  # O usuário pode mudar a porta antes de iniciar
        self.latitude = tk.DoubleVar()
        self.longitude = tk.DoubleVar()
        self.ip_local = obter_ip_local()
        self.usuarios = {}  # {username: (latitude, longitude, ip, porta_rpc)}
        self.mensagens = []  # Histórico de mensagens
        self.iniciado = False  # Para garantir que nome e porta só sejam definidos uma vez

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
        self.entry_nome = tk.Entry(frame_top, textvariable=self.username)
        self.entry_nome.grid(row=0, column=1)

        tk.Label(frame_top, text="IP Local:", font=("Arial", 10)).grid(row=1, column=0)
        tk.Label(frame_top, text=f"{self.ip_local}", font=("Arial", 10, "bold")).grid(row=1, column=1)

        tk.Label(frame_top, text="Porta RPC:", font=("Arial", 10)).grid(row=2, column=0)
        self.entry_porta = tk.Entry(frame_top, textvariable=self.porta_rpc)
        self.entry_porta.grid(row=2, column=1)

        tk.Button(frame_top, text="Iniciar", command=self.iniciar_cliente).grid(row=3, column=1)

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

    def iniciar_cliente(self):
        """Inicia o cliente após o usuário definir nome e porta uma única vez."""
        if self.iniciado:
            return  # Não permite reiniciar

        if not self.username.get():
            print("⚠️ Digite um nome!")
            return

        # Desativar entrada de nome e porta após iniciar
        self.entry_nome.config(state="disabled")
        self.entry_porta.config(state="disabled")

        self.publicar_localizacao()
        threading.Thread(target=self.iniciar_servidor_rpc, daemon=True).start()
        threading.Thread(target=self.monitorar_vizinhos, daemon=True).start()
        self.iniciado = True  # Marca como iniciado

    def iniciar_servidor_rpc(self):
        """Inicia o servidor XML-RPC para receber mensagens."""
        servidor = SimpleXMLRPCServer(("0.0.0.0", self.porta_rpc.get()), allow_none=True)
        servidor.register_function(self.receber_mensagem, "receber_mensagem")
        servidor.serve_forever()

    def receber_mensagem(self, remetente, mensagem, timestamp):
        """Recebe mensagens via RPC e as exibe no chat."""
        self.mensagens.append(f"{timestamp} - {remetente}: {mensagem}")
        self.atualizar_chat()
        return True

    def enviar_mensagem(self):
        """Envia uma mensagem para o usuário selecionado."""
        destinatario = self.combobox_usuarios.get().split(" ")[0]
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
            "ip": self.ip_local,
            "port": self.porta_rpc.get()
        })
        self.client.publish(TOPICO_GERAL, payload, retain=True)

    def monitorar_vizinhos(self):
        """Atualiza lista de usuários e exibe no ComboBox."""
        lista_usuarios = []
        for user, (lat, lon, ip, port) in self.usuarios.items():
            lista_usuarios.append(f"{user} ({ip}:{port})")
        self.combobox_usuarios["values"] = lista_usuarios

    def atualizar_chat(self):
        """Atualiza a caixa de texto com o histórico do chat."""
        self.text_chat.delete(1.0, tk.END)
        self.text_chat.insert(tk.END, "\n".join(self.mensagens))
        self.text_chat.yview(tk.END)

    def on_message(self, client, userdata, msg):
        """Recebe mensagens MQTT."""
        payload = json.loads(msg.payload.decode())
        username = payload.get("username")
        if msg.topic.startswith(TOPICO_GERAL):
            self.usuarios[username] = (payload.get("ip"), payload.get("port"))

def obter_ip_local():
    """Obtém o IP local."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    return s.getsockname()[0]

if __name__ == "__main__":
    root = tk.Tk()
    app = ClienteChat(root)
    root.mainloop()
