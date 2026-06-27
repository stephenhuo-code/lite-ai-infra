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

it('Enter sends, but not while IME composing (中文输入选词回车不发送)', () => {
  const onSend = vi.fn()
  render(<AgentChat items={[]} onSend={onSend} onResolve={() => {}} />)
  const ta = screen.getByPlaceholderText(/探查数据/)
  fireEvent.change(ta, { target: { value: '当前的数据目录的coco' } })
  // 输入法合成中(选词)按回车 → 不发送
  fireEvent.keyDown(ta, { key: 'Enter', isComposing: true })
  expect(onSend).not.toHaveBeenCalled()
  // 合成结束后回车 → 发送
  fireEvent.keyDown(ta, { key: 'Enter' })
  expect(onSend).toHaveBeenCalledWith('当前的数据目录的coco')
})

it('ASK approve calls onResolve', () => {
  const onResolve = vi.fn()
  render(<AgentChat items={items} onSend={() => {}} onResolve={onResolve} />)
  fireEvent.click(screen.getByText('批准'))
  expect(onResolve).toHaveBeenCalledWith('el-1', true)
})
