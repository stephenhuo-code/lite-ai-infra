import { it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

const fetchModelCredentials = vi.fn()
const putModelCredential = vi.fn()
const deleteModelCredential = vi.fn()

vi.mock('../../api/devws', () => ({
  fetchModelCredentials: () => fetchModelCredentials(),
  putModelCredential: (p: string, s: string) => putModelCredential(p, s),
  deleteModelCredential: (p: string) => deleteModelCredential(p),
}))

import { ModelCredentials } from './ModelCredentials'

beforeEach(() => {
  fetchModelCredentials.mockReset().mockResolvedValue({ claude: false, codex: false })
  putModelCredential.mockReset().mockResolvedValue(undefined)
  deleteModelCredential.mockReset().mockResolvedValue(undefined)
})

it('renders both providers', async () => {
  render(<ModelCredentials />)
  await waitFor(() => expect(fetchModelCredentials).toHaveBeenCalled())
  expect(screen.getByText('Claude')).toBeTruthy()
  expect(screen.getByText('Codex')).toBeTruthy()
  expect(screen.getByTestId('secret-claude')).toBeTruthy()
  expect(screen.getByTestId('secret-codex')).toBeTruthy()
})

it('typing a secret and clicking connect calls put(provider, secret)', async () => {
  render(<ModelCredentials />)
  await waitFor(() => expect(fetchModelCredentials).toHaveBeenCalled())
  const ta = screen.getByTestId('secret-claude')
  fireEvent.change(ta, { target: { value: 'tok-x' } })
  fireEvent.click(screen.getByTestId('connect-claude'))
  await waitFor(() => expect(putModelCredential).toHaveBeenCalledWith('claude', 'tok-x'))
})

it('clicking disconnect on a connected provider calls delete(provider)', async () => {
  fetchModelCredentials.mockResolvedValue({ claude: true, codex: false })
  render(<ModelCredentials />)
  await waitFor(() => expect(fetchModelCredentials).toHaveBeenCalled())
  await waitFor(() => expect(screen.getByTestId('disconnect-claude')).toBeTruthy())
  fireEvent.click(screen.getByTestId('disconnect-claude'))
  await waitFor(() => expect(deleteModelCredential).toHaveBeenCalledWith('claude'))
})
