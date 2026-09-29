const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('botto', {
  enviarMensagem: (texto) => ipcRenderer.invoke('enviar-mensagem', texto),
  alternarModo: (modo) => ipcRenderer.invoke('alternar-modo', modo),
  iniciarSSE: (callback) => ipcRenderer.on('sse-evento', (_, data) => callback(data)),
  onLoadingStatus: (callback) => ipcRenderer.on('loading-status', (_, msg) => callback(msg)),
  onLoadingProgress: (callback) => ipcRenderer.on('loading-progress', (_, data) => callback(data)),
  onLoadingDone: (callback) => ipcRenderer.on('loading-done', () => callback()),
  onLoadingError: (callback) => ipcRenderer.on('loading-error', () => callback()),
})