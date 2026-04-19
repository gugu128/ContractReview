import React, { useEffect, useMemo, useRef, useState } from 'react'
import { buildMarkedHtml } from '../utils/highlighter'

const levelColorMap = {
  低: 'bg-emerald-500/15 text-emerald-300 ring-emerald-500/20',
  中: 'bg-amber-500/15 text-amber-300 ring-amber-500/20',
  高: 'bg-orange-500/15 text-orange-300 ring-orange-500/20',
  严重: 'bg-rose-500/15 text-rose-300 ring-rose-500/20',
}

export default function ContractViewer({ file, documentText, results = [], summaryResult = null, compareResults = [], loading = false, onReset, onExplainRisk, onChallengeRisk }) {
  const docRef = useRef(null)
  const [previewText, setPreviewText] = useState(documentText || '')
  const [activeId, setActiveId] = useState(null)

  useEffect(() => {
    setPreviewText(documentText || '')
  }, [documentText])

  const ranges = useMemo(
    () => results.map((item, index) => ({ ...item, start: item.char_index?.start ?? 0, end: item.char_index?.end ?? 0, id: item.id || `result-${index}` })),
    [results],
  )

  const highlightedHtml = useMemo(() => buildMarkedHtml(previewText, ranges), [previewText, ranges])

  const focusRange = (range) => {
    const el = document.getElementById(range.id)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' })
      setActiveId(range.id)
    }
  }

  const applySuggestion = (result) => {
    const current = result.original_quote || ''
    const suggestion = result.suggestion || ''
    if (!current) return
    setPreviewText((prev) => prev.replace(current, suggestion || current))
  }

  const empty = !loading && !file && results.length === 0 && !summaryResult

  return (
    <div className="grid min-h-[calc(100vh-9rem)] grid-cols-1 gap-4 p-4 lg:grid-cols-[1.3fr_0.9fr]">
      <section className="rounded-3xl border border-white/10 bg-slate-950/80 p-5 shadow-glow backdrop-blur">
        <div className="mb-4 flex items-center justify-between gap-3">
          <div>
            <h2 className="text-xl font-semibold text-white">智能合同阅读器</h2>
            <p className="text-sm text-slate-400">支持 PDF / Word / TXT 预览，风险坐标与原文文本层联动。</p>
          </div>
          <div className="flex gap-2">
            {onReset && (
              <button className="rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-sm text-slate-200" onClick={onReset}>
                清空
              </button>
            )}
            <button className="rounded-xl border border-sky-400/20 bg-sky-500/10 px-4 py-2 text-sm text-sky-200 transition hover:bg-sky-500/20" onClick={() => setPreviewText(documentText || '')}>
              还原原文
            </button>
          </div>
        </div>

        <div ref={docRef} className="h-[72vh] overflow-auto rounded-2xl border border-white/8 bg-slate-900/80 p-4 leading-8 text-slate-200">
          {loading ? (
            <div className="flex h-full items-center justify-center">
              <div className="animate-pulse rounded-2xl border border-sky-400/20 bg-sky-500/10 px-6 py-4 text-sky-200">DeepSeek 正在思考中...</div>
            </div>
          ) : empty ? (
            <div className="flex h-full flex-col items-center justify-center gap-3 text-center text-slate-400">
              <div className="text-lg text-white">暂无文件预览</div>
              <div className="max-w-md text-sm">上传合同后，这里会展示可滚动预览、字符高亮和风险定位；手机端也能通过原文层进行精准跳转。</div>
            </div>
          ) : (
            <div className="whitespace-pre-wrap" dangerouslySetInnerHTML={{ __html: highlightedHtml }} />
          )}
        </div>
      </section>

      <section className="rounded-3xl border border-white/10 bg-slate-950/80 p-5 shadow-glow backdrop-blur">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-xl font-semibold text-white">审核结果</h2>
            <p className="text-sm text-slate-400">点击卡片自动定位到左侧高亮。</p>
          </div>
          <span className="rounded-full bg-sky-500/10 px-3 py-1 text-xs text-sky-200">{results.length} 条风险</span>
        </div>

        <div className="mb-4 grid grid-cols-4 gap-2 text-center text-xs">
          {['低', '中', '高', '严重'].map((level) => {
            const count = results.filter((item) => item.risk_level === level).length
            return (
              <div key={level} className="rounded-2xl border border-white/8 bg-white/5 p-3">
                <div className={`mb-2 rounded-full px-2 py-1 text-[11px] ring-1 ${levelColorMap[level]}`}>{level}</div>
                <div className="text-lg font-semibold text-white">{count}</div>
              </div>
            )
          })}
        </div>

        {summaryResult && (
          <div className="mb-4 rounded-3xl border border-violet-400/20 bg-violet-500/10 p-4">
            <div className="mb-2 flex items-center justify-between">
              <div className="text-sm font-semibold text-violet-100">首席审计官总结</div>
              <div className="text-xs text-violet-200">合规评分</div>
            </div>
            <div className="mb-3 h-2 overflow-hidden rounded-full bg-white/10">
              <div className="h-full rounded-full bg-gradient-to-r from-sky-400 to-violet-400" style={{ width: `${Math.max(10, 100 - (results.filter((item) => item.risk_level !== '低').length * 12))}%` }} />
            </div>
            <p className="text-sm leading-6 text-slate-100">{summaryResult.risk_description}</p>
          </div>
        )}

        <div className="space-y-3 overflow-auto pr-1" style={{ maxHeight: '58vh' }}>
          {results.length === 0 && !loading ? (
            <div className="rounded-2xl border border-dashed border-white/10 bg-white/5 p-6 text-center text-sm text-slate-400">上传后这里会出现结构化风险卡片；如果接口返回空数组，也会展示空态。</div>
          ) : null}
          {ranges.map((item) => (
            <article key={item.id} id={item.id} className={`cursor-pointer rounded-2xl border p-4 transition hover:border-sky-400/40 ${activeId === item.id ? 'border-sky-400/50 bg-sky-500/10' : 'border-white/8 bg-white/5'}`} onClick={() => focusRange(item)}>
              <div className="mb-2 flex items-center justify-between gap-3">
                <span className={`rounded-full px-3 py-1 text-xs ring-1 ${levelColorMap[item.risk_level] || levelColorMap['中']}`}>{item.risk_level}</span>
                <span className="text-xs text-slate-400">{item.audit_item}</span>
              </div>
              <p className="text-sm leading-6 text-slate-200">{item.risk_description}</p>
              <p className="mt-3 rounded-xl bg-slate-900/80 p-3 text-xs leading-6 text-slate-300">{item.original_quote}</p>
              {item.suggested_revision && (
                <div className="mt-3 rounded-xl border border-dashed border-violet-400/20 bg-violet-500/10 p-3 text-xs text-violet-100">
                  <div className="mb-2 font-semibold">Suggested Revision</div>
                  <pre className="whitespace-pre-wrap break-words">{item.suggested_revision}</pre>
                </div>
              )}
              <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
                <div className="flex gap-2">
                  <button className="rounded-xl bg-emerald-500/10 px-3 py-2 text-xs text-emerald-200 transition hover:bg-emerald-500/20" onClick={(e) => { e.stopPropagation(); applySuggestion(item) }}>
                    一键替换
                  </button>
                  <button className="rounded-xl bg-sky-500/10 px-3 py-2 text-xs text-sky-200 transition hover:bg-sky-500/20" onClick={(e) => { e.stopPropagation(); onExplainRisk?.(item.id) }}>
                    为什么？
                  </button>
                  <button className="rounded-xl bg-rose-500/10 px-3 py-2 text-xs text-rose-200 transition hover:bg-rose-500/20" onClick={(e) => { e.stopPropagation(); onChallengeRisk?.(item.id) }}>
                    我不认同
                  </button>
                </div>
                <span className="text-xs text-slate-500">{item.char_index?.start} ~ {item.char_index?.end}</span>
              </div>
            </article>
          ))}

          {compareResults.length > 0 && (
            <div className="mt-6 rounded-2xl border border-white/8 bg-white/5 p-4">
              <h3 className="mb-3 text-sm font-semibold text-white">比对结果</h3>
              <div className="space-y-3 text-sm text-slate-300">
                {compareResults.map((item, index) => (
                  <div key={index} className="rounded-xl bg-slate-900/70 p-3">
                    <div className="mb-1 text-xs text-sky-300">{item.change_type}</div>
                    <div>{item.impact_analysis}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </section>
    </div>
  )
}
