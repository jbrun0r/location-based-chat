# Location Based Chat

![Screenshot](https://github.com/jbrun0r/assets/blob/main/location-based-chat/Captura%20de%20Tela%202025-02-26%20a%CC%80s%2007.46.36.png?raw=true)

Este é um chat baseado em localização, que utiliza **MQTT** e **RPC** para comunicação entre usuários próximos. O chat permite enviar mensagens apenas para usuários dentro de um determinado raio de distância.

## Instalação

1. Clone este repositório:
   ```sh
   git clone https://github.com/seu-usuario/chat-localizacao.git
   cd chat-localizacao
   ```
2. Instale os requirements:
   ```sh
   pip install -r requirements.txt
   ```
3. Execute o chat:
   ```sh
   python chat.py
   ```

## Lógica de Conexão

### Descoberta de Usuários

1. Assim que um novo usuário entra no chat, ele publica suas informações (incluindo seu endereço) no **tópico geral** do MQTT.
2. Todos os usuários já conectados que estão ouvindo esse tópico recebem a informação e adicionam o novo usuário à sua lista de contatos.
3. Após receber as informações do novo usuário, os usuários já conectados enviam seus próprios endereços para o **tópico específico** do novo usuário.
4. Dessa forma, o novo usuário também consegue adicionar todos os usuários que estavam online antes de sua entrada.

### Envio e Recebimento de Mensagens

1. Se um usuário deseja enviar uma mensagem para outro usuário, a distância entre eles é calculada.
2. **Se estiver dentro do limite de distância**, a mensagem é enviada diretamente via **RPC** para o endereço do destinatário.
3. **Se estiver fora do limite de distância**, a mensagem é enviada para uma **fila(queue) MQTT** que o destinatário escuta.
4. No caso de mensagens pendentes na fila MQTT, elas só são entregues quando o destinatário estiver novamente dentro da área de alcance do remetente.

## Uso

1. Insira seu **nome de usuário**, **porta** e **localização (latitude e longitude)**.
2. Clique em **Iniciar** para se conectar ao chat.
3. Selecione um usuário próximo e envie mensagens.
4. Caso o destinatário esteja fora da área de alcance, a mensagem será enviada via MQTT e entregue quando ele ficar próximo novamente.
