const { app, BrowserWindow, ipcMain } = require('electron')
const { spawn } = require('child_process')
const path = require('path')
const http = require('http')

let pythonProcess = null
let mainWindow = null

function startPython() {
  let pythonPath, args

  if (app.isPackaged) {
    // Rodando como executável empacotado
    pythonPath = path.join(process.resourcesPath, 'dist', 'api', 'api.exe')
    args = []
  } else {
    // Rodando em desenvolvimento
    pythonPath = 'python'
    args = [path.join(__dirname, '..', 'api.py')]
  }

  pythonProcess = spawn(pythonPath, args)
  pythonProcess.stdout.on('data', (data) => console.log('Python:', data.toString()))
  pythonProcess.stderr.on('data', (data) => console.error('Python err:', data.toString()))
  pythonProcess.on('close', (code) => console.log('Python encerrou com código:', code))
}

function postJSON(rota, body) {
  return new Promise((resolve, reject) => {
    const data = JSON.stringify(body)
    const req = http.request({
      hostname: 'localhost', port: 5001, path: rota, method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) }
    }, (res) => {
      let raw = ''
      res.on('data', chunk => raw += chunk)
      res.on('end', () => resolve(JSON.parse(raw)))
    })
    req.on('error', reject)
    req.write(data)
    req.end()
  })
}

function iniciarSSE() {
  const req = http.request({
    hostname: 'localhost', port: 5001, path: '/stream', method: 'GET'
  }, (res) => {
    res.on('data', (chunk) => {
      const linhas = chunk.toString().split('\n')
      for (const linha of linhas) {
        if (linha.startsWith('data: ')) {
          try {
            const evento = JSON.parse(linha.slice(6))
            if (mainWindow) mainWindow.webContents.send('sse-evento', evento)
          } catch {}
        }
      }
    })
    res.on('end', () => setTimeout(iniciarSSE, 5000))
  })
  req.on('error', () => setTimeout(iniciarSSE, 10000))
  req.end()
}

ipcMain.handle('enviar-mensagem', async (_, texto) => {
  return await postJSON('/mensagem', { texto })
})

ipcMain.handle('alternar-modo', async (_, modo) => {
  return await postJSON('/modo', { modo })
})

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 900, height: 700,
    frame: false, resizable: true,
    minWidth: 700, minHeight: 500,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true
    }
  })
  mainWindow.loadFile('renderer/index.html')
}

app.whenReady().then(() => {
  startPython()
  setTimeout(() => {
    createWindow()
    setTimeout(iniciarSSE, 3000)
  }, 5000)
})

app.on('window-all-closed', () => {
  if (pythonProcess) pythonProcess.kill()
  app.quit()
})