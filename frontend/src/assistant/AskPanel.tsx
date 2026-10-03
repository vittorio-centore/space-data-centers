import { useRef, useState } from 'react'
import { playAudioB64, useAssistant } from './useAssistant'
import type { ChatLine } from './types'
import './AskPanel.css'

type SpeechRec = {
  lang: string
  interimResults: boolean
  onresult: ((ev: { results: { 0: { 0: { transcript: string } } } }) => void) | null
  onerror: (() => void) | null
  onend: (() => void) | null
  start: () => void
  stop: () => void
}

function browserSpeech(): SpeechRec | null {
  const w = window as unknown as {
    SpeechRecognition?: new () => SpeechRec
    webkitSpeechRecognition?: new () => SpeechRec
  }
  const Ctor = w.SpeechRecognition || w.webkitSpeechRecognition
  return Ctor ? new Ctor() : null
}

export default function AskPanel({ onAfterAction }: { onAfterAction?: () => Promise<unknown> | void }) {
  const { status, ask, sendVoice } = useAssistant()
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [listening, setListening] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [lines, setLines] = useState<ChatLine[]>([])
  const recRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])

  const live = Boolean(status?.grok)
  const modeLabel = live ? `Grok${status?.model ? ` · ${status.model}` : ''}` : 'Offline'

  const push = (line: Omit<ChatLine, 'id'>) => {
    setLines((prev) => [...prev, { ...line, id: `${Date.now()}-${prev.length}` }])
  }

  const handleResult = async (res: Awaited<ReturnType<typeof ask>>, spoken?: string) => {
    if (res.error) {
      setErr(res.error)
      push({ role: 'system', text: res.error })
      return
    }
    if (spoken) {
      push({ role: 'user', text: spoken, source: 'voice' })
    }
    push({ role: 'assistant', text: res.reply || 'Done.' })
    if (res.audio_b64) playAudioB64(res.audio_b64)
    if (res.actions && res.actions.length > 0) {
      await onAfterAction?.()
    }
  }

  const sendText = async () => {
    const q = text.trim()
    if (!q || busy) return
    setBusy(true)
    setErr(null)
    push({ role: 'user', text: q, source: 'text' })
    setText('')
    try {
      const res = await ask(q, 'text')
      await handleResult(res)
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'ask failed')
    } finally {
      setBusy(false)
    }
  }

  const startBrowserVoice = () => {
    const rec = browserSpeech()
    if (!rec) {
      setErr('This browser cannot capture speech. Type a command instead.')
      return
    }
    rec.lang = 'en-US'
    rec.interimResults = false
    rec.onresult = (ev) => {
      const spoken = ev.results[0][0].transcript
      void (async () => {
        setBusy(true)
        try {
          const res = await ask(spoken, 'voice')
          await handleResult(res, spoken)
        } catch (e) {
          setErr(e instanceof Error ? e.message : 'ask failed')
        } finally {
          setBusy(false)
          setListening(false)
        }
      })()
    }
    rec.onerror = () => {
      setListening(false)
      setErr('Voice capture stopped.')
    }
    rec.onend = () => setListening(false)
    setListening(true)
    rec.start()
  }

  const toggleVoice = async () => {
    if (busy) return
    if (listening && recRef.current) {
      recRef.current.stop()
      return
    }
    setErr(null)
    if (!live) {
      startBrowserVoice()
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const rec = new MediaRecorder(stream)
      chunksRef.current = []
      rec.ondataavailable = (e) => {
        if (e.data.size) chunksRef.current.push(e.data)
      }
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop())
        recRef.current = null
        setListening(false)
        const blob = new Blob(chunksRef.current, { type: rec.mimeType || 'audio/webm' })
        void (async () => {
          setBusy(true)
          try {
            const res = await sendVoice(blob)
            await handleResult(res, res.transcript || undefined)
          } catch (e) {
            setErr(e instanceof Error ? e.message : 'voice failed')
          } finally {
            setBusy(false)
          }
        })()
      }
      recRef.current = rec
      setListening(true)
      rec.start()
    } catch {
      setErr('Microphone permission is required for xAI Voice.')
    }
  }

  return (
    <section className="ask-panel">
      <button type="button" className="ask-toggle" onClick={() => setOpen((v) => !v)}>
        <h2>Ask Grok</h2>
        <span className="ask-mode" data-testid="ask-mode-label">
          {open ? 'Hide' : modeLabel}
        </span>
      </button>
      {open && (
        <div className="ask-body">
          <p className="ask-hint" data-testid="ask-mode-note">
            {live
              ? 'Live Grok + xAI Voice. Every command is validated; the planner still chooses the node.'
              : status?.note ||
                'Offline (no XAI_API_KEY). Keyword parser + browser speech; the same validated tools run.'}
          </p>
          {lines.length > 0 && (
            <div className="ask-log" aria-live="polite">
              {lines.map((l) => (
                <div key={l.id} className={`ask-line ${l.role}`}>
                  <span className="ask-who">
                    {l.role === 'user' ? (l.source === 'voice' ? 'You (voice)' : 'You') : l.role === 'assistant' ? 'Grok' : 'Note'}
                  </span>
                  {l.text}
                </div>
              ))}
            </div>
          )}
          <div className="ask-row">
            <input
              type="text"
              placeholder="Pause, submit a job, explain the plan…"
              value={text}
              disabled={busy}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void sendText()
              }}
            />
            <button type="button" className="primary" disabled={busy || !text.trim()} onClick={() => void sendText()}>
              Ask
            </button>
            <button
              type="button"
              className={listening ? 'listening' : ''}
              disabled={busy}
              onClick={() => void toggleVoice()}
              aria-pressed={listening}
            >
              {listening ? 'Stop' : 'Voice'}
            </button>
          </div>
          {err && <p className="ask-err">{err}</p>}
        </div>
      )}
    </section>
  )
}
