import { it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { AgentChat } from './AgentChat'
import type { ChatItem } from './useSessionStream'

const items: ChatItem[] = [
  { kind: 'user', text: '你好 agent' },
  { kind: 'assistant', text: 'Red Green Blue' },
]

it('渲染 user + assistant 气泡(9a 无 tool/ask 卡)', () => {
  render(<AgentChat items={items} onSend={() => {}} />)
  expect(screen.getByText('你好 agent')).toBeTruthy()
  expect(screen.getByText('Red Green Blue')).toBeTruthy()
  // 9a 红线:不渲染 9b 的卡片/审批
  expect(screen.queryByText('can() 通过')).toBeNull()
  expect(screen.queryByText('批准')).toBeNull()
})

it('点发送按钮调用 onSend', () => {
  const onSend = vi.fn()
  render(<AgentChat items={[]} onSend={onSend} />)
  fireEvent.change(screen.getByPlaceholderText(/发条消息/), { target: { value: '写个 recipe' } })
  fireEvent.click(screen.getByText('发送'))
  expect(onSend).toHaveBeenCalledWith('写个 recipe')
})

it('Enter 发送,但输入法合成中(中文选词回车)不发送', () => {
  const onSend = vi.fn()
  render(<AgentChat items={[]} onSend={onSend} />)
  const ta = screen.getByPlaceholderText(/发条消息/)
  fireEvent.change(ta, { target: { value: '当前的数据目录的coco' } })
  // 合成中(选词)按回车 → 不发送
  fireEvent.keyDown(ta, { key: 'Enter', isComposing: true })
  expect(onSend).not.toHaveBeenCalled()
  // 合成结束后回车 → 发送
  fireEvent.keyDown(ta, { key: 'Enter' })
  expect(onSend).toHaveBeenCalledWith('当前的数据目录的coco')
})

it('Shift+Enter 不发送(换行)', () => {
  const onSend = vi.fn()
  render(<AgentChat items={[]} onSend={onSend} />)
  const ta = screen.getByPlaceholderText(/发条消息/)
  fireEvent.change(ta, { target: { value: 'line1' } })
  fireEvent.keyDown(ta, { key: 'Enter', shiftKey: true })
  expect(onSend).not.toHaveBeenCalled()
})
