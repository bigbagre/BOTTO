import requests

SERVIDOR = 'http://100.123.51.17:5000'  # troca pelo IP real do Tailscale

# --- POST: enviar um novo dado pro servidor ---
novo_dado = {'Nome': 'Sensor1', 'Valor': 15}
resposta = requests.post(f'{SERVIDOR}/teste', json=novo_dado)

print(resposta.status_code)  # 201 = criado com sucesso
print(resposta.json())       # {'status': 'criado', 'id': 1, 'Nome': 'Sensor1', 'Valor': 15}


# --- GET: buscar todos os dados salvos ---
resposta = requests.get(f'{SERVIDOR}/teste')

print(resposta.status_code)  # 200 = ok
print(resposta.json())       # lista com todos os registros, ex: [{'id': 1, 'Nome': 'Sensor1', 'Valor': 15, 'criado_em': '...'}, ...]