import React, { useCallback, useMemo, useRef, useState } from 'react'
import ContractViewer from './components/ContractViewer'
import { uploadAudit } from './api'

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
  const inputRef = useRef(null)

  const header = useMemo(
    () => ({
      title: '合规罗盘 · 前端工作台',
      desc: '真实上传、后端审查、IM 回跳和 PDF/Word 预览已经接通。',
    }),
    [],
  )

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
    setMessage('DeepSeek 正在思考合同风险，请稍候...')
    console.log('[UI] 开始审查')
    console.log('[Backend] 上传成功，准备调用 DeepSeek')

    try {
      console.log('[DeepSeek] 调用中...')
      const response = await uploadAudit(uploadState.file)
      const normalized = Array.isArray(response) ? response : response?.results || []
      setResults(normalized)
      setMessage(normalized.length ? `审查完成，已生成 ${normalized.length} 条风险卡片。` : '审查完成，未发现明显风险，当前为空态。')
      console.log('[Backend] 审查完成', { count: normalized.length })
    } catch (err) {
      const detail = err?.message || '上传失败，请稍后重试。'
      setResults([])
      setError(detail)
      setMessage('审查失败，请检查后端日志。')
      console.error('[Backend] 审查失败', err)
    } finally {
      setLoading(false)
      setReviewing(false)
    }
  }, [uploadState.file])

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
        {error && <div className="mx-4 mb-3 rounded-2xl border border-rose-400/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">{error}</div>}
        <div className="mx-4 mb-3 rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-slate-300">{message}</div>
        <ContractViewer
          file={uploadState.objectUrl ? { url: uploadState.objectUrl, name: uploadState.fileName, type: uploadState.fileType } : null}
          documentText={uploadState.text}
          results={results}
          compareResults={compareResults}
          loading={loading}
          onReset={resetUpload}
        />
      </main>
    </div>
  )
}
