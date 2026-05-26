import type { Card, DrawResponse, PoolResponse, Textbook } from './types'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    const detail = payload?.detail ?? 'Request failed'
    throw new Error(detail)
  }
  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

export async function listTextbooks(): Promise<Textbook[]> {
  return request<Textbook[]>('/api/textbooks')
}

export async function importTextbook(file: File): Promise<void> {
  const formData = new FormData()
  formData.append('file', file)
  await request('/api/textbooks/import', {
    method: 'POST',
    body: formData,
  })
}

export async function drawCard(sessionId?: string): Promise<DrawResponse> {
  const headers = sessionId ? { 'X-Session-Id': sessionId } : undefined
  return request<DrawResponse>('/api/cards/draw', { headers })
}

export async function resetSession(sessionId: string): Promise<void> {
  await request(`/api/sessions/${sessionId}/reset`, { method: 'POST' })
}

export async function updateCard(sessionId: string | undefined, cardId: number, payload: Partial<Card>): Promise<Card> {
  const headers: HeadersInit = { 'Content-Type': 'application/json' }
  if (sessionId) {
    headers['X-Session-Id'] = sessionId
  }
  return request<Card>(`/api/cards/${cardId}`, {
    method: 'PATCH',
    headers,
    body: JSON.stringify(payload),
  })
}

export async function markCard(sessionId: string | undefined, cardId: number, action: 'mark-familiar' | 'mark-uncertain' | 'ignore'): Promise<Card> {
  const headers = sessionId ? { 'X-Session-Id': sessionId } : undefined
  return request<Card>(`/api/cards/${cardId}/${action}`, {
    method: 'POST',
    headers,
  })
}

export async function deleteCard(sessionId: string | undefined, cardId: number): Promise<void> {
  const headers = sessionId ? { 'X-Session-Id': sessionId } : undefined
  await request(`/api/cards/${cardId}`, {
    method: 'DELETE',
    headers,
  })
}

export async function fetchPool(kind: 'familiar' | 'uncertain', query = ''): Promise<PoolResponse> {
  const url = query ? `/api/pools/${kind}?q=${encodeURIComponent(query)}` : `/api/pools/${kind}`
  return request<PoolResponse>(url)
}
