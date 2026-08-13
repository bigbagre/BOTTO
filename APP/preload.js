
const { contextBridge } = require('electron') 
contextBridge.exposeInMainWorld('botto', { enviarMensagem: async (texto) => { const res = await fetch('http://localhost:5001/mensagem', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ texto }) }) 
return res.json() } }) 