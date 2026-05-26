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
  skipped_cards: number
  total_chunks: number
  processed_chunks: number
  failed_chunks: number
}

export interface Card {
  id: number
  textbook_id: number
  concept_name: string
  english_name: string | null
  summary: string
  chapter: string
  page_number: number | null
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

export interface TextbookEnqueueResponse {
  textbook: Textbook
  message: string
}

export interface ImportChunkFailure {
  id: number
  textbook_id: number
  chunk_index: number
  page_number: number | null
  section_path: string | null
  chunk_excerpt: string
  error_message: string
  retry_count: number
  resolved: boolean
  created_at: string
  updated_at: string
}

export interface ImportChunkRetryResponse {
  textbook: Textbook
  failure: ImportChunkFailure
  imported_cards: number
  skipped_cards: number
}

export interface ImportChunkRetryBatchResponse {
  textbook: Textbook
  retried_count: number
  resolved_count: number
  remaining_failures: number
}
