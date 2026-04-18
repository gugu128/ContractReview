import React, { useCallback, useMemo, useState } from 'react'
import ContractViewer from './components/ContractViewer'
import { uploadAudit } from './api'

const emptyUpload = {
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
  const [error, setError] = useState('')
  const [message, setMessage] = useState('请上传 PDF、Word 或 TXT 文件，结果会自动联动到右侧风险卡片。')

  const header = useMemo(
    () => ({
      title: '合规罗盘 · 前端工作台',
      desc: '真实上传、后端审查、IM 回跳和 PDF/Word 预览已经接通。',
    }),
    [],
  )

  const resetUpload = useCallback(() => {
    if (uploadState.objectUrl) URL.revokeObjectURL(uploadState.objectUrl)
    setUploadState(emptyUpload)
    setResults([])
    setError('')
    setMessage('已清空当前文件，请重新上传。')
  }, [uploadState.objectUrl])

  const handleUpload = useCallback(async (event) => {
    const file = event.target.files?.[0]
    if (!file) return

    if (uploadState.objectUrl) URL.revokeObjectURL(uploadState.objectUrl)
    const objectUrl = URL.createObjectURL(file)
    setUploadState({ fileName: file.name, fileType: file.type, objectUrl, text: '' })
    setLoading(true)
    setError('')
    setMessage('DeepSeek 正在思考合同风险，请稍候...')

    try {
      const response = await uploadAudit(file)
      const normalized = Array.isArray(response) ? response : response?.results || []
      setResults(normalized)
      setMessage(normalized.length ? `已生成 ${normalized.length} 条风险卡片。` : '未发现明显风险，当前合同暂时为空态。')
    } catch (err) {
      setResults([])
      setError(err?.message || '上传失败，请稍后重试。')
      setMessage('上传失败，已切换到错误态。')
    } finally {
      setLoading(false)
    }
  }, [uploadState.objectUrl])

  return (
    <div className="min-h-screen text-slate-100">
      <header className="mx-auto flex max-w-7xl flex-col gap-4 px-4 py-5 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-white">{header.title}</h1>
          <p className="mt-1 text-sm text-slate-400">{header.desc}</p>
        </div>
        <label className="inline-flex cursor-pointer items-center justify-center rounded-2xl border border-sky-400/20 bg-sky-500/10 px-4 py-3 text-sm text-sky-200 transition hover:bg-sky-500/20">
          上传合同文件
          <input className="hidden" type="file" accept=".pdf,.doc,.docx,.txt" onChange={handleUpload} />
        </label>
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
