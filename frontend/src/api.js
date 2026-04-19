const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

async function readJson(response) {
  const text = await response.text()
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

async function postJson(url, payload, label = 'api') {
  console.debug(`[${label}] request`, { url, payload })
  const startedAt = performance.now()
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

  const elapsed = Math.round(performance.now() - startedAt)
  console.debug(`[${label}] response`, { status: response.status, elapsedMs: elapsed })

  if (!response.ok) {
    const detail = (await response.text()) || '请求失败'
    console.error(`[${label}] error`, detail)
    throw new Error(detail)
  }

  return readJson(response)
}

export async function uploadAudit(file, ruleSetId = 'default') {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('rule_set_id', ruleSetId)

  const response = await fetch(`${API_BASE}/api/v1/audit/upload`, {
    method: 'POST',
    body: formData,
  })

  if (!response.ok) {
    throw new Error(await response.text())
  }

  return response.json()
}

export async function explainRisk(resultId) {
  return postJson(`${API_BASE}/api/v1/audit/explain`, { result_id: resultId }, 'explainRisk')
}

export async function submitUserChallenge(resultId, message) {
  return postJson(`${API_BASE}/api/v1/audit/challenge`, { result_id: resultId, message }, 'challengeRisk')
}

export async function submitClarification(taskId, answer) {
  return postJson(`${API_BASE}/api/v1/audit/resume`, { task_id: taskId, answer }, 'submitClarification')
}

export async function compareFiles(baseFile, currentFile) {
  const formData = new FormData()
  formData.append('base_file', baseFile)
  formData.append('current_file', currentFile)

  const response = await fetch(`${API_BASE}/api/v1/compare/files`, {
    method: 'POST',
    body: formData,
  })

  if (!response.ok) {
    throw new Error(await response.text())
  }

  return response.json()
}
