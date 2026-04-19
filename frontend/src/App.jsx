import React, { useCallback, useMemo, useRef, useState } from 'react'
import AgentTimeline from './components/AgentTimeline'
import ContractViewer from './components/ContractViewer'
import { explainRisk, submitClarification, submitUserChallenge, uploadAudit } from './api'

const emptyUpload = {
  file: null,
  fileName: '',
  fileType: '',
  objectUrl: '',
  text: '',
}

export default function App() {
  const [uploadState, setUploadState] = useState(emptyUpload)
  const [results, setResults] = useState([])
  const [compareResults] = useState([])
  const [loading, setLoading] = useState(false)
  const [reviewing, setReviewing] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('请先上传合同文件，再点击“开始审查”。')
  const [clarification, setClarification] = useState(null)
  const [clarificationAnswer, setClarificationAnswer] = useState('')
  const [clarificationSubmitting, setClarificationSubmitting] = useState(false)
  const [challengeState, setChallengeState] = useState({ open: false, resultId: '', message: '' })
  const [explainText, setExplainText] = useState('')
  const [thinkingHint, setThinkingHint] = useState('')
  const [agentEvents, setAgentEvents] = useState([])
  const inputRef = useRef(null)

  const header = useMemo(
    () => ({
      title: '合规罗盘 · 前端工作台',
      desc: '真实上传、后端审查、IM 回跳和 PDF/Word 预览已经接通。',
    }),
    [],
  )

  const pushEvent = useCallback((type, message, meta = null) => {
    setAgentEvents((prev) => [{ type, message, meta, time: new Date().toLocaleTimeString() }, ...prev].slice(0, 20))
    console.debug(`[${type}]`, message, meta || '')
  }, [])

  const readTextFromFile = useCallback((file) => {
    return new Promise((resolve) => {
      if (file?.type?.includes('text') || file?.name?.toLowerCase().endsWith('.txt')) {
        const reader = new FileReader()
        reader.onload = () => resolve(String(reader.result || ''))
        reader.onerror = () => resolve('')
        reader.readAsText(file, 'utf-8')
        return
      }
      resolve('')
    })
  }, [])

  const resetUpload = useCallback(() => {
    if (uploadState.objectUrl) URL.revokeObjectURL(uploadState.objectUrl)
    setUploadState(emptyUpload)
    setResults([])
    setError('')
    setMessage('已清空当前文件，请重新上传。')
    setClarification(null)
    setExplainText('')
    setAgentEvents([])
    if (inputRef.current) inputRef.current.value = ''
    console.log('[UI] 已清空当前文件')
  }, [uploadState.objectUrl])

  const handleFileSelect = useCallback(async (event) => {
    const file = event.target.files?.[0]
    if (!file) return

    if (uploadState.objectUrl) URL.revokeObjectURL(uploadState.objectUrl)
    const objectUrl = URL.createObjectURL(file)
    const localText = await readTextFromFile(file)

    setUploadState({ file, fileName: file.name, fileType: file.type, objectUrl, text: localText })
    setResults([])
    setError('')
    setLoading(false)
    setReviewing(false)
    setClarification(null)
    setAgentEvents([])
    setMessage(`已选择文件：${file.name}，请点击“开始审查”。`)
    console.log('[UI] 文件选择成功', { name: file.name, type: file.type, size: file.size })
  }, [readTextFromFile, uploadState.objectUrl])

  const handleStartReview = useCallback(async () => {
    if (!uploadState.file) {
      setError('请先选择合同文件。')
      setMessage('请先上传合同文件，再开始审查。')
      console.warn('[UI] 未选择文件，无法开始审查')
      return
    }

    setReviewing(true)
    setLoading(true)
    setError('')
    setThinkingHint('Agent 正在制定审计计划...')
    pushEvent('plan', 'Agent 正在制定审计计划...', { fileName: uploadState.file.name })

    try {
      const response = await uploadAudit(uploadState.file)
      if (response?.question) {
        setClarification({
          taskId: response.task_id || response.taskId || '',
          question: response.question,
          options: response.options || [],
          context_fragment: response.context_fragment || '',
        })
        setResults([])
        setMessage('Agent 需要进一步澄清关键信息。')
        pushEvent('clarification_requested', response.question, response)
        return
      }
      const normalized = Array.isArray(response) ? response : response?.results || []
      setResults(normalized)
      setMessage(normalized.length ? `审查完成，已生成 ${normalized.length} 条风险卡片。` : '审查完成，未发现明显风险，当前为空态。')
      pushEvent('completed', `审查完成，生成 ${normalized.length} 条结果。`, { count: normalized.length })
    } catch (err) {
      const detail = err?.message || '上传失败，请稍后重试。'
      setResults([])
      setError(detail)
      setMessage('审查失败，请检查后端日志。')
      pushEvent('error', detail)
    } finally {
      setLoading(false)
      setReviewing(false)
      setThinkingHint('')
    }
  }, [uploadState.file])

  const handleExplainRisk = useCallback(async (resultId) => {
    setThinkingHint('Agent 正在解释该风险点...')
    pushEvent('explain', 'Agent 正在解释该风险点...', { resultId })
    try {
      const data = await explainRisk(resultId)
      setExplainText(typeof data === 'string' ? data : data?.content || JSON.stringify(data, null, 2))
    } catch (err) {
      setExplainText(err?.message || '解释失败')
    } finally {
      setThinkingHint('')
    }
  }, [])

  const handleChallengeRisk = useCallback(async (resultId, messageText) => {
    setThinkingHint('Agent 正在接收质疑并重新评估...')
    pushEvent('challenge', 'Agent 正在接收质疑并重新评估...', { resultId, messageText })
    try {
      await submitUserChallenge(resultId, messageText)
      setMessage('已提交挑战，Agent 正在重新审查。')
    } catch (err) {
      setError(err?.message || '挑战提交失败')
    } finally {
      setThinkingHint('')
      setChallengeState({ open: false, resultId: '', message: '' })
    }
  }, [])

  const handleClarificationSubmit = useCallback(async () => {
    if (!clarification?.taskId) return
    setClarificationSubmitting(true)
    setThinkingHint('Agent 正在接收回答并继续审计...')
    pushEvent('clarification_received', 'Agent 正在接收回答并继续审计...', { taskId: clarification.taskId, answer: clarificationAnswer })
    try {
      const response = await submitClarification(clarification.taskId, clarificationAnswer)
      const normalized = Array.isArray(response) ? response : response?.results || []
      setResults(normalized)
      setClarification(null)
      setClarificationAnswer('')
      setMessage(`已恢复审计，生成 ${normalized.length} 条结果。`)
    } catch (err) {
      setError(err?.message || '恢复审计失败')
    } finally {
      setClarificationSubmitting(false)
      setThinkingHint('')
    }
  }, [clarification, clarificationAnswer])

  const summaryResult = results.find((item) => item.audit_item === '整体风险总结')
  const riskResults = results.filter((item) => item.audit_item !== '整体风险总结')

  return (
    <div className="min-h-screen text-slate-100">
      <header className="mx-auto flex max-w-7xl flex-col gap-4 px-4 py-5 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-white">{header.title}</h1>
          <p className="mt-1 text-sm text-slate-400">{header.desc}</p>
        </div>
        <div className="flex flex-wrap gap-3">
          <label className="inline-flex cursor-pointer items-center justify-center rounded-2xl border border-sky-400/20 bg-sky-500/10 px-4 py-3 text-sm text-sky-200 transition hover:bg-sky-500/20">
            选择合同文件
            <input ref={inputRef} className="hidden" type="file" accept=".pdf,.doc,.docx,.txt" onChange={handleFileSelect} />
          </label>
          <button
            className="inline-flex items-center justify-center rounded-2xl border border-emerald-400/20 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-200 transition hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-50"
            disabled={!uploadState.file || loading}
            onClick={handleStartReview}
          >
            {reviewing ? '正在审查...' : '开始审查'}
          </button>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-2 pb-4">
        {(error || thinkingHint) && <div className="mx-4 mb-3 rounded-2xl border border-sky-400/20 bg-sky-500/10 px-4 py-3 text-sm text-sky-200">{error || thinkingHint}</div>}
        <div className="mx-4 mb-3 rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-slate-300">{message}</div>
        <div className="mx-4 mb-3">
          <AgentTimeline events={agentEvents} />
        </div>
        <ContractViewer
          file={uploadState.objectUrl ? { url: uploadState.objectUrl, name: uploadState.fileName, type: uploadState.fileType } : null}
          documentText={uploadState.text}
          results={riskResults}
          summaryResult={summaryResult}
          compareResults={compareResults}
          loading={loading}
          onReset={resetUpload}
          onExplainRisk={handleExplainRisk}
          onChallengeRisk={(resultId) => setChallengeState({ open: true, resultId, message: '' })}
        />

        {clarification && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/70 p-4 backdrop-blur-sm">
            <div className="w-full max-w-xl rounded-3xl border border-white/10 bg-slate-950 p-6 shadow-2xl">
              <div className="mb-3 text-lg font-semibold text-white">意图澄清对话框</div>
              <div className="mb-2 text-sm text-slate-300">{clarification.question}</div>
              {clarification.context_fragment && <div className="mb-4 rounded-2xl bg-white/5 p-3 text-xs leading-6 text-slate-400">{clarification.context_fragment}</div>}
              <textarea className="mb-3 min-h-28 w-full rounded-2xl border border-white/10 bg-white/5 p-3 text-sm text-white outline-none" value={clarificationAnswer} onChange={(e) => setClarificationAnswer(e.target.value)} placeholder="请输入你的回答..." />
              <div className="mb-4 flex flex-wrap gap-2">
                {(clarification.options || []).map((opt) => <button key={opt} className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-slate-200" onClick={() => setClarificationAnswer(opt)}>{opt}</button>)}
              </div>
              <div className="flex justify-end gap-2">
                <button className="rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-sm text-slate-200" onClick={() => setClarification(null)}>稍后再说</button>
                <button className="rounded-xl bg-sky-500 px-4 py-2 text-sm text-white disabled:opacity-50" disabled={clarificationSubmitting || !clarificationAnswer.trim()} onClick={handleClarificationSubmit}>{clarificationSubmitting ? '提交中...' : '提交回答并继续'}</button>
              </div>
            </div>
          </div>
        )}

        {challengeState.open && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/70 p-4 backdrop-blur-sm">
            <div className="w-full max-w-xl rounded-3xl border border-white/10 bg-slate-950 p-6 shadow-2xl">
              <div className="mb-3 text-lg font-semibold text-white">挑战这个风险项</div>
              <textarea className="mb-4 min-h-28 w-full rounded-2xl border border-white/10 bg-white/5 p-3 text-sm text-white outline-none" value={challengeState.message} onChange={(e) => setChallengeState((prev) => ({ ...prev, message: e.target.value }))} placeholder="说明你为何不认同..." />
              <div className="flex justify-end gap-2">
                <button className="rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-sm text-slate-200" onClick={() => setChallengeState({ open: false, resultId: '', message: '' })}>取消</button>
                <button className="rounded-xl bg-emerald-500 px-4 py-2 text-sm text-white disabled:opacity-50" disabled={!challengeState.message.trim()} onClick={() => handleChallengeRisk(challengeState.resultId, challengeState.message)}>提交挑战</button>
              </div>
            </div>
          </div>
        )}

        {explainText && <div className="mx-4 mt-3 rounded-2xl border border-violet-400/20 bg-violet-500/10 px-4 py-3 text-sm text-violet-100 whitespace-pre-wrap">{explainText}</div>}
      </main>
    </div>
  )
}
