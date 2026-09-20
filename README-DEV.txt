>>>>>INICIAR APP BOTTO<<<<<

    1- Instale node.js (https://nodejs.org/pt-br/download) - Executor de Java script
    2- No terminal, rode : "node --version" e "npm --version" 
    3- No terminal, abra o diretorio de onde você colocou o repositorio na pasta electron (Ex: cd "C:\...\APP\electron) 
    4- No terminal, rode: "npm init -y", "npm install electron --save-dev", "npm install electron-builder --save-dev" (Instalou a versão mais recente do electron do electron no seu repositorio local)
    5- Após todas as instalações, no terminal, rode: "npm start", com isso o app deve abrir, antes de mandar mensagem sempre veja o log para confirmar a conexão SSE

    Outras informações importantes:
        O código backend do app é o api.py na pasta electron. Em tese, ele é o mesmo que o código main.py, a diferença só existe para facilitar na hora de fazer testes temporarios
        
        O main.js, é a ponte entre o backend e o frontend

        A pasta renderer contem todas as informações frontend

        O .gitignore existe para que todos tenham as versões mais recentes do electron no seu repositorio, pois originalmente no meu computador é ali onde comporta os arquivos do electron, isso não afeta vocês.
        

        Para o servidor:
               Somente quem tem acesso ao servidor fisico: 
                Tailscaled & - abre a vpn
                Tailscale up - conecta a vpn

               Quem vai acessar:
                Faça login no tailscale.com, pode fazer de qualquer forma, mas eu fiz com o github
                Entrem no link de convite: (https://login.tailscale.com/uinv/ieGeoEtnam11t8kJgZzbq11)
                Utilize o Ip do servidor (nomeado como puppylinux) quando for implementar o seu código
                http://100.123.51.17:5000/teste - Abre o banco de dados e informa os comandos para enviar e buscar os dados

                Como testar:
                    Vai no teste_servidor.py, altera os valores (tanto o nome quanto o valor) = (isso em : 'Nome': 'vc vai mudar aq', 'Valor': 'vc vai mudar aqui tbm')
                    Quando rodar o código, no terminal deve aparecer algo do tipo: 
                        201
                        {'Nome': 'Sensor1', 'Valor': 15, 'id': 1, 'status': 'criado'}
                        200
                        [{'Nome': 'Sensor1', 'Valor': 15, 'criado_em': '2026-09-20 14:17:16', 'id': 1}]

                    Se aparecer isso, coloca no seu navegador: http://100.123.51.17:5000/teste e lá deve aparecer os seus valores