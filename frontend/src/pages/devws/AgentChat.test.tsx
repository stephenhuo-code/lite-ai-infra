import { it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { AgentChat } from './AgentChat'
import type { ChatItem } from './useSessionStream'

const items: ChatItem[] = [
  { kind: 'user', text: '探查 coco' },
  { kind: 'assistant', text: 'coco 是 webdataset' },
  { kind: 'tool', name: 'liteai__catalog_read_schema' },
  { kind: 'ask', id: 'el-1', prompt: 'run_dj?' },
]

it('renders bubbles, tool card and ask card', () => {
  render(<AgentChat items={items} onSend={() => {}} onResolve={() => {}} />)
  expect(screen.getByText('探查 coco')).toBeTruthy()
  expect(screen.getByText('coco 是 webdataset')).toBeTruthy()
  expect(screen.getByText('liteai__catalog_read_schema')).toBeTruthy()
  expect(screen.getByText('run_dj?')).toBeTruthy()
})

it('composer sends text', () => {
  const onSend = vi.fn()
  render(<AgentChat items={[]} onSend={onSend} onResolve={() => {}} />)
  fireEvent.change(screen.getByPlaceholderText(/探查数据/), { target: { value: '写个 recipe' } })
  fireEvent.click(screen.getByText('发送'))
  expect(onSend).toHaveBeenCalledWith('写个 recipe')
})

it('ASK approve calls onResolve', () => {
  const onResolve = vi.fn()
  render(<AgentChat items={items} onSend={() => {}} onResolve={onResolve} />)
  fireEvent.click(screen.getByText('批准'))
  expect(onResolve).toHaveBeenCalledWith('el-1', true)
})
