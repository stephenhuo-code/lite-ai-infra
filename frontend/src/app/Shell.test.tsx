import { it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { Shell } from './Shell'
it('侧栏可折叠', () => {
  render(<MemoryRouter><Shell enterprise="华研科技" /></MemoryRouter>)
  const aside = document.querySelector('aside')!
  expect(aside.className).toContain('w-64')
  fireEvent.click(screen.getByLabelText('折叠'))
  expect(aside.className).toContain('w-16')
})
