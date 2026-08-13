// =============================================
//  BOTTO UI — app.js
// =============================================

const chatHistory = document.getElementById('chat-history')
const logArea     = document.getElementById('log-area')
const userInput   = document.getElementById('user-input')
const sendBtn     = document.getElementById('send-btn')
const avatarCore  = document.getElementById('avatar-core')
const statusText  = document.getElementById('status-text')
const modeToggle = document.getElementById('mode-toggle')
const modeDot    = document.getElementById('mode-dot')
const modeLabel  = document.getElementById('mode-label')

let modoTexto = true  // false = voz, true = texto


function alternarModo() {
  modoTexto = !modoTexto
  if (modoTexto) {
    modeDot.className   = 'dot dot-orange pulse'
    modeLabel.textContent = 'MODO TEXTO'
    addLog('SYS', 'Modo texto ativado — entrada por teclado.', 'tag-req')
  } else {
    modeDot.className   = 'dot dot-green pulse'
    modeLabel.textContent = 'MODO VOZ'
    addLog('SYS', 'Modo voz ativado — entrada por microfone.', 'tag-info')
  }
}

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

  // Linhas verticais
  for (let x = 0; x < canvas.width + spacing; x += spacing) {
    ctx.beginPath()
    ctx.moveTo(x, 0)
    ctx.lineTo(x, canvas.height)
    ctx.stroke()
  }
  // Linhas horizontais animadas
  for (let y = (gridOffset % spacing) - spacing; y < canvas.height + spacing; y += spacing) {
    const alpha = Math.abs(Math.sin((y / canvas.height) * Math.PI)) * 0.6 + 0.1
    ctx.globalAlpha = alpha
    ctx.beginPath()
    ctx.moveTo(0, y)
    ctx.lineTo(canvas.width, y)
    ctx.stroke()
    ctx.globalAlpha = 1
  }

  // Linha de varredura
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
    bubble.textContent = texto
  }

  wrap.appendChild(label)
  wrap.appendChild(bubble)
  chatHistory.appendChild(wrap)
  chatHistory.scrollTop = chatHistory.scrollHeight

  return wrap
}

function setStatus(estado) {
  const estados = {
    'idle':      { text: 'AGUARDANDO',   cls: '' },
    'thinking':  { text: 'PROCESSANDO',  cls: 'thinking' },
    'speaking':  { text: 'RESPONDENDO',  cls: 'speaking' },
  }
  const e = estados[estado] || estados['idle']
  statusText.textContent = e.text
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
    const audioData = 'data:audio/mpeg;base64,' + audioB64
    const audio     = new Audio(audioData)
    audio.onended  = resolve
    audio.onerror  = resolve
    audio.play()
  })
}

// ── ENVIAR MENSAGEM ───────────────────────────

async function enviar() {
  const texto = userInput.value.trim()
  addLog('SYS', `Entrada via ${modoTexto ? 'texto' : 'voz'}.`, 'tag-info')
  if (!texto) return

  userInput.value = ''
  setBusy(true)
  setStatus('thinking')

  // Exibe mensagem do usuário
  addMsg('user', texto)

  // Log da requisição
  addLog('REQ', `POST /mensagem → "${texto.substring(0, 40)}${texto.length > 40 ? '...' : ''}"`, 'tag-req')
  addLog('GEM', 'Enviando para Gemini 2.5 Flash...', 'tag-info')

  // Bolha "pensando"
  const thinkingBubble = addMsg('bot', '', true)

  try {
    const inicio = Date.now()

    const res  = await window.botto.enviarMensagem(texto)
    const ms   = Date.now() - inicio

    // Remove bolha de pensamento
    thinkingBubble.remove()

    if (res.erro) {
      addLog('ERR', res.erro, 'tag-err')
      addMsg('bot', `Erro: ${res.erro}`)
      setStatus('idle')
      setBusy(false)
      return
    }

    // Log da resposta
    addLog('GEM', `Resposta em ${ms}ms (${res.texto.length} chars)`, 'tag-res')
    addLog('TTS', 'Sintetizando áudio via ElevenLabs...', 'tag-tts')

    // Exibe texto da resposta
    addMsg('bot', res.texto)

    // Reproduz áudio
    setStatus('speaking')
    if (res.audio) {
      await reproduzirAudio(res.audio)
      addLog('TTS', 'Reprodução concluída.', 'tag-tts')
    }

  } catch (err) {
    thinkingBubble.remove()
    addLog('ERR', `Falha na conexão: ${err.message}`, 'tag-err')
    addMsg('bot', 'Erro de conexão com o backend. Verifique se o api.py está rodando.')
  }

  setStatus('idle')
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

// ── INICIALIZAÇÃO ─────────────────────────────

window.addEventListener('DOMContentLoaded', () => {
  // Atualiza os horários dos logs iniciais para o horário real
  document.querySelectorAll('.log-time').forEach(el => {
    el.textContent = agora()
  })
  userInput.focus()
})
