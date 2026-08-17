const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('botto', {
  enviarMensagem: (texto) => ipcRenderer.invoke('enviar-mensagem', texto),
  alternarModo: (modo) => ipcRenderer.invoke('alternar-modo', modo),
  iniciarSSE: (callback) => ipcRenderer.on('sse-evento', (_, data) => callback(data))
})