import { it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
vi.mock('./FileViewer', () => ({ FileViewer: () => <div>FILE</div> }))
vi.mock('./Terminal', () => ({ Terminal: () => <div>TERM</div> }))
import { RightPane } from './RightPane'

it('switches tabs', () => {
  render(<RightPane fileContent="x" termLines={[]} previewName="coco" onCollapse={() => {}} />)
  expect(screen.getByText('FILE')).toBeTruthy()           // 默认文件
  fireEvent.click(screen.getByText('终端'))
  expect(screen.getByText('TERM')).toBeTruthy()
  fireEvent.click(screen.getByText('数据预览'))
  expect(screen.getByText('coco', { exact: false })).toBeTruthy()
})

it('collapse button fires', () => {
  const onC = vi.fn()
  render(<RightPane fileContent="" termLines={[]} onCollapse={onC} />)
  fireEvent.click(screen.getByTitle('收起'))
  expect(onC).toHaveBeenCalled()
})
