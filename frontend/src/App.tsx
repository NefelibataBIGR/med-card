import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'

import {
  deleteCard,
  drawCard,
  fetchPool,
  importTextbook,
  listTextbooks,
  markCard,
  resetSession,
  updateCard,
} from './api'
import type { Card, Textbook } from './types'

type TabKey = 'import' | 'draw' | 'pools'
type PoolKey = 'familiar' | 'uncertain'

const emptyCardForm = {
  concept_name: '',
  summary: '',
  chapter: '',
  source_excerpt: '',
}

export function App() {
  const [tab, setTab] = useState<TabKey>('import')
  const [textbooks, setTextbooks] = useState<Textbook[]>([])
  const [currentCard, setCurrentCard] = useState<Card | null>(null)
  const [sessionId, setSessionId] = useState('')
  const [drawMessage, setDrawMessage] = useState('Draw a card to start this review round.')
  const [roundComplete, setRoundComplete] = useState(false)
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const [editForm, setEditForm] = useState(emptyCardForm)
  const [poolKind, setPoolKind] = useState<PoolKey>('uncertain')
  const [poolQuery, setPoolQuery] = useState('')
  const [poolItems, setPoolItems] = useState<Card[]>([])

  useEffect(() => {
    void refreshTextbooks()
  }, [])

  useEffect(() => {
    if (currentCard) {
      setEditForm({
        concept_name: currentCard.concept_name,
        summary: currentCard.summary,
        chapter: currentCard.chapter,
        source_excerpt: currentCard.source_excerpt,
      })
    } else {
      setEditForm(emptyCardForm)
    }
  }, [currentCard])

  useEffect(() => {
    if (tab === 'pools') {
      void refreshPool(poolKind, poolQuery)
    }
  }, [tab, poolKind, poolQuery])

  async function refreshTextbooks() {
    try {
      setTextbooks(await listTextbooks())
    } catch (err) {
      setError((err as Error).message)
    }
  }

  async function refreshPool(kind: PoolKey, query: string) {
    try {
      const result = await fetchPool(kind, query)
      setPoolItems(result.items)
    } catch (err) {
      setError((err as Error).message)
    }
  }

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const input = event.currentTarget.elements.namedItem('pdf') as HTMLInputElement | null
    const file = input?.files?.[0]
    if (!file) {
      setError('Choose a PDF file first.')
      return
    }
    setUploading(true)
    setError('')
    try {
      await importTextbook(file)
      await refreshTextbooks()
      event.currentTarget.reset()
      setDrawMessage('Import completed. You can start drawing cards now.')
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setUploading(false)
    }
  }

  async function handleDraw() {
    setLoading(true)
    setError('')
    try {
      const result = await drawCard(sessionId || undefined)
      setSessionId(result.session_id)
      setCurrentCard(result.card)
      setRoundComplete(result.round_complete)
      setDrawMessage(result.message)
      if (result.card) {
        setTab('draw')
      }
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  async function handleResetRound() {
    if (!sessionId) {
      return
    }
    setLoading(true)
    setError('')
    try {
      await resetSession(sessionId)
      setCurrentCard(null)
      setRoundComplete(false)
      setDrawMessage('Round reset. Draw again when ready.')
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  async function handleAction(action: 'mark-familiar' | 'mark-uncertain' | 'ignore' | 'delete') {
    if (!currentCard) {
      return
    }
    setLoading(true)
    setError('')
    try {
      if (action === 'delete') {
        await deleteCard(sessionId || undefined, currentCard.id)
        setCurrentCard(null)
        setDrawMessage('Card deleted.')
      } else {
        const updated = await markCard(sessionId || undefined, currentCard.id, action)
        setCurrentCard(updated)
        setDrawMessage('Card status updated.')
      }
      await refreshPool(poolKind, poolQuery)
      await refreshTextbooks()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  async function handleSaveEdit() {
    if (!currentCard) {
      return
    }
    setLoading(true)
    setError('')
    try {
      const updated = await updateCard(sessionId || undefined, currentCard.id, editForm)
      setCurrentCard(updated)
      setDrawMessage('Card content saved.')
      await refreshPool(poolKind, poolQuery)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="shell">
      <header className="hero">
        <div>
          <p className="eyebrow">Medical Revision Cards</p>
          <h1>Med Card</h1>
          <p className="lede">
            Import a textbook PDF, extract revision cards, and review with uncertain cards first and no repeats
            inside one round.
          </p>
        </div>
        <div className="heroPanel">
          <span>Current round</span>
          <strong>{sessionId ? sessionId.slice(0, 8) : 'Not started'}</strong>
          <p>{drawMessage}</p>
        </div>
      </header>

      <nav className="tabs">
        <button className={tab === 'import' ? 'active' : ''} onClick={() => setTab('import')} type="button">
          Import
        </button>
        <button className={tab === 'draw' ? 'active' : ''} onClick={() => setTab('draw')} type="button">
          Draw
        </button>
        <button className={tab === 'pools' ? 'active' : ''} onClick={() => setTab('pools')} type="button">
          Pools
        </button>
      </nav>

      {error ? <div className="errorBanner">{error}</div> : null}

      <main className="grid">
        {tab === 'import' ? (
          <>
            <section className="panel">
              <h2>Import Textbook</h2>
              <form className="uploadForm" onSubmit={handleUpload}>
                <input accept="application/pdf" name="pdf" type="file" />
                <button disabled={uploading} type="submit">
                  {uploading ? 'Importing...' : 'Upload and Extract'}
                </button>
              </form>
              <p className="hint">
                Configure `MED_CARD_LLM_API_KEY` in `.env`. For local smoke tests, switch the provider to `mock`.
              </p>
            </section>
            <section className="panel">
              <h2>Import History</h2>
              <div className="list">
                {textbooks.length === 0 ? <p className="hint">No imports yet.</p> : null}
                {textbooks.map((item) => (
                  <article className="listItem" key={item.id}>
                    <div>
                      <strong>{item.filename}</strong>
                      <p>{item.summary ?? 'Still processing or no summary available yet.'}</p>
                    </div>
                    <div className="meta">
                      <span>{item.status}</span>
                      <span>{item.card_count} cards</span>
                    </div>
                  </article>
                ))}
              </div>
            </section>
          </>
        ) : null}

        {tab === 'draw' ? (
          <>
            <section className="panel cardPanel">
              <div className="cardToolbar">
                <button disabled={loading} onClick={() => void handleDraw()} type="button">
                  {loading ? 'Working...' : 'Draw Next'}
                </button>
                <button disabled={!sessionId || loading} onClick={() => void handleResetRound()} type="button">
                  Reset Round
                </button>
              </div>

              {currentCard ? (
                <article className="cardView">
                  <span className={`statusBadge status-${currentCard.status}`}>{currentCard.status}</span>
                  <h2>{currentCard.concept_name}</h2>
                  <p className="chapter">{currentCard.chapter}</p>
                  <p>{currentCard.summary}</p>
                  <blockquote>{currentCard.source_excerpt}</blockquote>
                </article>
              ) : (
                <div className="emptyState">
                  <p>{roundComplete ? 'This round is complete. Reset to start again.' : 'No card has been drawn yet.'}</p>
                </div>
              )}
            </section>

            <section className="panel">
              <h2>Review Actions</h2>
              <div className="actionRow">
                <button disabled={!currentCard || loading} onClick={() => void handleAction('mark-familiar')} type="button">
                  Familiar
                </button>
                <button disabled={!currentCard || loading} onClick={() => void handleAction('mark-uncertain')} type="button">
                  Uncertain
                </button>
                <button disabled={!currentCard || loading} onClick={() => void handleAction('ignore')} type="button">
                  Ignore
                </button>
                <button className="danger" disabled={!currentCard || loading} onClick={() => void handleAction('delete')} type="button">
                  Delete
                </button>
              </div>
              <div className="editGrid">
                <label>
                  Concept
                  <input
                    value={editForm.concept_name}
                    onChange={(event) => setEditForm((value) => ({ ...value, concept_name: event.target.value }))}
                  />
                </label>
                <label>
                  Chapter
                  <input
                    value={editForm.chapter}
                    onChange={(event) => setEditForm((value) => ({ ...value, chapter: event.target.value }))}
                  />
                </label>
                <label className="full">
                  Summary
                  <textarea
                    rows={4}
                    value={editForm.summary}
                    onChange={(event) => setEditForm((value) => ({ ...value, summary: event.target.value }))}
                  />
                </label>
                <label className="full">
                  Source Excerpt
                  <textarea
                    rows={5}
                    value={editForm.source_excerpt}
                    onChange={(event) =>
                      setEditForm((value) => ({ ...value, source_excerpt: event.target.value }))
                    }
                  />
                </label>
              </div>
              <button disabled={!currentCard || loading} onClick={() => void handleSaveEdit()} type="button">
                Save Edits
              </button>
            </section>
          </>
        ) : null}

        {tab === 'pools' ? (
          <>
            <section className="panel">
              <div className="poolToolbar">
                <div className="segmented">
                  <button
                    className={poolKind === 'uncertain' ? 'active' : ''}
                    onClick={() => setPoolKind('uncertain')}
                    type="button"
                  >
                    Uncertain
                  </button>
                  <button
                    className={poolKind === 'familiar' ? 'active' : ''}
                    onClick={() => setPoolKind('familiar')}
                    type="button"
                  >
                    Familiar
                  </button>
                </div>
                <input
                  placeholder="Search concept, summary, or chapter"
                  value={poolQuery}
                  onChange={(event) => setPoolQuery(event.target.value)}
                />
              </div>
            </section>
            <section className="panel">
              <h2>{poolKind === 'uncertain' ? 'Uncertain Pool' : 'Familiar Pool'}</h2>
              <div className="list">
                {poolItems.length === 0 ? <p className="hint">No cards in this pool.</p> : null}
                {poolItems.map((item) => (
                  <article className="listItem stacked" key={item.id}>
                    <div className="meta">
                      <strong>{item.concept_name}</strong>
                      <span>{item.chapter}</span>
                    </div>
                    <p>{item.summary}</p>
                  </article>
                ))}
              </div>
            </section>
          </>
        ) : null}
      </main>
    </div>
  )
}
