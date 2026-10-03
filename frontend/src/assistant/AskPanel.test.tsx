import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

const ask = vi.fn()
const sendVoice = vi.fn()

vi.mock('./useAssistant', () => ({
  useAssistant: () => ({
    status: {
      mode: 'offline',
      grok: false,
      voice: false,
      voice_offline: 'browser',
      model: null,
      tools: ['pause'],
      planner: 'deterministic',
      note: 'Offline (no XAI_API_KEY).',
    },
    ask,
    sendVoice,
    error: null,
    refreshStatus: async () => null,
  }),
  playAudioB64: vi.fn(),
}))

import AskPanel from './AskPanel'

describe('AskPanel offline', () => {
  afterEach(() => {
    cleanup()
    ask.mockReset()
  })

  it('shows the offline note and runs Ask through the hook', async () => {
    ask.mockResolvedValue({
      reply: 'Offline (no XAI_API_KEY). Simulation paused at t=12s.',
      parser: 'offline',
      mode: 'offline',
      actions: [{ tool: 'pause', args: {}, ok: true }],
    })
    render(<AskPanel />)
    fireEvent.click(screen.getByRole('button', { name: /Ask Grok/i }))
    expect(screen.getByTestId('ask-mode-note').textContent).toMatch(/Offline \(no XAI_API_KEY\)/)
    fireEvent.change(screen.getByPlaceholderText(/Pause/i), { target: { value: 'pause' } })
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }))
    await waitFor(() => expect(ask).toHaveBeenCalledWith('pause', 'text'))
    expect(await screen.findByText(/Simulation paused/)).toBeTruthy()
  })
})
