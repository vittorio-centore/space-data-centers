export type AssistantMode = 'live' | 'offline'

export interface AssistantStatus {
  mode: AssistantMode
  grok: boolean
  voice: boolean
  voice_offline: string
  model: string | null
  tools: string[]
  planner: string
}

export interface AssistantAction {
  tool: string
  args: Record<string, unknown>
  ok: boolean
}

export interface AssistantAskResult {
  ok?: boolean
  reply: string
  source?: string
  parser?: string
  mode?: AssistantMode
  grok_error?: string | null
  actions?: AssistantAction[]
  rejected?: { tool: string; error: string }[]
  results?: Record<string, unknown>[]
  audio_b64?: string | null
  transcript?: string | null
  error?: string
}

export interface ChatLine {
  id: string
  role: 'user' | 'assistant' | 'system'
  text: string
  source?: 'text' | 'voice'
}
