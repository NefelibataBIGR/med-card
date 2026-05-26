import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'

import {
  deleteCard,
  drawCard,
  fetchPool,
  importTextbook,
  listImportFailures,
  listTextbooks,
  markCard,
  resetSession,
  retryAllImportFailures,
  retryImportFailure,
  updateCard,
} from './api'
import type { Card, ImportChunkFailure, Textbook } from './types'

type TabKey = 'import' | 'draw' | 'pools'

const emptyCardForm = {
  concept_name: '',
  summary: '',
  chapter: '',
  source_excerpt: '',
}

const textbookStatusLabels: Record<Textbook['status'], string> = {
  pending: '排队中',
  processing: '处理中',
  completed: '已完成',
  failed: '失败',
}

const cardStatusLabels: Record<Card['status'], string> = {
  new: '新卡',
  familiar: '熟悉',
  uncertain: '模糊',
  ignored: '忽略',
}

export function App() {
  const [tab, setTab] = useState<TabKey>('import')
  const [textbooks, setTextbooks] = useState<Textbook[]>([])
  const [currentCard, setCurrentCard] = useState<Card | null>(null)
  const [sessionId, setSessionId] = useState('')
  const [drawMessage, setDrawMessage] = useState('点击“抽取下一张”，开始本轮复习。')
  const [roundComplete, setRoundComplete] = useState(false)
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const [editForm, setEditForm] = useState(emptyCardForm)
  const [poolQuery, setPoolQuery] = useState('')
  const [uncertainPoolItems, setUncertainPoolItems] = useState<Card[]>([])
  const [familiarPoolItems, setFamiliarPoolItems] = useState<Card[]>([])
  const [isEditorOpen, setIsEditorOpen] = useState(false)
  const [selectedTextbookId, setSelectedTextbookId] = useState<number | null>(null)
  const [importFailures, setImportFailures] = useState<ImportChunkFailure[]>([])
  const [retryingFailureId, setRetryingFailureId] = useState<number | null>(null)
  const [retryingAllFailures, setRetryingAllFailures] = useState(false)

  useEffect(() => {
    void refreshTextbooks()
  }, [])

  useEffect(() => {
    const hasActiveImport = textbooks.some((item) => item.status === 'pending' || item.status === 'processing')
    if (!hasActiveImport) {
      return
    }

    const timer = window.setInterval(() => {
      void refreshTextbooks()
    }, 2000)

    return () => window.clearInterval(timer)
  }, [textbooks])

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
      void refreshPools(poolQuery)
    }
  }, [tab, poolQuery])

  useEffect(() => {
    if (selectedTextbookId === null) {
      setImportFailures([])
      return
    }
    void refreshImportFailures(selectedTextbookId)
  }, [selectedTextbookId, textbooks])

  async function refreshTextbooks() {
    try {
      setTextbooks(await listTextbooks())
    } catch (err) {
      setError((err as Error).message)
    }
  }

  async function refreshPool(kind: 'uncertain' | 'familiar', query: string) {
    try {
      const result = await fetchPool(kind, query)
      if (kind === 'uncertain') {
        setUncertainPoolItems(result.items)
      } else {
        setFamiliarPoolItems(result.items)
      }
    } catch (err) {
      setError((err as Error).message)
    }
  }

  async function refreshPools(query: string) {
    await Promise.all([refreshPool('uncertain', query), refreshPool('familiar', query)])
  }

  async function refreshImportFailures(textbookId: number) {
    try {
      setImportFailures(await listImportFailures(textbookId))
    } catch (err) {
      setError((err as Error).message)
    }
  }

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const input = event.currentTarget.elements.namedItem('pdf') as HTMLInputElement | null
    const file = input?.files?.[0]
    if (!file) {
      setError('请先选择一个 PDF 文件。')
      return
    }
    setUploading(true)
    setError('')
    try {
      const result = await importTextbook(file)
      await refreshTextbooks()
      event.currentTarget.reset()
      setDrawMessage(result.message)
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
      setDrawMessage('本轮已重置，可以重新抽卡。')
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
        setDrawMessage('卡片已删除。')
      } else {
        const updated = await markCard(sessionId || undefined, currentCard.id, action)
        setCurrentCard(updated)
        setDrawMessage('卡片状态已更新。')
      }
      await refreshPools(poolQuery)
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
      setDrawMessage('卡片内容已保存。')
      setIsEditorOpen(false)
      await refreshPools(poolQuery)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  async function handleRetryFailure(textbookId: number, failureId: number) {
    setRetryingFailureId(failureId)
    setError('')
    try {
      await retryImportFailure(textbookId, failureId)
      await refreshTextbooks()
      await refreshImportFailures(textbookId)
      setDrawMessage('失败文本块已重试。')
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setRetryingFailureId(null)
    }
  }

  async function handleRetryAllFailures(textbookId: number) {
    setRetryingAllFailures(true)
    setError('')
    try {
      const result = await retryAllImportFailures(textbookId)
      await refreshTextbooks()
      await refreshImportFailures(textbookId)
      setDrawMessage(
        `已重试 ${result.retried_count} 个失败块，成功恢复 ${result.resolved_count} 个，剩余 ${result.remaining_failures} 个。`,
      )
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setRetryingAllFailures(false)
    }
  }

  return (
    <div className="shell">
      <header className="hero">
        <div>
          <p className="eyebrow">MED CARD</p>
          <h1>医学教材抽卡复习</h1>
          <p className="lede">
            导入教材 PDF，抽取复习卡片，并按“模糊优先、单轮不重复”的规则推进复习。
          </p>
        </div>
        <div className="heroPanel">
          <span>当前轮次</span>
          <strong>{sessionId ? sessionId.slice(0, 8) : '未开始'}</strong>
          <p>{drawMessage}</p>
        </div>
      </header>

      <nav className="tabs">
        <button className={tab === 'import' ? 'active' : ''} onClick={() => setTab('import')} type="button">
          导入页
        </button>
        <button className={tab === 'draw' ? 'active' : ''} onClick={() => setTab('draw')} type="button">
          抽卡页
        </button>
        <button className={tab === 'pools' ? 'active' : ''} onClick={() => setTab('pools')} type="button">
          卡池页
        </button>
      </nav>

      {error ? <div className="errorBanner">{error}</div> : null}

      <main className="grid">
        {tab === 'import' ? (
          <>
            <section className="panel">
              <h2>导入教材</h2>
              <form className="uploadForm" onSubmit={handleUpload}>
                <input accept="application/pdf" name="pdf" type="file" />
                <button disabled={uploading} type="submit">
                  {uploading ? '导入中...' : '上传并抽取'}
                </button>
              </form>
              <p className="hint">
                在 `.env` 中配置 `MED_CARD_LLM_API_KEY`。本地烟测时可切换到 `mock` 提供者。
              </p>
            </section>
            <section className="panel">
              <h2>导入记录</h2>
              <div className="list">
                {textbooks.length === 0 ? <p className="hint">暂时还没有导入记录。</p> : null}
                {textbooks.map((item) => (
                  <article className="listItem" key={item.id}>
                    <div>
                      <strong>{item.filename}</strong>
                      <p>{item.summary ?? '正在处理中，暂时还没有摘要。'}</p>
                      {item.processed_at ? <p className="hint">完成时间：{new Date(item.processed_at).toLocaleString()}</p> : null}
                      <p className="hint">
                        进度 {item.processed_chunks}/{item.total_chunks || 0} 个文本块，失败 {item.failed_chunks} 个，
                        跳过 {item.skipped_cards} 个
                      </p>
                      {item.error_message ? <p className="hint">{item.error_message}</p> : null}
                    </div>
                    <div className="meta">
                      <span>{textbookStatusLabels[item.status]}</span>
                      <span>{item.card_count} 张卡片</span>
                      <button
                        className="ghost"
                        onClick={() => setSelectedTextbookId((current) => (current === item.id ? null : item.id))}
                        type="button"
                      >
                        {selectedTextbookId === item.id ? '收起失败块' : '查看失败块'}
                      </button>
                    </div>
                  </article>
                ))}
              </div>
            </section>
            <section className="panel">
              <div className="sectionHeader">
                <h2>失败文本块</h2>
                {selectedTextbookId !== null ? (
                  <button disabled={retryingAllFailures || importFailures.length === 0} onClick={() => void handleRetryAllFailures(selectedTextbookId)} type="button">
                    {retryingAllFailures ? '批量重试中...' : '全部重试'}
                  </button>
                ) : null}
              </div>
              {selectedTextbookId === null ? <p className="hint">先选择一条导入记录，再查看失败文本块。</p> : null}
              {selectedTextbookId !== null && importFailures.length === 0 ? (
                <p className="hint">这条导入记录当前没有未解决的失败文本块。</p>
              ) : null}
              <div className="list">
                {importFailures.map((failure) => (
                  <article className="listItem stacked" key={failure.id}>
                    <div className="meta">
                      <strong>文本块 {failure.chunk_index}</strong>
                      <span>已重试 {failure.retry_count} 次</span>
                    </div>
                    <p>{failure.error_message}</p>
                    <blockquote>{failure.chunk_excerpt}</blockquote>
                    <button
                      disabled={retryingFailureId === failure.id}
                      onClick={() => void handleRetryFailure(failure.textbook_id, failure.id)}
                      type="button"
                    >
                      {retryingFailureId === failure.id ? '重试中...' : '重试该文本块'}
                    </button>
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
                  {loading ? '处理中...' : '抽取下一张'}
                </button>
                <button disabled={!sessionId || loading} onClick={() => void handleResetRound()} type="button">
                  重置本轮
                </button>
              </div>

              {currentCard ? (
                <article className="cardView">
                  <span className={`statusBadge status-${currentCard.status}`}>{cardStatusLabels[currentCard.status]}</span>
                  <h2>{currentCard.concept_name}</h2>
                  <p className="chapter">{currentCard.chapter}</p>
                  <p>{currentCard.summary}</p>
                  <blockquote>{currentCard.source_excerpt}</blockquote>
                </article>
              ) : (
                <div className="emptyState">
                  <p>{roundComplete ? '本轮已完成，可重置后重新开始。' : '当前还没有抽出的卡片。'}</p>
                </div>
              )}
            </section>

            <section className="panel">
              <h2>卡片操作</h2>
              <div className="actionRow">
                <button disabled={!currentCard || loading} onClick={() => void handleAction('mark-familiar')} type="button">
                  熟悉
                </button>
                <button disabled={!currentCard || loading} onClick={() => void handleAction('mark-uncertain')} type="button">
                  模糊
                </button>
                <button disabled={!currentCard || loading} onClick={() => void handleAction('ignore')} type="button">
                  忽略
                </button>
                <button disabled={!currentCard || loading} onClick={() => setIsEditorOpen(true)} type="button">
                  编辑
                </button>
                <button className="danger" disabled={!currentCard || loading} onClick={() => void handleAction('delete')} type="button">
                  删除
                </button>
              </div>
            </section>
          </>
        ) : null}

        {tab === 'pools' ? (
          <>
            <section className="panel">
              <div className="poolToolbar">
                <p className="hint">同时浏览模糊池与熟悉池，支持统一搜索。</p>
                <input
                  placeholder="搜索概念、释义或章节"
                  value={poolQuery}
                  onChange={(event) => setPoolQuery(event.target.value)}
                />
              </div>
            </section>
            <section className="panel poolPanel">
              <div className="poolColumns">
                <div className="poolColumn">
                  <div className="sectionHeader">
                    <h2>模糊池</h2>
                    <span className="hint">{uncertainPoolItems.length} 张</span>
                  </div>
                  <div className="list">
                    {uncertainPoolItems.length === 0 ? <p className="hint">模糊池当前没有卡片。</p> : null}
                    {uncertainPoolItems.map((item) => (
                      <article className="listItem stacked" key={`uncertain-${item.id}`}>
                        <div className="meta">
                          <strong>{item.concept_name}</strong>
                          <span>{item.chapter}</span>
                        </div>
                        <p>{item.summary}</p>
                      </article>
                    ))}
                  </div>
                </div>
                <div className="poolColumn">
                  <div className="sectionHeader">
                    <h2>熟悉池</h2>
                    <span className="hint">{familiarPoolItems.length} 张</span>
                  </div>
                  <div className="list">
                    {familiarPoolItems.length === 0 ? <p className="hint">熟悉池当前没有卡片。</p> : null}
                    {familiarPoolItems.map((item) => (
                      <article className="listItem stacked" key={`familiar-${item.id}`}>
                        <div className="meta">
                          <strong>{item.concept_name}</strong>
                          <span>{item.chapter}</span>
                        </div>
                        <p>{item.summary}</p>
                      </article>
                    ))}
                  </div>
                </div>
              </div>
            </section>
          </>
        ) : null}
      </main>

      {isEditorOpen && currentCard ? (
        <div className="modalShell" role="dialog" aria-modal="true">
          <div className="modalCard">
            <div className="modalHeader">
              <div>
                <p className="eyebrow">卡片详情</p>
                <h2>{currentCard.concept_name}</h2>
              </div>
              <button className="ghost" onClick={() => setIsEditorOpen(false)} type="button">
                关闭
              </button>
            </div>
            <div className="editGrid">
              <label>
                概念名
                <input
                  value={editForm.concept_name}
                  onChange={(event) => setEditForm((value) => ({ ...value, concept_name: event.target.value }))}
                />
              </label>
              <label>
                章节
                <input
                  value={editForm.chapter}
                  onChange={(event) => setEditForm((value) => ({ ...value, chapter: event.target.value }))}
                />
              </label>
              <label className="full">
                精简释义
                <textarea
                  rows={4}
                  value={editForm.summary}
                  onChange={(event) => setEditForm((value) => ({ ...value, summary: event.target.value }))}
                />
              </label>
              <label className="full">
                原文片段
                <textarea
                  rows={6}
                  value={editForm.source_excerpt}
                  onChange={(event) =>
                    setEditForm((value) => ({ ...value, source_excerpt: event.target.value }))
                  }
                />
              </label>
            </div>
            <div className="modalActions">
              <button className="ghost" onClick={() => setIsEditorOpen(false)} type="button">
                取消
              </button>
              <button disabled={loading} onClick={() => void handleSaveEdit()} type="button">
                保存编辑
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
