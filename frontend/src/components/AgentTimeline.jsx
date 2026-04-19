import React from 'react'

export default function AgentTimeline({ events = [] }) {
  return (
    <div className="rounded-3xl border border-white/10 bg-slate-950/80 p-4 shadow-glow backdrop-blur">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-white">Agent 运行轨迹</h3>
          <p className="text-xs text-slate-400">前端可见的审计过程日志</p>
        </div>
        <span className="rounded-full bg-sky-500/10 px-3 py-1 text-[11px] text-sky-200">{events.length} 事件</span>
      </div>
      <div className="max-h-56 space-y-2 overflow-auto pr-1 text-xs text-slate-300">
        {events.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-white/10 bg-white/5 p-3 text-slate-400">等待 Agent 开始审计...</div>
        ) : events.map((event, index) => (
          <div key={`${event.type}-${index}`} className="rounded-2xl border border-white/8 bg-white/5 p-3">
            <div className="mb-1 flex items-center justify-between gap-3">
              <span className="font-medium text-sky-200">{event.type}</span>
              <span className="text-[11px] text-slate-500">{event.time}</span>
            </div>
            <div className="whitespace-pre-wrap leading-6 text-slate-300">{event.message}</div>
            {event.meta && (
              <pre className="mt-2 overflow-auto rounded-xl bg-slate-900/80 p-2 text-[11px] leading-5 text-slate-400">{JSON.stringify(event.meta, null, 2)}</pre>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
