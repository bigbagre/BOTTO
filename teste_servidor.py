import requests

SERVIDOR = 'http://100.123.51.17:5001'  # troca pelo IP real do Tailscale

# --- POST: enviar um novo dado pro servidor ---
novo_dado = {'Valor' : 15}
resposta = requests.post(f'{SERVIDOR}/Sensor', json=novo_dado)
  
print(resposta.status_code)  # 201 = criado com sucesso
print(resposta.json())       # {'message': 'Dado gravado com sucesso!'}


# --- GET: buscar todos os dados salvos ---
resposta = requests.get(f'{SERVIDOR}/Sensor')

print(resposta.status_code)  # 200 = ok
print(resposta.json())       # lista com todos os registros, ex: [{'id': 1, 'nome': 'Sensor1', 'idade': 25}, ...]