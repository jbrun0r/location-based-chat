import json
import time
import threading
import numpy as np
import paho.mqtt.client as mqtt
from xmlrpc.server import SimpleXMLRPCServer
import xmlrpc.client
import socket

BROKER = "test.mosquitto.org"
DISTANCIA_LIMITE = 200  # metros
TOPICO_GERAL = "users/online"  # Tópico onde todos publicam suas informações

class ClienteChat:
    def __init__(self, username, latitude, longitude, porta_rpc):
        self.username = username
        self.localizacao = np.array([latitude, longitude])
        self.usuarios = {}  # {username: (latitude, longitude, ip, porta_rpc)}
        self.mensagens_pendentes = {}  # {username: [mensagens]}
        self.porta_rpc = int(porta_rpc)

        # Conectar ao broker MQTT
        self.client = mqtt.Client()
        self.client.on_message = self.on_message
        self.client.connect(BROKER)

        # Assinar o tópico geral
        self.client.subscribe(TOPICO_GERAL)
        self.client.loop_start()

        self.publicar_localizacao()  # Publica as informações para que todos saibam
        threading.Thread(target=self.iniciar_servidor_rpc, daemon=True).start()
        threading.Thread(target=self.atualizar_vizinhos, daemon=True).start()

    def iniciar_servidor_rpc(self):
        """Inicia um servidor XML-RPC para receber mensagens."""
        servidor = SimpleXMLRPCServer(("0.0.0.0", self.porta_rpc), allow_none=True)
        servidor.register_function(self.receber_mensagem, "receber_mensagem")
        print(f"📡 Servidor XML-RPC iniciado na porta {self.porta_rpc}")
        servidor.serve_forever()

    def receber_mensagem(self, remetente, mensagem):
        """Recebe mensagens enviadas via RPC."""
        print(f"\n📩 Nova mensagem de {remetente}: {mensagem}")
        return True

    def enviar_mensagem(self, destinatario, mensagem):
        """Envia uma mensagem via XML-RPC, armazenando se o usuário estiver offline."""
        if destinatario in self.usuarios and self.distancia(self.usuarios[destinatario][:2]) <= DISTANCIA_LIMITE:
            ip_destino = self.usuarios[destinatario][2]
            porta_destino = self.usuarios[destinatario][3]

            try:
                proxy = xmlrpc.client.ServerProxy(f"http://{ip_destino}:{porta_destino}/")
                proxy.receber_mensagem(self.username, mensagem)
                print(f"✅ Mensagem enviada para {destinatario}: {mensagem}")

            except Exception as e:
                print(f"⚠️ Erro ao enviar mensagem para {destinatario}: {e}")
                self.mensagens_pendentes.setdefault(destinatario, []).append(mensagem)

    def publicar_localizacao(self):
        """Publica a localização e IP via MQTT no tópico geral."""
        payload = json.dumps({
            "username": self.username,
            "latitude": self.localizacao[0],
            "longitude": self.localizacao[1],
            "ip": obter_ip_local(),
            "port": self.porta_rpc
        })
        print(f"📤 Publicando localização no tópico geral: {payload}")
        self.client.publish(TOPICO_GERAL, payload)

    def atualizar_vizinhos(self):
        """Atualiza a lista de vizinhos a cada intervalo de tempo."""
        while True:
            time.sleep(60)
            print("\n🔄 Atualizando distâncias dos usuários:")
            for user, (lat, lon, ip, port) in self.usuarios.items():
                distancia = self.distancia((lat, lon))
                status = "✅ Dentro da zona de visão" if distancia <= DISTANCIA_LIMITE else "❌ Fora da zona de visão"
                print(f"   - {user} ({ip}:{port}): {distancia:.2f} metros ({status})")

            for user in list(self.mensagens_pendentes.keys()):
                if user in self.usuarios and self.distancia(self.usuarios[user][:2]) <= DISTANCIA_LIMITE:
                    print(f"📨 Entregando mensagens pendentes para {user}: {self.mensagens_pendentes[user]}")
                    for msg in self.mensagens_pendentes[user]:
                        self.enviar_mensagem(user, msg)
                    del self.mensagens_pendentes[user]

    def distancia(self, localizacao):
        """Calcula a distância Euclidiana em metros."""
        return np.linalg.norm(self.localizacao - np.array(localizacao)) * 111139

    def on_message(self, client, userdata, msg):
        """Processa mensagens MQTT recebidas no tópico geral."""
        try:
            payload = json.loads(msg.payload.decode())

            username = payload.get("username")
            latitude = payload.get("latitude")
            longitude = payload.get("longitude")
            ip = payload.get("ip")
            porta_rpc = payload.get("port")

            if None in (username, latitude, longitude, ip, porta_rpc):
                print(f"⚠️ Mensagem MQTT inválida recebida: {payload}")
                return

            if username != self.username:
                if username not in self.usuarios:
                    print(f"👥 Novo usuário detectado: {username}. Enviando minhas informações para ele!")
                    self.publicar_localizacao()  # Manda as infos para o novo usuário

                self.usuarios[username] = (latitude, longitude, ip, porta_rpc)
                print(f"✅ {username} foi adicionado à lista de usuários.")

        except Exception as e:
            print(f"Erro ao processar mensagem: {e}")

def obter_ip_local():
    """Obtém o IP local correto da máquina."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip_local = s.getsockname()[0]
        s.close()
        return ip_local
    except:
        return "127.0.0.1"

if __name__ == "__main__":
    username = input("Digite seu nome: ")
    lat = float(input("Digite sua latitude: "))
    lon = float(input("Digite sua longitude: "))
    porta_rpc = input("Digite sua porta RPC: ")

    cliente = ClienteChat(username, lat, lon, porta_rpc)

    while True:
        cmd = input("\n📨 Digite 'm' para enviar mensagem ou 'l' para atualizar localização: ")

        if cmd == "m":
            dest = input("Digite o destinatário: ")
            msg = input("Digite a mensagem: ")
            cliente.enviar_mensagem(dest, msg)

        elif cmd == "l":
            lat = float(input("Nova latitude: "))
            lon = float(input("Nova longitude: "))
            cliente.localizacao = np.array([lat, lon])
            cliente.publicar_localizacao()
            print("📍 Localização atualizada!")
