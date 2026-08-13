
const { app, BrowserWindow } = require('electron') 
const { spawn } = require('child_process') 
const path = require('path') 
let pythonProcess = null 
function startPython() { pythonProcess = spawn('python', [ path.join(__dirname, 'C:\\Users\\renat\\OneDrive\\Área de Trabalho\\Engenharia\\BOTTO\\APP', 'api.py') ]) } 
function createWindow() { const win = new BrowserWindow({ width: 480, height: 700, frame: false, resizable: true, minWidth: 700, minHeight: 500, webPreferences: { preload: path.join(__dirname, 'preload.js'), contextIsolation: true } }) 
win.loadFile('renderer/index.html') } app.whenReady().then(() => { startPython() 
    setTimeout(createWindow, 1500) }) 
    app.on('window-all-closed', () => { if (pythonProcess) pythonProcess.kill() 
        app.quit() })