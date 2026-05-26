export type TextbookStatus = 'pending' | 'processing' | 'completed' | 'failed'
export type CardStatus = 'new' | 'familiar' | 'uncertain' | 'ignored'

export interface Textbook {
  id: number
  filename: string
  imported_at: string
  processed_at: string | null
  status: TextbookStatus
  summary: string | null
  error_message: string | null
  card_count: number
}

export interface Card {
  id: number
  textbook_id: number
  concept_name: string
  summary: string
  chapter: string
  source_excerpt: string
  status: CardStatus
  created_at: string
  updated_at: string
}

export interface DrawResponse {
  session_id: string
  card: Card | null
  round_complete: boolean
  message: string
}

export interface PoolResponse {
  items: Card[]
  total: number
  query: string
}
