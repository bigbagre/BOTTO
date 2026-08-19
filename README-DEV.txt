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
        