import { it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { LeftTree } from './LeftTree'

const base = {
  workingFiles: ['recipe.py', 'README.md'],
  datasets: [{ name: 'coco', kind: 'raw' }],
  gitChanges: [{ x: 'M', path: 'recipe.py' }],
  onSelectDataset: vi.fn(),
}

it('renders three sections', () => {
  render(<LeftTree {...base} />)
  expect(screen.getByText('工作目录')).toBeTruthy()
  expect(screen.getByText('数据目录')).toBeTruthy()
  expect(screen.getByText('Git')).toBeTruthy()
})

it('clicking a dataset calls onSelectDataset', () => {
  const onSel = vi.fn()
  render(<LeftTree {...base} onSelectDataset={onSel} />)
  fireEvent.click(screen.getByText('coco'))
  expect(onSel).toHaveBeenCalledWith('coco')
})

it('collapsing 工作目录 hides its items', () => {
  render(<LeftTree {...base} />)
  expect(screen.getByText('README.md')).toBeTruthy()
  fireEvent.click(screen.getByText('工作目录'))
  expect(screen.queryByText('README.md')).toBeNull()
})
