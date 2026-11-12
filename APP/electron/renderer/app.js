// =============================================
//  BOTTO UI — app.js
// =============================================

const chatHistory = document.getElementById('chat-history')
const logArea     = document.getElementById('log-area')
const userInput   = document.getElementById('user-input')
const sendBtn     = document.getElementById('send-btn')
const avatarCore  = document.getElementById('avatar-core')
const statusText  = document.getElementById('status-text')
const modeToggle  = document.getElementById('mode-toggle')
const modeDot     = document.getElementById('mode-dot')
const modeLabel   = document.getElementById('mode-label')

let modoTexto = true  // true = texto, false = voz

// ── CANVAS FUNDO: GRID ANIMADO ──────────────
const canvas = document.getElementById('grid-canvas')
const ctx    = canvas.getContext('2d')

function resizeCanvas() {
  canvas.width  = window.innerWidth
  canvas.height = window.innerHeight
}
resizeCanvas()
window.addEventListener('resize', resizeCanvas)

let gridOffset = 0
function drawGrid() {
  ctx.clearRect(0, 0, canvas.width, canvas.height)
  ctx.strokeStyle = '#00d4ff'
  ctx.lineWidth   = 0.5
  const spacing = 40

  for (let x = 0; x < canvas.width + spacing; x += spacing) {
    ctx.beginPath()
    ctx.moveTo(x, 0)
    ctx.lineTo(x, canvas.height)
    ctx.stroke()
  }
  for (let y = (gridOffset % spacing) - spacing; y < canvas.height + spacing; y += spacing) {
    const alpha = Math.abs(Math.sin((y / canvas.height) * Math.PI)) * 0.6 + 0.1
    ctx.globalAlpha = alpha
    ctx.beginPath()
    ctx.moveTo(0, y)
    ctx.lineTo(canvas.width, y)
    ctx.stroke()
    ctx.globalAlpha = 1
  }

  const scanY = (gridOffset * 2) % canvas.height
  const grad  = ctx.createLinearGradient(0, scanY - 40, 0, scanY + 40)
  grad.addColorStop(0,   'rgba(0,212,255,0)')
  grad.addColorStop(0.5, 'rgba(0,212,255,0.08)')
  grad.addColorStop(1,   'rgba(0,212,255,0)')
  ctx.fillStyle = grad
  ctx.fillRect(0, scanY - 40, canvas.width, 80)

  gridOffset += 0.3
  requestAnimationFrame(drawGrid)
}
drawGrid()

// ── UTILITÁRIOS ──────────────────────────────

function agora() {
  return new Date().toLocaleTimeString('pt-BR', { hour12: false })
}

function processarTextoLaTeX(texto) {
  if (!texto) return texto
  // Converter block equations $$...$$
  let html = texto.replace(/\$\$(.+?)\$\$/gs, '<div class="math-block">$1</div>')
  // Converter inline $...$ (não capturando $$)
  html = html.replace(/(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)/g, '<span class="math-inline">$1</span>')
  return html
}

function addLog(tag, msg, tagClass = 'tag-sys') {
  const line = document.createElement('div')
  line.className = 'log-line new'
  line.innerHTML = `
    <span class="log-time">${agora()}</span>
    <span class="log-tag ${tagClass}">[${tag}]</span>
    <span>${msg}</span>
  `
  logArea.appendChild(line)
  logArea.scrollTop = logArea.scrollHeight
}

function addMsg(role, texto, thinking = false) {
  const wrap = document.createElement('div')
  wrap.className = `msg msg-${role}${thinking ? ' msg-thinking' : ''}`

  const label  = document.createElement('span')
  label.className = 'msg-label'
  label.textContent = role === 'user' ? 'VOCÊ' : 'BOTTO'

  const bubble = document.createElement('div')
  bubble.className = 'msg-bubble'

  if (thinking) {
    bubble.innerHTML = `Processando<span class="dots-anim"></span>`
  } else {
    bubble.innerHTML = processarTextoLaTeX(texto)
  }

  wrap.appendChild(label)
  wrap.appendChild(bubble)
  chatHistory.appendChild(wrap)
  chatHistory.scrollTop = chatHistory.scrollHeight

  return wrap
}

function setStatus(estado) {
  const estados = {
    'AGUARDANDO':  { cls: '' },
    'PROCESSANDO': { cls: 'thinking' },
    'FALANDO':     { cls: 'speaking' },
    'OUVINDO':     { cls: 'thinking' },
    'WAKE WORD':   { cls: 'speaking' },
  }
  const e = estados[estado] || { cls: '' }
  statusText.textContent = estado
  avatarCore.className   = `avatar-core ${e.cls}`
}

function setBusy(busy) {
  userInput.disabled = busy
  sendBtn.disabled   = busy
  if (!busy) userInput.focus()
}

// ── REPRODUTOR DE ÁUDIO ──────────────────────

function reproduzirAudio(audioB64) {
  return new Promise((resolve) => {
    const audio = new Audio('data:audio/wav;base64,' + audioB64)
    audio.onended = resolve
    audio.onerror = () => { console.error('Erro de áudio:', audio.error); resolve() }
    audio.play().catch(e => { console.error('play falhou:', e); resolve() })
  })
}

// ── SSE: RECEBER EVENTOS DO BACKEND ──────────

const audioQueue = []
let reproduzindo = false

async function reproduzirFila() {
    if (reproduzindo || audioQueue.length === 0) return
    reproduzindo = true
    const { audio, indice } = audioQueue.shift()
    await reproduzirAudio(audio)
    reproduzindo = false
    reproduzirFila()
}

let sseIniciado = false

function iniciarSSE() {
  if (sseIniciado) return
  sseIniciado = true

  window.botto.iniciarSSE(async ({ tipo, dados }) => {
    if (tipo === 'log') {
      const tagMap = {
        'SYS': 'tag-sys', 'REQ': 'tag-req', 'GEM': 'tag-res',
        'TTS': 'tag-tts', 'VOZ': 'tag-info', 'WAKE': 'tag-res', 'ERR': 'tag-err'
      }
      addLog(dados.tag, dados.msg, tagMap[dados.tag] || 'tag-sys')
    }
    if (tipo === 'status') setStatus(dados)
    if (tipo === 'transcricao') addMsg('user', dados)
    if (tipo === 'resposta') {
      addMsg('bot', dados.texto)
      if (dados.audio) await reproduzirAudio(dados.audio)
    }
    if (tipo === 'stream_inicio') {
      audioQueue.length = 0
      reproduzindo = false
      addMsg('bot', '', true)
    }
    if (tipo === 'stream_token') {
      const ultima = chatHistory.lastElementChild
      if (ultima && ultima.classList.contains('msg-thinking')) {
        const bubble = ultima.querySelector('.msg-bubble')
        bubble.classList.remove('dots-anim')
        bubble.textContent += dados.token
      }
    }
    if (tipo === 'stream_audio_chunk') {
      audioQueue.push({ audio: dados.audio, indice: dados.indice })
      audioQueue.sort((a, b) => a.indice - b.indice)
      reproduzirFila()
    }
    if (tipo === 'stream_fim') {
      const ultima = chatHistory.lastElementChild
      if (ultima) ultima.classList.remove('msg-thinking')
      setStatus('AGUARDANDO')
      setBusy(false)
    }
  })
}

// ── MODO TEXTO / VOZ ─────────────────────────

async function alternarModo() {
 console.log('alternarModo chamado, modoTexto atual:', modoTexto)
  modoTexto = !modoTexto
  const novoModo = modoTexto ? 'texto' : 'voz'
  console.log('novo modo:', novoModo)

  try {
    const res = await window.botto.alternarModo(novoModo)
    console.log('resposta do backend:', res)
  } catch (e) {
    console.log('erro:', e)
  }

  if (modoTexto) {
    modeDot.className     = 'dot dot-green pulse'
    modeLabel.textContent = 'MODO TEXTO'
    userInput.disabled    = false
    sendBtn.disabled      = false
    userInput.placeholder = 'Digite um comando...'
    userInput.focus()
  } else {
    modeDot.className     = 'dot dot-orange pulse'
    modeLabel.textContent = 'MODO VOZ'
    userInput.disabled    = true
    sendBtn.disabled      = true
    userInput.placeholder = 'Modo voz ativo — fale "Hey Bot"'
    setStatus('AGUARDANDO')
  }
}

// ── ENVIAR MENSAGEM (MODO TEXTO) ─────────────

async function enviar() {
  if (!modoTexto) return
  const texto = userInput.value.trim()
  if (!texto) return

  userInput.value = ''
  setBusy(true)
  setStatus('PROCESSANDO')

  addMsg('user', texto)

  const thinkingBubble = addMsg('bot', '', true)

  try {
    const res = await window.botto.enviarMensagem(texto)

    if (res.erro) {
      thinkingBubble.remove()
      addLog('ERR', res.erro, 'tag-err')
      addMsg('bot', `Erro: ${res.erro}`)
      setStatus('AGUARDANDO')
      setBusy(false)
      return
    }

    thinkingBubble.remove()
    addMsg('bot', res.texto)
    if (res.audio) await reproduzirAudio(res.audio)
  } catch (err) {
    thinkingBubble.remove()
    addLog('ERR', `Falha na conexão: ${err.message}`, 'tag-err')
    addMsg('bot', 'Erro de conexão com o backend.')
  }

  setStatus('AGUARDANDO')
  setBusy(false)
}

// ── ATALHOS DE TECLADO ────────────────────────

userInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    enviar()
  }
  if (e.key === 'Escape') {
    userInput.value = ''
  }
})

// ── AUTENTICAÇÃO ──────────────────────────────

// Hoje: Flask local. No beta: trocar pela URL do Funnel (https://SUA-URL.ts.net)
const API_AUTH = 'http://localhost:5001'

const loginScreen  = document.getElementById('login-screen')
const loginForm    = document.getElementById('login-form')
const registerForm = document.getElementById('register-form')
const showRegister = document.getElementById('show-register')
const hideRegister = document.getElementById('hide-register')
const loginMsg     = document.getElementById('login-msg')
const userPanel    = document.getElementById('user-panel')
const userName     = document.getElementById('user-name')
const userEmail    = document.getElementById('user-email')
const userMenu     = document.getElementById('user-menu')
const menuNome     = document.getElementById('menu-nome')
const menuEmail    = document.getElementById('menu-email')

// ... rest of existing code

function mostrarMsgLogin(msg, erro = true) {
  loginMsg.textContent = msg || ''
  loginMsg.style.color = erro ? 'var(--red)' : 'var(--green)'
}

function mostrarFormLogin() {
  registerForm.style.display = 'none'
  loginForm.style.display = 'block'
}

function mostrarFormRegistro() {
  mostrarMsgLogin('')
  loginForm.style.display = 'none'
  registerForm.style.display = 'block'
}

function mostrarTelaLogin() {
  document.getElementById('loading-screen').classList.add('hidden')
  loginScreen.classList.remove('hidden')
  mostrarFormLogin()
}

function entrarNoApp(usuario) {
  loginScreen.classList.add('hidden')
  document.getElementById('loading-screen').classList.add('hidden')
  document.getElementById('main-shell').classList.remove('hidden')
  mostrarUsuario(usuario)
  iniciarSSE()
  userInput.focus()
}

function mostrarUsuario(usuario) {
  const email = (usuario && usuario.email) || ''
  const nome  = (usuario && usuario.nome) || email.split('@')[0] || 'Convidado'
  userName.textContent  = nome
  userEmail.textContent = email
  menuNome.textContent  = nome
  menuEmail.textContent = email
  userPanel.classList.add('logado')
}

function fecharMenu() {
  userMenu.classList.remove('aberto')
  userName.classList.remove('clicked')
}

// Chamada SÓ depois que o carregamento terminou (ver onLoadingDone)
async function verificarLembrete() {
  const token = localStorage.getItem('botto-token')
  if (!token) return mostrarTelaLogin()

  try {
    const res = await fetch(API_AUTH + '/api/auth/remember-me', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token })
    })
    const data = await res.json()
    if (data.autenticado) {
      localStorage.setItem('botto-token', data.token)  // token rotacionado
      entrarNoApp(data)
    } else {
      localStorage.removeItem('botto-token')
      mostrarTelaLogin()
    }
  } catch {
    mostrarTelaLogin()  // servidor fora do ar: mantém o token guardado
  }
}

async function login() {
  const email   = document.getElementById('login-email').value.trim()
  const senha   = document.getElementById('login-password').value
  const lembrar = document.getElementById('remember-me').checked

  if (!email || !senha) return mostrarMsgLogin('Preencha email e senha')

  try {
    const res = await fetch(API_AUTH + '/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password: senha, lembrar })
    })
    const data = await res.json()
    if (!res.ok) return mostrarMsgLogin(data.erro || 'Falha no login')

    if (lembrar && data.token) localStorage.setItem('botto-token', data.token)
    else localStorage.removeItem('botto-token')

    document.getElementById('login-password').value = ''
    entrarNoApp(data)
  } catch {
    mostrarMsgLogin('Não foi possível conectar ao servidor')
  }
}

async function registrar() {
  const email = document.getElementById('register-email').value.trim()
  const senha = document.getElementById('register-password').value
  const nome  = document.getElementById('register-nome').value.trim()

  if (!email || !senha) return mostrarMsgLogin('Preencha email e senha')

  try {
    const res = await fetch(API_AUTH + '/api/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password: senha, nome })
    })
    const data = await res.json()
    if (!res.ok) return mostrarMsgLogin(data.erro || 'Falha no registro')

    document.getElementById('register-password').value = ''
    mostrarFormLogin()
    mostrarMsgLogin('Conta criada! Faça login.', false)
  } catch {
    mostrarMsgLogin('Não foi possível conectar ao servidor')
  }
}

loginForm.addEventListener('submit', (e) => { e.preventDefault(); login() })
registerForm.addEventListener('submit', (e) => { e.preventDefault(); registrar() })
showRegister.addEventListener('click', (e) => { e.preventDefault(); mostrarFormRegistro() })
hideRegister.addEventListener('click', () => { mostrarMsgLogin(''); mostrarFormLogin() })

// ── painel de usuário (bottom-left) ────────────────
// ── painel de usuário (canto inferior esquerdo) ──
userName.addEventListener('click', (e) => {
  e.stopPropagation()
  userMenu.classList.toggle('aberto')
  userName.classList.toggle('clicked')
})

document.addEventListener('click', (e) => {
  if (!userPanel.contains(e.target)) fecharMenu()
})

// ── LOADING SCREEN ─────────────────────────────

const loadingScreen = document.getElementById('loading-screen')
const mainShell     = document.getElementById('main-shell')
const loadingStatus = document.getElementById('loading-status')
const loadingBar    = document.getElementById('loading-bar')
const loadingLog    = document.getElementById('loading-log')

const loadingSteps = [
  'Iniciando Flask API...',
  'Carregando modelos de voz...',
  'Conectando ao Gemini...',
  'Inicializando ElevenLabs...',
  'Verificando wake word...',
]

function addLoadingLog(msg, tipo = '') {
  const line = document.createElement('div')
  line.className = `loading-log-line ${tipo}`
  line.textContent = msg
  loadingLog.appendChild(line)
  if (loadingLog.children.length > 5) loadingLog.removeChild(loadingLog.firstChild)
}

window.botto.onLoadingStatus((msg) => {
  loadingStatus.innerHTML = msg + '<span class="dots-anim"></span>'
})

window.botto.onLoadingProgress(({ progresso, tentativa }) => {
  loadingBar.style.width = progresso + '%'
  if (tentativa > 0 && tentativa % 4 === 0) {
    const stepIdx = Math.floor((tentativa / 40) * loadingSteps.length)
    if (loadingSteps[stepIdx]) addLoadingLog(loadingSteps[stepIdx])
  }
})

window.botto.onLoadingDone(() => {
  loadingBar.style.width = '100%'
  loadingStatus.innerHTML = 'SISTEMA PRONTO'
  addLoadingLog('✓ Backend conectado', 'ok')
  addLoadingLog('✓ Pronto para uso', 'ok')
  setTimeout(verificarLembrete, 800)
})

window.botto.onLoadingError(() => {
  loadingStatus.innerHTML = 'FALHA NA CONEXÃO'
  addLoadingLog('✗ Backend não respondeu', 'err')
  addLoadingLog('Verifique o api.py e tente novamente', 'err')
  loadingBar.style.background = 'var(--red)'
})

// ── LOGUT ───────────────────────────────────────
async function logout() {
  const token = localStorage.getItem('botto-token')
  localStorage.removeItem('botto-token')

  try {
    if (token) {
      await fetch(API_AUTH + '/api/auth/logout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token })
      })
    }
  } catch {}  // mesmo sem rede, o logout local vale

  fecharMenu()
  userPanel.classList.remove('logado')
  document.getElementById('main-shell').classList.add('hidden')
  mostrarTelaLogin()
  mostrarMsgLogin('Você foi desconectado', false)
}


